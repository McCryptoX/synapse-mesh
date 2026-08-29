import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import run_disposable_verification as host_runner
from verification.worker import verify_bundle as worker


def _archivable_artifact(*, completed_at: str = "2026-08-27T12:00:00Z") -> dict:
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "synapse-bundle-verification-run",
        "contractVersion": "bundle-4-stage-v1",
        "bundleId": "bundle_test_archive_001",
        "bundleSha256": "b" * 64,
        "outcome": "PASSED",
        "completedAt": completed_at,
    }


def _inspection_fixture() -> tuple[dict, dict, dict]:
    image_id = f"sha256:{'a' * 64}"
    image = {"Id": image_id}
    raw_report = {
        "controlsObserved": {
            "uid": 10001,
            "gid": 10001,
            "capabilitiesDropped": True,
            "noNewPrivileges": True,
            "seccompMode": "2",
            "rootFilesystemReadOnly": True,
            "workspaceExecutable": True,
            "workspaceNoSuid": True,
            "workspaceNoDev": True,
            "outputExecutable": False,
            "onlyLoopbackInterface": True,
            "sensitiveEnvironmentPresent": False,
            "productionPathsPresent": False,
            "dockerSocketPresent": False,
            "workspaceSizeBytes": host_runner.WORKSPACE_LIMIT_BYTES,
            "memoryMaxBytes": host_runner.MEMORY_LIMIT_BYTES,
            "memorySwapMaxBytes": 0,
            "pidsMax": host_runner.PIDS_LIMIT,
        }
    }
    inspection = {
        "Image": image_id,
        "Config": {
            "User": "10001:10001",
            "Env": [
                "HOME=/work",
                "LANG=C.UTF-8",
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE=1",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges=true"],
            "PidsLimit": host_runner.PIDS_LIMIT,
            "Memory": host_runner.MEMORY_LIMIT_BYTES,
            "MemorySwap": host_runner.MEMORY_LIMIT_BYTES,
            "NanoCpus": host_runner.NANO_CPUS,
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "CgroupnsMode": "private",
            "UsernsMode": "",
            "Binds": None,
            "Mounts": None,
            "Devices": [],
            "DeviceRequests": None,
            "LogConfig": {"Type": "none"},
            "Tmpfs": {
                "/work": (
                    f"rw,nosuid,nodev,exec,size={host_runner.WORKSPACE_LIMIT_BYTES},"
                    "uid=10001,gid=10001,mode=0700"
                ),
                "/output": (
                    f"rw,nosuid,nodev,noexec,size={host_runner.OUTPUT_LIMIT_BYTES},"
                    "uid=10001,gid=10001,mode=0700"
                ),
            },
        },
        "State": {"ExitCode": 0, "OOMKilled": False, "Error": ""},
        "Mounts": [],
    }
    return inspection, image, raw_report


def test_allowlisted_target_is_bound_to_current_bundle_bytes():
    target = host_runner._load_target("httpx-0.28.1-asgi-transport")

    assert target["bundleId"] == "bundle_httpx_028_asgi_transport_001"
    assert target["bundleSha256"] == hashlib.sha256(
        target["_bundlePath"].read_bytes()
    ).hexdigest()
    assert host_runner._source_revision(target).startswith("sha256:")


def test_container_control_inspection_accepts_only_the_exact_profile():
    inspection, image, raw_report = _inspection_fixture()

    controls = host_runner._inspect_controls(inspection, image, raw_report)

    assert controls["networkMode"] == "none"
    assert controls["bindMountCount"] == 0
    assert controls["hostDockerSocketMounted"] is False
    assert controls["seccompMode"] == "filter"

    inspection["HostConfig"]["NetworkMode"] = "bridge"
    with pytest.raises(host_runner.JobFailure):
        host_runner._inspect_controls(inspection, image, raw_report)


