import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.core.autonomous_pipeline import (
    Autonomous4StageVerifier,
    AutonomousEnvironmentManager,
    AutonomousEvidencePublisher,
    AutonomousPipelineOrchestrator,
    DraftEligibilityGate,
)
from app.core.run_artifacts import load_valid_run_artifact
from app.api.bundles import load_all_published_bundles, load_all_golden_bundles
from app.main import app


@pytest.fixture
def pydantic_settings_draft() -> Dict[str, Any]:
    """A real-world Python draft for Pydantic v2 BaseSettings breaking change."""
    return {
        "schemaVersion": "1.0.0",
        "bundleId": "draft_pydantic_v2_basesettings_001",
        "status": "DRAFT",
        "description": "BaseSettings moved from pydantic to pydantic-settings in Pydantic v2.",
        "scope": {
            "package": "pydantic",
            "runtime": "python",
            "runtimeVersion": f"python=={platform.python_version()}",
            "fromVersion": "1.10.0",
            "toVersion": "2.13.4",
            "affectedVersionRange": ">=2.0.0",
            "platform": "all",
        },
        "fingerprint": {
            "errorSignature": "PydanticImportError: `BaseSettings` has been moved to the `pydantic-settings` package.",
            "regex": r"BaseSettings.*moved to.*pydantic-settings",
            "matchStream": "stderr",
        },
        "patch": {
            "targetFile": "config.py",
            "unifiedDiff": (
                "--- config.py\n"
                "+++ config.py\n"
                "@@ -1,3 +1,3 @@\n"
                "-from pydantic import BaseSettings\n"
                "+from pydantic_settings import BaseSettings\n"
                " \n"
                " class AppConfig(BaseSettings):\n"
            ),
            "pinnedDependencies": {
                "python": f"=={platform.python_version()}",
                "pydantic": ">=2.0.0",
                "pydantic-settings": ">=2.0.0",
            },
            "doNot": [
                "Do not import BaseSettings from pydantic in v2",
                "Do not write custom mock settings classes",
            ],
        },
        "verification": {
            "scriptLanguage": "python",
            "workspaceFiles": {
                "config.py": (
                    "from pydantic import BaseSettings\n\n"
                    "class AppConfig(BaseSettings):\n"
                    "    app_name: str = 'SynapseTest'\n"
                ),
            },
            "reproductionScript": (
                "import sys\n"
                "try:\n"
                "    import config\n"
                "except Exception as e:\n"
                "    sys.stderr.write(f'{type(e).__name__}: {str(e)}\\n')\n"
                "    sys.exit(1)\n"
                "sys.exit(0)\n"
            ),
            "testSuite": (
                "from pydantic_settings import BaseSettings\n"
                "import config\n"
                "cfg = config.AppConfig()\n"
                "assert cfg.app_name == 'SynapseTest'\n"
                "assert isinstance(cfg, BaseSettings)\n"
                "assert issubclass(config.AppConfig, BaseSettings)\n"
            ),
            "mutations": [
                {
                    "id": "mut_wrong_import",
                    "description": "Imports BaseModel instead of BaseSettings",
                    "unifiedDiff": (
                        "--- config.py\n"
                        "+++ config.py\n"
                        "@@ -1,3 +1,3 @@\n"
                        "-from pydantic import BaseSettings\n"
                        "+from pydantic import BaseModel as BaseSettings\n"
                        " \n"
                        " class AppConfig(BaseSettings):\n"
                    ),
                },
                {
                    "id": "mut_dummy_object",
                    "description": "Defines BaseSettings as dummy object",
                    "unifiedDiff": (
                        "--- config.py\n"
                        "+++ config.py\n"
                        "@@ -1,3 +1,3 @@\n"
                        "-from pydantic import BaseSettings\n"
                        "+BaseSettings = object\n"
                        " \n"
                        " class AppConfig(BaseSettings):\n"
                    ),
                },
            ],
            "expectedPreExit": 1,
            "expectedPostExit": 0,
            "timeoutMs": 15000,
        },
        "provenance": {
            "spdxLicense": "MIT",
            "primarySources": [
                "https://docs.pydantic.dev/latest/migration/#basesettings-has-moved-to-pydantic-settings"
            ],
            "verifiedAt": "2026-08-29T12:00:00Z",
        },
    }


