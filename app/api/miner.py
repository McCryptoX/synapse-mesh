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
    persist: bool = True,
    x_admin_key: Optional[str] = Header(None, alias="X-Synapse-Admin-Key")
):
    """Executes zero-token autonomous upstream changelog and git mining."""
    if settings.admin_token and x_admin_key != settings.admin_token:
        # If admin token is configured, enforce auth for server-side persistence
        raise HTTPException(status_code=403, detail="Forbidden: Admin key required to persist mined bundles.")

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
