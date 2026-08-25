import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import init_db
from app.config import settings


@pytest.mark.asyncio
async def test_ops_unauthenticated_login_page():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ops")
        assert response.status_code == 200
        assert "Ops Observatory Access" in response.text
        assert "Passwort oder Access Key" in response.text


@pytest.mark.asyncio
async def test_ops_login_success_and_dashboard():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Submit login form
        response = await client.post("/ops/login", data={"password": settings.ops_password or "synapse-ops-2026"})
        assert response.status_code == 303
        assert "synapse_ops_session" in response.cookies
        
        # Access with session cookie
        dash_res = await client.get("/ops", cookies=response.cookies)
        assert dash_res.status_code == 200
        assert "Synapse-Mesh Ops" in dash_res.text
        assert "Verified" in dash_res.text


@pytest.mark.asyncio
async def test_ops_login_invalid_password():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/ops/login", data={"password": "wrong_password"})
        assert response.status_code == 401
        assert "Ungültiges Passwort" in response.text


@pytest.mark.asyncio
async def test_ops_query_key_access():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/ops?key={settings.ops_password or synapse-ops-2026}")
        assert response.status_code == 200
        assert "Synapse-Mesh Ops" in response.text
