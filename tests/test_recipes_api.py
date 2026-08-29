import pytest
import json
import shutil
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from app.main import app
import app.database as database
from app.database import get_db_connection, init_db
from app.models.recipe import EvidenceDefinition
from app.api.bundles import load_all_golden_bundles


def test_database_loader_excludes_ambiguous_bundle_ids(monkeypatch, tmp_path: Path):
    source = (
        Path(__file__).resolve().parent.parent
        / "bundles"
        / "golden"
        / "bundle_httpx_028_asgi_transport.json"
    )
    shutil.copyfile(source, tmp_path / "copy-one.json")
    shutil.copyfile(source, tmp_path / "copy-two.json")
    monkeypatch.setattr(database, "GOLDEN_BUNDLES_DIR", tmp_path)

    assert database._load_golden_bundles() == []


@pytest.mark.asyncio
async def test_submit_and_search_recipe():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Submit
        submit_payload = {
            "id": "rec_test_001",
            "problem": {
                "errorSignature": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
                "runtime": "python",
                "packages": {},
                "description": "Attempting to add int and str directly without cast."
            },
            "solution": {
                "summary": "Cast integer to string using str(val) or format string.",
                "codeDiff": "--- old.py\n+++ new.py\n@@ -1,1 +1,1 @@\n-res = 5 + 'test'\n+res = str(5) + 'test'",
                "instructions": ["Use str(x)"]
            },
            "reproduction": {
                "script": "res = 5 + 'test'",
                "testSuite": "assert str(5) + 'test' == '5test'\nprint('ALL TESTS PASSED')"
            },
            "primarySource": "https://docs.python.org/3/library/functions.html#func-str"
        }
        res = await ac.post("/api/v1/recipes/submit", json=submit_payload)
        assert res.status_code == 201
        created = res.json()
        assert created["id"] == "rec_test_001"
        assert created["evidence"]["verificationStatus"] == "DRAFT"
        assert created["evidence"]["evidenceContract"] is None
        assert created["evidence"]["passedTests"] == 0
        assert created["evidence"]["isolationProfile"] == {}

        # Search
        search_res = await ac.post("/api/v1/recipes/search", json={
            "errorSignature": "unsupported operand type",
            "runtime": "python"
        })
        assert search_res.status_code == 200
        found = search_res.json()
        assert all(item["id"] != "rec_test_001" for item in found)

        draft_res = await ac.get("/api/v1/recipes?status=DRAFT")
        assert draft_res.status_code == 200
        assert any(item["id"] == "rec_test_001" for item in draft_res.json())

        verify_res = await ac.post("/api/v1/recipes/rec_test_001/verify")
        assert verify_res.status_code == 403


