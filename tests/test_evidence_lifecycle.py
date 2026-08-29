import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.evidence_lifecycle import (
    FRESHNESS_MAX_AGE,
    canonical_artifact_sha256,
    evaluate_evidence_lifecycle,
)


BASE_COMPLETED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
BASE_NOW = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bundle(
    bundle_id: str = "bundle_lifecycle_source_001",
    *,
    package: str = "httpx",
    runtime: str = "python",
) -> dict:
    return {
        "bundleId": bundle_id,
        "scope": {"package": package, "runtime": runtime},
    }


def _artifact(
    *,
    bundle_sha256: str = "a" * 64,
    completed_at: datetime = BASE_COMPLETED_AT,
) -> dict:
    return {
        "bundleSha256": bundle_sha256,
        "completedAt": _iso_z(completed_at),
    }


def _lifecycle_record(
    bundle: dict,
    artifact: dict,
    *,
    state: str = "DISPUTED",
    effective_at: datetime = BASE_COMPLETED_AT + timedelta(days=1),
    **extra: object,
) -> dict:
    record = {
        "schemaVersion": "1.0.0",
        "recordType": "synapse-bundle-evidence-lifecycle",
        "bundleId": bundle["bundleId"],
        "bundleSha256": artifact["bundleSha256"],
        "canonicalRunArtifactSha256": canonical_artifact_sha256(artifact),
        "canonicalization": "synapse-json-v1",
        "state": state,
        "effectiveAt": _iso_z(effective_at),
        "reasonCode": "EVIDENCE_CHALLENGED",
        "reason": "A reviewed challenge prevents current evidence qualification.",
    }
    record.update(extra)
    return record


def _write_record(lifecycle_dir: Path, record: dict) -> Path:
    lifecycle_dir.mkdir(parents=True, exist_ok=True)
    path = lifecycle_dir / f"{record['bundleId']}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _evaluate(
    bundle: dict,
    artifact: dict,
    *,
    lifecycle_dir: Path,
    now: datetime = BASE_NOW,
    bundles_dir: Path | None = None,
    artifacts_dir: Path | None = None,
) -> dict:
    return evaluate_evidence_lifecycle(
        bundle,
        artifact,
        lifecycle_dir=lifecycle_dir,
        bundles_dir=bundles_dir,
        artifacts_dir=artifacts_dir,
        now=now,
    )


def test_freshness_is_current_until_exact_boundary(tmp_path: Path):
    bundle = _bundle()
    artifact = _artifact()
    lifecycle_dir = tmp_path / "lifecycle"
    fresh_until = BASE_COMPLETED_AT + FRESHNESS_MAX_AGE

    just_before = _evaluate(
        bundle,
        artifact,
        lifecycle_dir=lifecycle_dir,
        now=fresh_until - timedelta(microseconds=1),
    )
    at_boundary = _evaluate(
        bundle,
        artifact,
        lifecycle_dir=lifecycle_dir,
        now=fresh_until,
    )

    assert just_before["status"] == "VERIFIED"
    assert just_before["qualified"] is True
    assert just_before["freshUntil"] == _iso_z(fresh_until)
    assert at_boundary["status"] == "STALE"
    assert at_boundary["qualified"] is False
    assert at_boundary["reasonCode"] == "RUN_ARTIFACT_STALE"


def test_timezone_naive_evaluation_time_fails_closed(tmp_path: Path):
    result = _evaluate(
        _bundle(),
        _artifact(),
        lifecycle_dir=tmp_path / "lifecycle",
        now=datetime(2026, 1, 3),
    )

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "INVALID_EVALUATION_TIME"


def test_run_timestamp_too_far_in_future_fails_closed(tmp_path: Path):
    result = _evaluate(
        _bundle(),
        _artifact(completed_at=BASE_NOW + timedelta(minutes=5, microseconds=1)),
        lifecycle_dir=tmp_path / "lifecycle",
        now=BASE_NOW,
    )

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "RUN_TIMESTAMP_IN_FUTURE"


def test_malformed_lifecycle_json_fails_closed_as_unknown(tmp_path: Path):
    bundle = _bundle()
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    (lifecycle_dir / f"{bundle['bundleId']}.json").write_text(
        "{not-json", encoding="utf-8"
    )

    result = _evaluate(bundle, _artifact(), lifecycle_dir=lifecycle_dir)

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "LIFECYCLE_RECORD_INVALID"


