import pytest
from app.core.sandbox import SandboxRunner
from app.database import init_db
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_sandbox_success():
    script = "def test_math(): assert 2 + 2 == 4\ntest_math()"
    res = await SandboxRunner.run_python_test(script)
    assert res["passed"] is True
    assert res["exitCode"] == 0
    assert res["durationMs"] > 0


@pytest.mark.asyncio
async def test_sandbox_failure():
    script = "def test_fail(): assert 2 + 2 == 5\ntest_fail()"
    res = await SandboxRunner.run_python_test(script)
    assert res["passed"] is False
    assert res["exitCode"] != 0
    assert "AssertionError" in res["stderr"]


@pytest.mark.asyncio
async def test_recipe_stats_endpoint():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/recipes/stats")
    assert res.status_code == 200
    data = res.json()
    assert "totalRecipes" in data
    assert "verifiedRecipes" in data
    assert "agentUsage" in data
