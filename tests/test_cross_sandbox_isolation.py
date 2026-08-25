import asyncio
import os
import uuid
import pytest
from app.core.sandbox import SandboxRunner
from app.core.kernel_sandbox import KernelSandboxRunner


@pytest.mark.asyncio
async def test_concurrent_cross_sandbox_zero_information_leakage():
    """
    Adversarial Test: Sandbox A runs concurrently with secret token A.
    Sandbox B actively searches /proc, /tmp, and filesystem looking for Sandbox A's secret.
    Asserts that Sandbox B cannot read or detect Sandbox A's private data (Zero Leakage).
    """
    secret_nonce_a = f"SYNAPSE_SECRET_A_{uuid.uuid4().hex}"

    # Sandbox A script: persists secret in memory and writes to local workspace file
    script_a = f"""
import time, os
secret = "{secret_nonce_a}"
with open("private_secret.txt", "w") as f:
    f.write(secret)
# Keep alive briefly for concurrency
time.sleep(2.0)
print("JOB_A_DONE")
"""

    # Sandbox B script (Adversarial Scanner): attempts to discover secret_nonce_a
    script_b = f"""
import os, glob

discovered = []
target_token = "{secret_nonce_a}"

# 1. Probe sibling sandbox directories in /tmp
for fpath in glob.glob("/tmp/synapse_sandbox_*/*"):
    try:
        with open(fpath, "r", errors="ignore") as f:
            content = f.read()
            if target_token in content:
                discovered.append(fpath)
    except Exception:
        pass

# 2. Scan /proc for other process cmdlines and environ
if os.path.exists("/proc"):
    for pid_entry in os.listdir("/proc"):
        if pid_entry.isdigit() and pid_entry != str(os.getpid()):
            for fname in ("cmdline", "environ"):
                fpath = f"/proc/{{pid_entry}}/{{fname}}"
                try:
                    with open(fpath, "rb") as f:
                        if target_token.encode() in f.read():
                            discovered.append(fpath)
                except Exception:
                    pass

if discovered:
    print(f"LEAK_DETECTED: {{discovered}}")
else:
    print("ZERO_LEAK_CONFIRMED")
"""

    # Launch Sandbox A and Sandbox B concurrently
    task_a = asyncio.create_task(
        SandboxRunner.run_workspace_test(
            files={"worker_a.py": script_a},
            entrypoint="worker_a.py",
            runtime="python"
        )
    )

    # Small delay to ensure Sandbox A is actively executing
    await asyncio.sleep(0.3)

    task_b = asyncio.create_task(
        SandboxRunner.run_workspace_test(
            files={"scanner_b.py": script_b},
            entrypoint="scanner_b.py",
            runtime="python"
        )
    )

    res_a, res_b = await asyncio.gather(task_a, task_b)

    assert res_a["passed"]
    assert res_b["passed"]
    assert "ZERO_LEAK_CONFIRMED" in res_b["stdout"]
    assert "LEAK_DETECTED" not in res_b["stdout"]
