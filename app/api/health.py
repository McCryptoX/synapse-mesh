from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from app.config import settings

router = APIRouter()

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "templates" / "index.html"


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
async def root(request: Request):
    accept = request.headers.get("accept", "")
    
    # Return HTML if requested by browser
    if "text/html" in accept and INDEX_HTML_PATH.exists():
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
            
    # Default JSON manifest for API / Agents
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
