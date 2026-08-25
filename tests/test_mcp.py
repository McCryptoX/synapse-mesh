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
            "params": {"protocolVersion": "2024-11-05"}
        })
    assert res.status_code == 200
    data = res.json()
    assert data["result"]["serverInfo"]["name"] == "synapse-mesh"
    assert data["result"]["protocolVersion"] == "2024-11-05"


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


@pytest.mark.asyncio
async def test_mcp_server_discover():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "server/discover",
            "params": {}
        })
    assert res.status_code == 200
    data = res.json()
    assert "supportedVersions" in data["result"]
    assert "2024-11-05" in data["result"]["supportedVersions"]
    assert data["result"]["serverInfo"]["name"] == "synapse-mesh"


@pytest.mark.asyncio
async def test_mcp_unknown_error_returns_no_verified_match():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "QuantumWidgetError: flux capacitor handshake timed out while rendering banana mode"
                }
            }
        })
    assert res.status_code == 200
    data = res.json()
    import json
    content = json.loads(data["result"]["content"][0]["text"])
    assert content["status"] == "NO_VERIFIED_MATCH"
    assert content["matchConfidence"] == 0.0


@pytest.mark.asyncio
async def test_mcp_adversarial_queries_rejected():
    adversarial_queries = [
        "RuntimeError: session execute model router timed out while processing unrelated widget payload",
        "WidgetPipelineError: model router session execute failed after banana checksum mismatch",
        "PipelineProcessingError: random payload validation failed on worker 42"
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for q in adversarial_queries:
            res = await ac.post("/mcp", json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "find_solution",
                    "arguments": {"errorSignature": q}
                }
            })
            assert res.status_code == 200
            data = res.json()
            import json
            content = json.loads(data["result"]["content"][0]["text"])
            assert content["status"] == "NO_VERIFIED_MATCH"
            assert content["matchConfidence"] == 0.0


@pytest.mark.asyncio
async def test_mcp_structural_attribute_discriminator():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Negative 1: appendix
        res1 = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {"errorSignature": "AttributeError: 'DataFrame' object has no attribute 'appendix'"}
            }
        })
        import json
        c1 = json.loads(res1.json()["result"]["content"][0]["text"])
        assert c1["status"] == "NO_VERIFIED_MATCH"
        assert c1["matchConfidence"] == 0.0

        # Negative 2: frobnicate
        res2 = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {"errorSignature": "AttributeError: 'DataFrame' object has no attribute 'frobnicate'"}
            }
        })
        c2 = json.loads(res2.json()["result"]["content"][0]["text"])
        assert c2["status"] == "NO_VERIFIED_MATCH"
        assert c2["matchConfidence"] == 0.0

        # Positive: append
        res3 = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {"errorSignature": "AttributeError: 'DataFrame' object has no attribute 'append'"}
            }
        })
        c3 = json.loads(res3.json()["result"]["content"][0]["text"])
        assert c3["status"] == "VERIFIED_MATCH"
        assert c3["matchConfidence"] >= 0.98
        assert c3["recipeId"] == "bundle_pandas_20_dataframe_append_001"



