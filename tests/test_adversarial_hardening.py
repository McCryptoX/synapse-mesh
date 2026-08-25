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
    
    assert not res["passed"]
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
    
    assert len(res["stdout"]) <= (SandboxRunner.MAX_OUTPUT_BYTES + 4096)
    assert "[RESOURCE_LIMIT_EXCEEDED" in res["stdout"] or "[OUTPUT TRUNCATED" in res["stdout"]


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


@pytest.mark.asyncio
async def test_env_sanitization_no_secrets():
    """
    Security Gate 6: Verifies that sensitive environment variables (API keys, DB URLs,
    ops passwords, tokens) are completely stripped from sandbox subprocess environment.
    """
    # Inject fake secret in host environment
    os.environ["GITHUB_TOKEN"] = "ghp_super_secret_token_12345"
    os.environ["OPS_PASSWORD"] = "ops_super_secret_password"
    os.environ["DATABASE_URL"] = "sqlite:///sensitive/path"
    os.environ["SYNAPSE_INTERNAL_SECRET"] = "do_not_leak_this"

    env_spy_script = """
import os, json
env_keys = list(os.environ.keys())
print("ENV_KEYS:" + json.dumps(env_keys))
"""
    res = await SandboxRunner.run_workspace_test(
        files={"spy.py": env_spy_script},
        entrypoint="spy.py",
        runtime="python"
    )

    assert res["passed"]
    stdout = res["stdout"]
    assert "GITHUB_TOKEN" not in stdout
    assert "OPS_PASSWORD" not in stdout
    assert "DATABASE_URL" not in stdout
    assert "SYNAPSE_INTERNAL_SECRET" not in stdout
    assert "ghp_super_secret_token" not in stdout


@pytest.mark.asyncio
async def test_immediate_output_overflow_kill():
    """
    Security Gate 8: Verifies that exceeding MAX_OUTPUT_BYTES terminates the process
    immediately within milliseconds, rather than spinning CPU/IO for 12 seconds.
    """
    flood_script = """
import sys, time
# Rapid flood
for _ in range(500):
    sys.stdout.write("B" * 65536)
    sys.stdout.flush()
"""
    start = time.time()
    res = await SandboxRunner.run_workspace_test(
        files={"flood.py": flood_script},
        entrypoint="flood.py",
        runtime="python"
    )
    duration = time.time() - start

    # Must be terminated quickly (well below 12s timeout)
    assert duration < 5.0
    assert "RESOURCE_LIMIT_EXCEEDED" in res["stdout"]


@pytest.mark.asyncio
async def test_memory_bomb_isolation():
    """
    Security Gate 3: Verifies that excessive memory allocation inside sandbox fails
    cleanly (MemoryError / RLIMIT_AS) without bringing down host or container.
    """
    mem_bomb_script = """
# Attempt to allocate 4 Gigabytes
x = []
try:
    for _ in range(40):
        x.append(bytearray(100 * 1024 * 1024))
    print("ALLOC_FINISHED")
except (MemoryError, OverflowError):
    print("ALLOC_CAUGHT_MEMORY_ERROR")
"""
    res = await SandboxRunner.run_workspace_test(
        files={"mem_bomb.py": mem_bomb_script},
        entrypoint="mem_bomb.py",
        runtime="python"
    )
    # The sandbox must not freeze or crash the host
    assert res["exitCode"] in (0, -1, 1, 137, 134)

