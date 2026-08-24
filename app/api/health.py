from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from app.config import settings

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
INDEX_HTML_PATH = TEMPLATES_DIR / "index.html"
IMPRESSUM_HTML_PATH = TEMPLATES_DIR / "impressum.html"
DATENSCHUTZ_HTML_PATH = TEMPLATES_DIR / "datenschutz.html"


@router.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "synapse-mesh",
        "version": settings.app_version,
        "environment": settings.environment,
        "evidenceFirst": True
    }


@router.get("/impressum", tags=["Legal"], response_class=HTMLResponse)
async def impressum_page():
    if IMPRESSUM_HTML_PATH.exists():
        with open(IMPRESSUM_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Impressum</h1><p>Synapse-Mesh Operator - contact@synapsemesh.dev</p>")


@router.get("/datenschutz", tags=["Legal"], response_class=HTMLResponse)
@router.get("/privacy", tags=["Legal"], response_class=HTMLResponse)
async def datenschutz_page():
    if DATENSCHUTZ_HTML_PATH.exists():
        with open(DATENSCHUTZ_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Datenschutz</h1><p>Zero-PII Architecture.</p>")


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
            "openapi": "/openapi.json",
            "impressum": "/impressum",
            "datenschutz": "/datenschutz"
        }
    }
