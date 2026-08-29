import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.bundles import load_all_golden_bundles
from app.config import settings
from app.core.sandbox import SandboxRunner
from app.core.sanitizer import ZeroPiiSanitizer
from app.core.signature_matcher import SignatureMatcher
from app.core.version_matcher import VersionMatcher
from app.database import get_db_connection
from app.main import app
from app.models.recipe import EvidenceDefinition
from scripts.batch_importer import process_candidate_recipes
from scripts.synapse_reverify import apply_patch_unified, bundle_has_recorded_verification_contract


def test_signature_class_gate_precedes_substring_match():
    matched, confidence = SignatureMatcher.compute_match(
        "ValueError: TypeError: unexpected keyword argument 'app'",
        "TypeError: unexpected keyword argument 'app'",
    )
    assert matched is False
    assert confidence == 0.0


@pytest.mark.parametrize("requested", ["", "not-a-version", ">=2,<broken", "???"])
def test_invalid_version_constraints_fail_closed(requested):
    assert VersionMatcher.check_version_compatibility(requested, ">=1,<3") is False


@pytest.mark.parametrize("requested", ["0.28.0rc1", ">=0.28", "0.28.*", "0.28.0,<=0.28.1"])
def test_run_evidence_requires_exact_observed_version(requested):
    assert VersionMatcher.matches_exact_observed_version(requested, "0.28.1") is False
    assert VersionMatcher.matches_exact_observed_version("0.28.1", "0.28.1") is True
    assert VersionMatcher.matches_exact_observed_version("==0.28.1", "0.28.1") is True


def test_sanitizer_redacts_compressed_ipv6_and_dictionary_keys():
    cleaned = ZeroPiiSanitizer.sanitize_data(
        {
            "private.person@example.invalid": "connect to 2001:db8::1 or ::1",
            "safe": "127.0.0.1",
        }
    )
    rendered = json.dumps(cleaned)
    assert "private.person@example.invalid" not in rendered
    assert "2001:db8::1" not in rendered
    assert "::1" not in rendered
    assert "127.0.0.1" not in rendered