def test_eligibility_gate_validates_real_python_draft(pydantic_settings_draft):
    decision = DraftEligibilityGate.evaluate_draft(pydantic_settings_draft)
    assert decision.eligible is True
    assert decision.details["package"] == "pydantic"
    assert decision.details["runtime"] == "python"


def test_eligibility_gate_rejects_mock_oracle(pydantic_settings_draft):
    bad_draft = dict(pydantic_settings_draft)
    bad_draft["verification"] = dict(bad_draft["verification"])
    bad_draft["verification"]["workspaceFiles"] = {
        "config.py": "class MockSession:\n    pass\n"
    }
    decision = DraftEligibilityGate.evaluate_draft(bad_draft)
    assert decision.eligible is False
    assert decision.rejection_code == "PUPPET_ORACLE_DETECTED"


def test_eligibility_gate_rejects_unsafe_code(pydantic_settings_draft):
    unsafe_draft = dict(pydantic_settings_draft)
    unsafe_draft["verification"] = dict(unsafe_draft["verification"])
    unsafe_draft["verification"]["reproductionScript"] = "import os; os.system('rm -rf /')"
    decision = DraftEligibilityGate.evaluate_draft(unsafe_draft)
    assert decision.eligible is False
    assert decision.rejection_code == "UNSAFE_WORKSPACE_CODE"


def test_eligibility_gate_requires_at_least_two_mutations(pydantic_settings_draft):
    one_mut_draft = dict(pydantic_settings_draft)
    one_mut_draft["verification"] = dict(one_mut_draft["verification"])
    one_mut_draft["verification"]["mutations"] = [one_mut_draft["verification"]["mutations"][0]]
    decision = DraftEligibilityGate.evaluate_draft(one_mut_draft)
    assert decision.eligible is False
    assert decision.rejection_code == "INSUFFICIENT_MUTATIONS"


def test_autonomous_environment_pins_check(pydantic_settings_draft):
    pins = pydantic_settings_draft["patch"]["pinnedDependencies"]
    ok, msg = AutonomousEnvironmentManager.check_pins_installed(pins)
    assert ok is True
    toolchains, lock_sha256 = AutonomousEnvironmentManager.resolve_toolchains(pins)
    assert "pydantic" in toolchains
    assert "python" in toolchains
    assert len(lock_sha256) == 64


def test_autonomous_4stage_verifier_executes_successfully(pydantic_settings_draft):
    passed, verif_result = Autonomous4StageVerifier.execute_verification(pydantic_settings_draft)
    assert passed is True
    stages = verif_result["stages"]
    assert stages["pre"]["exitCode"] == 1
    assert stages["pre"]["signatureMatched"] is True
    assert stages["pre"]["exceptionClassMatched"] is True
    assert stages["patch"]["strictUnifiedDiffApplied"] is True
    assert stages["post"]["passed"] is True
    assert len(stages["mutations"]) == 2
    for m in stages["mutations"]:
        assert m["rejected"] is True
        assert m["exitCode"] != 0


