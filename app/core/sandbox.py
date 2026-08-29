import asyncio
import os
import re
import signal
import shutil
import sys
import tempfile
import time
import resource
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from app.models.recipe import EvidenceDefinition
from datetime import datetime, timezone


def kill_process_tree(process_or_pid):
    """Kills entire process tree (process group) to prevent orphan child leaks."""
    pid = process_or_pid.pid if hasattr(process_or_pid, "pid") else process_or_pid
    try:
        os.killpg(pid, signal.SIGKILL)
    except BaseException:
        pass
    try:
        os.kill(pid, signal.SIGKILL)
    except BaseException:
        pass
    if hasattr(process_or_pid, "kill"):
        try:
            process_or_pid.kill()
        except BaseException:
            pass


def sandbox_preexec_limits(
    address_space_limit_bytes: Optional[int] = None,
    max_file_size_bytes: int = 10 * 1024 * 1024,
):
    """Apply the configured POSIX resource limits to the child process."""
    # 1. Bound each created file. Repository-owned compiler harnesses need
    # larger debug/link outputs but remain inside the outer tmpfs and cgroup.
    max_file = max(1, min(max_file_size_bytes, 128 * 1024 * 1024))
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_file, max_file))
    except BaseException:
        pass

    # 2. Limit Max CPU Time to 10s (prevents CPU starvation)
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (10, 12))
    except BaseException:
        pass

    # 3. Limit Max Processes/Threads (prevents fork bombs)
    try:
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except BaseException:
        pass

    # Python does not reserve a large virtual heap at startup, so a per-process
    # address-space ceiling is usable here. Node/V8 and compiler processes have
    # different virtual-memory behaviour and remain bounded by the container
    # cgroup until they are moved to a dedicated worker boundary.
    if address_space_limit_bytes and hasattr(resource, "RLIMIT_AS"):
        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (address_space_limit_bytes, address_space_limit_bytes),
            )
        except BaseException:
            pass

    # 4. Linux-specific: Ensure death signal is sent if parent dies
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            libc = ctypes.CDLL(None)
            PR_SET_PDEATHSIG = 1
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
        except BaseException:
            pass


async def read_stream_capped(
    stream: asyncio.StreamReader,
    max_bytes: int = 512 * 1024,
    on_limit_exceeded: Optional[Callable[[], None]] = None
) -> str:
    """Reads stream asynchronously with strict byte cap and immediate process termination on overflow."""
    buf = bytearray()
    truncated = False
    try:
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            if len(buf) + len(chunk) <= max_bytes:
                buf.extend(chunk)
            else:
                if not truncated:
                    remaining = max_bytes - len(buf)
                    if remaining > 0:
                        buf.extend(chunk[:remaining])
                    buf.extend(b"\n[RESOURCE_LIMIT_EXCEEDED: Output exceeded 512 KiB limit]\n")
                    truncated = True
                    if on_limit_exceeded:
                        on_limit_exceeded()
                # Continue draining remaining stream to allow child process to unblock and die
    except (asyncio.CancelledError, Exception):
        pass
    return buf.decode(errors="replace")


