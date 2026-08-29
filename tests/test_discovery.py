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
    assert data["transport"]["endpoint"] == "https://mcp.synapsemesh.dev/mcp"
    assert "UNVERIFIED_MATCH" in data["resultSemantics"]
    assert "No exact-version run evidence applies" in data["resultSemantics"]["UNVERIFIED_MATCH"]
    assert "supplied package version equals" in data["resultSemantics"]["VERIFIED_MATCH"]
    assert data["publicSubmissionPolicy"].endswith("unexecuted DRAFT")


@pytest.mark.asyncio
async def test_well_known_agent():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/.well-known/agent.json")
    assert res.status_code == 200
    data = res.json()
    assert data["agentName"] == "Synapse-Mesh-Exocortex"
    assert data["evidenceFirst"] is True
    assert data["dataMinimising"] is True
    assert data["verifiedRequiresRunArtifact"] is True
    assert data["publicSubmissionCodeExecuted"] is False
    assert data["autonomousMaintenanceRequiresLlm"] is False
    assert "MCP/2026-07-28" in data["protocols"]


@pytest.mark.asyncio
async def test_legal_and_privacy_pages():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res_legal = await ac.get("/legal")
        assert res_legal.status_code == 200
        assert "Legal Notice" in res_legal.text
        assert "Synapse-Mesh Operator" in res_legal.text
        assert "mesh-direct" in res_legal.text
        assert 'data-u="mesh-direct"' in res_legal.text
        assert 'data-d="synapsemesh.dev"' in res_legal.text
        assert "mesh-direct@synapsemesh.dev" not in res_legal.text
        assert "AS IS" in res_legal.text

        res_priv = await ac.get("/privacy")
        assert res_priv.status_code == 200
        assert "Privacy Policy" in res_priv.text
        assert "Data-Minimizing" in res_priv.text
        assert "mesh-direct" in res_priv.text
        assert 'data-u="mesh-direct"' in res_priv.text
        assert 'data-d="synapsemesh.dev"' in res_priv.text
        assert "mesh-direct@synapsemesh.dev" not in res_priv.text
        assert "synapse_ops_session" in res_priv.text
        assert "SameSite=Strict" in res_priv.text
        assert "ec.europa.eu/consumers/odr" not in res_legal.text

        res_imp = await ac.get("/impressum")
        assert res_imp.status_code == 404
        res_ds = await ac.get("/datenschutz")
        assert res_ds.status_code == 404
        assert "/impressum" not in res_legal.text
        assert "/datenschutz" not in res_legal.text
        assert "/impressum" not in res_priv.text
        assert "/datenschutz" not in res_priv.text


def test_user_agent_summary_never_stores_raw_string():
    from app.mcp.server import summarize_user_agent
    assert summarize_user_agent("codex-mcp-client/0.149.0-alpha.4.1") == "Codex-Client"
    fingerprint = "TotallyNovelAgent/99.1 (secret-fingerprint-xyz)"
    assert summarize_user_agent(fingerprint) == "Other-Agent"
    assert "secret-fingerprint" not in summarize_user_agent(fingerprint)
    assert summarize_user_agent("Antigravity/1.0") == "Gemini-Client"
    assert summarize_user_agent("Codex-Client") == "Codex-Client"
    assert summarize_user_agent("") == "Unknown-Agent"


def test_harvester_extracts_breaking_sections_for_synthesis():
    from scripts.github_harvester import GitHubReleaseHarvester
    from app.core.upstream_miner import BundleSynthesizer

    body = """
# Features
new widgets
# Breaking Changes
Calling `np.NAN` raises `AttributeError: np.NAN was removed in NumPy 2.0. Use np.nan instead.`.
Before:
```python
x = np.NAN
```
After:
```python
x = np.nan
```
"""
    sections = GitHubReleaseHarvester().extract_breaking_sections(body)
    assert sections
    bundle = BundleSynthesizer.synthesize_bundle({
        "package": "numpy",
        "version": "2.0.0",
        "runtime": "python",
        "release_notes": "\n".join(sections),
        "url": "https://github.com/numpy/numpy/releases",
    })
    assert bundle is not None
    assert bundle.status == "DRAFT"
    assert "np.nan" in bundle.patch.unifiedDiff

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
        assert "Curated bundle API" in res.text
        assert "explicitly unverified candidate" in " ".join(res.text.split())
        assert "no A2A task gateway is implemented" in " ".join(res.text.split())
        assert "hermetic" not in res.text.lower()

        res_full = await ac.get("/llms-full.txt")
        assert res_full.status_code == 200
        assert "# Synapse-Mesh" in res_full.text
        assert "A2A task gateway" not in res_full.text
        assert "UNVERIFIED_MATCH" in res_full.text
        assert "reproduce every stage before considering it" in res_full.text

@pytest.mark.asyncio
async def test_benchmark_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/benchmark")
        assert res.status_code == 200
        assert "Evaluation Scope" in res.text
        assert "RESULT WITHHELD" in res.text
        assert "production-runtime revalidation did not satisfy every required case" in res.text
        assert "9 / 9" not in res.text
        assert "No published A/B model result" in res.text
        assert "16.7%" not in res.text
        assert "25.0%" not in res.text
