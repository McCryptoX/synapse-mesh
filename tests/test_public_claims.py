import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.bundles import load_all_golden_bundles
from app.database import get_db_connection
from app.main import app


PUBLIC_TEMPLATE_NAMES = (
    "index.html",
    "benchmark.html",
    "verification.html",
    "legal.html",
    "privacy.html",
    "recipe_detail.html",
    "api_docs.html",
)


@pytest.mark.asyncio
async def test_homepage_registry_uses_only_disk_curated_bundles():
    legacy_id = "rec_sqlite_verified_must_not_reach_homepage"
    db = await get_db_connection()
    try:
        await db.execute("DELETE FROM recipes WHERE id = ?", (legacy_id,))
        await db.execute(
            """
            INSERT INTO recipes
                (id, runtime, error_signature, problem_json, solution_json,
                 reproduction_json, evidence_json, confidence_score, verification_status)
            VALUES (?, 'python', 'LegacyError', ?, ?, ?, ?, 1.0, 'VERIFIED')
            """,
            (
                legacy_id,
                json.dumps({"runtime": "python", "errorSignature": "LegacyError", "description": "legacy"}),
                json.dumps({"summary": "legacy"}),
                json.dumps({"script": "pass", "testSuite": "pass"}),
                json.dumps({"verificationStatus": "VERIFIED", "evidenceContract": "bundle-4-stage-v1"}),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/")
        assert response.status_code == 200
        assert legacy_id not in response.text
        assert "/api/v1/recipes?limit=" not in response.text
        for bundle in load_all_golden_bundles():
            assert bundle["bundleId"] in response.text
    finally:
        db = await get_db_connection()
        try:
            await db.execute("DELETE FROM recipes WHERE id = ?", (legacy_id,))
            await db.commit()
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_machine_home_manifest_discloses_execution_and_autonomy_limits():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/?format=json")
    assert response.status_code == 200
    data = response.json()
    assert data["registry"]["source"] == "curated-bundle-files"
    assert data["registry"]["bundleCount"] == len(load_all_golden_bundles())
    assert data["registry"]["evidenceQualifiedCount"] == sum(
        bundle["status"] == "VERIFIED" for bundle in load_all_golden_bundles()
    )
    assert data["registry"]["legacySqliteVerifiedClaimsIncluded"] is False
    assert data["executionPolicy"]["publicSubmissionCodeExecuted"] is False
    assert data["autonomousMaintenance"]["requiresLlm"] is False
    assert data["autonomousMaintenance"]["selfModifiesApplicationCode"] is False
    assert data["autonomousMaintenance"]["selfPromotesGoldenEvidence"] is False
    assert "UNVERIFIED_MATCH" in data["matchSemantics"]


@pytest.mark.asyncio
async def test_recipe_detail_is_status_aware_and_json_ld_is_script_safe():
    recipe_id = "rec_public_claim_xss_001"
    signature = '</script><script id="injected-script">alert(1)</script>'
    db = await get_db_connection()
    try:
        await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        await db.execute(
            """
            INSERT INTO recipes
                (id, runtime, error_signature, problem_json, solution_json,
                 reproduction_json, evidence_json, confidence_score, verification_status)
            VALUES (?, 'python', ?, ?, ?, ?, ?, 0.0, 'DRAFT')
            """,
            (
                recipe_id,
                signature,
                json.dumps({"runtime": "python", "errorSignature": signature, "description": "draft", "packages": {}}),
                json.dumps({"summary": "Unreviewed draft", "codeDiff": "", "pinnedDependencies": {}, "doNot": []}),
                json.dumps({"script": "pass", "testSuite": "pass"}),
                json.dumps(
                    {
                        "verificationStatus": "DRAFT",
                        "confidenceScore": 0.0,
                        "sandboxExitCode": 0,
                        "passedTests": 0,
                        "totalTests": 0,
                        "mutationsKilled": "0/0",
                        "primarySource": "javascript:alert(1)",
                    }
                ),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/recipes/{recipe_id}")
        assert response.status_code == 200
        assert '<script id="injected-script">' not in response.text
        assert 'href="javascript:' not in response.text
        assert "DRAFT — not evidence-qualified" in response.text
        assert "0 / 0" in response.text
        assert "0/0" in response.text
        assert "SANDBOX VERIFIED" not in response.text
        assert "Proposed Patch / Diff" in response.text
    finally:
        db = await get_db_connection()
        try:
            await db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            await db.commit()
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_public_architecture_states_current_limits():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        verification = await client.get("/verification")
        benchmark = await client.get("/benchmark")
    assert verification.status_code == 200
    assert "Public recipe submissions" in verification.text
    assert "not executed by the server" in verification.text
    assert "Active: hourly draft maintenance" in verification.text
    assert "Active: daily exact allowlist" in verification.text
    assert "Not implemented: public hostile-code runner" in verification.text
    assert "does not attest a read-only root filesystem" in verification.text
    assert "No published A/B model result" in benchmark.text
    assert "RESULT WITHHELD" in benchmark.text
    assert "9 / 9" not in benchmark.text


@pytest.mark.asyncio
async def test_homepage_does_not_expose_runtime_output():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        homepage = await client.get("/")
        llms_full = await client.get("/llms-full.txt")
    assert homepage.status_code == 200
    assert llms_full.status_code == 200
    assert "NOT EXPOSED" in homepage.text
    assert "RUNTIME OUTPUT" in homepage.text
    assert "WITHHELD" not in homepage.text
    assert "NO APP IP LOGGING" in homepage.text
    assert "CONFIGURED MINIMIZATION" in homepage.text
    assert "FAIL CLOSED" in homepage.text
    assert "MISSING EVIDENCE" in homepage.text
    assert "9/9" not in homepage.text
    assert "9 / 9" not in homepage.text
    assert "9/9" not in llms_full.text
    assert "numeric result is currently withheld" in " ".join(llms_full.text.split())


def test_homepage_install_command_and_copy_action_match():
    source = (Path(__file__).resolve().parent.parent / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    command = "curl -fsSL https://synapsemesh.dev/install.sh | bash"
    assert f">{command}</code>" in source
    assert f"navigator.clipboard.writeText('{command}')" in source


@pytest.mark.asyncio
async def test_verified_recipe_projection_does_not_inherit_isolation_attestation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/recipes?status=VERIFIED")
    assert response.status_code == 200
    recipes = response.json()
    assert all(recipe["evidence"]["isolationProfile"] == {} for recipe in recipes)
    assert '"ATTESTED"' not in json.dumps(recipes)


def test_public_templates_use_one_shared_header_footer_and_stylesheet():
    templates_dir = Path(__file__).resolve().parent.parent / "app" / "templates"
    for template_name in PUBLIC_TEMPLATE_NAMES:
        source = (templates_dir / template_name).read_text(encoding="utf-8")
        assert source.count('{% include "partials/public_header.html" %}') == 1
        assert source.count('{% include "partials/public_footer.html" %}') == 1
        assert "<header" not in source
        assert "<footer" not in source
        assert '<link rel="stylesheet" href="/style.min.css">' in source

    homepage = (templates_dir / "index.html").read_text(encoding="utf-8")
    architecture = (templates_dir / "verification.html").read_text(encoding="utf-8")
    assert "<style" not in homepage
    assert 'id="connect"' in homepage
    assert 'inline-flex max-w-full min-w-0' in homepage
    assert '<span class="min-w-0 truncate">MCP Discovery' in homepage
    assert "HISTORICAL_SAMPLE_BUNDLES" not in homepage
    assert "callCanonicalFindSolution" in homepage
    assert "fetch('/mcp'" in homepage
    assert 'description: "Package names mapped to exact target versions"' in homepage
    assert "return { results: matches }" not in homepage
    assert homepage.count('{% include "partials/verification_contract.html" %}') == 1
    assert architecture.count('{% include "partials/verification_contract.html" %}') == 1
    assert "1. Pre-Fail Validation" not in homepage
    assert "1. Pre-Fail Validation" not in architecture
    assert "https://mcp.synapsemesh.dev/mcp" not in homepage
    assert "https://mcp.synapsemesh.dev/mcp" not in (
        templates_dir / "recipe_detail.html"
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_shared_public_layout_and_compiled_css_render_on_every_route():
    bundle_id = load_all_golden_bundles()[0]["bundleId"]
    routes = (
        "/",
        "/benchmark",
        "/verification",
        "/legal",
        "/privacy",
        f"/recipes/{bundle_id}",
        "/docs",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for route in routes:
            response = await client.get(route)
            assert response.status_code == 200
            assert response.text.count('aria-label="Main Navigation"') == 1
            assert response.text.count('aria-label="Footer Navigation"') == 1
            assert response.text.count("Evidence before claims") == 1
            assert 'href="/#connect"' in response.text

        homepage = await client.get("/")
        stylesheet = await client.get("/style.min.css")
        stylesheet_head = await client.head("/style.min.css")

    assert 'id="connect"' in homepage.text
    assert "Profile: <code>bundle-4-stage-v1</code>" in homepage.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert ".text-brand-300" in stylesheet.text
    assert ".md\\:col-span-2" in stylesheet.text
    assert "form:tool-form-active" in stylesheet.text
    assert stylesheet_head.status_code == 200
    assert stylesheet_head.headers["content-type"].startswith("text/css")
