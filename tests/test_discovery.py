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
    assert data["transport"]["endpoint"] == "https://mcp.synapsemesh.dev"


@pytest.mark.asyncio
async def test_well_known_agent():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/.well-known/agent.json")
    assert res.status_code == 200
    data = res.json()
    assert data["agentName"] == "Synapse-Mesh-Exocortex"
    assert data["evidenceFirst"] is True
    assert data["zeroPii"] is True
    assert "MCP/2026-07-28" in data["protocols"]


@pytest.mark.asyncio
async def test_impressum_and_privacy_pages():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res_imp = await ac.get("/impressum")
        assert res_imp.status_code == 200
        assert "Impressum" in res_imp.text
        assert "Synapse-Mesh Operator" in res_imp.text

        res_priv = await ac.get("/datenschutz")
        assert res_priv.status_code == 200
        assert "Datenschutzerklärung" in res_priv.text
        assert "Zero-PII" in res_priv.text

@pytest.mark.asyncio
async def test_install_script_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/install.sh")
        assert res.status_code == 200
        assert "Synapse-Mesh" in res.text
        assert "claude_desktop_config.json" in res.text

@pytest.mark.asyncio
async def test_well_known_agent_card_standard():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/.well-known/agent-card.json")
        assert res.status_code == 200
        data = res.json()
        assert data["agentName"] == "Synapse-Mesh-Exocortex"
        assert data["evidenceFirst"] is True

@pytest.mark.asyncio
async def test_llms_txt_standard():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/llms.txt")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/markdown")
        assert "# Synapse-Mesh" in res.text
        assert "Verified Compatibility Bundles" in res.text

        res_full = await ac.get("/llms-full.txt")
        assert res_full.status_code == 200
        assert "# Synapse-Mesh" in res_full.text

@pytest.mark.asyncio
async def test_benchmark_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/benchmark")
        assert res.status_code == 200
        assert "Hallucination Elimination" in res.text
        assert "GROUP C (SYNAPSE)" in res.text
