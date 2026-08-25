import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
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


def test_bundle_synthesizer():
    entry = {
        "package": "duckdb",
        "version": "0.10.0",
        "runtime": "python",
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
    assert bundle.bundleId.startswith("bundle_duckdb_0100_")
    assert bundle.scope.package == "duckdb"
    assert bundle.status == "VERIFIED"
    assert "duckdb.BinderException" in bundle.fingerprint.errorSignature
    assert "client.py" in bundle.patch.targetFile
    assert len(bundle.verification.mutations) > 0


@pytest.mark.asyncio
async def test_upstream_mining_engine_execution():
    bundles = await UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=False)
    assert len(bundles) >= 3
    packages = [b.scope.package for b in bundles]
    assert "sqlalchemy" in packages
    assert "numpy" in packages
    assert "duckdb" in packages


@pytest.mark.asyncio
async def test_miner_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res_targets = await ac.get("/api/v1/miner/targets")
        assert res_targets.status_code == 200
        data_targets = res_targets.json()
        assert data_targets["count"] > 0
        assert data_targets["tokenCost"] == 0

        res_run = await ac.post("/api/v1/miner/run?persist=false")
        assert res_run.status_code == 200
        data_run = res_run.json()
        assert data_run["status"] == "COMPLETED"
        assert data_run["minedCount"] >= 3
        assert data_run["tokenCost"] == 0
