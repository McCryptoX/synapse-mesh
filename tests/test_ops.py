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
        assert "Password or Access Key" in response.text


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
        assert "Invalid password" in response.text


@pytest.mark.asyncio
async def test_ops_query_key_access():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/ops?key={settings.ops_password or synapse-ops-2026}")
        assert response.status_code == 200
        assert "Synapse-Mesh Ops" in response.text


@pytest.mark.asyncio
async def test_ops_change_password_workflow():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Login with initial password
        initial_pw = settings.ops_password or "synapse-ops-2026"
        login_res = await client.post("/ops/login", data={"password": initial_pw})
        cookies = login_res.cookies

        # 2. Change password to new password
        new_pw = "synapse-super-secret-2026"
        change_res = await client.post(
            "/ops/change-password",
            data={
                "current_password": initial_pw,
                "new_password": new_pw,
                "confirm_password": new_pw
            },
            cookies=cookies
        )
        assert change_res.status_code == 303

        # 3. Verify old password no longer works
        old_login = await client.post("/ops/login", data={"password": "wrong_old_password_123"})
        assert old_login.status_code == 401

        # 4. Verify new password works
        new_login = await client.post("/ops/login", data={"password": new_pw})
        assert new_login.status_code == 303
