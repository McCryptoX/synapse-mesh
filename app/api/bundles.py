import json
import re
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.models.bundle import CompatibilityBundle
from scripts.synapse_reverify import verify_golden_bundle

router = APIRouter(prefix="/api/v1/bundles", tags=["Compatibility Bundles"])
BUNDLES_DIR = Path(__file__).resolve().parent.parent.parent / "bundles" / "golden"


def load_all_golden_bundles() -> List[dict]:
    bundles = []
    if BUNDLES_DIR.exists():
        for f in BUNDLES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                bundles.append(data)
            except Exception:
                pass
    return bundles


@router.get("", response_model=List[CompatibilityBundle])
async def list_bundles(runtime: Optional[str] = None):
    """Lists all verified Compatibility Bundles."""
    all_b = load_all_golden_bundles()
    if runtime:
        all_b = [b for b in all_b if b.get("scope", {}).get("runtime", "").lower() == runtime.lower()]
    return all_b


@router.get("/{bundle_id}", response_model=CompatibilityBundle)
async def get_bundle_by_id(bundle_id: str):
    """Retrieves a specific Compatibility Bundle by ID."""
    for b in load_all_golden_bundles():
        if b.get("bundleId") == bundle_id:
            return b
    raise HTTPException(status_code=404, detail=f"Compatibility bundle '{bundle_id}' not found")


class BundleSearchRequest(BaseModel):
    query: str
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


class BundleVerificationResponse(BaseModel):
    verified: bool
    bundleId: str
    message: str


@router.post("/verify", response_model=BundleVerificationResponse)
async def verify_bundle_endpoint(bundle: CompatibilityBundle):
    """Executes the hermetic 4-stage sandbox verification on a submitted bundle."""
    try:
        ok = verify_golden_bundle(bundle.model_dump())
        return BundleVerificationResponse(
            verified=ok,
            bundleId=bundle.bundleId,
            message="4-Stage verification PASSED with 100% mutant kills" if ok else "Verification FAILED"
        )
    except Exception as e:
        return BundleVerificationResponse(
            verified=False,
            bundleId=bundle.bundleId,
            message=f"Sandbox execution error: {str(e)}"
        )
