import pytest
import json
import shutil
from httpx import AsyncClient, ASGITransport
import app.api.bundles as bundles_api
from app.main import app
from app.config import settings
from app.core.run_artifacts import load_valid_run_artifact
from app.api.bundles import BUNDLES_DIR


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
    assert '"ATTESTED"' not in json.dumps(bundles)
    assert all(
        bundle["isolationProfile"]["isolationStatus"] == "NOT_ATTESTED"
        and bundle["isolationProfile"]["attestationAvailable"] is False
        for bundle in bundles
    )


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
async def test_bundle_evidence_endpoint_follows_exact_run_gate():
    bundle_id = "bundle_httpx_028_asgi_transport_001"
    bundle_path = BUNDLES_DIR / "bundle_httpx_028_asgi_transport.json"
    source_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    expected_artifact = load_valid_run_artifact(source_bundle, bundle_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        listing = await ac.get("/api/v1/bundles")
        response = await ac.get(f"/api/v1/bundles/{bundle_id}/evidence")

    public_bundle = next(
        bundle for bundle in listing.json() if bundle["bundleId"] == bundle_id
    )
    publication = public_bundle["evidencePublication"]
    if expected_artifact is None:
        assert response.status_code == 404
        assert publication["qualified"] is False
        assert publication["runArtifactUrl"] is None
        assert publication["runArtifactSummary"] is None
    else:
        assert response.status_code == 200
        assert response.json() == expected_artifact
        assert publication["qualified"] is True
        assert publication["runArtifactUrl"] == f"/api/v1/bundles/{bundle_id}/evidence"
        assert publication["runArtifactSummary"]["completedAt"] == expected_artifact["completedAt"]


@pytest.mark.asyncio
async def test_bundle_evidence_endpoint_rejects_invalid_or_unqualified_ids():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        invalid = await ac.get("/api/v1/bundles/not-a-bundle/evidence")
        unqualified = await ac.get(
            "/api/v1/bundles/bundle_pydantic_v2_model_validator_001/evidence"
        )
    assert invalid.status_code == 404
    assert unqualified.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_bundle_ids_fail_closed(monkeypatch, tmp_path):
    source = BUNDLES_DIR / "bundle_httpx_028_asgi_transport.json"
    shutil.copyfile(source, tmp_path / "copy-one.json")
    shutil.copyfile(source, tmp_path / "copy-two.json")
    monkeypatch.setattr(bundles_api, "BUNDLES_DIR", tmp_path)

    assert bundles_api.load_all_golden_bundles() == []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(
            "/api/v1/bundles/bundle_httpx_028_asgi_transport_001/evidence"
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_bundles():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post("/api/v1/bundles/search", json={"query": "root_validator"})
    assert res.status_code == 200
    results = res.json()
    assert len(results) >= 1
    assert results[0]["bundleId"] == "bundle_pydantic_v2_model_validator_001"


@pytest.mark.asyncio
async def test_verify_endpoint_requires_auth():
    bundle_payload = {
        "schemaVersion": "1.0.0",
        "bundleId": "test_bundle",
        "status": "VERIFIED",
        "description": "Test",
        "scope": {"package": "test", "runtime": "python"},
        "fingerprint": {"errorSignature": "TestError"},
        "patch": {"targetFile": "main.py", "unifiedDiff": "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"},
        "verification": {"reproductionScript": "a", "testSuite": "b", "workspaceFiles": {"main.py": "a"}}
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Unauthenticated request -> 403
        res = await ac.post("/api/v1/bundles/verify", json=bundle_payload)
        assert res.status_code == 403

        # 2. Invalid admin token -> 403
        res_bad = await ac.post("/api/v1/bundles/verify", json=bundle_payload, headers={"X-Synapse-Admin-Key": "wrong_key"})
        assert res_bad.status_code == 403


@pytest.mark.asyncio
async def test_verify_endpoint_authenticated_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "test_secret_admin_token_123")
    
    bundle_payload = {
        "schemaVersion": "1.0.0",
        "bundleId": "test_auth_bundle",
        "status": "VERIFIED",
        "description": "Test Auth Bundle",
        "scope": {"package": "test", "runtime": "python", "affectedVersionRange": ">=1.0.0"},
        "fingerprint": {"errorSignature": "ZeroDivisionError"},
        "patch": {
            "targetFile": "calc.py",
            "unifiedDiff": "--- a/calc.py\n+++ b/calc.py\n@@ -1,1 +1,1 @@\n-x = 1 / 0\n+x = 1 / 1\n"
        },
        "verification": {
            "reproductionScript": "x = 1 / 0\n",
            "testSuite": "import calc\nassert calc.x == 1\n",
            "workspaceFiles": {"calc.py": "x = 1 / 0\n"},
            "mutations": [
                {
                    "id": "mut_still_zero",
                    "unifiedDiff": "--- a/calc.py\n+++ b/calc.py\n@@ -1,1 +1,1 @@\n-x = 1 / 0\n+x = 0 / 0\n"
                }
            ]
        }
    }
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.post(
            "/api/v1/bundles/verify",
            json=bundle_payload,
            headers={"X-Synapse-Admin-Key": "test_secret_admin_token_123"}
        )
        assert res.status_code == 503
        assert "dedicated isolated job runner" in res.json()["detail"]
