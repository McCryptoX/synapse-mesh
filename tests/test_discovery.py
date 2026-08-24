import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_well_known_mcp():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/.well-known/mcp.json")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Synapse-Mesh"
    assert "find_solution" in data["capabilities"]["tools"]
    assert data["transport"]["type"] == "streamable-http"


@pytest.mark.asyncio
async def test_well_known_agent():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/.well-known/agent.json")
    assert res.status_code == 200
    data = res.json()
    assert data["agentName"] == "Synapse-Mesh-Exocortex"
    assert data["evidenceFirst"] is True
    assert data["zeroPii"] is True
    assert "MCP/2026" in data["protocols"]
