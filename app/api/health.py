from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from pathlib import Path
from typing import Optional
from app.config import settings
from app.database import get_db_connection

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML_PATH = TEMPLATES_DIR / "index.html"
LEGAL_HTML_PATH = TEMPLATES_DIR / "legal.html"
PRIVACY_HTML_PATH = TEMPLATES_DIR / "privacy.html"
VERIFICATION_HTML_PATH = TEMPLATES_DIR / "verification.html"
BENCHMARK_HTML_PATH = TEMPLATES_DIR / "benchmark.html"
FAVICON_SVG_PATH = STATIC_DIR / "favicon.svg"
OG_IMAGE_PATH = STATIC_DIR / "og-image.png"
STYLE_CSS_PATH = STATIC_DIR / "style.min.css"

@router.get("/static/style.min.css", tags=["Assets"])
@router.get("/style.min.css", tags=["Assets"])
async def style_css():
    """Serves ultra-optimized, pre-compiled and minified standalone CSS stylesheet for 100/100 PageSpeed."""
    if STYLE_CSS_PATH.exists():
        return FileResponse(
            path=STYLE_CSS_PATH,
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )
    return Response(status_code=404)


@router.get("/og-image.png", tags=["Assets"])
@router.get("/og-image.jpg", tags=["Assets"])
async def og_image():
    """Serves high-resolution 1200x630 OpenGraph Social Preview Banner."""
    if OG_IMAGE_PATH.exists():
        return FileResponse(
            path=OG_IMAGE_PATH,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"}
        )
    return Response(status_code=404)


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
    <loc>{settings.base_url}/benchmark</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""",
        f"""  <url>
    <loc>{settings.base_url}/legal</loc>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>""",
        f"""  <url>
    <loc>{settings.base_url}/privacy</loc>
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

    return Response(
        content=sitemap_content,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"}
    )


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


@router.get("/benchmark", tags=["Architecture"], response_class=HTMLResponse)
async def benchmark_page():
    if BENCHMARK_HTML_PATH.exists():
        with open(BENCHMARK_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Benchmark Dashboard</h1>")

@router.get("/verification", tags=["Architecture"], response_class=HTMLResponse)
@router.get("/architecture", tags=["Architecture"], response_class=HTMLResponse)
async def verification_page():
    if VERIFICATION_HTML_PATH.exists():
        with open(VERIFICATION_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Verification Architecture</h1>")


@router.get("/legal", tags=["Legal"], response_class=HTMLResponse)
async def legal_page():
    if LEGAL_HTML_PATH.exists():
        with open(LEGAL_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Legal Notice</h1><p>Synapse-Mesh Operator - mesh-direct@synapsemesh.dev</p>")


@router.get("/privacy", tags=["Legal"], response_class=HTMLResponse)
async def privacy_page():
    if PRIVACY_HTML_PATH.exists():
        with open(PRIVACY_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Privacy Policy</h1><p>Zero-PII Architecture.</p>")


@router.get("/", tags=["System"])
async def root(request: Request, format: Optional[str] = Query(None)):
    accept = request.headers.get("accept", "").lower()
    
    # Return JSON ONLY if explicitly asked via query param ?format=json or pure Accept: application/json without text/html
    if format == "json" or ("application/json" in accept and "text/html" not in accept and "*/*" not in accept):
        return {
            "message": "Welcome to Synapse-Mesh (Project Exocortex) - Verified Compatibility Layer for AI Agents",
            "axiom": "Synapse does not try to be known by AIs. Synapse is built so that AIs can discover, understand, and immediately execute it as a tool.",
            "protocolVersion": settings.mcp_protocol_version,
            "version": settings.app_version,
            "discovery": {
                "mcp": "/.well-known/mcp.json",
                "agent": "/.well-known/agent.json",
                "sitemap": "/sitemap.xml",
                "robots": "/robots.txt",
                "favicon": "/favicon.svg",
                "legalNotice": "/legal",
                "privacyPolicy": "/privacy",
                "llmsTxt": "/llms.txt"
            },
            "endpoints": {
                "mcpCanonical": settings.canonical_mcp_url,
                "verificationArchitecture": "/verification",
                "benchmarkDashboard": "/benchmark",
                "search": "/api/v1/recipes/search",
                "submit": "/api/v1/recipes/submit",
                "docs": "/docs",
                "openapi": "/openapi.json",
                "impressum": "/impressum",
                "datenschutz": "/datenschutz"
            }
        }

    # Default to HTML for all browsers and social crawlers (WhatsApp, Telegram, Discord, Facebook, Googlebot, etc.)
    if INDEX_HTML_PATH.exists():
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
            
    return HTMLResponse("<h1>Synapse-Mesh</h1>")
