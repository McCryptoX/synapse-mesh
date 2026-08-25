import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_list_bundles():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/bundles")
    assert res.status_code == 200
    bundles = res.json()
    assert len(bundles) >= 3
    ids = [b["bundleId"] for b in bundles]
    assert "bundle_httpx_028_asgi_transport_001" in ids
    assert "bundle_pydantic_v2_model_validator_001" in ids


@pytest.mark.asyncio
async def test_get_bundle_detail():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/bundles/bundle_pydantic_v2_model_validator_001")
    assert res.status_code == 200
    bundle = res.json()
    assert bundle["bundleId"] == "bundle_pydantic_v2_model_validator_001"
    assert bundle["scope"]["package"] == "pydantic"
    assert "workspaceFiles" in bundle["verification"]


@pytest.mark.asyncio
async def test_search_bundles():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/bundles/search", json={"query": "root_validator"})
    assert res.status_code == 200
    results = res.json()
    assert len(results) >= 1
    assert results[0]["bundleId"] == "bundle_pydantic_v2_model_validator_001"
