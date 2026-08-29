import asyncio
import uuid

import pytest

from app.core.sandbox import SandboxRunner


@pytest.mark.asyncio
async def test_concurrent_trusted_runner_exposes_shared_workspace_boundary(tmp_path, monkeypatch):
    """
    Prove the documented limitation instead of claiming per-run isolation.

    Concurrent trusted fixtures share the API container's filesystem namespace,
    so a sibling workspace is visible when its path is discovered. Public or
    crawled code must therefore never be executed by this runner.
    """
    boundary_marker = f"SYNAPSE_BOUNDARY_MARKER_{uuid.uuid4().hex}"
    workspace_a = tmp_path / "job-a"
    workspace_b = tmp_path / "job-b"
    allocated = iter((workspace_a, workspace_b))

    def allocate_workspace(*, prefix):
        assert prefix == "synapse_sandbox_"
        path = next(allocated)
        path.mkdir()
        return str(path)

    monkeypatch.setattr("app.core.sandbox.tempfile.mkdtemp", allocate_workspace)

    # Fixture A writes a marker and remains active while fixture B inspects the
    # shared parent directory.
    script_a = f"""
import time
with open("private_marker.txt", "w") as f:
    f.write("{boundary_marker}")
time.sleep(2.0)
print("JOB_A_DONE")
"""

    script_b = f"""
from pathlib import Path

target = "{boundary_marker}"
marker_file = Path({str(workspace_a / 'private_marker.txt')!r})
if marker_file.is_file() and target in marker_file.read_text(errors="ignore"):
    print("SIBLING_WORKSPACE_VISIBLE")
else:
    print("SIBLING_WORKSPACE_NOT_OBSERVED")
"""

    task_a = asyncio.create_task(
        SandboxRunner.run_workspace_test(
            files={"worker_a.py": script_a},
            entrypoint="worker_a.py",
            runtime="python"
        )
    )

    marker_path = workspace_a / "private_marker.txt"
    for _ in range(100):
        if marker_path.exists():
            break
        await asyncio.sleep(0.02)
    assert marker_path.exists()

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
    assert "SIBLING_WORKSPACE_VISIBLE" in res_b["stdout"]
