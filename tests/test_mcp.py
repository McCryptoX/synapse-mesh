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


@pytest.mark.asyncio
async def test_mcp_variant_recall_and_version_mismatch():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        import json

        # 1. Variant Recall: Series.append
        res1 = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "AttributeError: 'Series' object has no attribute 'append'",
                    "packages": {"pandas": ">=2.0.0"}
                }
            }
        })
        c1 = json.loads(res1.json()["result"]["content"][0]["text"])
        assert c1["status"] == "VERIFIED_MATCH"
        assert c1["recipeId"] == "bundle_pandas_20_dataframe_append_001"
        assert c1["signatureConfidence"] >= 0.98
        assert c1["environmentConfidence"] == 1.0

        # 2. Variant Recall: np.Inf
        res2 = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "AttributeError: `np.Inf` was removed in the NumPy 2.0 release. Use `np.inf` instead."
                }
            }
        })
        c2 = json.loads(res2.json()["result"]["content"][0]["text"])
        assert c2["status"] == "VERIFIED_MATCH"
        assert c2["recipeId"] == "bundle_numpy_20_nan_alias_removal_001"

        # 3. Version Mismatch: pandas 1.5.3 on DataFrame.append removal
        res3 = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "AttributeError: 'DataFrame' object has no attribute 'append'",
                    "packages": {"pandas": "1.5.3"}
                }
            }
        })
        c3 = json.loads(res3.json()["result"]["content"][0]["text"])
        assert c3["status"] == "VERSION_MISMATCH"
        assert c3["signatureConfidence"] >= 0.98
        assert c3["environmentConfidence"] == 0.0
        assert c3["requestedVersion"] == "1.5.3"
        assert c3["recipeAffectedVersions"] == ">=2.0.0"


@pytest.mark.asyncio
async def test_mcp_numpy_bool_rejected_claim_level():
    """
    Verifies that 'np.bool' is NOT matched as removed in NumPy 2.0
    because 'numpy.bool' is present in NumPy 2.0 (canonical name for bool_).
    """
    import numpy as np
    assert hasattr(np, "bool")
    assert np.bool is np.bool_

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        import json
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "AttributeError: `np.bool` was removed in the NumPy 2.0 release. Use `bool` instead.",
                    "packages": {"numpy": "2.0.0"}
                }
            }
        })
        c = json.loads(res.json()["result"]["content"][0]["text"])
        assert c["status"] == "NO_VERIFIED_MATCH"
        assert c["matchConfidence"] == 0.0


@pytest.mark.asyncio
async def test_mcp_unspecified_environment_is_unknown():
    """
    Verifies that when query has DataFrame.append but packages only specifies numpy >= 2.0.0,
    environmentStatus is 'UNKNOWN' and environmentConfidence is null.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        import json
        res = await ac.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "AttributeError: 'DataFrame' object has no attribute 'append'",
                    "packages": {"numpy": ">=2.0.0"}
                }
            }
        })
        c = json.loads(res.json()["result"]["content"][0]["text"])
        assert c["status"] == "VERIFIED_MATCH"
        assert c["signatureConfidence"] >= 0.98
        assert c["environmentStatus"] == "UNKNOWN"
        assert c["environmentConfidence"] is None


@pytest.mark.asyncio
async def test_mcp_semver_compound_interval_matrix():
    """
    Tests full SemVer interval intersection matrix against affectedVersions '>=2.0.0'.
    """
    matrix = [
        ("1.5.3", "VERSION_MISMATCH", "MISMATCH", 0.0),
        ("<2.0", "VERSION_MISMATCH", "MISMATCH", 0.0),
        (">=1.5,<2.0", "VERSION_MISMATCH", "MISMATCH", 0.0),
        (">=2.0,<3.0", "VERIFIED_MATCH", "MATCH", 1.0),
        (">=2.5", "VERIFIED_MATCH", "MATCH", 1.0),
        (">=1.5", "VERIFIED_MATCH", "MATCH", 1.0),
        ("==2.0.0", "VERIFIED_MATCH", "MATCH", 1.0),
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        import json
        for idx, (req_ver, exp_status, exp_env_status, exp_env_conf) in enumerate(matrix):
            res = await ac.post("/mcp", json={
                "jsonrpc": "2.0",
                "id": 100 + idx,
                "method": "tools/call",
                "params": {
                    "name": "find_solution",
                    "arguments": {
                        "errorSignature": "AttributeError: 'DataFrame' object has no attribute 'append'",
                        "packages": {"pandas": req_ver}
                    }
                }
            })
            assert res.status_code == 200
            data = res.json()
            c = json.loads(data["result"]["content"][0]["text"])
            assert c["status"] == exp_status, f"Failed for {req_ver}: expected status {exp_status}, got {c['status']}"
            assert c["environmentStatus"] == exp_env_status, f"Failed for {req_ver}: expected envStatus {exp_env_status}, got {c['environmentStatus']}"
            assert c["environmentConfidence"] == exp_env_conf, f"Failed for {req_ver}: expected envConf {exp_env_conf}, got {c['environmentConfidence']}"







