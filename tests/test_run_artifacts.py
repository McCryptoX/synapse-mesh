import hashlib
import json
import shutil
from pathlib import Path

from app.core.run_artifacts import (
    bundle_has_publishable_verification_contract,
    load_valid_run_artifact,
)


SOURCE_BUNDLE = Path("bundles/golden/bundle_httpx_028_asgi_transport.json")


def _fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    bundle_path = tmp_path / "bundle.json"
    shutil.copyfile(SOURCE_BUNDLE, bundle_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    artifacts_dir = tmp_path / "runs"
    artifacts_dir.mkdir()
    artifact_path = artifacts_dir / f"{bundle['bundleId']}.json"
    scope = bundle["scope"]
    patch = bundle["patch"]
    verification = bundle["verification"]
    artifact = {
        "schemaVersion": "1.0.0",
        "artifactType": "synapse-bundle-verification-run",
        "contractVersion": "bundle-4-stage-v1",
        "bundleId": bundle["bundleId"],
        "bundleSha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "outcome": "PASSED",
        "startedAt": "2026-08-27T12:00:00+00:00",
        "completedAt": "2026-08-27T12:01:00+00:00",
        "sourceRevisionKind": "source-tree-sha256",
        "sourceRevision": f"sha256:{'a' * 64}",
        "dependencyLockSha256": "f" * 64,
        "rawReportSha256": "1" * 64,
        "publicationValidatorImageDigest": f"sha256:{'2' * 64}",
        "runner": {
            "imageDigest": f"sha256:{'b' * 64}",
            "runnerVersion": "test-runner-v1",
            "networkMode": "none",
            "rootFilesystemReadOnly": True,
            "nonRoot": True,
            "capabilitiesDropped": True,
            "noNewPrivileges": True,
            "productionDataMounted": False,
            "credentialsPresent": False,
            "workspaceExecutable": True,
            "workspaceNoSuid": True,
            "workspaceNoDev": True,
            "outputExecutable": False,
            "pidNamespacePrivate": True,
            "mountNamespacePrivate": True,
            "cgroupNamespacePrivate": True,
            "userNamespaceMode": "daemon-default-host-uid",
            "hostDockerSocketMounted": False,
            "bindMountCount": 0,
            "privileged": False,
            "seccompMode": "filter",
            "oomKilled": False,
            "workspaceSizeLimitBytes": 64 * 1024 * 1024,
            "memoryLimitBytes": 1024 * 1024 * 1024,
            "memorySwapLimitBytes": 1024 * 1024 * 1024,
            "pidsLimit": 128,
            "cpuLimit": 2.0,
        },
        "toolchainVersions": {
            scope["runtime"]: scope["runtimeVersion"],
            **patch["pinnedDependencies"],
        },
        "stages": {
            "pre": {
                "exitCode": verification["expectedPreExit"],
                "signatureMatched": True,
                "exceptionClassMatched": True,
                "outputSha256": "c" * 64,
            },
            "patch": {
                "strictUnifiedDiffApplied": True,
                "diffSha256": hashlib.sha256(
                    patch["unifiedDiff"].encode("utf-8")
                ).hexdigest(),
            },
            "post": {
                "exitCode": verification["expectedPostExit"],
                "passed": True,
                "outputSha256": "d" * 64,
            },
            "mutations": [
                {
                    "id": mutation["id"],
                    "diffSha256": hashlib.sha256(
                        mutation["unifiedDiff"].encode("utf-8")
                    ).hexdigest(),
                    "strictUnifiedDiffApplied": True,
                    "exitCode": 1,
                    "rejected": True,
                    "rejectionKind": "ASSERTION_FAILURE",
                    "outputSha256": "e" * 64,
                }
                for mutation in verification["mutations"]
            ],
        },
        "controlsObserved": {
            "uid": 10001,
            "gid": 10001,
            "nonRoot": True,
            "capabilitiesDropped": True,
            "noNewPrivileges": True,
            "seccompMode": "2",
            "rootFilesystemReadOnly": True,
            "workspaceExecutable": True,
            "workspaceNoSuid": True,
            "workspaceNoDev": True,
            "outputExecutable": False,
            "onlyLoopbackInterface": True,
            "networkInterfaces": ["lo"],
            "sensitiveEnvironmentPresent": False,
            "productionPathsPresent": False,
            "dockerSocketPresent": False,
            "workspaceSizeBytes": 64 * 1024 * 1024,
            "memoryMaxBytes": 1024 * 1024 * 1024,
            "memorySwapMaxBytes": 0,
            "pidsMax": 128,
        },
    }
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    return bundle, bundle_path, artifacts_dir, artifact_path


def test_missing_artifact_fails_closed(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, artifact_path = _fixture(tmp_path)
    artifact_path.unlink()

    assert not bundle_has_publishable_verification_contract(
        bundle, bundle_path, artifacts_dir=artifacts_dir
    )


def test_exact_run_bound_artifact_is_accepted(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, _ = _fixture(tmp_path)

    artifact = load_valid_run_artifact(
        bundle, bundle_path, artifacts_dir=artifacts_dir
    )

    assert artifact is not None
    assert artifact["bundleId"] == bundle["bundleId"]


def test_artifact_is_bound_to_exact_bundle_bytes(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, _ = _fixture(tmp_path)
    bundle_path.write_bytes(bundle_path.read_bytes() + b"\n")

    assert not bundle_has_publishable_verification_contract(
        bundle, bundle_path, artifacts_dir=artifacts_dir
    )


def test_toolchain_mismatch_and_infrastructure_mutation_fail_closed(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, artifact_path = _fixture(tmp_path)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["toolchainVersions"]["httpx"] = "0.28.0"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None

    artifact["toolchainVersions"]["httpx"] = "0.28.1"
    artifact["stages"]["mutations"][0]["exitCode"] = -1
    artifact["stages"]["mutations"][0]["rejectionKind"] = "INFRASTRUCTURE_FAILURE"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None


def test_symlinked_artifact_is_rejected(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, artifact_path = _fixture(tmp_path)
    outside_artifact = tmp_path / "outside.json"
    artifact_path.replace(outside_artifact)
    artifact_path.symlink_to(outside_artifact)

    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None


def test_artifact_rejects_backwards_time_and_ambiguous_source_revision(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, artifact_path = _fixture(tmp_path)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["completedAt"] = "2026-08-27T11:59:00+00:00"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None

    artifact["completedAt"] = "2026-08-27T12:01:00+00:00"
    artifact["sourceRevisionKind"] = "unknown"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None


def test_artifact_rejects_mutation_diff_digest_mismatch(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, artifact_path = _fixture(tmp_path)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["stages"]["mutations"][0]["diffSha256"] = "0" * 64
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None


def test_artifact_rejects_missing_publication_chain_or_false_control(tmp_path: Path):
    bundle, bundle_path, artifacts_dir, artifact_path = _fixture(tmp_path)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact.pop("publicationValidatorImageDigest")
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None

    artifact["publicationValidatorImageDigest"] = f"sha256:{'2' * 64}"
    artifact["controlsObserved"]["onlyLoopbackInterface"] = False
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_valid_run_artifact(bundle, bundle_path, artifacts_dir=artifacts_dir) is None
