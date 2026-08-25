import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import init_db


@pytest.mark.asyncio
async def test_ops_dashboard_html():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ops")
        assert response.status_code == 200
        assert "Synapse-Mesh Ops" in response.text
        assert "Verified" in response.text
        assert "Candidate Drafts" in response.text


@pytest.mark.asyncio
async def test_ops_telemetry_json():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/ops/telemetry")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "items" in data
        assert isinstance(data["items"], list)
