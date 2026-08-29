"""One fail-closed, request-time projection of the public registry.

Curated bundle files and their current run artifacts are authoritative for
curated records. SQLite remains authoritative for submitted records, while
repository-owned draft bundle files are added only when their identifiers are
not already present. This avoids copying run timestamps into SQLite and then
serving stale evidence after the daily verifier refreshes an artifact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.core.evidence_contract import (
    recipe_backing_lifecycle,
    recipe_has_recorded_verification_contract,
)
from app.database import get_db_connection
from app.models.bundle import CompatibilityBundle
from app.models.recipe import (
    EvidenceDefinition,
    ProblemDefinition,
    ReproductionDefinition,
    SolutionDefinition,
    VERIFIED_EVIDENCE_CONTRACT,
    VerifiedRecipe,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DRAFT_BUNDLES_DIR = PROJECT_ROOT / "bundles" / "drafts"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
SAFE_RECIPE_ID = re.compile(r"^(?:rec|bundle|draft)_[a-z0-9][a-z0-9_-]{0,119}$")
SAFE_RUNTIME = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,31}$")


@dataclass(frozen=True)
class RegistryEntry:
    recipe: VerifiedRecipe
    record_class: str
    source: str
    updated_at: str
    invalid_record: bool = False

    @property
    def evidence_status(self) -> str:
        return str(self.recipe.evidence.verificationStatus).upper()

    def as_ops_item(self) -> dict[str, Any]:
        evidence = self.recipe.evidence
        return {
            "id": self.recipe.id,
            "runtime": self.recipe.problem.runtime.lower(),
            "errorSignature": self.recipe.problem.errorSignature,
            "description": self.recipe.problem.description,
            "summary": self.recipe.solution.summary,
            "codeDiff": self.recipe.solution.codeDiff
            or self.recipe.solution.patchDiff
            or "",
            "doNot": self.recipe.solution.doNot,
            "recordClass": self.record_class,
            "evidenceStatus": self.evidence_status,
            # Compatibility for private telemetry consumers. New UI code uses
            # evidenceStatus and recordClass explicitly.
            "status": self.evidence_status,
            "invalidRecord": self.invalid_record,
            "preExit": evidence.preExit if evidence.preExit != -1 else None,
            "postExit": evidence.postExit if evidence.postExit != -1 else None,
            "mutationsKilled": (
                evidence.mutationsKilled
                if evidence.mutationsKilled != "0/0"
                else None
            ),
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class RegistrySnapshot:
    entries: tuple[RegistryEntry, ...]
    invalid_records: int

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def curated(self) -> int:
        return sum(entry.record_class == "CURATED" for entry in self.entries)

    @property
    def autonomous(self) -> int:
        return sum(entry.record_class == "AUTONOMOUS" for entry in self.entries)

    @property
    def evidence_qualified_curated(self) -> int:
        return sum(
            entry.record_class == "CURATED"
            and entry.evidence_status == "VERIFIED"
            for entry in self.entries
        )

    @property
    def evidence_qualified_autonomous(self) -> int:
        return sum(
            entry.record_class == "AUTONOMOUS"
            and entry.evidence_status == "VERIFIED"
            for entry in self.entries
        )

    @property
    def drafts(self) -> int:
        return sum(entry.record_class == "DRAFT" for entry in self.entries)

    @property
    def failed(self) -> int:
        return sum(entry.record_class == "FAILED" for entry in self.entries)

    @property
    def by_runtime(self) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    entry.recipe.problem.runtime.lower() for entry in self.entries
                ).items()
            )
        )

    @property
    def evidence_statuses(self) -> dict[str, int]:
        return dict(sorted(Counter(entry.evidence_status for entry in self.entries).items()))

    def find(self, record_id: str) -> RegistryEntry | None:
        return next((entry for entry in self.entries if entry.recipe.id == record_id), None)


def project_recipe_row(row: Any) -> VerifiedRecipe | None:
    """Deserialize one SQLite row and derive its current evidence tier."""
    try:
        problem = json.loads(row["problem_json"])
        solution = json.loads(row["solution_json"])
        reproduction = json.loads(row["reproduction_json"])
        evidence = json.loads(row["evidence_json"])
        if not all(
            isinstance(value, dict)
            for value in (problem, solution, reproduction, evidence)
        ):
            return None

        # No stored recipe currently has a separately validated, run-bound
        # isolation attestation. Never inherit a historical passport.
        evidence["isolationProfile"] = {}

        recorded_status = str(row["verification_status"] or "DRAFT").upper()
        contract_verified = (
            recorded_status == "VERIFIED"
            and recipe_has_recorded_verification_contract(
                row["id"], problem, solution, reproduction, evidence
            )
        )
        if not contract_verified:
            # Only a row that asserts VERIFIED can require a backing lifecycle
            # lookup. Draft/failed rows carry no evidence passport, and avoiding
            # a repository scan for each of them keeps request-time snapshots
            # bounded as the draft table grows.
            lifecycle = (
                recipe_backing_lifecycle(row["id"])
                if recorded_status == "VERIFIED"
                else None
            )
            lifecycle_status = (
                lifecycle.get("status") if isinstance(lifecycle, dict) else None
            )
            if lifecycle_status in {
                "STALE",
                "BROKEN",
                "DISPUTED",
                "SUPERSEDED",
            }:
                evidence["verificationStatus"] = lifecycle_status
                evidence["verificationNote"] = lifecycle["reason"]
                evidence["confidenceScore"] = None
                return VerifiedRecipe(
                    id=row["id"],
                    problem=ProblemDefinition(**problem),
                    solution=SolutionDefinition(**solution),
                    reproduction=ReproductionDefinition(**reproduction),
                    evidence=EvidenceDefinition(**evidence),
                )

            allowed_statuses = {
                "DRAFT",
                "UNVERIFIED",
                "PROVISIONAL",
                "STALE",
                "BROKEN",
                "DISPUTED",
                "SUPERSEDED",
                "FAILED",
            }
            public_status = (
                recorded_status if recorded_status in allowed_statuses else "DRAFT"
            )
            claimed_verified = (
                recorded_status == "VERIFIED"
                or evidence.get("verificationStatus") == "VERIFIED"
            )
            evidence["verificationStatus"] = (
                "DRAFT" if claimed_verified else public_status
            )
            evidence["evidenceContract"] = None
            if claimed_verified:
                evidence.update(
                    {
                        "verificationNote": (
                            "Stored evidence is incomplete or contradictory and is "
                            "presented fail closed as DRAFT."
                        ),
                        "sandboxExitCode": -1,
                        "passedTests": 0,
                        "totalTests": 0,
                        "confidenceScore": None,
                        "preExit": -1,
                        "postExit": -1,
                        "mutationsKilled": "0/0",
                        "badges": [],
                        "isolationProfile": {},
                    }
                )

        return VerifiedRecipe(
            id=row["id"],
            problem=ProblemDefinition(**problem),
            solution=SolutionDefinition(**solution),
            reproduction=ReproductionDefinition(**reproduction),
            evidence=EvidenceDefinition(**evidence),
        )
    except (
        TypeError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
        KeyError,
    ):
        return None


def _safe_source(provenance: dict[str, Any]) -> str | None:
    for value in provenance.get("primarySources") or []:
        if not isinstance(value, str) or len(value) > 2048:
            continue
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
    return None


def _bundle_recipe(bundle: dict[str, Any], *, curated: bool = False, evidence_qualified: bool = False) -> VerifiedRecipe:
    scope = bundle.get("scope") or {}
    fingerprint = bundle.get("fingerprint") or {}
    patch = bundle.get("patch") or {}
    verification = bundle.get("verification") or {}
    provenance = bundle.get("provenance") or {}
    pins = patch.get("pinnedDependencies") or {}
    publication = bundle.get("evidencePublication") or {}
    artifact = publication.get("runArtifactSummary") or {}
    has_valid_evidence = curated or evidence_qualified
    status = str(bundle.get("status") or "DRAFT").upper() if has_valid_evidence else "DRAFT"
    artifact_available = bool(publication.get("runArtifactAvailable")) if has_valid_evidence else False
    declared = int(artifact.get("mutationsDeclared") or 0) if artifact_available else 0
    rejected = int(artifact.get("mutationsRejected") or 0) if artifact_available else 0
    primary_source = _safe_source(provenance)

    evidence = EvidenceDefinition(
        verificationStatus=status,
        evidenceContract=(VERIFIED_EVIDENCE_CONTRACT if artifact_available else None),
        verificationNote=(
            publication.get("reason")
            if has_valid_evidence
            else "Repository-owned candidate draft; no execution evidence is published."
        ),
        lastTestedAt=artifact.get("completedAt") if artifact_available else None,
        sandboxExitCode=artifact.get("postExit", -1) if artifact_available else -1,
        passedTests=0,
        totalTests=0,
        confidenceScore=None,
        preExit=artifact.get("preExit", -1) if artifact_available else -1,
        postExit=artifact.get("postExit", -1) if artifact_available else -1,
        mutationsKilled=(f"{rejected}/{declared}" if artifact_available else "0/0"),
        toolchainVersions=(artifact.get("toolchainVersions") or {}),
        badges=(
            ["BUNDLE_4_STAGE_CONTRACT"]
            + (["SOURCE_BACKED"] if primary_source else [])
            if artifact_available
            else (["SOURCE_BACKED"] if primary_source else [])
        ),
        isolationProfile={},
        primarySource=primary_source,
    )
    return VerifiedRecipe(
        id=str(bundle["bundleId"]),
        problem=ProblemDefinition(
            errorSignature=fingerprint.get("errorSignature") or "Unknown error signature",
            runtime=scope.get("runtime") or "unknown",
            packages=pins,
            description=bundle.get("description") or "Compatibility record.",
        ),
        solution=SolutionDefinition(
            summary=bundle.get("description") or "Compatibility record.",
            codeDiff=patch.get("unifiedDiff"),
            patchDiff=patch.get("unifiedDiff"),
            instructions=[],
            pinnedDependencies=pins,
            doNot=patch.get("doNot") or [],
        ),
        reproduction=ReproductionDefinition(
            script=verification.get("reproductionScript") or "",
            testSuite=verification.get("testSuite") or "",
        ),
        evidence=evidence,
    )


def _invalid_placeholder(row: Any) -> VerifiedRecipe:
    raw_id = str(row["id"] or "")
    if SAFE_RECIPE_ID.fullmatch(raw_id):
        record_id = raw_id
    else:
        digest = hashlib.sha256(raw_id.encode("utf-8", errors="replace")).hexdigest()
        record_id = f"rec_invalid_{digest[:12]}"
    raw_runtime = str(row["runtime"] or "").lower()
    runtime = raw_runtime if SAFE_RUNTIME.fullmatch(raw_runtime) else "unknown"
    status = str(row["verification_status"] or "DRAFT").upper()
    if status not in {"DRAFT", "UNVERIFIED", "PROVISIONAL", "FAILED"}:
        status = "DRAFT"
    return VerifiedRecipe(
        id=record_id,
        problem=ProblemDefinition(
            errorSignature="Stored draft record is unavailable",
            runtime=runtime,
            packages={},
            description=(
                "This record failed schema validation and is exposed only as a "
                "fail-closed placeholder."
            ),
        ),
        solution=SolutionDefinition(
            summary="No solution is published for this invalid stored record."
        ),
        reproduction=ReproductionDefinition(script="", testSuite=""),
        evidence=EvidenceDefinition(
            verificationStatus=status,
            verificationNote="Stored record failed schema validation; no evidence is asserted.",
        ),
    )


def _draft_bundle_records() -> tuple[list[tuple[dict[str, Any], str]], int]:
    from app.api.bundles import _run_artifact_summary
    from app.core.evidence_lifecycle import evaluate_evidence_lifecycle
    from app.core.run_artifacts import load_valid_run_artifact

    parsed: list[tuple[dict[str, Any], str]] = []
    invalid = 0
    try:
        paths = sorted(DRAFT_BUNDLES_DIR.resolve().glob("*.json"))[:1000]
    except OSError:
        return [], 0
    for path in paths:
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > MAX_BUNDLE_BYTES
            ):
                invalid += 1
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            model = CompatibilityBundle.model_validate(raw)
            bundle_dict = model.model_dump(by_alias=True)
            run_artifact = load_valid_run_artifact(raw, path)
            if run_artifact is not None and run_artifact.get("outcome") == "PASSED":
                lifecycle = evaluate_evidence_lifecycle(raw, run_artifact)
                if lifecycle.get("qualified") is True:
                    bundle_dict["status"] = (
                        lifecycle["status"]
                        if lifecycle["status"] in {"VERIFIED", "STALE"}
                        else "UNVERIFIED"
                    )
                    bundle_dict["recordClass"] = "AUTONOMOUS"
                    if not bundle_dict.get("provenance"):
                        bundle_dict["provenance"] = {}
                    bundle_dict["provenance"]["curation"] = "MACHINE_VERIFIED"
                    bundle_dict["provenance"]["source"] = "autonomous-pipeline"
                    bundle_dict["evidencePublication"] = {
                        "qualified": True,
                        "runArtifactAvailable": True,
                        "runArtifactUrl": f"/api/v1/bundles/{model.bundleId}/evidence",
                        "runArtifactSummary": _run_artifact_summary(run_artifact),
                        "recordedContractShapeSatisfied": True,
                        "reason": lifecycle["reason"],
                        "lifecycle": lifecycle,
                    }
            updated_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            parsed.append((bundle_dict, updated_at))
        except (OSError, TypeError, json.JSONDecodeError, ValidationError, ValueError):
            invalid += 1

    counts = Counter(bundle["bundleId"] for bundle, _ in parsed)
    invalid += sum(count - 1 for count in counts.values() if count > 1)
    unique = [
        (bundle, updated_at)
        for bundle, updated_at in parsed
        if counts[bundle["bundleId"]] == 1
    ]
    return unique, invalid


async def build_registry_snapshot(db=None) -> RegistrySnapshot:
    """Build the current registry from its three authoritative sources."""
    # Import lazily: app.api.__init__ exposes every router, while this core
    # projection is itself used by the recipes router.
    from app.api.bundles import load_all_golden_bundles

    owns_db = db is None
    if db is None:
        db = await get_db_connection()
    entries: list[RegistryEntry] = []
    invalid_records = 0
    seen: set[str] = set()
    try:
        # Curated files and current artifacts win over their SQLite startup
        # projection so a daily artifact refresh is visible immediately.
        for bundle in load_all_golden_bundles():
            try:
                recipe = _bundle_recipe(bundle, curated=True)
            except (TypeError, ValueError, ValidationError, KeyError):
                invalid_records += 1
                continue
            entries.append(
                RegistryEntry(
                    recipe=recipe,
                    record_class="CURATED",
                    source="curated-bundle",
                    updated_at=(
                        recipe.evidence.lastTestedAt.isoformat().replace("+00:00", "Z")
                        if recipe.evidence.lastTestedAt
                        else "not recorded"
                    ),
                )
            )
            seen.add(recipe.id)

        cursor = await db.execute("SELECT * FROM recipes ORDER BY rowid DESC")
        for row in await cursor.fetchall():
            if row["id"] in seen:
                continue
            recipe = project_recipe_row(row)
            invalid = recipe is None
            if recipe is None:
                recipe = _invalid_placeholder(row)
                invalid_records += 1
            recorded_status = str(row["verification_status"] or "DRAFT").upper()
            record_class = (
                "FAILED"
                if recorded_status == "FAILED"
                or recipe.evidence.verificationStatus == "FAILED"
                else "DRAFT"
            )
            entries.append(
                RegistryEntry(
                    recipe=recipe,
                    record_class=record_class,
                    source="sqlite",
                    updated_at=row["updated_at"] or row["created_at"] or "not recorded",
                    invalid_record=invalid,
                )
            )
            seen.add(recipe.id)

        disk_drafts, invalid_drafts = _draft_bundle_records()
        invalid_records += invalid_drafts
        for bundle, updated_at in disk_drafts:
            bundle_id = str(bundle.get("bundleId") or "")
            if not bundle_id or bundle_id in seen:
                continue
            is_qualified = bool((bundle.get("evidencePublication") or {}).get("qualified"))
            try:
                recipe = _bundle_recipe(bundle, curated=False, evidence_qualified=is_qualified)
            except (TypeError, ValueError, ValidationError, KeyError):
                invalid_records += 1
                continue
            record_class = "AUTONOMOUS" if is_qualified else "DRAFT"
            source = "autonomous-pipeline" if is_qualified else "draft-bundle"
            entries.append(
                RegistryEntry(
                    recipe=recipe,
                    record_class=record_class,
                    source=source,
                    updated_at=updated_at,
                )
            )
            seen.add(recipe.id)
    finally:
        if owns_db:
            await db.close()

    class_order = {"CURATED": 0, "AUTONOMOUS": 1, "FAILED": 2, "DRAFT": 3}
    entries.sort(key=lambda item: (class_order.get(item.record_class, 4), item.recipe.id))
    return RegistrySnapshot(tuple(entries), invalid_records)