def test_patch_application_rejects_plain_text_and_path_change(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("value = 1\n", encoding="utf-8")
    assert apply_patch_unified(target, "value = 2\n", tmp_path) is False
    assert apply_patch_unified(
        target,
        "--- a/app.py\n+++ b/../outside.py\n@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
        tmp_path,
    ) is False
    assert target.read_text(encoding="utf-8") == "value = 1\n"


@pytest.mark.asyncio
async def test_process_runner_rejects_workspace_traversal(tmp_path):
    outside = tmp_path / "outside.py"
    result = await SandboxRunner.run_workspace_test(
        {"../outside.py": "raise SystemExit(0)"},
        "../outside.py",
        runtime="python",
    )
    assert result["unverified"] is True
    assert outside.exists() is False


def test_only_exact_run_bound_curated_bundle_is_advertised_verified():
    bundles = {bundle["bundleId"]: bundle for bundle in load_all_golden_bundles()}
    assert bundles["bundle_duckdb_010_substring_casting_001"]["status"] == "UNVERIFIED"
    httpx = bundles["bundle_httpx_028_asgi_transport_001"]
    assert httpx["status"] == "VERIFIED"
    publication = httpx["evidencePublication"]
    assert publication["qualified"] is True
    assert publication["runArtifactAvailable"] is True
    assert publication["runArtifactUrl"] == (
        "/api/v1/bundles/bundle_httpx_028_asgi_transport_001/evidence"
    )
    assert publication["recordedContractShapeSatisfied"] is True
    assert publication["reason"] == (
        "An exact run-bound four-stage verification artifact is current and validated."
    )
    assert publication["lifecycle"]["status"] == "VERIFIED"
    assert publication["lifecycle"]["qualified"] is True
    assert publication["runArtifactSummary"]["canonicalization"] == "synapse-json-v1"
    assert publication["runArtifactSummary"]["toolchainVersions"]["httpx"] == "0.28.1"
    assert publication["runArtifactSummary"]["mutationsRejected"] == 2


def test_recorded_bundle_contract_rejects_missing_mutations():
    bundle_path = Path("bundles/golden/bundle_httpx_028_asgi_transport.json")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle_has_recorded_verification_contract(bundle) is True
    bundle["verification"]["mutations"] = []
    assert bundle_has_recorded_verification_contract(bundle) is False


def test_verified_evidence_model_rejects_missing_four_stage_proof():
    with pytest.raises(ValueError):
        EvidenceDefinition(
            verificationStatus="VERIFIED",
            evidenceContract="bundle-4-stage-v1",
            preExit=1,
            postExit=0,
            mutationsKilled="1/1",
        )


@pytest.mark.asyncio
async def test_direct_recipe_detail_downgrades_contradictory_verified_row():
    recipe_id = "rec_contradictory_verified_001"
    db = await get_db_connection()
    try:
        await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        await db.execute(
            """
            INSERT INTO recipes
                (id, runtime, error_signature, problem_json, solution_json,
                 reproduction_json, evidence_json, confidence_score, verification_status)
            VALUES (?, 'python', 'ContradictoryError', ?, ?, ?, ?, 1.0, 'VERIFIED')
            """,
            (
                recipe_id,
                json.dumps({"runtime": "python", "errorSignature": "ContradictoryError", "description": "legacy row", "packages": {"example": "1.0.0"}}),
                json.dumps({
                    "summary": "legacy row",
                    "codeDiff": "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n",
                    "pinnedDependencies": {"example": "1.0.0"},
                }),
                json.dumps({"script": "raise RuntimeError()", "testSuite": "assert True"}),
                json.dumps({
                    "verificationStatus": "VERIFIED",
                    "evidenceContract": "bundle-4-stage-v1",
                    "lastTestedAt": "2026-08-27T00:00:00+00:00",
                    "sandboxExitCode": 0,
                    "confidenceScore": 1.0,
                    "preExit": 1,
                    "postExit": 0,
                    "mutationsKilled": "2/2",
                    "toolchainVersions": {"python": "3.12.0", "example": "1.0.0"},
                    "badges": ["BUNDLE_4_STAGE_CONTRACT"],
                    "primarySource": "https://example.invalid/release",
                }),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/recipes/{recipe_id}")
        assert response.status_code == 200
        evidence = response.json()["evidence"]
        assert evidence["verificationStatus"] == "DRAFT"
        assert evidence["evidenceContract"] is None
        assert evidence["confidenceScore"] is None
    finally:
        db = await get_db_connection()
        try:
            await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            await db.commit()
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_malformed_evidence_fails_closed_without_breaking_public_queries():
    recipe_id = "rec_malformed_evidence_001"
    db = await get_db_connection()
    try:
        await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        await db.execute(
            """
            INSERT INTO recipes
                (id, runtime, error_signature, problem_json, solution_json,
                 reproduction_json, evidence_json, confidence_score, verification_status)
            VALUES (?, 'python', 'MalformedEvidenceError', ?, ?, ?, 'not-json', 1.0, 'VERIFIED')
            """,
            (
                recipe_id,
                json.dumps({"runtime": "python", "errorSignature": "MalformedEvidenceError", "description": "invalid evidence", "packages": {}}),
                json.dumps({"summary": "must not be served as verified"}),
                json.dumps({"script": "raise RuntimeError()", "testSuite": "assert True"}),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            stats = await client.get("/api/v1/recipes/stats")
            listing = await client.get("/api/v1/recipes", params={"status": "VERIFIED"})
            search = await client.post(
                "/api/v1/recipes/search",
                json={"errorSignature": "MalformedEvidenceError", "minConfidence": 0},
            )
        assert stats.status_code == 200
        assert listing.status_code == 200
        assert search.status_code == 200
        assert recipe_id not in {item["id"] for item in listing.json()}
        assert recipe_id not in {item["id"] for item in search.json()}
    finally:
        db = await get_db_connection()
        try:
            await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            await db.commit()
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_global_request_body_limit_rejects_oversized_anonymous_input():
    oversized = b'{"jsonrpc":"2.0","id":1,"method":"ping","padding":"' + (b"x" * 1_000_000) + b'"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            content=oversized,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_global_request_body_limit_rejects_oversized_chunked_input():
    async def chunks():
        yield b"x" * 600_000
        yield b"y" * 600_001

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_global_request_body_limit_rejects_invalid_content_length():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/mcp",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "invalid"},
        )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Content-Length header"}


@pytest.mark.asyncio
async def test_sse_session_registry_has_a_per_worker_capacity_bound():
    from app.mcp.server import MAX_SSE_SESSIONS, sse_sessions

    original = dict(sse_sessions)
    try:
        sse_sessions.clear()
        for index in range(MAX_SSE_SESSIONS):
            sse_sessions[f"occupied-{index}"] = asyncio.Queue(maxsize=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert response.status_code == 429
    finally:
        sse_sessions.clear()
        sse_sessions.update(original)


@pytest.mark.asyncio
async def test_legacy_batch_import_never_executes_candidate_code(tmp_path, monkeypatch):
    database_path = tmp_path / "batch.sqlite3"
    sentinel = tmp_path / "executed.txt"
    monkeypatch.setattr(settings, "db_path", str(database_path))
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(
        json.dumps(
            [
                {
                    "id": "rec_security_noexec_001",
                    "runtime": "python",
                    "errorSignature": "RuntimeError: safe draft fixture",
                    "description": "Regression fixture for storage-only candidate intake.",
                    "summary": "Keep executable legacy material as a draft.",
                    "codeDiff": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
                    "reproScript": f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\nraise RuntimeError('x')\n",
                    "testSuite": "assert True\n",
                    "primarySource": "https://example.invalid/release",
                }
            ]
        ),
        encoding="utf-8",
    )

    await process_candidate_recipes(str(candidate_path))

    assert sentinel.exists() is False
    db = await get_db_connection()
    try:
        row = await (
            await db.execute(
                "SELECT verification_status, evidence_json FROM recipes WHERE id = ?",
                ("rec_security_noexec_001",),
            )
        ).fetchone()
    finally:
        await db.close()
    assert row["verification_status"] == "DRAFT"
    assert json.loads(row["evidence_json"])["evidenceContract"] is None
