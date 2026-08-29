#!/usr/bin/env python3
"""Run one pre-approved repository fixture and emit a raw evidence report.

This process deliberately knows nothing about Docker and cannot publish proof.
The host-side orchestrator separately inspects the stopped container, binds its
controls and image ID to this report, and only then constructs a publishable
artifact. Public or crawled input must never be copied into this image.
"""

from __future__ import annotations

import errno
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import resource
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


RUNNER_VERSION = "synapse-disposable-verifier-v1"
CONTRACT_VERSION = "bundle-4-stage-v1"
WORK_ROOT = Path("/work")
JOB_ROOT = WORK_ROOT / "job"
STAGE_OUTPUT_ROOT = WORK_ROOT / "stage-outputs"
LOCK_PATH = Path("/runner/requirements.lock")
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_DIFF_BYTES = 1024 * 1024
MAX_WORKSPACE_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
MAX_WORKSPACE_FILES = 64
MAX_TIMEOUT_SECONDS = 60.0
EXPECTED_MEMORY_LIMIT = 1024 * 1024 * 1024
EXPECTED_PIDS_LIMIT = 128
EXPECTED_WORKSPACE_LIMIT = 64 * 1024 * 1024
BUNDLE_ID_RE = re.compile(r"^(?:bundle|draft)_[a-z0-9][a-z0-9_-]{2,119}$")
EXCEPTION_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Warning|Exception))\b"
)
EXACT_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[A-Za-z0-9_.+-]*)$")
SENSITIVE_ENV_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|DATABASE_URL|PRIVATE_KEY|API_KEY|AWS_)",
    re.IGNORECASE,
)
SEMANTIC_COMPILER_RE = re.compile(
    r"(?:\bTS\d{4}\b|\berror\[E\d{4}\]|compiler diagnostic)", re.IGNORECASE
)
INFRASTRUCTURE_CODES = {126, 127}
_OUTPUT_COUNTER = count()


class VerificationFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    output: str
    output_sha256: str
    infrastructure_failure: bool
    timed_out: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_small_regular_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise VerificationFailure("INPUT_NOT_REGULAR")
    if path.stat().st_size > limit:
        raise VerificationFailure("INPUT_TOO_LARGE")
    return path.read_bytes()


def _safe_workspace_path(relative_path: Any) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path:
        return None
    try:
        rel = Path(relative_path)
        root = JOB_ROOT.resolve()
        resolved = (root / rel).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if (
        rel.is_absolute()
        or ".." in rel.parts
        or resolved == root
        or root not in resolved.parents
        or any(part.startswith(".synapse_") for part in rel.parts)
    ):
        return None
    return resolved


def _diff_path(value: str) -> str:
    token = value.strip().split("\t", 1)[0]
    if token.startswith(("a/", "b/")):
        token = token[2:]
    return token


def _line_equal(left: str, right: str) -> bool:
    return left.rstrip("\r\n") == right.rstrip("\r\n")


