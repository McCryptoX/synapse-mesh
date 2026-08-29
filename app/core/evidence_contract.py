"""Fail-closed validation for SQLite recipe projections of bundle evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT
from app.core.evidence_lifecycle import evaluate_evidence_lifecycle
from app.core.run_artifacts import load_valid_run_artifact


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_BACKING_BUNDLE_BYTES = 2 * 1024 * 1024
BUNDLE_ID_PATTERN = re.compile(r"^bundle_[a-z0-9][a-z0-9_-]{2,119}$")


def _backing_bundle_id(recipe_id: Any) -> str | None:
    if not isinstance(recipe_id, str):
        return None
    candidate = recipe_id[4:] if recipe_id.startswith("rec_bundle_") else recipe_id
    return candidate if BUNDLE_ID_PATTERN.fullmatch(candidate) else None


def _load_backing_bundle(
    recipe_id: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    bundle_id = _backing_bundle_id(recipe_id)
    if bundle_id is None:
        return None
    matches: list[tuple[Path, dict[str, Any]]] = []
    for directory in (PROJECT_ROOT / "bundles" / "golden", PROJECT_ROOT / "bundles" / "drafts"):
        for path in sorted(directory.glob("*.json"))[:1000]:
            try:
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_size > MAX_BACKING_BUNDLE_BYTES
                ):
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("bundleId") == bundle_id:
                matches.append((path, data))

    # A recipe ID is not a safe evidence binding when more than one repository
    # record claims it, even if only one of those records currently has an
    # artifact. This also keeps REST, MCP, and SQLite projections aligned.
    if len(matches) != 1:
        return None
    path, data = matches[0]
    artifact = load_valid_run_artifact(data, path)
    if artifact is None:
        return None
    lifecycle = evaluate_evidence_lifecycle(data, artifact)
    return data, artifact, lifecycle


def recipe_backing_lifecycle(recipe_id: Any) -> dict[str, Any] | None:
    """Return current exact-run lifecycle state for a projected recipe."""
    backing = _load_backing_bundle(recipe_id)
    return backing[2] if backing is not None else None


def recipe_has_recorded_verification_contract(
    recipe_id: Any,
    problem: Any,
    solution: Any,
    reproduction: Any,
    evidence: Any,
) -> bool:
    """Require a complete recipe projection bound to an eligible bundle file.

    SQLite fields alone are assertions, not evidence. A public ``VERIFIED``
    recipe must be an exact projection of a curated or repository-owned draft
    bundle with a valid run artifact bound to the exact bundle bytes.
    """
    if not all(isinstance(value, dict) for value in (problem, solution, reproduction, evidence)):
        return False

    backing = _load_backing_bundle(recipe_id)
    if backing is None:
        return False
    bundle, artifact, lifecycle = backing
    if lifecycle.get("qualified") is not True:
        return False

    scope = bundle.get("scope") or {}
    fingerprint = bundle.get("fingerprint") or {}
    patch = bundle.get("patch") or {}
    verification = bundle.get("verification") or {}
    provenance = bundle.get("provenance") or {}
    pins = patch.get("pinnedDependencies") or {}
    sources = provenance.get("primarySources") or []
    projected_diff = solution.get("codeDiff") or solution.get("patchDiff")
    stages = artifact["stages"]
    pre_stage = stages["pre"]
    post_stage = stages["post"]
    mutation_stages = stages["mutations"]

    if not all(
        (
            evidence.get("verificationStatus") == "VERIFIED",
            evidence.get("evidenceContract") == VERIFIED_EVIDENCE_CONTRACT,
            evidence.get("sandboxExitCode") == 0,
            evidence.get("preExit") == pre_stage.get("exitCode"),
            evidence.get("postExit") == post_stage.get("exitCode") == 0,
            evidence.get("mutationsKilled")
            == f"{len(mutation_stages)}/{len(mutation_stages)}",
            "BUNDLE_4_STAGE_CONTRACT" in (evidence.get("badges") or []),
            problem.get("errorSignature") == fingerprint.get("errorSignature"),
            str(problem.get("runtime") or "").lower() == str(scope.get("runtime") or "").lower(),
            problem.get("packages") == pins,
            solution.get("pinnedDependencies") == pins,
            projected_diff == patch.get("unifiedDiff"),
            reproduction.get("script") == verification.get("reproductionScript"),
            reproduction.get("testSuite") == verification.get("testSuite"),
            evidence.get("lastTestedAt") == artifact.get("completedAt"),
            evidence.get("primarySource") in sources,
        )
    ):
        return False

    source = evidence.get("primarySource")
    if not isinstance(source, str):
        return False
    parsed_source = urlsplit(source)
    if parsed_source.scheme not in {"http", "https"} or not parsed_source.netloc:
        return False

    toolchain = evidence.get("toolchainVersions")
    if not isinstance(toolchain, dict) or not toolchain:
        return False
    return toolchain == artifact.get("toolchainVersions")