def test_orchestrator_end_to_end_verification_and_publication(tmp_path: Path, pydantic_settings_draft):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    draft_file = drafts_dir / f"{pydantic_settings_draft['bundleId']}.json"
    draft_file.write_text(json.dumps(pydantic_settings_draft, indent=2), encoding="utf-8")

    evidence_dir = tmp_path / "evidence_runs"
    evidence_dir.mkdir()

    result = AutonomousPipelineOrchestrator.process_draft_bundle(
        draft_file,
        output_artifacts_dir=evidence_dir,
    )

    assert result["success"] is True
    assert result["bundleId"] == pydantic_settings_draft["bundleId"]
    artifact_path = Path(result["artifactPath"])
    assert artifact_path.is_file()

    # Validate that load_valid_run_artifact strictly validates the new artifact
    validated = load_valid_run_artifact(
        pydantic_settings_draft,
        draft_file,
        artifacts_dir=evidence_dir,
    )
    assert validated is not None
    assert validated["bundleId"] == pydantic_settings_draft["bundleId"]
    assert validated["outcome"] == "PASSED"
    assert validated["controlsObserved"]["uid"] == 10001
    assert validated["runner"]["networkMode"] == "none"


def test_mcp_find_solution_discovers_machine_verified_draft(tmp_path: Path, pydantic_settings_draft, monkeypatch):
    from app.core import autonomous_pipeline, run_artifacts, registry_snapshot
    from app.api import bundles

    # Materialize in bundles/drafts and evidence/runs
    draft_file = Path("bundles/drafts") / f"{pydantic_settings_draft['bundleId']}.json"
    draft_file.write_text(json.dumps(pydantic_settings_draft, indent=2), encoding="utf-8")

    try:
        # Run autonomous pipeline
        res = AutonomousPipelineOrchestrator.process_draft_bundle(draft_file)
        assert res["success"] is True

        client = TestClient(app)

        # 1. Exact observed version -> VERIFIED_MATCH with explicit machine provenance
        exact_ver = res["toolchainVersions"]["pydantic"]
        resp_exact = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "test_1",
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "PydanticImportError: `BaseSettings` has been moved to the `pydantic-settings` package.",
                    "runtime": "python",
                    "packages": {"pydantic": exact_ver}
                }
            }
        })
        assert resp_exact.status_code == 200
        data_exact = resp_exact.json()["result"]["content"][0]["text"]
        payload_exact = json.loads(data_exact)

        assert payload_exact["status"] == "VERIFIED_MATCH"
        assert payload_exact["actionability"] == "REPRODUCE_BEFORE_APPLY"
        assert payload_exact["provenance"]["curation"] == "MACHINE_VERIFIED"
        assert payload_exact["provenance"]["source"] == "autonomous-pipeline"
        assert payload_exact["_trustBoundary"]["curation"] == "MACHINE_VERIFIED"
        assert payload_exact["_trustBoundary"]["source"] == "RUN_BOUND_AUTONOMOUS_EVIDENCE"
        assert "from pydantic_settings import BaseSettings" in payload_exact["codeDiff"]

        # 2. Version mismatch / other version -> UNVERIFIED_MATCH (RUN_BOUND_EVIDENCE_OTHER_VERSION)
        resp_other = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": "test_2",
            "method": "tools/call",
            "params": {
                "name": "find_solution",
                "arguments": {
                    "errorSignature": "PydanticImportError: `BaseSettings` has been moved to the `pydantic-settings` package.",
                    "runtime": "python",
                    "packages": {"pydantic": "2.0.0"}
                }
            }
        })
        assert resp_other.status_code == 200
        data_other = resp_other.json()["result"]["content"][0]["text"]
        payload_other = json.loads(data_other)

        assert payload_other["status"] == "UNVERIFIED_MATCH"
        assert payload_other["evidenceTier"] == "RUN_BOUND_EVIDENCE_OTHER_VERSION"

        # 3. Golden bundles remain human-curated and unpolluted
        golden_bundles = load_all_golden_bundles()
        for gb in golden_bundles:
            assert gb.get("recordClass") == "CURATED"
            assert gb["bundleId"] != pydantic_settings_draft["bundleId"]

    finally:
        # Cleanup test draft & artifact
        draft_file.unlink(missing_ok=True)
        artifact_file = Path(f"evidence/runs/{pydantic_settings_draft['bundleId']}.json")
        artifact_file.unlink(missing_ok=True)