def test_container_control_inspection_rejects_bind_mount_and_sensitive_env():
    inspection, image, raw_report = _inspection_fixture()
    inspection["Mounts"] = [
        {"Type": "bind", "Source": "/opt/synapse-mesh/data", "Destination": "/data"}
    ]
    with pytest.raises(host_runner.JobFailure):
        host_runner._inspect_controls(inspection, image, raw_report)

    inspection, image, raw_report = _inspection_fixture()
    inspection["Config"]["Env"].append("API_TOKEN=not-a-real-secret")
    with pytest.raises(host_runner.JobFailure):
        host_runner._inspect_controls(inspection, image, raw_report)


def test_worker_strictly_applies_the_allowlisted_httpx_diff(tmp_path: Path, monkeypatch):
    job_root = tmp_path / "job"
    monkeypatch.setattr(worker, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(worker, "JOB_ROOT", job_root)
    monkeypatch.setattr(worker, "STAGE_OUTPUT_ROOT", tmp_path / "outputs")
    bundle = json.loads(
        Path("bundles/golden/bundle_httpx_028_asgi_transport.json").read_text(
            encoding="utf-8"
        )
    )
    worker._require_contract_shape(bundle)
    worker._materialize_workspace(bundle["verification"]["workspaceFiles"])
    target = worker._safe_workspace_path(bundle["patch"]["targetFile"])

    assert target is not None
    assert worker._apply_patch_unified(target, bundle["patch"]["unifiedDiff"])
    assert "ASGITransport" in target.read_text(encoding="utf-8")
    assert not worker._apply_patch_unified(target, bundle["patch"]["unifiedDiff"])


def test_worker_exception_class_gate_is_fail_closed():
    fingerprint = {
        "errorSignature": "TypeError: expected failure",
        "regex": "expected failure",
    }

    assert worker._signature_matches(fingerprint, "TypeError: expected failure") == (
        True,
        True,
    )
    assert worker._signature_matches(fingerprint, "ValueError: expected failure") == (
        False,
        False,
    )


def test_worker_image_is_pinned_and_contains_no_application_or_host_mount():
    dockerfile = Path("verification/worker/Dockerfile").read_text(encoding="utf-8")
    orchestrator = Path("scripts/run_disposable_verification.py").read_text(
        encoding="utf-8"
    )

    assert "python:3.12.13-slim-bookworm@sha256:" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "COPY app" not in dockerfile
    assert "docker.sock" not in dockerfile
    assert '"--network",\n                "none"' in orchestrator
    assert '"--read-only"' in orchestrator
    assert '"--cap-drop"' in orchestrator
    assert '"--log-driver",\n                "none"' in orchestrator


def test_application_gate_uses_no_host_mounts_with_private_tmp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    artifact = _archivable_artifact()
    calls: list[list[str]] = []
    streamed_inputs: list[str] = []

    def fake_run(command, *, capture_output=False, check=True, input_text=None):
        calls.append(command)
        if input_text is not None:
            streamed_inputs.append(input_text)
        if command[:2] == ["docker", "create"]:
            return type("Result", (), {"returncode": 0, "stdout": "container-id\n", "stderr": ""})()
        if command[:2] == ["docker", "wait"]:
            return type("Result", (), {"returncode": 0, "stdout": "0\n", "stderr": ""})()
        if command[:2] == ["docker", "inspect"]:
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": json.dumps(
                        [{"State": {"ExitCode": 0, "OOMKilled": False, "Error": ""}}]
                    ),
                    "stderr": "",
                },
            )()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(host_runner, "_run", fake_run)
    host_runner._validate_with_application_gate(
        {"_bundlePath": bundle_path},
        artifact,
        f"sha256:{'a' * 64}",
    )

    assert [command[:2] for command in calls] == [
        ["docker", "create"],
        ["docker", "start"],
        ["docker", "exec"],
        ["docker", "exec"],
        ["docker", "exec"],
        ["docker", "exec"],
        ["docker", "exec"],
        ["docker", "wait"],
        ["docker", "inspect"],
        ["docker", "rm"],
    ]
    assert streamed_inputs[0] == "{}"
    assert json.loads(streamed_inputs[1]) == artifact
    create_command = calls[0]
    assert "--network" in create_command
    assert "none" in create_command
    assert "--read-only" in create_command
    assert "--tmpfs" in create_command
    assert any(value.startswith("/verify:rw,nosuid,nodev,noexec") for value in create_command)
    assert "--mount" not in create_command
    assert "--volume" not in create_command


