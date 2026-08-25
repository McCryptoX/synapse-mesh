import asyncio
from app.core.upstream_miner import UpstreamMiningEngine

async def background_mining_worker():
    """Autonomous background worker executing periodic upstream mining with 0 tokens."""
    logger.info("Autonomous Upstream Mining Worker loop initialized.")
    while True:
        try:
            # Run every 6 hours
            await asyncio.sleep(21600)
            logger.info("Executing scheduled zero-token upstream mining cycle...")
            mined = await UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=True)
            logger.info(f"Scheduled mining cycle completed: {len(mined)} bundle(s) processed.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background mining worker cycle: {e}")

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.api import health_router, discovery_router, recipes_router, bundles_router, miner_router
from app.mcp import mcp_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("synapse_mesh")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Synapse-Mesh Engine...")
    await init_db()
    worker_task = asyncio.create_task(background_mining_worker())
    logger.info("Synapse-Mesh Engine is ready to serve agents.")
    yield
    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
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

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

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
