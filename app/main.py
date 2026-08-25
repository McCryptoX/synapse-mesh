import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import init_db
from app.api import health_router, discovery_router, recipes_router, bundles_router, miner_router
from app.mcp import mcp_router
from app.core.upstream_miner import UpstreamMiningEngine

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("synapse_mesh")


async def autonomous_mining_worker():
    """Autonomous background loop that continuously extracts, verifies, and publishes compatibility bundles."""
    await asyncio.sleep(5)  # Initial grace period on startup
    while True:
        try:
            logger.info("[Autonomous Miner] Triggering background upstream mining cycle...")
            mined_bundles = await UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=True)
            logger.info(f"[Autonomous Miner] Mining cycle finished. {len(mined_bundles)} candidate bundles processed & verified.")
        except asyncio.CancelledError:
            logger.info("[Autonomous Miner] Background mining worker cancelled.")
            break
        except Exception as e:
            logger.error(f"[Autonomous Miner] Mining cycle error: {e}")
        
        # Sleep for 6 hours before next autonomous discovery sweep
        try:
            await asyncio.sleep(6 * 3600)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Synapse-Mesh Engine...")
    await init_db()
    
    # Launch autonomous background miner task
    mining_task = asyncio.create_task(autonomous_mining_worker())
    logger.info("Synapse-Mesh Engine initialized: Autonomous 24/7 background miner ACTIVE.")
    
    yield
    
    # Shutdown
    logger.info("Stopping autonomous background worker...")
    mining_task.cancel()
    try:
        await mining_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down Synapse-Mesh Engine.")


app = FastAPI(
    title="Synapse-Mesh (Exocortex) API",
    description="Agent-native verified living solutions & sandbox test runner infrastructure.",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Include Routers
app.include_router(health_router)
app.include_router(discovery_router)
app.include_router(recipes_router)
app.include_router(bundles_router)
app.include_router(miner_router)
app.include_router(mcp_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
