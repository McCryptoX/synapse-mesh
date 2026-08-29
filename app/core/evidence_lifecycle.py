"""Fail-closed current-state policy for exact run-bound evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_DIR = PROJECT_ROOT / "evidence" / "lifecycle"
BUNDLES_DIR = PROJECT_ROOT / "bundles" / "golden"
MAX_RECORD_BYTES = 32 * 1024
FRESHNESS_MAX_AGE = timedelta(days=90)
ACTIVE_STATES = {"DISPUTED", "SUPERSEDED"}
BUNDLE_ID_RE = re.compile(r"^(?:bundle|draft)_[a-z0-9][a-z0-9_-]{2,119}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def _aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_artifact_sha256(artifact: dict[str, Any]) -> str:
    canonical = json.dumps(
        artifact,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _base_result(*, artifact: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": "UNVERIFIED",
        "qualified": False,
        "artifactAvailable": artifact is not None,
        "stateSource": "NO_VALID_RUN_ARTIFACT",
        "reasonCode": "NO_VALID_RUN_ARTIFACT",
        "reason": "No valid run artifact is published for these exact bundle bytes.",
        "freshnessMaxAgeSeconds": int(FRESHNESS_MAX_AGE.total_seconds()),
        "policyVersion": "evidence-lifecycle-v1",
        "freshUntil": None,
        "record": None,
    }


def _load_lifecycle_record(
    bundle: dict[str, Any],
    artifact: dict[str, Any],
    *,
    lifecycle_dir: Path,
    now: datetime,
) -> tuple[str, dict[str, Any] | None]:
    bundle_id = bundle.get("bundleId")
    record_path = lifecycle_dir.resolve() / f"{bundle_id}.json"
    if not record_path.exists() and not record_path.is_symlink():
        return "ABSENT", None
    try:
        if record_path.is_symlink():
            return "INVALID", None
        resolved = record_path.resolve(strict=True)
        if (
            resolved.parent != lifecycle_dir.resolve()
            or not resolved.is_file()
            or resolved.stat().st_size > MAX_RECORD_BYTES
        ):
            return "INVALID", None
        record = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RuntimeError):
        return "INVALID", None
    if not isinstance(record, dict):
        return "INVALID", None

    state = record.get("state")
    effective_at = _aware_timestamp(record.get("effectiveAt"))
    reason = record.get("reason")
    reason_code = record.get("reasonCode")
    superseded_by = record.get("supersededByBundleId")
    artifact_completed_at = _aware_timestamp(artifact.get("completedAt"))
    if not all(
        (
            record.get("schemaVersion") == "1.0.0",
            record.get("recordType") == "synapse-bundle-evidence-lifecycle",
            record.get("bundleId") == bundle_id,
            record.get("bundleSha256") == artifact.get("bundleSha256"),
            record.get("canonicalRunArtifactSha256")
            == canonical_artifact_sha256(artifact),
            state in ACTIVE_STATES,
            effective_at is not None,
            effective_at is not None and effective_at <= now + timedelta(minutes=5),
            effective_at is not None
            and artifact_completed_at is not None
            and effective_at >= artifact_completed_at,
            isinstance(reason_code, str)
            and REASON_CODE_RE.fullmatch(reason_code) is not None,
            isinstance(reason, str) and 1 <= len(reason.strip()) <= 500,
        )
    ):
        return "INVALID", None
    if state == "SUPERSEDED":
        if (
            not isinstance(superseded_by, str)
            or BUNDLE_ID_RE.fullmatch(superseded_by) is None
            or superseded_by == bundle_id
            or not isinstance(record.get("supersededByBundleSha256"), str)
            or SHA256_RE.fullmatch(record["supersededByBundleSha256"]) is None
            or not isinstance(
                record.get("supersededByCanonicalRunArtifactSha256"), str
            )
            or SHA256_RE.fullmatch(
                record["supersededByCanonicalRunArtifactSha256"]
            )
            is None
        ):
            return "INVALID", None
    elif any(
        record.get(key) is not None
        for key in (
            "supersededByBundleId",
            "supersededByBundleSha256",
            "supersededByCanonicalRunArtifactSha256",
        )
    ):
        return "INVALID", None
    allowed_keys = {
        "schemaVersion",
        "recordType",
        "bundleId",
        "bundleSha256",
        "canonicalRunArtifactSha256",
        "canonicalization",
        "state",
        "effectiveAt",
        "reasonCode",
        "reason",
        "supersededByBundleId",
        "supersededByBundleSha256",
        "supersededByCanonicalRunArtifactSha256",
    }
    if set(record) - allowed_keys or record.get("canonicalization") != "synapse-json-v1":
        return "INVALID", None
    return "VALID", record


def _load_unique_successor(
    successor_id: str,
    *,
    bundles_dir: Path,
) -> tuple[Path, dict[str, Any]] | None:
    matches: list[tuple[Path, dict[str, Any]]] = []
    try:
        paths = sorted(bundles_dir.resolve().glob("*.json"))[:1000]
    except OSError:
        return None
    for path in paths:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("bundleId") == successor_id:
            matches.append((path, data))
    return matches[0] if len(matches) == 1 else None


def _supersession_target_is_current(
    bundle: dict[str, Any],
    record: dict[str, Any],
    *,
    bundles_dir: Path,
    artifacts_dir: Path | None,
    lifecycle_dir: Path,
    now: datetime,
    visited: frozenset[str],
) -> bool:
    successor = _load_unique_successor(
        record["supersededByBundleId"],
        bundles_dir=bundles_dir,
    )
    if successor is None:
        return False
    successor_path, successor_bundle = successor
    try:
        successor_bytes = successor_path.read_bytes()
    except OSError:
        return False
    if hashlib.sha256(successor_bytes).hexdigest() != record["supersededByBundleSha256"]:
        return False
    current_scope = bundle.get("scope") or {}
    successor_scope = successor_bundle.get("scope") or {}
    if (
        successor_scope.get("package") != current_scope.get("package")
        or successor_scope.get("runtime") != current_scope.get("runtime")
    ):
        return False

    from app.core.run_artifacts import load_valid_run_artifact

    successor_artifact = load_valid_run_artifact(
        successor_bundle,
        successor_path,
        artifacts_dir=artifacts_dir,
    )
    if successor_artifact is None:
        return False
    if (
        canonical_artifact_sha256(successor_artifact)
        != record["supersededByCanonicalRunArtifactSha256"]
    ):
        return False
    effective_at = _aware_timestamp(record.get("effectiveAt"))
    successor_completed_at = _aware_timestamp(successor_artifact.get("completedAt"))
    if (
        effective_at is None
        or successor_completed_at is None
        or effective_at < successor_completed_at
    ):
        return False
    successor_lifecycle = evaluate_evidence_lifecycle(
        successor_bundle,
        successor_artifact,
        lifecycle_dir=lifecycle_dir,
        bundles_dir=bundles_dir,
        artifacts_dir=artifacts_dir,
        now=now,
        _visited=visited,
    )
    return (
        successor_lifecycle.get("status") == "VERIFIED"
        and successor_lifecycle.get("qualified") is True
    )


def evaluate_evidence_lifecycle(
    bundle: dict[str, Any],
    artifact: dict[str, Any] | None,
    *,
    lifecycle_dir: Path | None = None,
    bundles_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    now: datetime | None = None,
    _visited: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Derive current public state without mutating the bundle or artifact."""
    result = _base_result(artifact=artifact)
    if artifact is None:
        return result

    bundle_id = bundle.get("bundleId")
    if (
        not isinstance(bundle_id, str)
        or BUNDLE_ID_RE.fullmatch(bundle_id) is None
        or bundle_id in _visited
    ):
        result.update(
            {
                "status": "UNKNOWN",
                "stateSource": "LIFECYCLE_RELATION",
                "reasonCode": "LIFECYCLE_RELATION_INVALID",
                "reason": "Lifecycle identity is invalid or contains a supersession cycle.",
            }
        )
        return result
    visited = frozenset((*_visited, bundle_id))

    supplied_now = now or datetime.now(timezone.utc)
    if supplied_now.tzinfo is None or supplied_now.utcoffset() is None:
        result.update(
            {
                "status": "UNKNOWN",
                "stateSource": "INVALID_EVALUATION_TIME",
                "reasonCode": "INVALID_EVALUATION_TIME",
                "reason": "Lifecycle state cannot be evaluated with a timezone-naive clock.",
            }
        )
        return result
    evaluated_at = supplied_now.astimezone(timezone.utc)
    completed_at = _aware_timestamp(artifact.get("completedAt"))
    if completed_at is None:
        result.update(
            {
                "status": "UNKNOWN",
                "stateSource": "INVALID_RUN_TIMESTAMP",
                "reasonCode": "INVALID_RUN_TIMESTAMP",
                "reason": "The run timestamp cannot be evaluated safely.",
            }
        )
        return result
    if completed_at > evaluated_at + timedelta(minutes=5):
        result.update(
            {
                "status": "UNKNOWN",
                "stateSource": "INVALID_RUN_TIMESTAMP",
                "reasonCode": "RUN_TIMESTAMP_IN_FUTURE",
                "reason": "The run timestamp is too far in the future to evaluate safely.",
            }
        )
        return result
    fresh_until = completed_at + FRESHNESS_MAX_AGE
    result["freshUntil"] = _iso_z(fresh_until)

    marker_state, record = _load_lifecycle_record(
        bundle,
        artifact,
        lifecycle_dir=lifecycle_dir or LIFECYCLE_DIR,
        now=evaluated_at,
    )
    if marker_state == "INVALID":
        result.update(
            {
                "status": "UNKNOWN",
                "stateSource": "LIFECYCLE_RECORD",
                "reasonCode": "LIFECYCLE_RECORD_INVALID",
                "reason": "A lifecycle record exists but is malformed or not bound to this exact run.",
            }
        )
        return result
    if marker_state == "VALID" and record is not None:
        if record["state"] == "SUPERSEDED" and not _supersession_target_is_current(
            bundle,
            record,
            bundles_dir=bundles_dir or BUNDLES_DIR,
            artifacts_dir=artifacts_dir,
            lifecycle_dir=lifecycle_dir or LIFECYCLE_DIR,
            now=evaluated_at,
            visited=visited,
        ):
            result.update(
                {
                    "status": "UNKNOWN",
                    "stateSource": "LIFECYCLE_RECORD",
                    "reasonCode": "SUPERSESSION_TARGET_NOT_CURRENT",
                    "reason": "The declared superseding record is missing, ambiguous, cyclic, scope-mismatched, or not current exact-run evidence.",
                }
            )
            return result
        result.update(
            {
                "status": record["state"],
                "stateSource": "LIFECYCLE_RECORD",
                "reasonCode": record["reasonCode"],
                "reason": record["reason"],
                "record": record,
            }
        )
        return result
    if evaluated_at >= fresh_until:
        result.update(
            {
                "status": "STALE",
                "stateSource": "FRESHNESS_POLICY",
                "reasonCode": "RUN_ARTIFACT_STALE",
                "reason": "The latest valid run artifact is older than the 90-day freshness window.",
            }
        )
        return result

    result.update(
        {
            "status": "VERIFIED",
            "qualified": True,
            "stateSource": "RUN_ARTIFACT",
            "reasonCode": "EXACT_RUN_ARTIFACT_VALID",
            "reason": "An exact run-bound four-stage verification artifact is current and validated.",
        }
    )
    return result
