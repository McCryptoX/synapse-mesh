from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.upstream_miner import UpstreamMiningEngine, KNOWN_UPSTREAM_TARGETS
from app.models.bundle import CompatibilityBundle

router = APIRouter(prefix="/api/v1/miner", tags=["Autonomous Mining"])


class MiningRunResponse(BaseModel):
    minedCount: int
    bundles: List[CompatibilityBundle]
    status: str = "COMPLETED"
    tokenCost: int = 0


@router.post("/run", response_model=MiningRunResponse)
async def trigger_upstream_mining(
    persist: bool = False,
    x_admin_key: Optional[str] = Header(None, alias="X-Synapse-Admin-Key")
):
    """
    Authenticated endpoint for executing upstream mining.
    STRICT SECURITY GATE: Requires a valid non-empty X-Synapse-Admin-Key matching settings.admin_token.
    Output is strictly stored in `bundles/drafts/` with DRAFT/UNVERIFIED status (never golden).
    """
    if not settings.admin_token or not x_admin_key or x_admin_key != settings.admin_token:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Triggering upstream mining runs requires a valid X-Synapse-Admin-Key."
        )

    mined = await UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=persist)
    return MiningRunResponse(
        minedCount=len(mined),
        bundles=mined,
        status="COMPLETED",
        tokenCost=0
    )


@router.get("/targets", tags=["Autonomous Mining"])
async def list_mining_targets():
    """Lists all monitored upstream open-source package repositories."""
    return {
        "count": len(KNOWN_UPSTREAM_TARGETS),
        "targets": KNOWN_UPSTREAM_TARGETS,
        "tokenCost": 0
    }
