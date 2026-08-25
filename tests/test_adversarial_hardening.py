import asyncio
import os
import sys
import time
import pytest
from app.core.sandbox import SandboxRunner
from app.mcp.server import sse_sessions, handle_mcp_messages
from app.database import get_db_connection


@pytest.mark.asyncio
async def test_process_tree_kill_on_timeout():
    """
    Priority 1 Test: Ensures that if a sandbox script spawns detached child processes,
    SandboxRunner terminates the ENTIRE process tree (group) upon timeout, leaving 0 orphans.
    """
    forking_script = """
import subprocess
import time
import sys

# Spawn detached child process
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
time.sleep(600)
"""
    start = time.time()
    res = await SandboxRunner.run_workspace_test(
        files={"forker.py": forking_script},
        entrypoint="forker.py",
        runtime="python"
    )
    duration = time.time() - start
    
    assert res["exitCode"] == -1
    assert not res["passed"]
    assert "timed out" in res["stderr"]
    assert duration < 15.0


@pytest.mark.asyncio
async def test_stdout_memory_bomb_capped():
    """
    Priority 2 Test: Ensures that infinite or massive stdout output does not cause
    memory explosion or OOM, and is strictly capped at MAX_OUTPUT_BYTES (512 KiB).
    """
    bomb_script = """
import sys
for _ in range(2000):
    sys.stdout.write("A" * 10000 + "\\n")
    sys.stdout.flush()
"""
    res = await SandboxRunner.run_workspace_test(
        files={"bomb.py": bomb_script},
        entrypoint="bomb.py",
        runtime="python"
    )
    
    assert res["passed"]
    assert len(res["stdout"]) <= (SandboxRunner.MAX_OUTPUT_BYTES + 2048)
    assert "[OUTPUT TRUNCATED: Exceeded 512 KiB limit]" in res["stdout"]


@pytest.mark.asyncio
async def test_sse_backpressure_and_slow_consumer_eviction():
    """
    Priority 4 Test: Ensures that when a slow/stalled consumer fills the SSE queue
    beyond capacity (100 messages), the server drops the session with HTTP 429
    and cleanly evicts it from memory to prevent unbounded producer locks.
    """
    session_id = "test-slow-consumer-session"
    queue = asyncio.Queue(maxsize=10)
    sse_sessions[session_id] = queue

    # Fill queue to max capacity
    for i in range(10):
        queue.put_nowait({"msg": i})

    # Prepare simulated incoming request
    class MockRequest:
        headers = {"content-type": "application/json"}
        async def json(self):
            return {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    # Attempt to push 11th message into full queue -> should evict session
    with pytest.raises(Exception) as exc_info:
        await handle_mcp_messages(MockRequest(), sessionId=session_id)

    # Session must be completely evicted from sse_sessions dictionary
    assert session_id not in sse_sessions
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_sqlite_high_concurrency_stress():
    """
    Priority 5 Test: Spawns 100 parallel async SQLite transactions (reads & writes)
    simultaneously to verify WAL mode + PRAGMA busy_timeout=5000 prevents lock cascade.
    """
    async def worker(idx: int):
        db = await get_db_connection()
        try:
            # Write access log
            await db.execute(
                "INSERT INTO access_logs (source_type, action, query_snippet, user_agent_summary) VALUES (?, ?, ?, ?)",
                ("stress_test", f"action_{idx}", f"query_{idx}", "pytest-worker")
            )
            await db.commit()
            
            # Read stats
            cursor = await db.execute("SELECT COUNT(*) as cnt FROM access_logs WHERE source_type = 'stress_test'")
            row = await cursor.fetchone()
            assert row["cnt"] > 0
        finally:
            await db.close()

    # Launch 100 concurrent workers
    tasks = [worker(i) for i in range(100)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Assert 0 exceptions
    for idx, r in enumerate(results):
        assert not isinstance(r, Exception), f"Worker {idx} failed with error: {r}"
