import hashlib
import json
import re
import time

import pytest
from httpx import AsyncClient, ASGITransport, Cookies

from app.main import app
from app.database import get_db_connection, init_db
from app.config import settings
from app.api.bundles import load_all_golden_bundles
from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT
from app.api.ops import (
    COOKIE_NAME,
    SESSION_KEY_PREFIX,
    _legacy_ops_password_hash,
    _session_db_key,
)


BOOTSTRAP_PASSWORD = "test-bootstrap-password-2026"
ROTATED_PASSWORD = "test-rotated-password-2026"


async def reset_ops_auth() -> None:
    await init_db()
    db = await get_db_connection()
    try:
        await db.execute(
            "DELETE FROM system_config WHERE key = 'ops_password_hash' OR key GLOB ?",
            (f"{SESSION_KEY_PREFIX}*",),
        )
        await db.commit()
    finally:
        await db.close()


def configure_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ops_password", BOOTSTRAP_PASSWORD)
    monkeypatch.setattr(settings, "admin_token", "")


def _dashboard_status_for_recipe(html: str, recipe_id: str) -> str:
    recipe_position = html.index(recipe_id)
    class_position = html.rfind('class="card recipe-row"', 0, recipe_position)
    assert class_position >= 0
    row_position = html.rfind("<", 0, class_position)
    status_match = re.search(r'data-status="([^"]+)"', html[row_position:recipe_position])
    assert status_match is not None
    return status_match.group(1)


