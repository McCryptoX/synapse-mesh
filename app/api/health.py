from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from pathlib import Path
from app.config import settings
from app.database import get_db_connection

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML_PATH = TEMPLATES_DIR / "index.html"
IMPRESSUM_HTML_PATH = TEMPLATES_DIR / "impressum.html"
DATENSCHUTZ_HTML_PATH = TEMPLATES_DIR / "datenschutz.html"
VERIFICATION_HTML_PATH = TEMPLATES_DIR / "verification.html"
FAVICON_SVG_PATH = STATIC_DIR / "favicon.svg"


@router.get("/favicon.svg", tags=["Assets"])
@router.get("/favicon.ico", tags=["Assets"])
async def favicon():
    """Serves high-resolution custom Synapse-Mesh SVG favicon."""
    if FAVICON_SVG_PATH.exists():
        return FileResponse(
            path=FAVICON_SVG_PATH,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"}
        )
    return Response(status_code=404)


@router.get("/robots.txt", tags=["SEO"], response_class=PlainTextResponse)
async def robots_txt():
    """Search Engine Crawler Directives."""
    return f"""User-agent: *
Allow: /

Sitemap: {settings.base_url}/sitemap.xml
"""


@router.get("/sitemap.xml", tags=["SEO"])
async def sitemap_xml():
    """Dynamically generated XML Sitemap for Search Engines & AI Web Crawlers."""
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT id, updated_at FROM recipes WHERE verification_status = 'VERIFIED'")
        recipes = await cursor.fetchall()
    finally:
        await db.close()

    xml_entries = [
        f"""  <url>
    <loc>{settings.base_url}/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>""",
        f"""  <url>
    <loc>{settings.base_url}/verification</loc>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>""",
        f"""  <url>
    <loc>{settings.base_url}/impressum</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>""",
        f"""  <url>
    <loc>{settings.base_url}/datenschutz</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>"""
    ]

    for r in recipes:
        xml_entries.append(f"""  <url>
    <loc>{settings.base_url}/recipes/{r['id']}</loc>
    <lastmod>{str(r['updated_at'])[:10]}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    sitemap_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(xml_entries)}
</urlset>"""

    return Response(content=sitemap_content, media_type="application/xml")


@router.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "synapse-mesh",
        "version": settings.app_version,
        "protocol": f"MCP/{settings.mcp_protocol_version}",
        "environment": settings.environment,
        "evidenceFirst": True
    }


@router.get("/verification", tags=["Architecture"], response_class=HTMLResponse)
async def verification_page():
    if VERIFICATION_HTML_PATH.exists():
        with open(VERIFICATION_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Verification Architecture</h1>")


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
        "message": "Welcome to Synapse-Mesh (Projekt Exocortex) - CI/CD for AI Knowledge",
        "axiom": "Synapse soll nicht versuchen, von KIs 'gekannt' zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können.",
        "protocolVersion": settings.mcp_protocol_version,
        "version": settings.app_version,
        "discovery": {
            "mcp": "/.well-known/mcp.json",
            "agent": "/.well-known/agent.json",
            "sitemap": "/sitemap.xml",
            "robots": "/robots.txt",
            "favicon": "/favicon.svg"
        },
        "endpoints": {
            "mcpCanonical": settings.canonical_mcp_url,
            "verificationArchitecture": "/verification",
            "search": "/api/v1/recipes/search",
            "submit": "/api/v1/recipes/submit",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "impressum": "/impressum",
            "datenschutz": "/datenschutz"
        }
    }
