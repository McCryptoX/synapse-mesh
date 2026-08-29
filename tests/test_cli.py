import sys
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synapse_cli.main import cmd_doctor
from scripts.synapse_reverify import reverify_recipe, verify_bundle_data


def test_cli_doctor_runs_cleanly(capsys):
    cmd_doctor(api_base="https://api.synapsemesh.dev")
    captured = capsys.readouterr()
    assert "SYNAPSE-MESH AGENT ENVIRONMENT DOCTOR" in captured.out
    assert "Platform:" in captured.out
    assert "Connecting to Synapse-Mesh Node" in captured.out


def test_reverify_rejects_legacy_split_script_recipe():
    """Legacy recipes cannot be silently upgraded to the workspace/diff contract."""
    bundle = {
        "id": "bundle_test_valid_001",
        "problem": {
            "runtime": "python",
            "errorSignature": "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        },
        "solution": {
            "targetFile": "calc.py",
            "summary": "Convert integer to string",
            "patchDiff": "--- calc.py\n+++ calc.py\n@@ -1,1 +1,1 @@\n-result = 5 + 'test'\n+result = str(5) + 'test'\n",
            "mutations": [
                "# Mutant 1: Still adding int and str\nresult = 5 + 'test'"
            ]
        },
        "reproduction": {
            "script": "result = 5 + 'test'",
            "testSuite": "import calc\nassert calc.result == '5test'\nprint('ALL TESTS PASSED')"
        }
    }
    
    assert verify_bundle_data(bundle) is False


def test_reverify_structured_workspace_contract_success():
    """A structured bundle passes only with real runtime, diff and two mutant diffs."""
    runtime_version = platform.python_version()
    bundle = {
        "schemaVersion": "1.0.0",
        "bundleId": "bundle_test_python_runtime_001",
        "status": "DRAFT",
        "description": "Contract regression fixture",
        "scope": {
            "package": "python",
            "runtime": "python",
            "runtimeVersion": runtime_version,
            "affectedVersionRange": f"=={runtime_version}",
            "toVersion": runtime_version,
        },
        "fingerprint": {
            "errorSignature": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        },
        "patch": {
            "targetFile": "calc.py",
            "pinnedDependencies": {"python": runtime_version},
            "unifiedDiff": (
                "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
                "-import datetime\n-result = 5 + 'test'\n"
                "+import datetime\n+result = str(5) + 'test'\n"
            ),
        },
        "verification": {
            "workspaceFiles": {"calc.py": "import datetime\nresult = 5 + 'test'\n"},
            "reproductionScript": "import runpy\nrunpy.run_path('calc.py', run_name='__main__')\n",
            "testSuite": "import calc\nassert calc.result == '5test'\n",
            "expectedPreExit": 1,
            "expectedPostExit": 0,
            "mutations": [
                {
                    "id": "mut_type_error",
                    "unifiedDiff": (
                        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
                        "-import datetime\n-result = 5 + 'test'\n"
                        "+import datetime\n+result = 6 + 'test'\n"
                    ),
                },
                {
                    "id": "mut_wrong_value",
                    "unifiedDiff": (
                        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
                        "-import datetime\n-result = 5 + 'test'\n"
                        "+import datetime\n+result = 'wrong'\n"
                    ),
                },
            ],
        },
        "provenance": {"spdxLicense": "Python-2.0", "primarySources": []},
    }
    assert verify_bundle_data(bundle) is True


def test_reverify_rejects_missing_repro():
    """Testing that a bundle missing reproduction fails cleanly as UNVERIFIED."""
    bundle = {
        "id": "bundle_test_missing_repro",
        "problem": {"runtime": "python", "errorSignature": "SomeError"},
        "solution": {"targetFile": "calc.py", "patchDiff": "fix"},
        "reproduction": {"script": "", "testSuite": "assert True"}
    }
    assert verify_bundle_data(bundle) is False


def test_reverify_rejects_non_failing_repro():
    """Testing that a bundle whose repro script exits 0 is rejected at Stage 1."""
    bundle = {
        "id": "bundle_test_non_failing",
        "problem": {"runtime": "python", "errorSignature": "SomeError"},
        "solution": {"targetFile": "calc.py", "patchDiff": "fix"},
        "reproduction": {"script": "x = 10", "testSuite": "assert True"}
    }
    assert verify_bundle_data(bundle) is False


def test_reverify_rejects_escaping_mutant():
    """Testing that if a mutant passes the test suite, the bundle is rejected at Stage 4."""
    bundle = {
        "id": "bundle_test_escaping_mutant",
        "problem": {
            "runtime": "python",
            "errorSignature": "TypeError: unsupported operand type"
        },
        "solution": {
            "targetFile": "calc.py",
            "patchDiff": "--- calc.py\n+++ calc.py\n@@ -1,1 +1,1 @@\n-result = 5 + 'test'\n+result = str(5) + 'test'\n",
            "mutations": [
                "# Escaping mutant that happens to set valid result\nresult = '5test'"
            ]
        },
        "reproduction": {
            "script": "result = 5 + 'test'",
            "testSuite": "import calc\nassert calc.result == '5test'"
        }
    }
    assert verify_bundle_data(bundle) is False

BASE_DIR = Path(__file__).resolve().parent.parent


def _skip_without_exact_python_bundle_environment(data: dict) -> None:
    """A host-env smoke test is valid only when every declared pin is exact."""
    mismatches = []
    expected_runtime = data["scope"]["runtimeVersion"]
    actual_runtime = platform.python_version()
    if actual_runtime != expected_runtime:
        mismatches.append(f"python expected {expected_runtime}, got {actual_runtime}")
    for package, expected in data["patch"]["pinnedDependencies"].items():
        if package.lower() == "python":
            if expected == expected_runtime:
                continue
            actual = platform.python_version()
        else:
            try:
                actual = version(package)
            except PackageNotFoundError:
                actual = "unavailable"
        if actual != expected:
            mismatches.append(f"{package} expected {expected}, got {actual}")
    if mismatches:
        pytest.skip("exact Golden Bundle environment unavailable: " + "; ".join(mismatches))

def test_golden_httpx_bundle_full_4stage_pass():
    """Tests the real Golden Bundle for HTTPX 0.28 ASGITransport."""
    p = BASE_DIR / "bundles/golden/bundle_httpx_028_asgi_transport.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    _skip_without_exact_python_bundle_environment(data)
    assert verify_bundle_data(data) is True


def test_golden_pydantic_bundle_full_4stage_pass():
    """Tests the real Golden Bundle for Pydantic v2 model_validator."""
    p = BASE_DIR / "bundles/golden/bundle_pydantic_v2_model_validator.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    _skip_without_exact_python_bundle_environment(data)
    assert verify_bundle_data(data) is True
import shutil

def test_golden_nextjs_bundle_schema_and_fixture_structure():
    """Validates the Next.js 15 Golden Bundle structure, workspace files, and multi-mutation declarations.
    Note: Python Goldens execute here only when the host exactly matches every declared pin; Next.js is checked structurally in this legacy test."""
    p = BASE_DIR / "bundles/golden/bundle_nextjs_15_async_params.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "1.0.0"
    assert "verification" in data
    assert "workspaceFiles" in data["verification"]
    assert "app/blog/[slug]/page.tsx" in data["verification"]["workspaceFiles"]
    assert len(data["verification"]["mutations"]) >= 2

def test_golden_fastapi_bundle_full_4stage_pass():
    """Tests the real Golden Bundle for FastAPI 0.115 lifespan context manager."""
    p = BASE_DIR / "bundles/golden/bundle_fastapi_0115_lifespan_context.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    _skip_without_exact_python_bundle_environment(data)
    assert verify_bundle_data(data) is True

def test_golden_python_datetime_bundle_full_4stage_pass():
    """Tests the real Golden Bundle for Python 3.12+ datetime.now(timezone.utc) migration."""
    p = BASE_DIR / "bundles/golden/bundle_python_312_datetime_utc_aware.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    _skip_without_exact_python_bundle_environment(data)
    assert verify_bundle_data(data) is True

def test_golden_sqlalchemy_bundle_full_4stage_pass():
    """Tests the real Golden Bundle for SQLAlchemy 2.0 select scalars migration."""
    p = BASE_DIR / "bundles/golden/bundle_sqlalchemy_20_select_scalars.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    _skip_without_exact_python_bundle_environment(data)
    assert verify_bundle_data(data) is True


def test_golden_numpy_bundle_full_4stage_pass():
    """Tests the real Golden Bundle for NumPy 2.0 NaN alias removal."""
    p = BASE_DIR / "bundles/golden/bundle_numpy_20_nan_alias_removal.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    _skip_without_exact_python_bundle_environment(data)
    assert verify_bundle_data(data) is True


def test_duckdb_puppet_bundle_is_rejected_by_real_package_gate():
    """A hand-written DuckDB error string is not a real engine reproduction."""
    p = BASE_DIR / "bundles/golden/bundle_duckdb_010_substring_casting.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert verify_bundle_data(data) is False


def test_golden_express_bundle_schema_and_fixture_structure():
    """Tests the Express 5.0 Golden Bundle schema, diffs, and mutations."""
    p = BASE_DIR / "bundles/golden/bundle_express_50_path_to_regexp.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "1.0.0"
    assert "router.js" in data["verification"]["workspaceFiles"]
    assert len(data["verification"]["mutations"]) >= 2


def test_golden_typescript_bundle_schema_and_fixture_structure():
    """Tests the TypeScript 5.6 Golden Bundle schema, diffs, and mutations."""
    p = BASE_DIR / "bundles/golden/bundle_typescript_56_strict_map_lookup.json"
    assert p.exists()
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "1.0.0"
    assert "lookup.js" in data["verification"]["workspaceFiles"]
    assert len(data["verification"]["mutations"]) >= 2
