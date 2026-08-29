import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from app.core.upstream_miner import (
    UpstreamReleaseFetcher,
    BreakingChangeExtractor,
    BundleSynthesizer,
    UpstreamMiningEngine,
)


def test_breaking_change_extractor():
    sample_text = """
# Migration Guide
### Breaking Changes
- Calling `np.NAN` raises `AttributeError: np.NAN was removed in NumPy 2.0. Use np.nan instead.`.
### Example
Before:
```python
x = np.NAN
```
After:
```python
x = np.nan
```
Pin: numpy>=2.0.0
Do Not: Do not monkeypatch np.NAN on numpy module; do not silence AttributeError.
"""
    err = BreakingChangeExtractor.extract_error_signature(sample_text)
    assert err is not None
    assert "AttributeError" in err

    before_after = BreakingChangeExtractor.extract_before_after(sample_text)
    assert before_after is not None
    assert before_after["before"] == "x = np.NAN"
    assert before_after["after"] == "x = np.nan"

    pins = BreakingChangeExtractor.extract_pins(sample_text, "numpy")
    assert "numpy" in pins
    assert ">=2.0.0" in pins["numpy"]

    do_not = BreakingChangeExtractor.extract_do_not(sample_text)
    assert len(do_not) == 2
    assert "monkeypatch" in do_not[0]

    diff = BreakingChangeExtractor.generate_unified_diff(before_after["before"], before_after["after"])
    assert "--- a/app.py" in diff
    assert "-x = np.NAN" in diff
    assert "+x = np.nan" in diff


def test_bundle_synthesizer_creates_draft():
    entry = {
        "package": "duckdb",
        "version": "0.10.0",
        "runtime": "python",
        "trusted_code_examples": True,
        "release_notes": """
# DuckDB Release
### Breaking Changes
- String offsets in SUBSTRING raise `duckdb.BinderException: No function matches the given name and argument types`.
Before:
```python
con.execute("SELECT SUBSTRING(val, '1', '3')")
```
After:
```python
con.execute("SELECT SUBSTRING(val, 1, 3)")
```
Pin: duckdb>=0.10.0
Do Not: Do not pass string literals for offsets.
"""
    }
    bundle = BundleSynthesizer.synthesize_bundle(entry)
    assert bundle is not None
    assert bundle.bundleId.startswith("draft_duckdb_0100_")
    assert bundle.scope.package == "duckdb"
    assert bundle.status == "DRAFT"  # Must start as DRAFT
    assert "duckdb.BinderException" in bundle.fingerprint.errorSignature
    assert "client.py" in bundle.patch.targetFile
    assert len(bundle.verification.mutations) > 0


@pytest.mark.asyncio
async def test_upstream_mining_engine_execution(monkeypatch):
    import scripts.synapse_reverify as reverify

    def forbidden_verifier(*args, **kwargs):
        raise AssertionError("autonomous mining must not execute synthesized candidates")

    monkeypatch.setattr(reverify, "verify_golden_bundle", forbidden_verifier)
    monkeypatch.setattr(UpstreamReleaseFetcher, "fetch_pypi_changelog", classmethod(lambda cls, package: []))
    monkeypatch.setattr(UpstreamReleaseFetcher, "fetch_github_releases_atom", classmethod(lambda cls, repo, limit=5: []))
    monkeypatch.setattr(UpstreamReleaseFetcher, "fetch_pypi_rss_updates", classmethod(lambda cls, limit=10: []))
    bundles = await UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=False)
    assert len(bundles) >= 3
    packages = [b.scope.package for b in bundles]
    assert "sqlalchemy" in packages
    assert "numpy" in packages
    assert "httpx" in packages
    assert all(bundle.bundleId.startswith("draft_") for bundle in bundles)
    assert all(bundle.status == "DRAFT" for bundle in bundles)


@pytest.mark.asyncio
async def test_miner_api_requires_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "test_miner_admin_secret_key")
    monkeypatch.setattr(UpstreamReleaseFetcher, "fetch_pypi_changelog", classmethod(lambda cls, package: []))
    monkeypatch.setattr(UpstreamReleaseFetcher, "fetch_github_releases_atom", classmethod(lambda cls, repo, limit=5: []))
    monkeypatch.setattr(UpstreamReleaseFetcher, "fetch_pypi_rss_updates", classmethod(lambda cls, limit=10: []))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Public targets list
        res_targets = await ac.get("/api/v1/miner/targets")
        assert res_targets.status_code == 200
        data_targets = res_targets.json()
        assert data_targets["count"] > 0
        assert data_targets["tokenCost"] == 0

        # Unauthenticated mining run MUST fail with 403 Forbidden
        res_unauth = await ac.post("/api/v1/miner/run?persist=false")
        assert res_unauth.status_code == 403

        # Authenticated mining run succeeds
        res_auth = await ac.post(
            "/api/v1/miner/run?persist=false",
            headers={"X-Synapse-Admin-Key": "test_miner_admin_secret_key"}
        )
        assert res_auth.status_code == 200
        data_run = res_auth.json()
        assert data_run["status"] == "COMPLETED"
        assert data_run["minedCount"] >= 3
        assert data_run["tokenCost"] == 0


