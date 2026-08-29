import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.evidence_lifecycle import (
    canonical_artifact_sha256,
    evaluate_evidence_lifecycle,
)
from app.core.run_artifacts import load_valid_run_artifact
from app.models.bundle import BundleRunArtifact, CompatibilityBundle
from scripts.synapse_reverify import bundle_has_recorded_verification_contract

router = APIRouter(prefix="/api/v1/bundles", tags=["Compatibility Bundles"])
BUNDLES_DIR = Path(__file__).resolve().parent.parent.parent / "bundles" / "golden"
BUNDLE_ID_RE = re.compile(r"^(?:bundle|draft)_[a-z0-9][a-z0-9_\-]{2,119}$")
DRAFTS_DIR = Path(__file__).resolve().parent.parent.parent / "bundles" / "drafts"
PUBLIC_NON_ATTESTATION = {
    "isolationStatus": "NOT_ATTESTED",
    "attestationAvailable": False,
    "reason": (
        "No independently verifiable, run-bound isolation attestation is "
        "published for this bundle."
    ),
}


def _run_artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return the compact, run-observed fields used by list and MCP clients."""
    stages = artifact["stages"]
    mutations = stages["mutations"]
    return {
        "completedAt": artifact["completedAt"],
        "canonicalRunArtifactSha256": canonical_artifact_sha256(artifact),
        "canonicalization": "synapse-json-v1",
        "bundleSha256": artifact["bundleSha256"],
        "sourceRevisionKind": artifact["sourceRevisionKind"],
        "sourceRevision": artifact["sourceRevision"],
        "dependencyLockSha256": artifact["dependencyLockSha256"],
        "runnerImageDigest": artifact["runner"]["imageDigest"],
        "toolchainVersions": artifact["toolchainVersions"],
        "preExit": stages["pre"]["exitCode"],
        "postExit": stages["post"]["exitCode"],
        "mutationsDeclared": len(mutations),
        "mutationsRejected": sum(
            1 for mutation in mutations if mutation.get("rejected") is True
        ),
    }


def _load_schema_valid_bundle_entries() -> list[tuple[Path, dict[str, Any], CompatibilityBundle]]:
    entries: list[tuple[Path, dict[str, Any], CompatibilityBundle]] = []
    if not BUNDLES_DIR.exists():
        return entries
    for bundle_path in sorted(BUNDLES_DIR.glob("*.json")):
        try:
            data = json.loads(bundle_path.read_text(encoding="utf-8"))
            parsed = CompatibilityBundle.model_validate(data)
        except (OSError, json.JSONDecodeError, ValidationError):
            continue
        if BUNDLE_ID_RE.fullmatch(parsed.bundleId) is not None:
            entries.append((bundle_path, data, parsed))
    return entries


def _find_exact_bundle(bundle_id: str) -> tuple[Path, dict[str, Any]] | None:
    """Resolve one schema-valid bundle ID; duplicate IDs are ambiguous."""
    if BUNDLE_ID_RE.fullmatch(bundle_id) is None:
        return None
    matches = [
        (bundle_path, data)
        for bundle_path, data, parsed in _load_schema_valid_bundle_entries()
        if parsed.bundleId == bundle_id
    ]
    if len(matches) == 1:
        return matches[0]
    if DRAFTS_DIR.exists():
        for draft_path in sorted(DRAFTS_DIR.glob("*.json")):
            try:
                data = json.loads(draft_path.read_text(encoding="utf-8"))
                parsed = CompatibilityBundle.model_validate(data)
                if parsed.bundleId == bundle_id:
                    return draft_path, data
            except Exception:
                continue
    return None


def load_all_golden_bundles() -> List[dict]:
    """Load curated files and derive public evidence status fail closed."""
    bundles = []
    entries = _load_schema_valid_bundle_entries()
    id_counts = Counter(parsed.bundleId for _, _, parsed in entries)
    for f, data, parsed in entries:
        if id_counts[parsed.bundleId] != 1:
            continue
        try:
            # A curated file remains visible, but recorded metadata alone is
            # not a completed run. VERIFIED also requires a run artifact
            # bound to these exact file bytes and toolchain outcomes.
            recorded_contract = bundle_has_recorded_verification_contract(data)
            run_artifact = load_valid_run_artifact(data, f)
            lifecycle = evaluate_evidence_lifecycle(data, run_artifact)
            publishable_contract = lifecycle["qualified"] is True
            artifact_available = run_artifact is not None
            if parsed.status == "VERIFIED":
                parsed.status = (
                    lifecycle["status"]
                    if lifecycle["status"] in {"VERIFIED", "STALE"}
                    else "UNVERIFIED"
                )
            public_bundle = parsed.model_dump(by_alias=True)
            public_bundle["recordClass"] = "CURATED"
            public_bundle["evidencePublication"] = {
                "qualified": publishable_contract,
                "runArtifactAvailable": artifact_available,
                "runArtifactUrl": (
                    f"/api/v1/bundles/{parsed.bundleId}/evidence"
                    if artifact_available
                    else None
                ),
                "runArtifactSummary": (
                    _run_artifact_summary(run_artifact)
                    if run_artifact is not None
                    else None
                ),
                "recordedContractShapeSatisfied": recorded_contract,
                "reason": lifecycle["reason"],
                "lifecycle": lifecycle,
            }
            # Historical files may contain isolation labels from an older
            # runner. Without a separately verifiable artifact tied to the
            # exact run, those labels must not be inherited publicly.
            public_bundle["isolationProfile"] = dict(PUBLIC_NON_ATTESTATION)
            bundles.append(public_bundle)
        except (KeyError, TypeError, ValueError):
            # Projection remains fail closed if a future validator returns an
            # artifact shape this public schema does not understand.
            continue
    return sorted(bundles, key=lambda item: item["bundleId"])


def load_all_published_bundles() -> List[dict]:
    """Load curated golden bundles AND machine-verified draft bundles with valid run artifacts."""
    curated = load_all_golden_bundles()
    for item in curated:
        if not item.get("recordClass"):
            item["recordClass"] = "CURATED"
        if not item.get("provenance"):
            item["provenance"] = {}
        item["provenance"]["curation"] = "HUMAN_CURATED"

    draft_entries = []
    if DRAFTS_DIR.exists():
        for draft_path in sorted(DRAFTS_DIR.glob("*.json")):
            try:
                data = json.loads(draft_path.read_text(encoding="utf-8"))
                parsed = CompatibilityBundle.model_validate(data)
            except Exception:
                continue
            if BUNDLE_ID_RE.fullmatch(parsed.bundleId) is None:
                continue
            run_artifact = load_valid_run_artifact(data, draft_path)
            if run_artifact is not None and run_artifact.get("outcome") == "PASSED":
                lifecycle = evaluate_evidence_lifecycle(data, run_artifact)
                if lifecycle.get("qualified") is True:
                    parsed.status = (
                        lifecycle["status"]
                        if lifecycle["status"] in {"VERIFIED", "STALE"}
                        else "UNVERIFIED"
                    )
                    public_bundle = parsed.model_dump(by_alias=True)
                    public_bundle["recordClass"] = "AUTONOMOUS"
                    if not public_bundle.get("provenance"):
                        public_bundle["provenance"] = {}
                    public_bundle["provenance"]["curation"] = "MACHINE_VERIFIED"
                    public_bundle["provenance"]["source"] = "autonomous-pipeline"
                    public_bundle["evidencePublication"] = {
                        "qualified": True,
                        "runArtifactAvailable": True,
                        "runArtifactUrl": f"/api/v1/bundles/{parsed.bundleId}/evidence",
                        "runArtifactSummary": _run_artifact_summary(run_artifact),
                        "recordedContractShapeSatisfied": True,
                        "reason": lifecycle["reason"],
                        "lifecycle": lifecycle,
                    }
                    public_bundle["isolationProfile"] = dict(PUBLIC_NON_ATTESTATION)
                    draft_entries.append(public_bundle)

    seen_ids = {b["bundleId"] for b in curated}
    all_bundles = list(curated)
    for db in draft_entries:
        if db["bundleId"] not in seen_ids:
            all_bundles.append(db)
            seen_ids.add(db["bundleId"])

    return sorted(all_bundles, key=lambda item: item["bundleId"])


@router.get("", response_model=List[CompatibilityBundle])
async def list_bundles(response: Response, runtime: Optional[str] = None):
    """List schema-valid curated bundles with run-artifact-qualified status."""
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    all_b = load_all_golden_bundles()
    if runtime:
        all_b = [b for b in all_b if b.get("scope", {}).get("runtime", "").lower() == runtime.lower()]
    return all_b


@router.get("/{bundle_id}", response_model=CompatibilityBundle)
async def get_bundle_by_id(bundle_id: str, response: Response):
    """Retrieves a specific Compatibility Bundle by ID."""
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    for b in load_all_golden_bundles():
        if b.get("bundleId") == bundle_id:
            return b
    raise HTTPException(status_code=404, detail=f"Compatibility bundle '{bundle_id}' not found")


@router.get("/{bundle_id}/evidence", response_model=BundleRunArtifact)
async def get_bundle_run_evidence(bundle_id: str, response: Response):
    """Return only an artifact that still validates against exact bundle bytes."""
    match = _find_exact_bundle(bundle_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Compatibility bundle not found")
    bundle_path, bundle = match
    artifact = load_valid_run_artifact(bundle, bundle_path)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="No valid run artifact is published for these exact bundle bytes",
        )
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return artifact


class BundleSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=3, max_length=500)
    runtime: Optional[str] = None


@router.post("/search", response_model=List[CompatibilityBundle])
async def search_bundles(req: BundleSearchRequest):
    """Searches Compatibility Bundles by error signature, regex, or summary."""
    results = []
    q_lower = req.query.lower().strip()
    
    for b in load_all_golden_bundles():
        if req.runtime and b.get("scope", {}).get("runtime", "").lower() != req.runtime.lower():
            continue
            
        fp = b.get("fingerprint", {})
        err_sig = fp.get("errorSignature", "").lower()
        regex_pat = fp.get("regex", "")
        desc = b.get("description", "").lower()
        pkg = b.get("scope", {}).get("package", "").lower()

        matched = False
        if q_lower in err_sig or q_lower in desc or q_lower in pkg:
            matched = True
        elif regex_pat:
            try:
                if re.search(regex_pat, req.query, re.IGNORECASE):
                    matched = True
            except Exception:
                pass

        if matched:
            results.append(b)

    return results


from fastapi import Header
from app.config import settings

class BundleVerificationResponse(BaseModel):
    verified: bool
    bundleId: str
    message: str


@router.post("/verify", response_model=BundleVerificationResponse)
async def verify_bundle_endpoint(
    bundle: CompatibilityBundle,
    x_admin_key: Optional[str] = Header(None, alias="X-Synapse-Admin-Key")
):
    """Fail closed until verification runs in a dedicated hostile-code boundary."""
    if not settings.admin_token or not x_admin_key or x_admin_key != settings.admin_token:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Server-side bundle verification requires a valid X-Synapse-Admin-Key. Use client-side 'synapse reverify' for unauthenticated local execution."
        )

    raise HTTPException(
        status_code=503,
        detail=(
            "Server-side bundle execution is disabled until a dedicated isolated job runner is available. "
            "Use the local CLI only for code you trust."
        ),
    )
