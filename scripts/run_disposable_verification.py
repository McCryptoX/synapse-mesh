#!/usr/bin/env python3
"""Build and run one allowlisted trusted fixture in a disposable container.

The API never calls this script. It is an operator/host job that builds an
immutable, dependency-locked image, runs it with no network or host mounts,
inspects the stopped container, and only publishes an artifact when both the
semantic run and the observed container controls pass fail-closed checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TARGETS_PATH = ROOT / "verification" / "targets.json"
DEFAULT_ARTIFACTS_DIR = ROOT / "evidence" / "runs"
WORKSPACE_LIMIT_BYTES = 64 * 1024 * 1024
OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
PIDS_LIMIT = 128
NANO_CPUS = 2_000_000_000
RUNNER_VERSION = "synapse-disposable-verifier-v1"
CONTRACT_VERSION = "bundle-4-stage-v1"
TARGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,79}$")
IMAGE_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[a-z0-9][a-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BUNDLE_ID_RE = re.compile(r"^(?:bundle|draft)_[a-z0-9][a-z0-9_-]{2,119}$")
SENSITIVE_ENV_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|DATABASE_URL|PRIVATE_KEY|API_KEY|AWS_)",
    re.IGNORECASE,
)


class JobFailure(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    capture_output: bool = False,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=capture_output,
        input=input_text,
    )


def _read_json(path: Path, max_bytes: int = 2 * 1024 * 1024) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise JobFailure(f"unsafe or missing JSON input: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobFailure(f"invalid JSON input: {path.name}") from exc


def _resolve_project_file(value: Any, allowed_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise JobFailure("target path is missing")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise JobFailure("target path escapes the project")
    candidate = ROOT / relative
    if candidate.is_symlink():
        raise JobFailure("target path is symlinked")
    resolved = candidate.resolve()
    allowed = allowed_root.resolve()
    if allowed not in resolved.parents or resolved.is_symlink() or not resolved.is_file():
        raise JobFailure("target path is outside its allowlisted directory")
    return resolved


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_target(target_id: str) -> dict[str, Any]:
    if TARGET_ID_RE.fullmatch(target_id) is None:
        raise JobFailure("invalid target identifier")
    data = _read_json(TARGETS_PATH)
    if not isinstance(data, dict) or data.get("schemaVersion") != "1.0.0":
        raise JobFailure("unsupported targets manifest")
    targets = data.get("targets")
    if not isinstance(targets, list):
        raise JobFailure("targets manifest has no target list")
    matches = [item for item in targets if isinstance(item, dict) and item.get("targetId") == target_id]
    if len(matches) != 1:
        raise JobFailure("target is absent or duplicated")
    target = dict(matches[0])

    bundle_path = _resolve_project_file(target.get("bundlePath"), ROOT / "bundles" / "golden")
    dockerfile = _resolve_project_file(target.get("dockerfile"), ROOT / "verification" / "worker")
    lock_path = _resolve_project_file(target.get("requirementsLock"), ROOT / "verification" / "worker")
    runner_source = _resolve_project_file(target.get("runnerSource"), ROOT / "verification" / "worker")
    bundle_sha256 = target.get("bundleSha256")
    if not isinstance(bundle_sha256, str) or SHA256_RE.fullmatch(bundle_sha256) is None:
        raise JobFailure("target bundle digest is invalid")
    if _sha256_file(bundle_path) != bundle_sha256:
        raise JobFailure("allowlisted bundle bytes changed")
    bundle = _read_json(bundle_path)
    if not isinstance(bundle, dict) or bundle.get("bundleId") != target.get("bundleId"):
        raise JobFailure("target bundle identity mismatch")
    image_tag = target.get("imageTag")
    if not isinstance(image_tag, str) or IMAGE_TAG_RE.fullmatch(image_tag) is None:
        raise JobFailure("target image tag is invalid")
    if target.get("runnerVersion") != RUNNER_VERSION:
        raise JobFailure("target runner version is unsupported")

    target.update(
        {
            "_bundlePath": bundle_path,
            "_dockerfile": dockerfile,
            "_lockPath": lock_path,
            "_runnerSource": runner_source,
            "_bundle": bundle,
        }
    )
    return target


def _source_revision(target: dict[str, Any]) -> str:
    inputs = {
        TARGETS_PATH.resolve(),
        target["_bundlePath"],
        target["_dockerfile"],
        target["_lockPath"],
        target["_runnerSource"],
        Path(__file__).resolve(),
        (ROOT / "app" / "core" / "run_artifacts.py").resolve(),
        (ROOT / ".dockerignore").resolve(),
    }
    digest = hashlib.sha256(b"synapse-verifier-source-tree-v1\0")
    for path in sorted(inputs, key=lambda item: _relative(item)):
        relative = _relative(path).encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _docker_json(command: list[str]) -> Any:
    result = _run(command, capture_output=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise JobFailure("Docker returned malformed inspection JSON") from exc


def _build_image(target: dict[str, Any], source_revision: str) -> dict[str, Any]:
    _run(
        [
            "docker",
            "build",
            "--pull",
            "--platform",
            "linux/amd64",
            "--file",
            _relative(target["_dockerfile"]),
            "--build-arg",
            f"BUNDLE_PATH={_relative(target['_bundlePath'])}",
            "--build-arg",
            f"REQUIREMENTS_LOCK={_relative(target['_lockPath'])}",
            "--build-arg",
            f"SOURCE_REVISION={source_revision}",
            "--tag",
            target["imageTag"],
            ".",
        ]
    )
    images = _docker_json(["docker", "image", "inspect", target["imageTag"]])
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise JobFailure("unable to inspect verifier image")
    image = images[0]
    image_id = image.get("Id")
    labels = (image.get("Config") or {}).get("Labels") or {}
    if (
        not isinstance(image_id, str)
        or IMAGE_ID_RE.fullmatch(image_id) is None
        or labels.get("org.opencontainers.image.revision") != source_revision
        or labels.get("dev.synapse.runner.version") != RUNNER_VERSION
    ):
        raise JobFailure("verifier image identity or labels do not match")
    return image


def _parse_tmpfs_options(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    return set(value.split(","))


def _sensitive_container_environment(env: Any) -> bool:
    if not isinstance(env, list):
        return True
    for entry in env:
        if not isinstance(entry, str) or "=" not in entry:
            return True
        key = entry.split("=", 1)[0]
        if SENSITIVE_ENV_RE.search(key):
            return True
    return False


def _inspect_controls(
    inspection: dict[str, Any],
    image: dict[str, Any],
    raw_report: dict[str, Any],
) -> dict[str, Any]:
    host = inspection.get("HostConfig") or {}
    config = inspection.get("Config") or {}
    state = inspection.get("State") or {}
    mounts = inspection.get("Mounts") or []
    tmpfs = host.get("Tmpfs") or {}
    work_options = _parse_tmpfs_options(tmpfs.get("/work"))
    output_options = _parse_tmpfs_options(tmpfs.get("/output"))
    security_options = set(host.get("SecurityOpt") or [])
    cap_drop = {str(value).upper() for value in (host.get("CapDrop") or [])}
    binds = host.get("Binds") or []
    host_mounts = host.get("Mounts") or []
    bind_mount_count = sum(
        1 for mount in mounts if isinstance(mount, dict) and mount.get("Type") == "bind"
    )
    docker_socket_mounted = any(
        isinstance(mount, dict)
        and "/var/run/docker.sock" in {mount.get("Source"), mount.get("Destination")}
        for mount in mounts
    )
    observed = raw_report.get("controlsObserved") or {}
    image_id = image.get("Id")
    expected = (
        inspection.get("Image") == image_id,
        config.get("User") == "10001:10001",
        host.get("NetworkMode") == "none",
        host.get("ReadonlyRootfs") is True,
        host.get("Privileged") is False,
        cap_drop == {"ALL"},
        "no-new-privileges=true" in security_options,
        host.get("PidsLimit") == PIDS_LIMIT,
        host.get("Memory") == MEMORY_LIMIT_BYTES,
        host.get("MemorySwap") == MEMORY_LIMIT_BYTES,
        host.get("NanoCpus") == NANO_CPUS,
        host.get("PidMode") in ("", "private"),
        host.get("IpcMode") in ("", "private"),
        host.get("UTSMode") in ("", "private"),
        host.get("CgroupnsMode") in ("", "private"),
        not binds,
        not host_mounts,
        bind_mount_count == 0,
        not docker_socket_mounted,
        host.get("Devices") in (None, []),
        host.get("DeviceRequests") in (None, []),
        "rw" in work_options,
        "nosuid" in work_options,
        "nodev" in work_options,
        "exec" in work_options,
        f"size={WORKSPACE_LIMIT_BYTES}" in work_options,
        "rw" in output_options,
        "nosuid" in output_options,
        "nodev" in output_options,
        "noexec" in output_options,
        f"size={OUTPUT_LIMIT_BYTES}" in output_options,
        state.get("ExitCode") == 0,
        state.get("OOMKilled") is False,
        not state.get("Error"),
        ((host.get("LogConfig") or {}).get("Type") == "none"),
        _sensitive_container_environment(config.get("Env")) is False,
        observed.get("uid") == 10001,
        observed.get("gid") == 10001,
        observed.get("capabilitiesDropped") is True,
        observed.get("noNewPrivileges") is True,
        observed.get("seccompMode") == "2",
        observed.get("rootFilesystemReadOnly") is True,
        observed.get("workspaceExecutable") is True,
        observed.get("workspaceNoSuid") is True,
        observed.get("workspaceNoDev") is True,
        observed.get("outputExecutable") is False,
        observed.get("onlyLoopbackInterface") is True,
        observed.get("sensitiveEnvironmentPresent") is False,
        observed.get("productionPathsPresent") is False,
        observed.get("dockerSocketPresent") is False,
        observed.get("workspaceSizeBytes") == WORKSPACE_LIMIT_BYTES,
        observed.get("memoryMaxBytes") == MEMORY_LIMIT_BYTES,
        observed.get("memorySwapMaxBytes") == 0,
        observed.get("pidsMax") == PIDS_LIMIT,
    )
    if not all(expected):
        raise JobFailure("container control inspection failed closed")

    return {
        "imageDigest": image_id,
        "runnerVersion": RUNNER_VERSION,
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
        "cgroupNamespacePrivate": host.get("CgroupnsMode") in ("", "private"),
        "userNamespaceMode": host.get("UsernsMode") or "daemon-default-host-uid",
        "hostDockerSocketMounted": False,
        "bindMountCount": 0,
        "privileged": False,
        "seccompMode": "filter",
        "oomKilled": False,
        "workspaceSizeLimitBytes": WORKSPACE_LIMIT_BYTES,
        "memoryLimitBytes": MEMORY_LIMIT_BYTES,
        "memorySwapLimitBytes": MEMORY_LIMIT_BYTES,
        "pidsLimit": PIDS_LIMIT,
        "cpuLimit": 2.0,
    }


def _run_container(
    target: dict[str, Any],
    image: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    container_name = f"synapse_verify_{secrets.token_hex(8)}"
    work_tmpfs = (
        f"rw,nosuid,nodev,exec,size={WORKSPACE_LIMIT_BYTES},uid=10001,gid=10001,mode=0700"
    )
    output_tmpfs = (
        f"rw,nosuid,nodev,noexec,size={OUTPUT_LIMIT_BYTES},uid=10001,gid=10001,mode=0700"
    )
    created = False
    try:
        result = _run(
            [
                "docker",
                "create",
                "--name",
                container_name,
                "--network",
                "none",
                "--read-only",
                "--user",
                "10001:10001",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges=true",
                "--pids-limit",
                str(PIDS_LIMIT),
                "--memory",
                str(MEMORY_LIMIT_BYTES),
                "--memory-swap",
                str(MEMORY_LIMIT_BYTES),
                "--cpus",
                "2.0",
                "--ulimit",
                "core=0:0",
                "--ulimit",
                "nofile=256:256",
                "--log-driver",
                "none",
                "--tmpfs",
                f"/work:{work_tmpfs}",
                "--tmpfs",
                f"/output:{output_tmpfs}",
                "--label",
                "dev.synapse.verification-job=true",
                "--label",
                f"dev.synapse.target-id={target['targetId']}",
                target["imageTag"],
            ],
            capture_output=True,
        )
        created = True
        if not result.stdout.strip():
            raise JobFailure("Docker did not return a container ID")
        started = _run(
            ["docker", "start", "--attach", container_name],
            capture_output=True,
            check=False,
        )
        raw_bytes = started.stdout.encode("utf-8")
        if len(raw_bytes) > 64 * 1024 or len(started.stderr.encode("utf-8")) > 16 * 1024:
            raise JobFailure("verifier console output exceeded its bound")
        inspections = _docker_json(["docker", "inspect", container_name])
        if not isinstance(inspections, list) or len(inspections) != 1:
            raise JobFailure("unable to inspect stopped verifier container")
        inspection = inspections[0]
        try:
            raw_report = json.loads(started.stdout)
        except json.JSONDecodeError as exc:
            raise JobFailure("worker emitted malformed report JSON") from exc
        if not isinstance(raw_report, dict):
            raise JobFailure("worker report is not an object")
        if started.returncode != 0 or raw_report.get("outcome") != "PASSED":
            failure_code = raw_report.get("failureCode") or "WORKER_FAILED"
            raise JobFailure(f"trusted fixture did not pass: {failure_code}")
        runner_controls = _inspect_controls(inspection, image, raw_report)
        return raw_report, runner_controls, hashlib.sha256(raw_bytes).hexdigest()
    finally:
        if created:
            _run(
                ["docker", "rm", "--force", container_name],
                capture_output=True,
                check=False,
            )


def _construct_artifact(
    target: dict[str, Any],
    source_revision: str,
    raw_report: dict[str, Any],
    runner_controls: dict[str, Any],
    raw_report_sha256: str,
    publication_validator_image_digest: str,
) -> dict[str, Any]:
    bundle = target["_bundle"]
    if (
        raw_report.get("schemaVersion") != "1.0.0"
        or raw_report.get("reportType") != "synapse-trusted-fixture-raw-run"
        or raw_report.get("contractVersion") != CONTRACT_VERSION
        or raw_report.get("runnerVersion") != RUNNER_VERSION
        or raw_report.get("bundleId") != bundle.get("bundleId")
        or raw_report.get("bundleSha256") != target.get("bundleSha256")
        or raw_report.get("outcome") != "PASSED"
        or not isinstance(raw_report.get("toolchainVersions"), dict)
        or not isinstance(raw_report.get("dependencyLockSha256"), str)
        or SHA256_RE.fullmatch(raw_report["dependencyLockSha256"]) is None
        or not isinstance(raw_report.get("stages"), dict)
    ):
        raise JobFailure("raw report identity or schema mismatch")
    return {
        "schemaVersion": "1.0.0",
        "artifactType": "synapse-bundle-verification-run",
        "contractVersion": CONTRACT_VERSION,
        "bundleId": raw_report["bundleId"],
        "bundleSha256": raw_report["bundleSha256"],
        "outcome": "PASSED",
        "startedAt": raw_report["startedAt"],
        "completedAt": raw_report["completedAt"],
        "sourceRevisionKind": "source-tree-sha256",
        "sourceRevision": source_revision,
        "dependencyLockSha256": raw_report["dependencyLockSha256"],
        "rawReportSha256": raw_report_sha256,
        "publicationValidatorImageDigest": publication_validator_image_digest,
        "runner": runner_controls,
        "toolchainVersions": raw_report["toolchainVersions"],
        "stages": raw_report["stages"],
        "controlsObserved": raw_report["controlsObserved"],
    }


def _publication_validator_image_digest() -> str:
    images = _docker_json(["docker", "image", "inspect", "synapse-mesh-api:latest"])
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise JobFailure("publication validator image is unavailable")
    image_id = images[0].get("Id")
    if not isinstance(image_id, str) or IMAGE_ID_RE.fullmatch(image_id) is None:
        raise JobFailure("publication validator image digest is invalid")
    return image_id


def _validate_with_application_gate(
    target: dict[str, Any],
    artifact: dict[str, Any],
    validator_image_digest: str,
) -> None:
    bundle_id = artifact["bundleId"]
    container_name = f"synapse_artifact_gate_{secrets.token_hex(8)}"
    created = False
    bundle_text = target["_bundlePath"].read_text(encoding="utf-8")
    artifact_text = json.dumps(
        artifact,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ) + "\n"
    validation_code = (
        "import json; from pathlib import Path; "
        "from app.core.run_artifacts import load_valid_run_artifact; "
        "b=json.loads(Path('/verify/bundle.json').read_text()); "
        "raise SystemExit(0 if load_valid_run_artifact("
        "b, Path('/verify/bundle.json'), artifacts_dir=Path('/verify/runs')) else 1)"
    )
    try:
        created_result = _run(
            [
                "docker",
                "create",
                "--name",
                container_name,
                "--network",
                "none",
                "--read-only",
                "--user",
                "10001:10001",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges=true",
                "--pids-limit",
                "32",
                "--memory",
                "268435456",
                "--memory-swap",
                "268435456",
                "--log-driver",
                "none",
                "--tmpfs",
                "/verify:rw,nosuid,nodev,noexec,size=4194304,uid=10001,gid=10001,mode=0700",
                "--entrypoint",
                "/bin/sh",
                validator_image_digest,
                "-c",
                "while [ ! -f /verify/.ready ]; do sleep 1; done; exec python -c \"$1\"",
                "synapse-gate",
                validation_code,
            ],
            capture_output=True,
        )
        created = True
        if not created_result.stdout.strip():
            raise JobFailure("application publication gate was not created")

        _run(["docker", "start", container_name], capture_output=True)
        _run(
            ["docker", "exec", container_name, "mkdir", "-p", "/verify/runs"],
            capture_output=True,
        )
        _run(
            [
                "docker",
                "exec",
                "-i",
                container_name,
                "/bin/sh",
                "-c",
                "cat > /verify/bundle.json",
            ],
            capture_output=True,
            input_text=bundle_text,
        )
        _run(
            [
                "docker",
                "exec",
                "-i",
                container_name,
                "/bin/sh",
                "-c",
                f"cat > /verify/runs/{bundle_id}.json",
            ],
            capture_output=True,
            input_text=artifact_text,
        )
        _run(
            [
                "docker",
                "exec",
                container_name,
                "chmod",
                "0444",
                "/verify/bundle.json",
                f"/verify/runs/{bundle_id}.json",
            ],
            capture_output=True,
        )
        _run(
            ["docker", "exec", container_name, "touch", "/verify/.ready"],
            capture_output=True,
        )
        waited = _run(
            ["docker", "wait", container_name],
            capture_output=True,
        )
        inspections = _docker_json(["docker", "inspect", container_name])
        state = (
            inspections[0].get("State")
            if isinstance(inspections, list)
            and len(inspections) == 1
            and isinstance(inspections[0], dict)
            else None
        )
        if (
            waited.stdout.strip() != "0"
            or not isinstance(state, dict)
            or state.get("ExitCode") != 0
            or state.get("OOMKilled") is not False
            or state.get("Error")
        ):
            raise JobFailure("application publication gate rejected the artifact")
    finally:
        if created:
            _run(
                ["docker", "rm", "--force", container_name],
                capture_output=True,
                check=False,
            )


def _canonical_artifact_sha256(artifact: dict[str, Any]) -> str:
    try:
        canonical = json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JobFailure("artifact is not canonical JSON") from exc
    return hashlib.sha256(canonical).hexdigest()


def _render_artifact(artifact: dict[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                artifact,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JobFailure("artifact is not renderable JSON") from exc


def _require_archivable_artifact(
    value: Any,
    *,
    expected_bundle_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JobFailure("artifact JSON is not an object")
    bundle_id = value.get("bundleId")
    if (
        not isinstance(bundle_id, str)
        or BUNDLE_ID_RE.fullmatch(bundle_id) is None
        or (expected_bundle_id is not None and bundle_id != expected_bundle_id)
        or value.get("schemaVersion") != "1.0.0"
        or value.get("artifactType") != "synapse-bundle-verification-run"
        or value.get("contractVersion") != CONTRACT_VERSION
        or value.get("outcome") != "PASSED"
        or not isinstance(value.get("bundleSha256"), str)
        or SHA256_RE.fullmatch(value["bundleSha256"]) is None
    ):
        raise JobFailure("artifact identity is not archivable")
    _canonical_artifact_sha256(value)
    return value


def _read_archivable_artifact(path: Path, *, expected_bundle_id: str) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise JobFailure("existing artifact is unsafe or unreadable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 2 * 1024 * 1024:
            raise JobFailure("existing artifact is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(raw) > 2 * 1024 * 1024:
        raise JobFailure("existing artifact exceeds its size bound")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_non_finite(value: str) -> None:
        raise ValueError(f"non-finite JSON value: {value}")

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise JobFailure("existing artifact is malformed JSON") from exc
    return _require_archivable_artifact(
        parsed,
        expected_bundle_id=expected_bundle_id,
    )


def _ensure_real_directory(path: Path, *, parents: bool = False) -> Path:
    if path.is_symlink():
        raise JobFailure(f"refusing symlinked artifact directory: {path.name}")
    try:
        path.mkdir(mode=0o755, parents=parents, exist_ok=True)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise JobFailure(f"unable to create artifact directory: {path.name}") from exc
    if path.is_symlink() or not resolved.is_dir():
        raise JobFailure(f"artifact path is not a real directory: {path.name}")
    # systemd intentionally uses a restrictive umask. Evidence directories are
    # nevertheless read-only public inputs for the fixed non-root API user.
    os.chmod(resolved, 0o755)
    return resolved


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o444)
        os.fchmod(descriptor, 0o444)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        read_descriptor: int | None = None
        try:
            read_descriptor = os.open(
                path,
                os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
            )
            metadata = os.fstat(read_descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > len(content):
                raise JobFailure("archive destination is unsafe")
            with os.fdopen(read_descriptor, "rb", closefd=False) as stream:
                existing = stream.read(len(content) + 1)
            if existing != content:
                raise JobFailure("archive digest collision or immutable file mismatch")
            os.fchmod(read_descriptor, 0o444)
        except OSError as exc:
            raise JobFailure("archive destination is unsafe or unreadable") from exc
        finally:
            if read_descriptor is not None:
                os.close(read_descriptor)
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise JobFailure("unable to create immutable artifact file") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _archive_artifact(archive_dir: Path, artifact: dict[str, Any]) -> Path:
    artifact = _require_archivable_artifact(artifact)
    bundle_dir = _ensure_real_directory(archive_dir / artifact["bundleId"])
    digest = _canonical_artifact_sha256(artifact)
    archive_path = bundle_dir / f"{digest}.json"
    _write_exclusive(archive_path, _render_artifact(artifact))
    return archive_path


def _write_artifact(output_dir: Path, artifact: dict[str, Any]) -> Path:
    artifact = _require_archivable_artifact(artifact)
    bundle_id = artifact["bundleId"]
    output_dir = _ensure_real_directory(output_dir, parents=True)
    archive_dir = _ensure_real_directory(output_dir / "archive")
    output_path = output_dir / f"{bundle_id}.json"

    if output_path.is_symlink():
        raise JobFailure("refusing to replace a symlinked artifact")
    if output_path.exists():
        existing = _read_archivable_artifact(
            output_path,
            expected_bundle_id=bundle_id,
        )
        _archive_artifact(archive_dir, existing)

    # The validated incoming artifact is archived before the mutable current
    # pointer is replaced. Archive files are content-addressed and created with
    # O_EXCL; a pre-existing name must contain the exact deterministic bytes.
    _archive_artifact(archive_dir, artifact)

    rendered = _render_artifact(artifact)
    temporary = output_dir / f".{bundle_id}.{secrets.token_hex(8)}.tmp"
    try:
        _write_exclusive(temporary, rendered)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Exact targetId from verification/targets.json")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Write the validated artifact to evidence/runs (otherwise print a preview digest only)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    try:
        target = _load_target(args.target)
        source_revision = _source_revision(target)
        image = _build_image(target, source_revision)
        raw_report, controls, raw_sha256 = _run_container(target, image)
        validator_image_digest = _publication_validator_image_digest()
        artifact = _construct_artifact(
            target,
            source_revision,
            raw_report,
            controls,
            raw_sha256,
            validator_image_digest,
        )
        _validate_with_application_gate(target, artifact, validator_image_digest)
        artifact_digest = _canonical_artifact_sha256(artifact)
        if args.publish:
            output_path = _write_artifact(args.output_dir, artifact)
            print(f"published={output_path} artifactSha256={artifact_digest}")
        else:
            print(f"validated=true artifactSha256={artifact_digest} publish=false")
        return 0
    except (JobFailure, OSError, subprocess.SubprocessError) as exc:
        print(f"verification_job_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
