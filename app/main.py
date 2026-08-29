import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import init_db
from app.api import (
    bundles_router,
    discovery_router,
    docs_router,
    health_router,
    miner_router,
    ops_router,
    recipes_router,
)
from app.mcp import mcp_router
from app.core.upstream_miner import UpstreamMiningEngine

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("synapse_mesh")


class RequestBodyLimitMiddleware:
    """Buffer at most a small bounded body and reject oversized chunked input."""

    def __init__(self, app, max_bytes: int = 1_000_000):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length)
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length header"}, status_code=400)(scope, receive, send)
                return
            if declared < 0:
                await JSONResponse({"detail": "Invalid Content-Length header"}, status_code=400)(scope, receive, send)
                return
            if declared > self.max_bytes:
                await JSONResponse({"detail": "Request body exceeds the 1 MB limit"}, status_code=413)(scope, receive, send)
                return

        chunks = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await JSONResponse({"detail": "Request body exceeds the 1 MB limit"}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            more_body = bool(message.get("more_body", False))

        body = b"".join(chunks)
        replayed = False

        async def replay_receive():
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


async def autonomous_mining_worker():
    """Continuously discover sources and maintain drafts without LLM calls."""
    await asyncio.sleep(5)  # Initial grace period on startup

    # Standby workers retry the leader lock.  If the leader process dies, one
    # of them takes over without requiring a container restart.
    import fcntl
    lock_file = None
    while lock_file is None:
        candidate = None
        try:
            candidate = open("/tmp/synapse_worker_miner.lock", "w")
            fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file = candidate
        except BlockingIOError:
            candidate.close()
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if candidate is not None:
                candidate.close()
            logger.warning("[Autonomous Miner] Leader election unavailable (%s).", type(exc).__name__)
            await asyncio.sleep(60)

    while True:
        try:
            logger.info("[Autonomous Miner] Triggering background upstream mining & harvest cycle...")
            mined_bundles = await UpstreamMiningEngine.mine_and_verify_all(persist_to_disk=True)
            logger.info("[Autonomous Miner] Mining cycle finished: %s candidates processed.", len(mined_bundles))
            
            # Also run GitHub release harvester and verification pipeline
            try:
                from scripts.github_harvester import GitHubReleaseHarvester
                harvester = GitHubReleaseHarvester()
                await harvester.harvest_and_ingest()
            except Exception as exc:
                logger.warning("[Autonomous Harvester] Cycle failed (%s).", type(exc).__name__)

        except asyncio.CancelledError:
            logger.info("[Autonomous Miner] Background mining worker cancelled.")
            break
        except Exception as exc:
            logger.error("[Autonomous Miner] Mining cycle failed (%s).", type(exc).__name__)
        
        # Sweep every hour
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Synapse-Mesh Engine...")
    await init_db()
    
    # Launch the autonomous background worker unless this process is an
    # explicitly configured read-only preview or test instance.
    mining_task = None
    if settings.autonomous_mining_enabled:
        mining_task = asyncio.create_task(autonomous_mining_worker())
        logger.info("Synapse-Mesh Engine initialized: autonomous background miner active.")
    else:
        logger.info("Synapse-Mesh Engine initialized: autonomous background miner disabled by configuration.")
    
    yield
    
    # Shutdown
    if mining_task is not None:
        logger.info("Stopping autonomous background worker...")
        mining_task.cancel()
        try:
            await mining_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutting down Synapse-Mesh Engine.")


app = FastAPI(
    title="Synapse-Mesh (Exocortex) API",
    description="Agent-native compatibility evidence registry with fail-closed draft intake.",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json"
)

app.add_middleware(RequestBodyLimitMiddleware, max_bytes=1_000_000)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False if "*" in settings.cors_origins else True,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Accept",
        "MCP-Protocol-Version",
        "Mcp-Method",
        "Mcp-Name",
        "X-Synapse-Admin-Key",
    ],
)

@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/":
        # The homepage and its JSON representation expose current evidence
        # lifecycle counts. They must not outlive a revocation or freshness
        # boundary in a shared cache.
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    elif request.url.path.startswith("/api/v1/"):
        if any(request.url.path.startswith(p) for p in ["/api/v1/recipes/stats", "/api/v1/ops", "/api/v1/recipes/search"]):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif "cache-control" not in response.headers:
            if request.method in ["POST", "PUT", "DELETE"]:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            else:
                response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    return response

# Include Routers
app.include_router(health_router)
app.include_router(discovery_router)
app.include_router(recipes_router)
app.include_router(bundles_router)
app.include_router(miner_router)
app.include_router(mcp_router)
app.include_router(ops_router)
app.include_router(docs_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, access_log=False)
