import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional
from app.models.recipe import EvidenceDefinition
from datetime import datetime, timezone


class SandboxRunner:
    """Executes multi-ecosystem reproduction and test suites in isolated temporary workspaces with strict limits."""

    TIMEOUT_SECONDS = 12.0

    @classmethod
    async def run_workspace_test(
        cls,
        files: Dict[str, str],
        entrypoint: str,
        runtime: str = "python"
    ) -> Dict[str, Any]:
        """Executes a multi-file workspace hermetically in an isolated directory across Python, Node.js, and Rust."""
        start_time = time.time()
        temp_dir = tempfile.mkdtemp(prefix="synapse_sandbox_")

        try:
            # 1. Write all workspace files
            for rel_path, content in files.items():
                target_file = Path(temp_dir) / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding="utf-8")

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            if "NODE_PATH" not in env and os.path.exists("/usr/lib/node_modules"):
                env["NODE_PATH"] = "/usr/lib/node_modules"

            rt = runtime.lower()

            # 2. Select Executable & Command Line
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
                args = [executable, entrypoint]
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
                # For Rust, entrypoint specifies the cargo/rustc action (e.g. 'check' or 'test')
                if entrypoint == "check":
                    args = [cargo_bin, "check", "--offline"]
                elif entrypoint == "test":
                    args = [cargo_bin, "test", "--offline"]
                else:
                    rustc_bin = shutil.which("rustc")
                    args = [rustc_bin, entrypoint]
            else:
                executable = sys.executable
                args = [executable, entrypoint]

            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=temp_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=cls.TIMEOUT_SECONDS
                )
                exit_code = process.returncode
                stdout = stdout_bytes.decode(errors="replace")
                stderr = stderr_bytes.decode(errors="replace")
            except asyncio.TimeoutError:
                process.kill()
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
    async def verify_recipe(cls, runtime: str, test_suite: str, primary_source: str = None) -> EvidenceDefinition:
        rt = runtime.lower()
        if rt == "python":
            res = await cls.run_python_test(test_suite)
        elif rt in ("nodejs", "javascript", "typescript"):
            res = await cls.run_nodejs_test(test_suite)
        else:
            res = await cls.run_python_test(test_suite)

        status = "VERIFIED" if res["passed"] else "FAILED"
        confidence = 0.99 if res["passed"] else 0.10
        return EvidenceDefinition(
            verificationStatus=status,
            lastTestedAt=datetime.now(timezone.utc),
            sandboxExitCode=res["exitCode"],
            passedTests=1 if res["passed"] else 0,
            totalTests=1,
            confidenceScore=confidence,
            primarySource=primary_source
        )