def _apply_patch_unified(target_file: Path, patch_diff: str) -> bool:
    if not patch_diff or len(patch_diff.encode("utf-8")) > MAX_DIFF_BYTES:
        return False
    workspace_root = JOB_ROOT.resolve()
    try:
        target_rel = target_file.resolve().relative_to(workspace_root).as_posix()
    except (OSError, ValueError):
        return False
    safe_target = _safe_workspace_path(target_rel)
    if safe_target is None or safe_target != target_file.resolve() or not safe_target.is_file():
        return False

    lines = patch_diff.splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        return False
    if _diff_path(lines[0][4:]) != target_rel or _diff_path(lines[1][4:]) != target_rel:
        return False

    original = safe_target.read_text(encoding="utf-8").splitlines(keepends=True)
    result: list[str] = []
    source_index = 0
    index = 2
    saw_hunk = False
    header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    while index < len(lines):
        header = header_re.match(lines[index])
        if not header:
            return False
        saw_hunk = True
        old_start = int(header.group(1))
        old_count = int(header.group(2) or "1")
        new_count = int(header.group(4) or "1")
        requested_index = 0 if old_start == 0 else old_start - 1
        if requested_index < source_index or requested_index > len(original):
            return False
        result.extend(original[source_index:requested_index])
        source_index = requested_index
        index += 1
        consumed_old = 0
        produced_new = 0

        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            if not line or line[0] not in (" ", "+", "-"):
                return False
            marker, content = line[0], line[1:]
            if marker in (" ", "-"):
                if source_index >= len(original) or not _line_equal(original[source_index], content):
                    return False
                if marker == " ":
                    result.append(original[source_index])
                    produced_new += 1
                source_index += 1
                consumed_old += 1
            if marker == "+":
                result.append(content)
                produced_new += 1
            index += 1

        if consumed_old != old_count or produced_new != new_count:
            return False

    if not saw_hunk:
        return False
    result.extend(original[source_index:])
    rendered = "".join(result)
    if rendered == "".join(original):
        return False
    safe_target.write_text(rendered, encoding="utf-8")
    return True


def _child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 12))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def _execution_env() -> dict[str, str]:
    return {
        "HOME": str(WORK_ROOT),
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": str(WORK_ROOT),
        "TZ": "UTC",
    }


def _run_bounded(script_path: Path, timeout_seconds: float) -> ProcessResult:
    output_path = STAGE_OUTPUT_ROOT / f"stage-{next(_OUTPUT_COUNTER)}.log"
    STAGE_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    timed_out = False
    with output_path.open("wb") as output_handle:
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=JOB_ROOT,
            env=_execution_env(),
            stdin=subprocess.DEVNULL,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=_child_limits,
        )
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)

    output_bytes = output_path.read_bytes()
    output_limit_hit = len(output_bytes) >= MAX_OUTPUT_BYTES
    exit_code = -1 if timed_out else int(process.returncode)
    infrastructure_failure = (
        timed_out
        or output_limit_hit
        or exit_code < 0
        or exit_code in INFRASTRUCTURE_CODES
    )
    return ProcessResult(
        exit_code=exit_code,
        output=output_bytes.decode("utf-8", errors="replace"),
        output_sha256=_sha256_bytes(output_bytes),
        infrastructure_failure=infrastructure_failure,
        timed_out=timed_out,
    )


def _mount_options(mountpoint: str) -> set[str]:
    try:
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[1] == mountpoint:
                return set(fields[3].split(","))
    except OSError:
        return set()
    return set()


def _proc_status_value(name: str) -> str | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _cgroup_int(name: str) -> int | None:
    path = Path("/sys/fs/cgroup") / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _network_interfaces() -> list[str]:
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
    except OSError:
        return []
    return sorted(line.split(":", 1)[0].strip() for line in lines if ":" in line)