def test_symlinked_lifecycle_record_fails_closed_as_unknown(tmp_path: Path):
    bundle = _bundle()
    artifact = _artifact()
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps(_lifecycle_record(bundle, artifact)), encoding="utf-8"
    )
    (lifecycle_dir / f"{bundle['bundleId']}.json").symlink_to(outside)

    result = _evaluate(bundle, artifact, lifecycle_dir=lifecycle_dir)

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "LIFECYCLE_RECORD_INVALID"


def test_lifecycle_record_with_unknown_field_fails_closed(tmp_path: Path):
    bundle = _bundle()
    artifact = _artifact()
    lifecycle_dir = tmp_path / "lifecycle"
    _write_record(
        lifecycle_dir,
        _lifecycle_record(bundle, artifact, unreviewedField="must-not-be-ignored"),
    )

    result = _evaluate(bundle, artifact, lifecycle_dir=lifecycle_dir)

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "LIFECYCLE_RECORD_INVALID"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        pytest.param("bundleSha256", "b" * 64, id="bundle-digest-mismatch"),
        pytest.param(
            "canonicalRunArtifactSha256",
            "c" * 64,
            id="artifact-digest-mismatch",
        ),
        pytest.param(
            "effectiveAt",
            "2025-12-31T23:59:59Z",
            id="effective-before-run",
        ),
        pytest.param(
            "effectiveAt",
            "2026-01-03T00:05:00.000001Z",
            id="effective-too-far-in-future",
        ),
        pytest.param(
            "effectiveAt",
            "2026-01-02T00:00:00",
            id="effective-timezone-naive",
        ),
    ],
)
def test_invalid_binding_or_effective_time_fails_closed(
    tmp_path: Path,
    field: str,
    invalid_value: str,
):
    bundle = _bundle()
    artifact = _artifact()
    lifecycle_dir = tmp_path / "lifecycle"
    record = _lifecycle_record(bundle, artifact)
    record[field] = invalid_value
    _write_record(lifecycle_dir, record)

    result = _evaluate(bundle, artifact, lifecycle_dir=lifecycle_dir)

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "LIFECYCLE_RECORD_INVALID"


def test_valid_dispute_overrides_otherwise_current_artifact(tmp_path: Path):
    bundle = _bundle()
    artifact = _artifact()
    lifecycle_dir = tmp_path / "lifecycle"
    record = _lifecycle_record(bundle, artifact)
    _write_record(lifecycle_dir, record)

    result = _evaluate(bundle, artifact, lifecycle_dir=lifecycle_dir)

    assert result["status"] == "DISPUTED"
    assert result["qualified"] is False
    assert result["artifactAvailable"] is True
    assert result["stateSource"] == "LIFECYCLE_RECORD"
    assert result["reasonCode"] == "EVIDENCE_CHALLENGED"
    assert result["record"] == record


def test_broken_marker_without_recheck_failure_artifact_is_invalid(tmp_path: Path):
    bundle = _bundle()
    artifact = _artifact()
    lifecycle_dir = tmp_path / "lifecycle"
    _write_record(
        lifecycle_dir,
        _lifecycle_record(bundle, artifact, state="BROKEN"),
    )

    result = _evaluate(bundle, artifact, lifecycle_dir=lifecycle_dir)

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "LIFECYCLE_RECORD_INVALID"


def _write_bundle(bundles_dir: Path, bundle: dict, filename: str) -> Path:
    bundles_dir.mkdir(parents=True, exist_ok=True)
    path = bundles_dir / filename
    path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
    return path


def _supersession_record(
    bundle: dict,
    artifact: dict,
    successor_bundle: dict,
    successor_path: Path,
    successor_artifact: dict,
    *,
    effective_at: datetime = BASE_COMPLETED_AT + timedelta(days=1),
) -> dict:
    return _lifecycle_record(
        bundle,
        artifact,
        state="SUPERSEDED",
        effective_at=effective_at,
        reasonCode="REPLACED_BY_CURRENT_RECORD",
        reason="A current exact-scope record replaces this evidence.",
        supersededByBundleId=successor_bundle["bundleId"],
        supersededByBundleSha256=hashlib.sha256(successor_path.read_bytes()).hexdigest(),
        supersededByCanonicalRunArtifactSha256=canonical_artifact_sha256(
            successor_artifact
        ),
    )


def _install_artifact_loader(monkeypatch: pytest.MonkeyPatch, artifacts: dict[str, dict]):
    from app.core import run_artifacts

    def fake_load_valid_run_artifact(bundle: dict, _bundle_path: Path, **_kwargs):
        return artifacts.get(bundle.get("bundleId"))

    monkeypatch.setattr(
        run_artifacts, "load_valid_run_artifact", fake_load_valid_run_artifact
    )