@pytest.mark.asyncio
async def test_ops_unauthenticated_login_page_has_no_store(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.get("/ops")
        assert response.status_code == 200
        assert "Ops Observatory Access" in response.text
        assert "Password or Access Key" in response.text
        assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_ops_login_issues_opaque_server_side_secure_session(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
        assert response.status_code == 303
        token = response.cookies[COOKIE_NAME]
        assert token != BOOTSTRAP_PASSWORD
        assert token != hashlib.sha256(BOOTSTRAP_PASSWORD.encode()).hexdigest()

        set_cookie = response.headers["set-cookie"].lower()
        assert "secure" in set_cookie
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie
        assert "max-age=3600" in set_cookie
        assert response.headers["cache-control"].startswith("no-store")

        db = await get_db_connection()
        try:
            cursor = await db.execute(
                "SELECT key, value FROM system_config WHERE key = ?",
                (_session_db_key(token),),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert token not in row["key"]
            assert int(json.loads(row["value"])["expiresAt"]) > int(time.time())
        finally:
            await db.close()

        dash_res = await client.get("/ops")
        assert dash_res.status_code == 200
        assert "Synapse-Mesh Ops" in dash_res.text
        assert "Evidence-qualified Curated" in dash_res.text
        assert "Autonomous / Read Only" in dash_res.text
        assert "Run Verification Sweep" not in dash_res.text
        assert dash_res.headers["cache-control"].startswith("no-store")
        assert 'onclick="toggleDiff' not in dash_res.text
        assert "VERIFIED (100%)" not in dash_res.text
        assert "Pass-Rate in Sandbox" not in dash_res.text
        assert "Diff-Apply: AST OK" not in dash_res.text
        assert "Mounting isolated tmpfs" not in dash_res.text


@pytest.mark.asyncio
async def test_ops_verification_trigger_is_authenticated_and_fail_closed(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        unauthenticated = await client.post("/api/v1/ops/trigger-verify")
        assert unauthenticated.status_code == 403
        assert "no-store" in unauthenticated.headers["cache-control"]

        assert (
            await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
        ).status_code == 303
        disabled = await client.post("/api/v1/ops/trigger-verify")

    assert disabled.status_code == 503
    assert "no-store" in disabled.headers["cache-control"]
    assert disabled.json()["status"] == "DISABLED"
    assert "Synchronous server-side verification is disabled" in disabled.json()["detail"]
    assert "hostile-code verification" in disabled.json()["detail"]


@pytest.mark.asyncio
async def test_ops_verified_count_and_display_require_current_evidence_contract(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    qualified_id = "rec_ops_contract_qualified"
    missing_contract_id = "rec_ops_contract_missing"
    mismatched_status_id = "rec_ops_contract_mismatched"
    malformed_evidence_id = "rec_ops_contract_malformed"
    fixture_ids = (
        qualified_id,
        missing_contract_id,
        mismatched_status_id,
        malformed_evidence_id,
    )

    db = await get_db_connection()
    try:
        verified_before = sum(
            bundle["status"] == "VERIFIED" for bundle in load_all_golden_bundles()
        )

        common_problem = json.dumps(
            {
                "errorSignature": "RuntimeError: ops contract fixture",
                "runtime": "python",
                "packages": {},
                "description": "Private operations evidence-contract regression fixture.",
            }
        )
        common_solution = json.dumps({"summary": "Regression fixture."})
        common_reproduction = json.dumps({"script": "raise RuntimeError", "testSuite": "pass"})
        evidence_by_id = {
            qualified_id: json.dumps(
                {
                    "verificationStatus": "VERIFIED",
                    "evidenceContract": VERIFIED_EVIDENCE_CONTRACT,
                }
            ),
            missing_contract_id: json.dumps(
                {"verificationStatus": "VERIFIED", "evidenceContract": None}
            ),
            mismatched_status_id: json.dumps(
                {
                    "verificationStatus": "DRAFT",
                    "evidenceContract": VERIFIED_EVIDENCE_CONTRACT,
                }
            ),
            malformed_evidence_id: "{not-valid-json",
        }
        await db.executemany(
            """
            INSERT INTO recipes (
                id, runtime, error_signature, problem_json, solution_json,
                reproduction_json, evidence_json, confidence_score,
                verification_status
            ) VALUES (?, 'python', 'RuntimeError: ops contract fixture', ?, ?, ?, ?, 1.0, 'VERIFIED')
            """,
            [
                (
                    recipe_id,
                    common_problem,
                    common_solution,
                    common_reproduction,
                    evidence,
                )
                for recipe_id, evidence in evidence_by_id.items()
            ],
        )
        await db.commit()
    finally:
        await db.close()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            assert (
                await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
            ).status_code == 303

            dashboard = await client.get("/ops")
            assert dashboard.status_code == 200
            verified_match = re.search(
                r"Evidence-qualified Curated</div>\s*<div[^>]*>(\d+)</div>",
                dashboard.text,
            )
            assert verified_match is not None
            assert int(verified_match.group(1)) == verified_before
            assert _dashboard_status_for_recipe(dashboard.text, qualified_id) == "DRAFT"
            assert _dashboard_status_for_recipe(dashboard.text, missing_contract_id) == "DRAFT"
            assert _dashboard_status_for_recipe(dashboard.text, mismatched_status_id) == "DRAFT"
            assert _dashboard_status_for_recipe(dashboard.text, malformed_evidence_id) == "DRAFT"

            telemetry_response = await client.get("/api/v1/ops/telemetry")
            assert telemetry_response.status_code == 200
            telemetry = {
                item["id"]: item["status"]
                for item in telemetry_response.json()["items"]
                if item["id"] in fixture_ids
            }
            assert telemetry == {
                qualified_id: "DRAFT",
                missing_contract_id: "DRAFT",
                mismatched_status_id: "DRAFT",
                malformed_evidence_id: "DRAFT",
            }
    finally:
        db = await get_db_connection()
        try:
            await db.executemany(
                "DELETE FROM recipes WHERE id = ?",
                [(recipe_id,) for recipe_id in fixture_ids],
            )
            await db.commit()
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_ops_login_invalid_password(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post("/ops/login", data={"password": "wrong_password"})
        assert response.status_code == 401
        assert "Invalid password" in response.text
        assert response.headers["cache-control"].startswith("no-store")


@pytest.mark.asyncio
async def test_historical_builtin_password_is_not_a_credential(monkeypatch):
    await reset_ops_auth()
    monkeypatch.setattr(settings, "ops_password", "")
    monkeypatch.setattr(settings, "admin_token", "")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post(
            "/ops/login", data={"password": "synapse-ops-2026"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_existing_legacy_database_hash_is_upgraded_after_valid_login(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    db = await get_db_connection()
    try:
        await db.execute(
            "INSERT INTO system_config (key, value) VALUES ('ops_password_hash', ?)",
            (_legacy_ops_password_hash(BOOTSTRAP_PASSWORD),),
        )
        await db.commit()
    finally:
        await db.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
    assert response.status_code == 303

    db = await get_db_connection()
    try:
        cursor = await db.execute(
            "SELECT value FROM system_config WHERE key = 'ops_password_hash'"
        )
        row = await cursor.fetchone()
        assert row["value"].startswith("pbkdf2_sha256$")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ops_query_string_cannot_authenticate(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.get("/ops", params={"key": BOOTSTRAP_PASSWORD})
        assert response.status_code == 200
        assert "Ops Observatory Access" in response.text
        assert COOKIE_NAME not in response.cookies

        telemetry = await client.get(
            "/api/v1/ops/telemetry", params={"key": BOOTSTRAP_PASSWORD}
        )
        assert telemetry.status_code == 403
        assert "no-store" in telemetry.headers["cache-control"]


@pytest.mark.asyncio
async def test_database_password_hash_disables_every_config_fallback(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        assert (await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})).status_code == 303

        monkeypatch.setattr(settings, "ops_password", "different-env-password")
        monkeypatch.setattr(settings, "admin_token", "different-admin-token")
        assert (await client.post("/ops/login", data={"password": "different-env-password"})).status_code == 401
        assert (await client.post("/ops/login", data={"password": "different-admin-token"})).status_code == 401


@pytest.mark.asyncio
async def test_ops_password_rotation_revokes_old_password_and_sessions(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        login_res = await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
        assert login_res.status_code == 303
        old_token = login_res.cookies[COOKIE_NAME]

        change_res = await client.post(
            "/ops/change-password",
            data={
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": ROTATED_PASSWORD,
                "confirm_password": ROTATED_PASSWORD,
            },
        )
        assert change_res.status_code == 303
        assert change_res.cookies[COOKIE_NAME] != old_token

        assert (await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})).status_code == 401
        assert (await client.post("/ops/login", data={"password": ROTATED_PASSWORD})).status_code == 303

        stale_cookies = Cookies()
        stale_cookies.set(COOKIE_NAME, old_token, domain="testserver", path="/")
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            cookies=stale_cookies,
        ) as stale_client:
            stale_dash = await stale_client.get("/ops")
            assert "Ops Observatory Access" in stale_dash.text


@pytest.mark.asyncio
async def test_legacy_plaintext_and_password_hash_cookies_are_rejected(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        login = await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
        assert login.status_code == 303

    legacy_cookie_values = (
        BOOTSTRAP_PASSWORD,
        hashlib.sha256(
            f"synapse_ops_salt_2026_{BOOTSTRAP_PASSWORD}".encode("utf-8")
        ).hexdigest(),
    )
    for legacy_value in legacy_cookie_values:
        cookies = Cookies()
        cookies.set(COOKIE_NAME, legacy_value, domain="testserver", path="/")
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
            cookies=cookies,
        ) as legacy_client:
            response = await legacy_client.get("/ops")
            assert "Ops Observatory Access" in response.text


@pytest.mark.asyncio
async def test_ops_logout_revokes_server_side_session(monkeypatch):
    await reset_ops_auth()
    configure_bootstrap(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        login = await client.post("/ops/login", data={"password": BOOTSTRAP_PASSWORD})
        token = login.cookies[COOKIE_NAME]
        logout = await client.post("/ops/logout")
        assert logout.status_code == 303
        assert logout.headers["cache-control"].startswith("no-store")

        db = await get_db_connection()
        try:
            cursor = await db.execute(
                "SELECT 1 FROM system_config WHERE key = ?", (_session_db_key(token),)
            )
            assert await cursor.fetchone() is None
        finally:
            await db.close()