def _workspace_exec_probe() -> bool:
    probe = WORK_ROOT / ".synapse_exec_probe"
    try:
        shutil.copyfile("/bin/true", probe)
        probe.chmod(0o700)
        result = subprocess.run(
            [str(probe)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
            env=_execution_env(),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def _workspace_size_bytes() -> int | None:
    try:
        stats = os.statvfs(WORK_ROOT)
    except OSError:
        return None
    return int(stats.f_frsize * stats.f_blocks)


def _observe_controls() -> dict[str, Any]:
    root_options = _mount_options("/")
    work_options = _mount_options("/work")
    output_options = _mount_options("/output")
    interfaces = _network_interfaces()
    sensitive_env_present = any(SENSITIVE_ENV_RE.search(key) for key in os.environ)
    production_paths = (
        Path("/app/data"),
        Path("/data"),
        Path("/run/secrets"),
        Path("/var/run/docker.sock"),
    )
    return {
        "uid": os.geteuid(),
        "gid": os.getegid(),
        "nonRoot": os.geteuid() != 0,
        "capabilitiesDropped": int(_proc_status_value("CapEff") or "1", 16) == 0,
        "noNewPrivileges": _proc_status_value("NoNewPrivs") == "1",
        "seccompMode": _proc_status_value("Seccomp"),
        "rootFilesystemReadOnly": "ro" in root_options,
        "workspaceExecutable": _workspace_exec_probe(),
        "workspaceNoSuid": "nosuid" in work_options,
        "workspaceNoDev": "nodev" in work_options,
        "outputExecutable": "noexec" not in output_options,
        "onlyLoopbackInterface": interfaces == ["lo"],
        "networkInterfaces": interfaces,
        "sensitiveEnvironmentPresent": sensitive_env_present,
        "productionPathsPresent": any(path.exists() for path in production_paths),
        "dockerSocketPresent": Path("/var/run/docker.sock").exists(),
        "workspaceSizeBytes": _workspace_size_bytes(),
        "memoryMaxBytes": _cgroup_int("memory.max"),
        "memorySwapMaxBytes": _cgroup_int("memory.swap.max"),
        "pidsMax": _cgroup_int("pids.max"),
    }


def _require_observed_controls(controls: dict[str, Any]) -> None:
    required = (
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
        controls.get("sensitiveEnvironmentPresent") is False,
        controls.get("productionPathsPresent") is False,
        controls.get("dockerSocketPresent") is False,
        controls.get("workspaceSizeBytes") == EXPECTED_WORKSPACE_LIMIT,
        controls.get("memoryMaxBytes") == EXPECTED_MEMORY_LIMIT,
        controls.get("memorySwapMaxBytes") == 0,
        controls.get("pidsMax") == EXPECTED_PIDS_LIMIT,
    )
    if not all(required):
        raise VerificationFailure("CONTROL_ATTESTATION_FAILED")


def _parse_lock_versions() -> dict[str, str]:
    lock_text = _read_small_regular_file(LOCK_PATH, MAX_WORKSPACE_FILE_BYTES).decode("utf-8")
    versions: dict[str, str] = {}
    for line in lock_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s]+)\s+--hash=sha256:[0-9a-f]{64}$", stripped)
        if not match:
            raise VerificationFailure("DEPENDENCY_LOCK_INVALID")
        package, version = match.groups()
        if package.lower() in {name.lower() for name in versions}:
            raise VerificationFailure("DEPENDENCY_LOCK_DUPLICATE")
        versions[package] = version
    if not versions:
        raise VerificationFailure("DEPENDENCY_LOCK_EMPTY")
    return versions


def _toolchain_versions(bundle: dict[str, Any]) -> tuple[dict[str, str], str]:
    lock_versions = _parse_lock_versions()
    observed: dict[str, str] = {"python": platform.python_version()}
    for package, expected in lock_versions.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise VerificationFailure("TOOLCHAIN_DEPENDENCY_MISSING") from exc
        if actual != expected:
            raise VerificationFailure("TOOLCHAIN_LOCK_MISMATCH")
        observed[package] = actual

    scope = bundle.get("scope") or {}
    patch = bundle.get("patch") or {}
    if scope.get("runtime") != "python" or scope.get("runtimeVersion") != observed["python"]:
        raise VerificationFailure("RUNTIME_VERSION_MISMATCH")
    pins = patch.get("pinnedDependencies")
    if not isinstance(pins, dict) or not pins:
        raise VerificationFailure("DEPENDENCY_PINS_MISSING")
    for package, expected in pins.items():
        if not isinstance(package, str) or not isinstance(expected, str) or not EXACT_VERSION_RE.fullmatch(expected):
            raise VerificationFailure("DEPENDENCY_PIN_NOT_EXACT")
        if package == "python":
            actual = observed["python"]
        else:
            try:
                actual = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError as exc:
                raise VerificationFailure("DECLARED_DEPENDENCY_MISSING") from exc
        if actual != expected:
            raise VerificationFailure("DECLARED_DEPENDENCY_MISMATCH")
        observed[package] = actual

    package_name = scope.get("package")
    affected_range = scope.get("affectedVersionRange")
    if not isinstance(package_name, str) or not isinstance(affected_range, str):
        raise VerificationFailure("AFFECTED_RANGE_MISSING")
    try:
        package_version = importlib.metadata.version(package_name)
        if Version(package_version) not in SpecifierSet(affected_range):
            raise VerificationFailure("AFFECTED_RANGE_MISMATCH")
    except importlib.metadata.PackageNotFoundError as exc:
        raise VerificationFailure("AFFECTED_PACKAGE_MISSING") from exc
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise VerificationFailure("AFFECTED_RANGE_INVALID") from exc

    lock_sha256 = _sha256_bytes(LOCK_PATH.read_bytes())
    return observed, lock_sha256


