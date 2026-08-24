from fastapi import APIRouter
from app.config import settings

router = APIRouter()


@router.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "synapse-mesh",
        "version": settings.app_version,
        "environment": settings.environment,
        "evidenceFirst": True
    }


@router.get("/", tags=["System"])
async def root():
    return {
        "message": "Welcome to Synapse-Mesh (Projekt Exocortex) - Agent-Native Living Solutions Engine",
        "axiom": "Synapse soll nicht versuchen, von KIs 'gekannt' zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können.",
        "discovery": {
            "mcp": "/.well-known/mcp.json",
            "agent": "/.well-known/agent.json"
        },
        "endpoints": {
            "mcpStreamableHttp": "/mcp",
            "search": "/api/v1/recipes/search",
            "submit": "/api/v1/recipes/submit",
            "docs": "/docs",
            "openapi": "/openapi.json"
        }
    }
