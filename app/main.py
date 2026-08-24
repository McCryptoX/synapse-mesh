import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.api import health_router, discovery_router, recipes_router
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
    logger.info("Synapse-Mesh Engine is ready to serve agents.")
    yield
    # Shutdown
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

# Include Routers
app.include_router(health_router)
app.include_router(discovery_router)
app.include_router(recipes_router)
app.include_router(mcp_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