def _require_contract_shape(bundle: dict[str, Any]) -> None:
    if bundle.get("schemaVersion") != "1.0.0" or bundle.get("status") != "VERIFIED":
        raise VerificationFailure("BUNDLE_STATUS_OR_SCHEMA_INVALID")
    bundle_id = bundle.get("bundleId")
    if not isinstance(bundle_id, str) or BUNDLE_ID_RE.fullmatch(bundle_id) is None:
        raise VerificationFailure("BUNDLE_ID_INVALID")
    scope = bundle.get("scope") or {}
    fingerprint = bundle.get("fingerprint") or {}
    patch = bundle.get("patch") or {}
    verification = bundle.get("verification") or {}
    workspace_files = verification.get("workspaceFiles")
    target_file = patch.get("targetFile")
    mutations = verification.get("mutations")
    if (
        scope.get("runtime") != "python"
        or not isinstance(fingerprint.get("errorSignature"), str)
        or not fingerprint["errorSignature"].strip()
        or not isinstance(workspace_files, dict)
        or not workspace_files
        or len(workspace_files) > MAX_WORKSPACE_FILES
        or not all(isinstance(path, str) and isinstance(content, str) for path, content in workspace_files.items())
        or not isinstance(target_file, str)
        or target_file not in workspace_files
        or _safe_workspace_path(target_file) is None
        or not isinstance(verification.get("reproductionScript"), str)
        or not verification["reproductionScript"].strip()
        or not isinstance(verification.get("testSuite"), str)
        or not verification["testSuite"].strip()
        or not isinstance(verification.get("expectedPreExit"), int)
        or verification["expectedPreExit"] in (-1, 0)
        or verification.get("expectedPostExit") != 0
        or not isinstance(mutations, list)
        or len(mutations) < 2
    ):
        raise VerificationFailure("BUNDLE_CONTRACT_SHAPE_INVALID")

    package_name = str(scope.get("package") or "").replace("-", "_")
    source_blob = "\n".join(
        [*workspace_files.values(), verification["reproductionScript"], verification["testSuite"]]
    )
    if not re.search(rf"(?:^|\n)\s*(?:from|import)\s+{re.escape(package_name)}\b", source_blob):
        raise VerificationFailure("REAL_PACKAGE_IMPORT_MISSING")

    main_diff = patch.get("unifiedDiff")
    if not isinstance(main_diff, str) or not main_diff or len(main_diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise VerificationFailure("PATCH_INVALID")
    recorded_hash = patch.get("sha256")
    if recorded_hash is not None and recorded_hash != _sha256_bytes(main_diff.encode("utf-8")):
        raise VerificationFailure("PATCH_DIGEST_MISMATCH")
    mutation_ids: set[str] = set()
    mutation_diffs: set[str] = set()
    for mutation in mutations:
        if not isinstance(mutation, dict):
            raise VerificationFailure("MUTATION_INVALID")
        mutation_id = mutation.get("id")
        mutation_diff = mutation.get("unifiedDiff")
        if (
            not isinstance(mutation_id, str)
            or not mutation_id
            or mutation_id in mutation_ids
            or not isinstance(mutation_diff, str)
            or not mutation_diff
            or mutation_diff in mutation_diffs
        ):
            raise VerificationFailure("MUTATION_INVALID")
        mutation_ids.add(mutation_id)
        mutation_diffs.add(mutation_diff)


def _materialize_workspace(workspace_files: dict[str, str]) -> None:
    if JOB_ROOT.exists():
        for child in JOB_ROOT.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
    else:
        JOB_ROOT.mkdir(parents=True, mode=0o700)
    for relative_path, content in workspace_files.items():
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_WORKSPACE_FILE_BYTES:
            raise VerificationFailure("WORKSPACE_CONTENT_INVALID")
        destination = _safe_workspace_path(relative_path)
        if destination is None:
            raise VerificationFailure("WORKSPACE_PATH_INVALID")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _exception_class(value: str) -> str | None:
    match = EXCEPTION_RE.search(value)
    return match.group(1).lower() if match else None


def _signature_matches(fingerprint: dict[str, Any], output: str) -> tuple[bool, bool]:
    expected_signature = fingerprint.get("errorSignature") or ""
    expected_class = _exception_class(expected_signature)
    observed_class = _exception_class(output)
    class_matched = bool(expected_class and observed_class and expected_class == observed_class)
    if not class_matched:
        return False, False
    pattern = fingerprint.get("regex")
    if pattern:
        flags = re.IGNORECASE
        flag_text = str(fingerprint.get("regexFlags") or "").lower()
        if "m" in flag_text:
            flags |= re.MULTILINE
        if "s" in flag_text:
            flags |= re.DOTALL
        try:
            return re.search(pattern, output, flags) is not None, True
        except re.error:
            return False, True
    return expected_signature.lower() in output.lower(), True


def _mutation_rejection_kind(output: str) -> str:
    if "AssertionError" in output:
        return "ASSERTION_FAILURE"
    if SEMANTIC_COMPILER_RE.search(output):
        return "COMPILER_DIAGNOSTIC"
    return "RUNTIME_FAILURE"


def _execute_contract(bundle: dict[str, Any], report: dict[str, Any]) -> None:
    _require_contract_shape(bundle)
    toolchains, lock_sha256 = _toolchain_versions(bundle)
    report["toolchainVersions"] = toolchains
    report["dependencyLockSha256"] = lock_sha256

    patch = bundle["patch"]
    fingerprint = bundle["fingerprint"]
    verification = bundle["verification"]
    workspace_files = verification["workspaceFiles"]
    target_path = _safe_workspace_path(patch["targetFile"])
    if target_path is None:
        raise VerificationFailure("TARGET_PATH_INVALID")
    timeout_seconds = min(
        max(float(verification.get("timeoutMs", 30000)) / 1000.0, 0.1),
        MAX_TIMEOUT_SECONDS,
    )

    _materialize_workspace(workspace_files)
    repro_runner = JOB_ROOT / ".synapse_repro.py"
    repro_runner.write_text(verification["reproductionScript"], encoding="utf-8")
    pre = _run_bounded(repro_runner, timeout_seconds)
    signature_matched, class_matched = _signature_matches(fingerprint, pre.output)
    report["stages"]["pre"] = {
        "exitCode": pre.exit_code,
        "signatureMatched": signature_matched,
        "exceptionClassMatched": class_matched,
        "outputSha256": pre.output_sha256,
    }
    if pre.infrastructure_failure:
        raise VerificationFailure("PRE_INFRASTRUCTURE_FAILURE")
    if pre.exit_code != verification["expectedPreExit"]:
        raise VerificationFailure("PRE_EXIT_MISMATCH")
    if not signature_matched or not class_matched:
        raise VerificationFailure("PRE_SIGNATURE_MISMATCH")

    if not _apply_patch_unified(target_path, patch["unifiedDiff"]):
        raise VerificationFailure("PATCH_APPLICATION_FAILED")
    report["stages"]["patch"] = {
        "strictUnifiedDiffApplied": True,
        "diffSha256": _sha256_bytes(patch["unifiedDiff"].encode("utf-8")),
    }

    test_runner = JOB_ROOT / ".synapse_test.py"
    test_runner.write_text(verification["testSuite"], encoding="utf-8")
    post = _run_bounded(test_runner, timeout_seconds)
    report["stages"]["post"] = {
        "exitCode": post.exit_code,
        "passed": post.exit_code == verification["expectedPostExit"],
        "outputSha256": post.output_sha256,
    }
    if post.infrastructure_failure:
        raise VerificationFailure("POST_INFRASTRUCTURE_FAILURE")
    if post.exit_code != verification["expectedPostExit"]:
        raise VerificationFailure("POST_EXIT_MISMATCH")

    observed_mutations: list[dict[str, Any]] = []
    report["stages"]["mutations"] = observed_mutations
    for mutation in verification["mutations"]:
        _materialize_workspace(workspace_files)
        if not _apply_patch_unified(target_path, mutation["unifiedDiff"]):
            raise VerificationFailure("MUTATION_PATCH_APPLICATION_FAILED")
        test_runner = JOB_ROOT / ".synapse_test.py"
        test_runner.write_text(verification["testSuite"], encoding="utf-8")
        result = _run_bounded(test_runner, timeout_seconds)
        observed = {
            "id": mutation["id"],
            "diffSha256": _sha256_bytes(mutation["unifiedDiff"].encode("utf-8")),
            "strictUnifiedDiffApplied": True,
            "exitCode": result.exit_code,
            "rejected": result.exit_code != 0 and not result.infrastructure_failure,
            "rejectionKind": (
                "INFRASTRUCTURE_FAILURE"
                if result.infrastructure_failure
                else _mutation_rejection_kind(result.output)
            ),
            "outputSha256": result.output_sha256,
        }
        observed_mutations.append(observed)
        if result.infrastructure_failure:
            raise VerificationFailure("MUTATION_INFRASTRUCTURE_FAILURE")
        if result.exit_code == 0:
            raise VerificationFailure("MUTATION_SURVIVED")


def _write_report(output_path: Path, report: dict[str, Any]) -> str:
    output_parent = output_path.parent.resolve()
    if output_parent != Path("/output").resolve() or output_path.suffix != ".json":
        raise VerificationFailure("OUTPUT_PATH_INVALID")
    rendered = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    temporary = output_parent / f".{output_path.name}.tmp"
    temporary.write_text(rendered + "\n", encoding="utf-8")
    temporary.chmod(0o444)
    os.replace(temporary, output_path)
    return rendered + "\n"


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    bundle_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    started_at = _utc_now()
    report: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "reportType": "synapse-trusted-fixture-raw-run",
        "contractVersion": CONTRACT_VERSION,
        "runnerVersion": RUNNER_VERSION,
        "startedAt": started_at,
        "outcome": "FAILED",
        "stages": {},
    }
    exit_code = 1
    try:
        bundle_bytes = _read_small_regular_file(bundle_path, MAX_BUNDLE_BYTES)
        bundle = json.loads(bundle_bytes.decode("utf-8"))
        if not isinstance(bundle, dict):
            raise VerificationFailure("BUNDLE_JSON_NOT_OBJECT")
        report["bundleId"] = bundle.get("bundleId")
        report["bundleSha256"] = _sha256_bytes(bundle_bytes)
        controls = _observe_controls()
        report["controlsObserved"] = controls
        _require_observed_controls(controls)
        _execute_contract(bundle, report)
        report["outcome"] = "PASSED"
        exit_code = 0
    except VerificationFailure as exc:
        report["failureCode"] = exc.code
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report["failureCode"] = f"INTERNAL_{type(exc).__name__.upper()}"
    report["completedAt"] = _utc_now()
    try:
        rendered = _write_report(output_path, report)
    except (OSError, VerificationFailure):
        return 2
    sys.stdout.write(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