def test_supersession_requires_a_unique_current_exact_scope_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bundles_dir = tmp_path / "bundles"
    lifecycle_dir = tmp_path / "lifecycle"
    source = _bundle()
    source_path = _write_bundle(bundles_dir, source, "source.json")
    source_artifact = _artifact(
        bundle_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    successor = _bundle("bundle_lifecycle_successor_001")
    successor_path = _write_bundle(bundles_dir, successor, "successor.json")
    successor_artifact = _artifact(
        bundle_sha256=hashlib.sha256(successor_path.read_bytes()).hexdigest(),
        completed_at=BASE_COMPLETED_AT + timedelta(hours=1),
    )
    _install_artifact_loader(
        monkeypatch,
        {
            source["bundleId"]: source_artifact,
            successor["bundleId"]: successor_artifact,
        },
    )
    record = _supersession_record(
        source,
        source_artifact,
        successor,
        successor_path,
        successor_artifact,
    )
    _write_record(lifecycle_dir, record)

    result = _evaluate(
        source,
        source_artifact,
        lifecycle_dir=lifecycle_dir,
        bundles_dir=bundles_dir,
        artifacts_dir=tmp_path / "runs",
    )

    assert result["status"] == "SUPERSEDED"
    assert result["qualified"] is False
    assert result["reasonCode"] == "REPLACED_BY_CURRENT_RECORD"
    assert result["record"]["supersededByBundleId"] == successor["bundleId"]


@pytest.mark.parametrize("failure_mode", ["missing", "ambiguous", "scope", "stale"])
def test_invalid_supersession_target_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
):
    bundles_dir = tmp_path / "bundles"
    lifecycle_dir = tmp_path / "lifecycle"
    source = _bundle()
    source_path = _write_bundle(bundles_dir, source, "source.json")
    source_artifact = _artifact(
        bundle_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    successor = _bundle(
        "bundle_lifecycle_successor_001",
        package="numpy" if failure_mode == "scope" else "httpx",
    )
    successor_path = _write_bundle(bundles_dir, successor, "successor.json")
    successor_completed_at = (
        BASE_NOW - FRESHNESS_MAX_AGE
        if failure_mode == "stale"
        else BASE_COMPLETED_AT + timedelta(hours=1)
    )
    successor_artifact = _artifact(
        bundle_sha256=hashlib.sha256(successor_path.read_bytes()).hexdigest(),
        completed_at=successor_completed_at,
    )
    _install_artifact_loader(
        monkeypatch,
        {
            source["bundleId"]: source_artifact,
            successor["bundleId"]: successor_artifact,
        },
    )
    record = _supersession_record(
        source,
        source_artifact,
        successor,
        successor_path,
        successor_artifact,
    )
    _write_record(lifecycle_dir, record)

    if failure_mode == "missing":
        successor_path.unlink()
    elif failure_mode == "ambiguous":
        _write_bundle(bundles_dir, successor, "duplicate-successor.json")

    result = _evaluate(
        source,
        source_artifact,
        lifecycle_dir=lifecycle_dir,
        bundles_dir=bundles_dir,
        artifacts_dir=tmp_path / "runs",
    )

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "SUPERSESSION_TARGET_NOT_CURRENT"


def test_supersession_cycle_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bundles_dir = tmp_path / "bundles"
    lifecycle_dir = tmp_path / "lifecycle"
    first = _bundle("bundle_lifecycle_cycle_a_001")
    second = _bundle("bundle_lifecycle_cycle_b_001")
    first_path = _write_bundle(bundles_dir, first, "first.json")
    second_path = _write_bundle(bundles_dir, second, "second.json")
    first_artifact = _artifact(
        bundle_sha256=hashlib.sha256(first_path.read_bytes()).hexdigest()
    )
    second_artifact = _artifact(
        bundle_sha256=hashlib.sha256(second_path.read_bytes()).hexdigest()
    )
    _install_artifact_loader(
        monkeypatch,
        {
            first["bundleId"]: first_artifact,
            second["bundleId"]: second_artifact,
        },
    )
    _write_record(
        lifecycle_dir,
        _supersession_record(
            first, first_artifact, second, second_path, second_artifact
        ),
    )
    _write_record(
        lifecycle_dir,
        _supersession_record(
            second, second_artifact, first, first_path, first_artifact
        ),
    )

    result = _evaluate(
        first,
        first_artifact,
        lifecycle_dir=lifecycle_dir,
        bundles_dir=bundles_dir,
        artifacts_dir=tmp_path / "runs",
    )

    assert result["status"] == "UNKNOWN"
    assert result["qualified"] is False
    assert result["reasonCode"] == "SUPERSESSION_TARGET_NOT_CURRENT"