class SandboxRunner:
    """Run trusted test fixtures in a temporary, process-limited workspace.

    This runner is deliberately *not* described as a security sandbox.  A child
    process still shares the API container's filesystem and network namespaces.
    Public and crawled code must therefore never be passed to this class.
    """

    TIMEOUT_SECONDS = 12.0
    MAX_OUTPUT_BYTES = 512 * 1024  # 512 KiB per stream
    PYTHON_MAX_ADDRESS_SPACE_BYTES = 512 * 1024 * 1024
    TOOLCHAIN_MAX_FILE_BYTES = 64 * 1024 * 1024

    @classmethod
    async def run_workspace_test(
        cls,
        files: Dict[str, str],
        entrypoint: str,
        runtime: str = "python",
        *,
        allow_toolchain_subprocesses: bool = False,
    ) -> Dict[str, Any]:
        """Execute a trusted fixture with bounded time/output in a temporary directory.

        ``allow_toolchain_subprocesses`` is reserved for repository-owned Python
        harnesses that launch Node or compiler processes. Those tools reserve
        substantially more virtual address space and remain bounded by the
        outer container cgroup; ordinary Python fixtures retain RLIMIT_AS.
        """
        start_time = time.time()
        temp_dir = tempfile.mkdtemp(prefix="synapse_sandbox_")

        try:
            # 1. Write all workspace files
            if not files or len(files) > 64:
                return {
                    "exitCode": -1,
                    "passed": False,
                    "durationMs": 0.0,
                    "stdout": "",
                    "stderr": "UNVERIFIED: invalid workspace",
                    "unverified": True,
                }
            for rel_path, content in files.items():
                rel = Path(rel_path)
                target_file = (Path(temp_dir) / rel).resolve()
                workspace_root = Path(temp_dir).resolve()
                if (
                    rel.is_absolute()
                    or ".." in rel.parts
                    or target_file == workspace_root
                    or workspace_root not in target_file.parents
                    or len(content.encode("utf-8")) > 1024 * 1024
                ):
                    return {
                        "exitCode": -1,
                        "passed": False,
                        "durationMs": 0.0,
                        "stdout": "",
                        "stderr": "UNVERIFIED: unsafe workspace path or size",
                        "unverified": True,
                    }
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")

            # 2. Strict Environment Allowlist (Zero Secret Leakage)
            ALLOWED_ENV_VARS = {"PATH", "LANG", "LC_ALL", "TERM", "TZ"}
            env = {k: os.environ[k] for k in ALLOWED_ENV_VARS if k in os.environ}
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["HOME"] = temp_dir
            env["TMPDIR"] = temp_dir
            env["TEMP"] = temp_dir
            env["TMP"] = temp_dir
            if os.path.exists("/usr/lib/node_modules"):
                env["NODE_PATH"] = "/usr/lib/node_modules"

            rt = runtime.lower()

            # 3. Select Executable & Command Line
            if rt == "python":
                executable = sys.executable
                args = [executable, entrypoint]
            elif rt in ("nodejs", "node", "javascript", "typescript"):
                executable = shutil.which("node")
                if not executable:
                    return {
                        "exitCode": -1,
                        "passed": False,
                        "durationMs": 0.0,
                        "stdout": "",
                        "stderr": "UNVERIFIED: node runtime executable not found on host",
                        "unverified": True
                    }
                args = [executable, "--max-old-space-size=256", entrypoint]
            elif rt == "rust":
                cargo_bin = shutil.which("cargo")
                if not cargo_bin:
                    return {
                        "exitCode": -1,
                        "passed": False,
                        "durationMs": 0.0,
                        "stdout": "",
                        "stderr": "UNVERIFIED: cargo toolchain not found on host",
                        "unverified": True
                    }
                if entrypoint == "check":
                    args = [cargo_bin, "check", "--offline"]
                elif entrypoint == "test":
                    args = [cargo_bin, "test", "--offline"]
                else:
                    rustc_bin = shutil.which("rustc")
                    args = [rustc_bin, entrypoint]
            else:
                return {
                    "exitCode": -1,
                    "passed": False,
                    "durationMs": 0.0,
                    "stdout": "",
                    "stderr": f"UNVERIFIED: unsupported runtime '{rt}'",
                    "unverified": True,
                }

            entrypoint_path = (Path(temp_dir) / entrypoint).resolve()
            if Path(entrypoint).is_absolute() or Path(temp_dir).resolve() not in entrypoint_path.parents:
                return {
                    "exitCode": -1,
                    "passed": False,
                    "durationMs": 0.0,
                    "stdout": "",
                    "stderr": "UNVERIFIED: unsafe entrypoint",
                    "unverified": True,
                }

            # Spawn process in isolated process group with kernel resource limits
            address_space_limit = (
                cls.PYTHON_MAX_ADDRESS_SPACE_BYTES
                if rt == "python"
                and sys.platform.startswith("linux")
                and not allow_toolchain_subprocesses
                else None
            )
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=temp_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
                preexec_fn=lambda: sandbox_preexec_limits(
                    address_space_limit,
                    cls.TOOLCHAIN_MAX_FILE_BYTES
                    if allow_toolchain_subprocesses
                    else 10 * 1024 * 1024,
                )
            )

            def on_output_exceeded():
                kill_process_tree(process)

            stdout_task = asyncio.create_task(
                read_stream_capped(process.stdout, cls.MAX_OUTPUT_BYTES, on_limit_exceeded=on_output_exceeded)
            )
            stderr_task = asyncio.create_task(
                read_stream_capped(process.stderr, cls.MAX_OUTPUT_BYTES, on_limit_exceeded=on_output_exceeded)
            )

            try:
                await asyncio.wait_for(process.wait(), timeout=cls.TIMEOUT_SECONDS)
                exit_code = process.returncode
                stdout = await stdout_task
                stderr = await stderr_task
            except asyncio.TimeoutError:
                kill_process_tree(process.pid)
                try:
                    await process.wait()
                except Exception:
                    pass
                stdout_task.cancel()
                stderr_task.cancel()
                exit_code = -1
                stdout = ""
                stderr = f"Sandbox execution timed out after {cls.TIMEOUT_SECONDS}s"

            duration_ms = round((time.time() - start_time) * 1000, 2)
            passed = (exit_code == 0)

            return {
                "exitCode": exit_code,
                "passed": passed,
                "durationMs": duration_ms,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "unverified": False
            }
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    async def run_python_test(cls, test_script: str) -> Dict[str, Any]:
        return await cls.run_workspace_test(
            files={"test_script.py": test_script},
            entrypoint="test_script.py",
            runtime="python"
        )

    @classmethod
    async def run_nodejs_test(cls, test_script: str) -> Dict[str, Any]:
        return await cls.run_workspace_test(
            files={"test_script.js": test_script},
            entrypoint="test_script.js",
            runtime="nodejs"
        )

    @classmethod
    async def verify_recipe_full(
        cls,
        runtime: str,
        error_signature: str,
        repro_script: str,
        test_suite: str,
        mutations: Optional[List[str]] = None,
        primary_source: Optional[str] = None
    ) -> EvidenceDefinition:
        """Run the legacy split-script check for trusted internal fixtures.

        The method does not apply a unified diff to the failing workspace and its
        mutation inputs are standalone programs, not mutant diffs.  Consequently
        it can never issue the ``bundle-4-stage-v1`` contract or ``VERIFIED``.
        """
        rt = runtime.lower()
        if rt not in ("python", "nodejs", "node", "javascript", "typescript", "rust"):
            return EvidenceDefinition(
                verificationStatus="FAILED",
                sandboxExitCode=-1,
                passedTests=0,
                totalTests=0,
                confidenceScore=None,
                preExit=-1,
                postExit=-1,
                mutationsKilled="0/0",
                primarySource=primary_source,
            )
        ext = ".py" if rt == "python" else (".js" if rt in ("nodejs", "javascript", "typescript") else ".rs")

        # 1. Pre-Fail Validation
        pre_exit = 1
        pre_passed = False
        if repro_script:
            res_pre = await cls.run_workspace_test(
                files={f"repro{ext}": repro_script},
                entrypoint=f"repro{ext}",
                runtime=rt
            )
            pre_exit = res_pre["exitCode"]
            combined_pre = res_pre["stdout"] + "\n" + res_pre["stderr"]
            # Must fail and signature must be present in output
            if not res_pre["passed"]:
                if not error_signature or (error_signature.lower() in combined_pre.lower()):
                    pre_passed = True

        # 2. Post-Pass Execution
        res_post = await cls.run_workspace_test(
            files={f"test_suite{ext}": test_suite},
            entrypoint=f"test_suite{ext}",
            runtime=rt
        )
        post_exit = res_post["exitCode"]
        post_passed = res_post["passed"]

        # 3. Mutation Sanity
        mutations_killed = 0
        total_mutations = len(mutations) if mutations else 0
        if mutations:
            for idx, mut_code in enumerate(mutations):
                res_mut = await cls.run_workspace_test(
                    files={f"mut_{idx}{ext}": mut_code},
                    entrypoint=f"mut_{idx}{ext}",
                    runtime=rt
                )
                if not res_mut["passed"]:
                    mutations_killed += 1

        # Split scripts are useful diagnostics, but are never 4-stage evidence.
        if post_passed and pre_passed:
            status = "PROVISIONAL"
        elif post_passed:
            status = "DRAFT"
        else:
            status = "FAILED"

        return EvidenceDefinition(
            verificationStatus=status,
            lastTestedAt=datetime.now(timezone.utc),
            sandboxExitCode=post_exit,
            passedTests=1 if post_passed else 0,
            totalTests=1,
            confidenceScore=None,
            preExit=pre_exit,
            postExit=post_exit,
            mutationsKilled=f"{mutations_killed}/{total_mutations}",
            primarySource=primary_source,
            evidenceContract=None,
            isolationProfile={
                "verificationProfile": "trusted-process-limits-v1",
                "isolationStatus": "NOT_ATTESTED",
                "networkIsolation": False,
                "filesystemIsolation": False,
            },
        )

    @classmethod
    async def verify_recipe(cls, runtime: str, test_suite: str, primary_source: str = None) -> EvidenceDefinition:
        """Legacy helper delegating to basic execution (marked as DRAFT unless fully verified)."""
        rt = runtime.lower()
        if rt == "python":
            res = await cls.run_python_test(test_suite)
        elif rt in ("nodejs", "javascript", "typescript"):
            res = await cls.run_nodejs_test(test_suite)
        else:
            res = await cls.run_python_test(test_suite)

        status = "DRAFT" if res["passed"] else "FAILED"
        return EvidenceDefinition(
            verificationStatus=status,
            lastTestedAt=datetime.now(timezone.utc),
            sandboxExitCode=res["exitCode"],
            passedTests=1 if res["passed"] else 0,
            totalTests=1,
            confidenceScore=None,
            preExit=1,
            postExit=res["exitCode"],
            mutationsKilled="0/0",
            primarySource=primary_source
        )