def test_publication_archives_current_and_replacement_before_updating_pointer(
    tmp_path: Path,
):
    output_dir = tmp_path / "runs"
    first = _archivable_artifact(completed_at="2026-08-27T12:00:00Z")
    second = _archivable_artifact(completed_at="2026-08-28T12:00:00Z")

    previous_umask = os.umask(0o027)
    try:
        current_path = host_runner._write_artifact(output_dir, first)
    finally:
        os.umask(previous_umask)
    first_digest = host_runner._canonical_artifact_sha256(first)
    first_archive = (
        output_dir / "archive" / first["bundleId"] / f"{first_digest}.json"
    )
    assert json.loads(current_path.read_text(encoding="utf-8")) == first
    assert json.loads(first_archive.read_text(encoding="utf-8")) == first

    previous_umask = os.umask(0o027)
    try:
        host_runner._write_artifact(output_dir, second)
    finally:
        os.umask(previous_umask)
    second_digest = host_runner._canonical_artifact_sha256(second)
    second_archive = (
        output_dir / "archive" / second["bundleId"] / f"{second_digest}.json"
    )

    assert json.loads(current_path.read_text(encoding="utf-8")) == second
    assert json.loads(first_archive.read_text(encoding="utf-8")) == first
    assert json.loads(second_archive.read_text(encoding="utf-8")) == second
    assert current_path.stat().st_mode & 0o777 == 0o444
    assert first_archive.stat().st_mode & 0o777 == 0o444
    assert second_archive.stat().st_mode & 0o777 == 0o444
    assert first_archive.parent.stat().st_mode & 0o777 == 0o755


def test_publication_refuses_malformed_or_symlinked_current_artifact(tmp_path: Path):
    artifact = _archivable_artifact()

    malformed_dir = tmp_path / "malformed"
    malformed_dir.mkdir()
    malformed_current = malformed_dir / f"{artifact['bundleId']}.json"
    malformed_current.write_text("{not-json", encoding="utf-8")
    with pytest.raises(host_runner.JobFailure, match="malformed JSON"):
        host_runner._write_artifact(malformed_dir, artifact)
    assert malformed_current.read_text(encoding="utf-8") == "{not-json"

    symlink_dir = tmp_path / "symlink"
    symlink_dir.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("do-not-change", encoding="utf-8")
    symlink_current = symlink_dir / f"{artifact['bundleId']}.json"
    symlink_current.symlink_to(target)
    with pytest.raises(host_runner.JobFailure, match="symlinked artifact"):
        host_runner._write_artifact(symlink_dir, artifact)
    assert target.read_text(encoding="utf-8") == "do-not-change"


def test_publication_compares_preexisting_immutable_archive_bytes(tmp_path: Path):
    output_dir = tmp_path / "runs"
    artifact = _archivable_artifact()
    current_path = host_runner._write_artifact(output_dir, artifact)

    # Re-publishing identical evidence is idempotent: O_EXCL observes the
    # existing archive and accepts only its exact deterministic bytes.
    host_runner._write_artifact(output_dir, artifact)

    digest = host_runner._canonical_artifact_sha256(artifact)
    archive_path = output_dir / "archive" / artifact["bundleId"] / f"{digest}.json"
    archive_path.chmod(0o644)
    archive_path.write_text("{}\n", encoding="utf-8")
    current_before = current_path.read_bytes()

    with pytest.raises(host_runner.JobFailure, match="immutable file mismatch"):
        host_runner._write_artifact(output_dir, artifact)
    assert current_path.read_bytes() == current_before
