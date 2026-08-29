"""Validation of run-bound verification artifacts for curated bundles.

Bundle metadata describes an intended contract. It does not prove that the
contract ran. Publication as VERIFIED therefore also requires a separate,
machine-readable run artifact bound to the exact bundle bytes and toolchain.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT
from scripts.synapse_reverify import bundle_has_recorded_verification_contract


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ARTIFACTS_DIR = PROJECT_ROOT / "evidence" / "runs"
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CONTENT_REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BUNDLE_ID_RE = re.compile(r"^(?:bundle|draft)_[a-z0-9][a-z0-9_-]{2,119}$")
SEMANTIC_REJECTION_KINDS = {
    "ASSERTION_FAILURE",
    "COMPILER_DIAGNOSTIC",
    "RUNTIME_FAILURE",
}


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _has_valid_source_revision(artifact: dict[str, Any]) -> bool:
    kind = artifact.get("sourceRevisionKind")
    revision = artifact.get("sourceRevision")
    if not isinstance(revision, str):
        return False
    if kind == "git-commit":
        return GIT_REVISION_RE.fullmatch(revision) is not None
    if kind == "source-tree-sha256":
        return CONTENT_REVISION_RE.fullmatch(revision) is not None
    return False


def _has_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


def _pin_matches(actual: Any, declared: Any) -> bool:
    if not isinstance(actual, str) or not isinstance(declared, str):
        return False
    val = declared.strip()
    if not val:
        return False
    try:
        if val.startswith(("<", ">", "=", "!", "~")) or "," in val:
            return Version(actual) in SpecifierSet(val)
        return Version(actual) == Version(val.lstrip("v"))
    except (InvalidSpecifier, InvalidVersion, TypeError, ValueError):
        return False


def _required_toolchain_versions(bundle: dict[str, Any]) -> dict[str, str]:
    scope = bundle.get("scope") or {}
    patch = bundle.get("patch") or {}
    required: dict[str, str] = {}
    runtime = scope.get("runtime")
    runtime_version = scope.get("runtimeVersion")
    if isinstance(runtime, str) and isinstance(runtime_version, str):
        required[runtime] = runtime_version
    for package, version in (patch.get("pinnedDependencies") or {}).items():
        if isinstance(package, str) and isinstance(version, str):
            required[package] = version
    return required


def load_valid_run_artifact(
    bundle: dict[str, Any],
    bundle_path: Path,
    *,
    artifacts_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Return a validated artifact or ``None`` on any ambiguity.

    The validator is intentionally structural and fail closed. It does not
    execute code, infer missing controls, accept infrastructure failures as
    mutation kills, or copy an attestation between bundle revisions.
    """
    if not bundle_has_recorded_verification_contract(bundle):
        return None

    bundle_id = bundle.get("bundleId")
    if not isinstance(bundle_id, str) or BUNDLE_ID_RE.fullmatch(bundle_id) is None:
        return None

    try:
        if (
            not bundle_path.is_file()
            or bundle_path.is_symlink()
            or bundle_path.stat().st_size > MAX_BUNDLE_BYTES
        ):
            return None
        bundle_bytes = bundle_path.read_bytes()
    except OSError:
        return None

    root = (artifacts_dir or RUN_ARTIFACTS_DIR).resolve()
    artifact_path = root / f"{bundle_id}.json"
    try:
        # Check the directory entry before resolving it. ``resolved.is_symlink()``
        # can never detect the symlink that was followed by ``resolve()``.
        if artifact_path.is_symlink():
            return None
        resolved = artifact_path.resolve(strict=True)
        if (
            resolved.parent != root
            or not resolved.is_file()
            or resolved.stat().st_size > MAX_ARTIFACT_BYTES
        ):
            return None
        artifact = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RuntimeError):
        return None

    if not isinstance(artifact, dict):
        return None
    started_at = _parse_aware_timestamp(artifact.get("startedAt"))
    completed_at = _parse_aware_timestamp(artifact.get("completedAt"))
    if not all(
        (
            artifact.get("schemaVersion") == "1.0.0",
            artifact.get("artifactType") == "synapse-bundle-verification-run",
            artifact.get("contractVersion") == VERIFIED_EVIDENCE_CONTRACT,
            artifact.get("bundleId") == bundle_id,
            artifact.get("bundleSha256") == hashlib.sha256(bundle_bytes).hexdigest(),
            artifact.get("outcome") == "PASSED",
            started_at is not None,
            completed_at is not None,
            started_at is not None
            and completed_at is not None
            and completed_at >= started_at,
            completed_at is not None
            and completed_at <= datetime.now(timezone.utc) + timedelta(minutes=5),
            _has_valid_source_revision(artifact),
            _has_sha256(artifact.get("dependencyLockSha256")),
            _has_sha256(artifact.get("rawReportSha256")),
            isinstance(artifact.get("publicationValidatorImageDigest"), str)
            and IMAGE_DIGEST_RE.fullmatch(
                artifact["publicationValidatorImageDigest"]
            )
            is not None,
        )
    ):
        return None

    runner = artifact.get("runner")
    if not isinstance(runner, dict) or not all(
        (
            isinstance(runner.get("imageDigest"), str)
            and IMAGE_DIGEST_RE.fullmatch(runner["imageDigest"]) is not None,
            isinstance(runner.get("runnerVersion"), str)
            and bool(runner["runnerVersion"].strip()),
            runner.get("networkMode") == "none",
            runner.get("rootFilesystemReadOnly") is True,
            runner.get("nonRoot") is True,
            runner.get("capabilitiesDropped") is True,
            runner.get("noNewPrivileges") is True,
            runner.get("productionDataMounted") is False,
            runner.get("credentialsPresent") is False,
            runner.get("workspaceExecutable") is True,
            runner.get("workspaceNoSuid") is True,
            runner.get("workspaceNoDev") is True,
            runner.get("outputExecutable") is False,
            runner.get("pidNamespacePrivate") is True,
            runner.get("mountNamespacePrivate") is True,
            runner.get("cgroupNamespacePrivate") is True,
            isinstance(runner.get("userNamespaceMode"), str)
            and bool(runner["userNamespaceMode"].strip()),
            runner.get("hostDockerSocketMounted") is False,
            runner.get("bindMountCount") == 0,
            runner.get("privileged") is False,
            runner.get("seccompMode") == "filter",
            runner.get("oomKilled") is False,
            isinstance(runner.get("workspaceSizeLimitBytes"), int)
            and 0 < runner["workspaceSizeLimitBytes"] <= 2 * 1024 * 1024 * 1024,
            isinstance(runner.get("memoryLimitBytes"), int)
            and 0 < runner["memoryLimitBytes"] <= 16 * 1024 * 1024 * 1024,
            runner.get("memorySwapLimitBytes") == runner.get("memoryLimitBytes"),
            isinstance(runner.get("pidsLimit"), int)
            and 0 < runner["pidsLimit"] <= 4096,
            isinstance(runner.get("cpuLimit"), (int, float))
            and not isinstance(runner.get("cpuLimit"), bool)
            and 0 < runner["cpuLimit"] <= 64,
        )
    ):
        return None

    controls = artifact.get("controlsObserved")
    if not isinstance(controls, dict) or not all(
        (
            controls.get("uid") == 10001,
            controls.get("gid") == 10001,
            controls.get("nonRoot") is True,
            controls.get("capabilitiesDropped") is True,
            controls.get("noNewPrivileges") is True,
            controls.get("seccompMode") == "2",
            controls.get("rootFilesystemReadOnly") is True,
            controls.get("workspaceExecutable") is True,
            controls.get("workspaceNoSuid") is True,
            controls.get("workspaceNoDev") is True,
            controls.get("outputExecutable") is False,
            controls.get("onlyLoopbackInterface") is True,
            controls.get("networkInterfaces") == ["lo"],
            controls.get("sensitiveEnvironmentPresent") is False,
            controls.get("productionPathsPresent") is False,
            controls.get("dockerSocketPresent") is False,
            controls.get("workspaceSizeBytes")
            == runner.get("workspaceSizeLimitBytes"),
            controls.get("memoryMaxBytes") == runner.get("memoryLimitBytes"),
            controls.get("memorySwapMaxBytes") == 0,
            controls.get("pidsMax") == runner.get("pidsLimit"),
        )
    ):
        return None

    observed_toolchains = artifact.get("toolchainVersions")
    if not isinstance(observed_toolchains, dict):
        return None
    required_toolchains = _required_toolchain_versions(bundle)
    if not required_toolchains or any(
        not _pin_matches(observed_toolchains.get(name), version)
        for name, version in required_toolchains.items()
    ):
        return None

    stages = artifact.get("stages")
    if not isinstance(stages, dict):
        return None
    verification = bundle.get("verification") or {}
    patch = bundle.get("patch") or {}
    pre = stages.get("pre")
    patch_stage = stages.get("patch")
    post = stages.get("post")
    mutations = stages.get("mutations")
    if not all(isinstance(value, dict) for value in (pre, patch_stage, post)):
        return None
    if not isinstance(mutations, list):
        return None

    if not all(
        (
            pre.get("exitCode") == verification.get("expectedPreExit"),
            pre.get("exitCode") not in (-1, 0),
            pre.get("signatureMatched") is True,
            pre.get("exceptionClassMatched") is True,
            _has_sha256(pre.get("outputSha256")),
            patch_stage.get("strictUnifiedDiffApplied") is True,
            patch_stage.get("diffSha256")
            == hashlib.sha256(str(patch.get("unifiedDiff") or "").encode("utf-8")).hexdigest(),
            post.get("exitCode") == verification.get("expectedPostExit") == 0,
            post.get("passed") is True,
            _has_sha256(post.get("outputSha256")),
        )
    ):
        return None

    declared_mutations = verification.get("mutations") or []
    declared_by_id = {
        mutation.get("id"): mutation
        for mutation in declared_mutations
        if isinstance(mutation, dict)
    }
    declared_ids = set(declared_by_id)
    observed_ids: set[str] = set()
    if len(declared_ids) < 2 or len(mutations) != len(declared_ids):
        return None
    for mutation in mutations:
        if not isinstance(mutation, dict):
            return None
        mutation_id = mutation.get("id")
        if (
            not isinstance(mutation_id, str)
            or mutation_id not in declared_ids
            or mutation_id in observed_ids
            or mutation.get("strictUnifiedDiffApplied") is not True
            or mutation.get("rejected") is not True
            or not isinstance(mutation.get("exitCode"), int)
            or mutation.get("exitCode") in (-1, 0)
            or mutation.get("rejectionKind") not in SEMANTIC_REJECTION_KINDS
            or not _has_sha256(mutation.get("outputSha256"))
            or mutation.get("diffSha256")
            != hashlib.sha256(
                str(declared_by_id[mutation_id].get("unifiedDiff") or "").encode("utf-8")
            ).hexdigest()
        ):
            return None
        observed_ids.add(mutation_id)
    if observed_ids != declared_ids:
        return None

    return artifact


def bundle_has_publishable_verification_contract(
    bundle: dict[str, Any],
    bundle_path: Path,
    *,
    artifacts_dir: Path | None = None,
) -> bool:
    """Require both a structured record and a valid exact-run artifact."""
    return load_valid_run_artifact(
        bundle,
        bundle_path,
        artifacts_dir=artifacts_dir,
    ) is not None
