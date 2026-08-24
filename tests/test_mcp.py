import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_mcp_initialize():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        })
    assert res.status_code == 200
    data = res.json()
    assert data["result"]["serverInfo"]["name"] == "Synapse-Mesh-Exocortex"


@pytest.mark.asyncio
async def test_mcp_tools_list():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        })
    assert res.status_code == 200
    data = res.json()
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "find_solution" in tool_names
    assert "submit_solution" in tool_names


@pytest.mark.asyncio
async def test_mcp_tool_call_find_solution():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "unsupported operand type",
                    "runtime": "python"
                }
            }
        })
    assert res.status_code == 200
    data = res.json()
    assert "content" in data["result"]
    assert len(data["result"]["content"]) > 0