@pytest.mark.asyncio
async def test_recipe_search_never_inherits_exact_run_evidence_across_versions():
    signature = (
        "TypeError: AsyncClient.__init__() got an unexpected keyword argument 'app'"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        exact = await ac.post(
            "/api/v1/recipes/search",
            json={"errorSignature": signature, "packages": {"httpx": "0.28.1"}},
        )
        other = await ac.post(
            "/api/v1/recipes/search",
            json={"errorSignature": signature, "packages": {"httpx": "0.28.0"}},
        )
        ambiguous = await ac.post(
            "/api/v1/recipes/search",
            json={"errorSignature": signature, "packages": {"httpx": ">=0.28.0"}},
        )

    assert exact.status_code == other.status_code == ambiguous.status_code == 200
    assert [item["id"] for item in exact.json()] == [
        "bundle_httpx_028_asgi_transport_001"
    ]
    assert exact.json()[0]["evidence"]["verificationStatus"] == "VERIFIED"
    assert other.json() == []
    assert ambiguous.json() == []


@pytest.mark.asyncio
async def test_public_submit_never_executes_and_cannot_overwrite(tmp_path: Path):
    sentinel = tmp_path / "public-code-ran.txt"
    payload = {
        "id": "rec_no_execution_001",
        "problem": {
            "errorSignature": "RuntimeError: public submission must not run",
            "runtime": "python",
            "packages": {},
            "description": "A regression case for fail-closed public ingestion.",
        },
        "solution": {"summary": "Keep the submission in review."},
        "reproduction": {
            "script": f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')",
            "testSuite": f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')",
        },
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        first = await ac.post("/api/v1/recipes/submit", json=payload)
        assert first.status_code == 201
        assert first.json()["evidence"]["verificationStatus"] == "DRAFT"
        assert not sentinel.exists()

        changed = dict(payload)
        changed["solution"] = {"summary": "Attempted overwrite"}
        conflict = await ac.post("/api/v1/recipes/submit", json=changed)
        assert conflict.status_code == 409
        assert not sentinel.exists()

        stored = await ac.get("/api/v1/recipes/rec_no_execution_001")
        assert stored.status_code == 200
        assert stored.json()["solution"]["summary"] == "Keep the submission in review."


@pytest.mark.asyncio
async def test_public_submit_rejects_reserved_or_unsafe_ids():
    payload = {
        "problem": {
            "errorSignature": "ValueError: example",
            "runtime": "python",
            "packages": {},
            "description": "Example",
        },
        "solution": {"summary": "Example"},
        "reproduction": {"script": "raise ValueError('example')", "testSuite": "pass"},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for recipe_id in ("bundle_httpx_028_asgi_transport_001", "rec_BAD", "../rec_escape"):
            response = await ac.post("/api/v1/recipes/submit", json={**payload, "id": recipe_id})
            assert response.status_code == 422


def test_evidence_defaults_fail_closed():
    evidence = EvidenceDefinition()
    assert evidence.verificationStatus == "DRAFT"
    assert evidence.evidenceContract is None
    assert evidence.lastTestedAt is None
    assert evidence.sandboxExitCode == -1
    assert evidence.passedTests == evidence.totalTests == 0
    assert evidence.confidenceScore is None
    assert evidence.preExit == evidence.postExit == -1
    assert evidence.mutationsKilled == "0/0"
    assert evidence.badges == []
    assert evidence.isolationProfile == {}


@pytest.mark.asyncio
async def test_startup_migration_clears_query_text_and_quarantines_legacy_verified():
    legacy_id = "rec_legacy_claim_001"
    contract_id = "rec_contract_claim_001"
    db = await get_db_connection()
    try:
        base_values = (
            "python",
            "ValueError: migration",
            json.dumps({"errorSignature": "ValueError: migration", "runtime": "python", "description": "migration", "packages": {}}),
            json.dumps({"summary": "migration"}),
            json.dumps({"script": "pass", "testSuite": "pass"}),
        )
        for recipe_id, evidence in (
            (legacy_id, {"verificationStatus": "VERIFIED", "confidenceScore": 1.0, "badges": ["VERIFIED_SANDBOX"]}),
            (contract_id, {"verificationStatus": "VERIFIED", "evidenceContract": "bundle-4-stage-v1", "confidenceScore": 1.0}),
        ):
            await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            await db.execute(
                """
                INSERT INTO recipes
                    (id, runtime, error_signature, problem_json, solution_json, reproduction_json,
                     evidence_json, confidence_score, verification_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, 'VERIFIED')
                """,
                (recipe_id, *base_values, json.dumps(evidence)),
            )
        current_log = await db.execute(
            "INSERT INTO access_logs (source_type, action, query_snippet, user_agent_summary) VALUES ('mcp_call', 'initialize', 'private query text', 'secret-client/9.4')"
        )
        current_log_id = current_log.lastrowid
        old_log = await db.execute(
            """
            INSERT INTO access_logs (source_type, action, query_snippet, user_agent_summary, created_at)
            VALUES ('mcp_call', 'initialize', 'old private query text', 'secret-client/8.1', datetime('now', '-31 days'))
            """
        )
        old_log_id = old_log.lastrowid
        await db.commit()
    finally:
        await db.close()

    await init_db()

    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT verification_status, confidence_score, evidence_json FROM recipes WHERE id = ?", (legacy_id,))
        legacy = await cursor.fetchone()
        assert legacy["verification_status"] == "DRAFT"
        assert legacy["confidence_score"] == 0.0
        legacy_evidence = json.loads(legacy["evidence_json"])
        assert legacy_evidence["verificationStatus"] == "DRAFT"
        assert legacy_evidence["badges"] == []
        assert legacy_evidence["isolationProfile"] == {}

        cursor = await db.execute("SELECT verification_status FROM recipes WHERE id = ?", (contract_id,))
        assert (await cursor.fetchone())["verification_status"] == "DRAFT"
        cursor = await db.execute(
            "SELECT source_type, action, query_snippet, user_agent_summary FROM access_logs WHERE id = ?",
            (current_log_id,),
        )
        telemetry = await cursor.fetchone()
        assert telemetry["source_type"] == "mcp_call"
        assert telemetry["action"] == "initialize"
        assert telemetry["query_snippet"] == ""
        assert telemetry["user_agent_summary"] == "Other-Agent"
        cursor = await db.execute("SELECT COUNT(*) AS count FROM access_logs WHERE id = ?", (old_log_id,))
        assert (await cursor.fetchone())["count"] == 0
    finally:
        await db.execute("DELETE FROM recipes WHERE id IN (?, ?)", (legacy_id, contract_id))
        await db.execute("DELETE FROM access_logs WHERE id IN (?, ?)", (current_log_id, old_log_id))
        await db.commit()
        await db.close()

@pytest.mark.asyncio
async def test_recipe_detail_html_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/recipes/rec_test_001")
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "rec_test_001" in res.text
        assert "Recorded Execution Evidence" in res.text


@pytest.mark.asyncio
async def test_registry_stats_list_and_status_limit_share_one_snapshot():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        stats_response = await ac.get("/api/v1/recipes/stats")
        list_response = await ac.get("/api/v1/recipes?limit=1000")
        verified_response = await ac.get("/api/v1/recipes?status=VERIFIED&limit=1")

    assert stats_response.status_code == 200
    assert list_response.status_code == 200
    assert verified_response.status_code == 200
    stats = stats_response.json()
    records = list_response.json()
    assert stats["totalRecipes"] == len(records)
    assert sum(stats["recordClassCounts"].values()) == stats["totalRecipes"]
    assert stats["curatedBundles"] == len(load_all_golden_bundles())
    assert stats["verifiedRecipes"] == stats["evidenceQualifiedCurated"]
    assert len(verified_response.json()) == 1
    assert verified_response.json()[0]["evidence"]["verificationStatus"] == "VERIFIED"


@pytest.mark.asyncio
async def test_every_registry_count_matches_its_actual_filter_result():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        stats = (await ac.get("/api/v1/recipes/stats")).json()
        record_class_results = {
            record_class: (
                await ac.get(f"/api/v1/recipes?status={record_class}&limit=1000")
            ).json()
            for record_class in ("CURATED", "DRAFT", "FAILED")
        }
        evidence_status_results = {
            evidence_status: (
                await ac.get(f"/api/v1/recipes?status={evidence_status}&limit=1000")
            ).json()
            for evidence_status in ("VERIFIED", "UNVERIFIED")
        }

    for record_class, records in record_class_results.items():
        assert len(records) == stats["recordClassCounts"][record_class]
    for evidence_status, records in evidence_status_results.items():
        assert len(records) == stats["evidenceStatusCounts"][evidence_status]

    curated_ids = {record["id"] for record in record_class_results["CURATED"]}
    verified_ids = {record["id"] for record in evidence_status_results["VERIFIED"]}
    assert verified_ids <= curated_ids
    assert len(curated_ids) == stats["curatedBundles"]


@pytest.mark.asyncio
async def test_stats_coarsen_legacy_client_labels_again_at_read_time():
    db = await get_db_connection()
    try:
        cursor = await db.execute(
            """
            INSERT INTO access_logs
                (source_type, action, query_snippet, user_agent_summary)
            VALUES ('unexpected-source', 'unexpected-action', 'private-query-value', 'UniqueCrawler/93.7 device-token')
            """
        )
        log_id = cursor.lastrowid
        await db.commit()
    finally:
        await db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/recipes/stats")
        serialized = json.dumps(response.json())
        assert response.status_code == 200
        assert "UniqueCrawler" not in serialized
        assert "device-token" not in serialized
        assert "private-query-value" not in serialized
        assert "unexpected-source" not in serialized
        assert "unexpected-action" not in serialized
        assert "Other-Agent" in response.json()["agentUsage"]["agentBreakdown"]
    finally:
        db = await get_db_connection()
        try:
            await db.execute("DELETE FROM access_logs WHERE id = ?", (log_id,))
            await db.commit()
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_curated_projection_uses_current_artifact_not_stale_sqlite_copy():
    bundle_id = "bundle_httpx_028_asgi_transport_001"
    current_bundle = next(
        bundle for bundle in load_all_golden_bundles() if bundle["bundleId"] == bundle_id
    )
    assert current_bundle["status"] == "VERIFIED"
    completed_at = current_bundle["evidencePublication"]["runArtifactSummary"]["completedAt"]

    db = await get_db_connection()
    try:
        row = await (
            await db.execute(
                "SELECT evidence_json, verification_status FROM recipes WHERE id = ?",
                (bundle_id,),
            )
        ).fetchone()
        original_evidence = row["evidence_json"]
        original_status = row["verification_status"]
        stale_evidence = json.loads(original_evidence)
        stale_evidence["lastTestedAt"] = "2000-01-01T00:00:00Z"
        await db.execute(
            "UPDATE recipes SET evidence_json = ?, verification_status = 'VERIFIED' WHERE id = ?",
            (json.dumps(stale_evidence), bundle_id),
        )
        await db.commit()
    finally:
        await db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(f"/api/v1/recipes/{bundle_id}")
            filtered = await ac.get("/api/v1/recipes?status=VERIFIED&limit=1")
        assert response.status_code == 200
        assert response.json()["evidence"]["verificationStatus"] == "VERIFIED"
        assert response.json()["evidence"]["lastTestedAt"].replace("+00:00", "Z") == completed_at
        assert filtered.json()[0]["id"] == bundle_id
    finally:
        db = await get_db_connection()
        try:
            await db.execute(
                "UPDATE recipes SET evidence_json = ?, verification_status = ? WHERE id = ?",
                (original_evidence, original_status, bundle_id),
            )
            await db.commit()
        finally:
            await db.close()