def test_constructor_signature_heuristic():
    text = """
# HTTPX 0.28
Passing app= to AsyncClient raises `TypeError: AsyncClient.__init__() got an unexpected keyword argument 'app'. Pass transport=ASGITransport(app=app) instead.`
"""
    err = BreakingChangeExtractor.extract_error_signature(text)
    assert err is not None
    assert "TypeError" in err
    assert "unexpected keyword argument" in err

    result = BreakingChangeExtractor.extract_before_after(text, package="httpx", runtime="python")
    assert result is not None
    assert result["kind"] == "constructor"
    assert "from httpx import AsyncClient" in result["before"]
    assert "AsyncClient(app=None)" in result["before"]
    assert "AsyncClient(transport=None)" in result["after"]
    assert "import httpx" not in result["after"] or "from httpx import" in result["after"]


def test_async_migration_heuristic():
    text = """
`redis.Redis.execute_command` is now a coroutine and must be awaited.
Calling it from sync code raises `RuntimeWarning: coroutine 'execute_command' was never awaited`.
"""
    err = BreakingChangeExtractor.extract_error_signature(text)
    assert err is not None
    assert "never awaited" in err.lower() or "RuntimeWarning" in err

    result = BreakingChangeExtractor.extract_before_after(text, package="redis", runtime="python")
    assert result is not None
    assert result["kind"] == "async"
    assert "result = redis.Redis.execute_command()" in result["before"]
    assert "asyncio.run" in result["after"]
    assert "await redis.Redis.execute_command()" in result["after"]


def test_async_get_event_loop_heuristic():
    text = """
asyncio.get_event_loop() is deprecated in Python 3.12. Use asyncio.run() instead.
This raises DeprecationWarning: There is no current event loop.
"""
    result = BreakingChangeExtractor.extract_before_after(text, package="asyncio", runtime="python")
    assert result is not None
    assert result["kind"] == "async"
    assert "get_event_loop()" in result["before"]
    assert "asyncio.run(" in result["after"]


def test_deprecated_on_event_decorator_heuristic():
    text = """
@app.on_event is deprecated. Use a lifespan context manager instead of on_event handlers.
"""
    result = BreakingChangeExtractor.extract_before_after(text, package="fastapi", runtime="python")
    assert result is not None
    assert result["kind"] == "decorator"
    assert '@app.on_event("startup")' in result["before"]
    assert "async def lifespan(app):" in result["after"]
    assert "FastAPI(lifespan=lifespan)" in result["after"]


def test_deprecated_decorator_rename_heuristic():
    text = """
Use @field_validator instead of @validator when migrating Pydantic v1 models.
"""
    result = BreakingChangeExtractor.extract_before_after(text, package="pydantic", runtime="python")
    assert result is not None
    assert result["kind"] == "decorator"
    assert "@pydantic.validator" in result["before"]
    assert "@pydantic.field_validator" in result["after"]


def test_hyphenated_package_import_is_valid_python():
    text = """
`StrictRedis` was removed. Use `Redis` instead.
"""
    result = BreakingChangeExtractor.extract_before_after(text, package="redis-py", runtime="python")
    assert result is not None
    assert "import redis-py" not in result["before"]
    assert "import redis\n" in result["before"]
    assert "import redis\n" in result["after"]


def test_generic_tokens_are_rejected():
    text = "use the attribute instead of the method for this API change"
    result = BreakingChangeExtractor.extract_before_after(text, package="numpy", runtime="python")
    assert result is None


def test_repository_owned_workspace_uses_real_package():
    entry = UpstreamReleaseFetcher.get_seed_changelogs()[0]
    bundle = BundleSynthesizer.synthesize_bundle(entry)
    assert bundle is not None
    assert "from sqlalchemy" in bundle.verification.workspaceFiles["client.py"]
    assert UpstreamMiningEngine.is_synthetic_oracle(bundle) is False


def test_untrusted_embedded_code_is_not_used_as_workspace():
    entry = {
        "package": "duckdb",
        "version": "1.0.0",
        "runtime": "python",
        "release_notes": """
Breaking change.
Before:
```python
import os
os.system('touch /tmp/should-never-run')
```
After:
```python
print('pretend fix')
```
""",
    }
    assert BundleSynthesizer.synthesize_bundle(entry) is None


def test_constructor_heuristic_workspace_is_not_synthetic_oracle():
    entry = {
        "package": "httpx",
        "version": "0.28.0",
        "runtime": "python",
        "release_notes": """
AsyncClient.__init__() got an unexpected keyword argument 'app'.
Pass transport=ASGITransport(app=app) instead.
""",
    }
    bundle = BundleSynthesizer.synthesize_bundle(entry)
    assert bundle is not None
    assert UpstreamMiningEngine.is_synthetic_oracle(bundle) is False


def test_synthesizer_from_constructor_prose_stays_draft():
    entry = {
        "package": "httpx",
        "version": "0.28.0",
        "runtime": "python",
        "release_notes": """
# HTTPX 0.28
AsyncClient.__init__() got an unexpected keyword argument 'app'.
Pass transport=ASGITransport(app=app) instead.
Pin: httpx>=0.28.0
Do Not: Do not pass app= into AsyncClient.
""",
        "url": "https://www.python-httpx.org/compatibility/"
    }
    bundle = BundleSynthesizer.synthesize_bundle(entry)
    assert bundle is not None
    assert bundle.status == "DRAFT"
    assert bundle.bundleId.startswith("draft_httpx_")
    assert "transport" in bundle.patch.unifiedDiff
    assert "app=None" in bundle.patch.unifiedDiff
    assert bundle.verification.workspaceFiles["client.py"].startswith("import sys")
