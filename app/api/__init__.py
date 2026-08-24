from app.api.health import router as health_router
from app.api.discovery import router as discovery_router
from app.api.recipes import router as recipes_router

__all__ = ["health_router", "discovery_router", "recipes_router"]
