import json
from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from typing import Optional
from app.config import settings
from app.api.bundles import load_all_golden_bundles
from app.models.recipe import VERIFIED_EVIDENCE_CONTRACT

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML_PATH = TEMPLATES_DIR / "index.html"
FAVICON_SVG_PATH = STATIC_DIR / "favicon.svg"
OG_IMAGE_PATH = STATIC_DIR / "og-image.png"
STYLE_CSS_PATH = STATIC_DIR / "style.min.css"
PUBLIC_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
)


def _render_public_template(
    template_name: str,
    fallback: str,
    **context: object,
) -> HTMLResponse:
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        return HTMLResponse(fallback)
    template = PUBLIC_TEMPLATE_ENV.get_template(template_name)
    return HTMLResponse(template.render(**context))

@router.get("/static/style.min.css", tags=["Assets"])
@router.get("/style.min.css", tags=["Assets"])
@router.head("/static/style.min.css", tags=["Assets"])
@router.head("/style.min.css", tags=["Assets"])
async def style_css():
    """Serve the stylesheet with bounded caching so deployments can invalidate it."""
    if STYLE_CSS_PATH.exists():
        return FileResponse(
            path=STYLE_CSS_PATH,
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=0, must-revalidate"}
        )
    return Response(status_code=404)


@router.get("/og-image.png", tags=["Assets"])
@router.get("/og-image.jpg", tags=["Assets"])
@router.head("/og-image.png", tags=["Assets"])
@router.head("/og-image.jpg", tags=["Assets"])
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
@router.head("/favicon.svg", tags=["Assets"])
@router.head("/favicon.ico", tags=["Assets"])
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
@router.head("/health", tags=["System"])
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
@router.head("/benchmark", tags=["Architecture"])
async def benchmark_page():
    return _render_public_template(
        "benchmark.html",
        "<h1>Benchmark Dashboard</h1>",
        active_page="benchmark",
    )

@router.get("/verification", tags=["Architecture"], response_class=HTMLResponse)
@router.head("/verification", tags=["Architecture"])
@router.get("/architecture", tags=["Architecture"], response_class=HTMLResponse)
@router.head("/architecture", tags=["Architecture"])
async def verification_page():
    return _render_public_template(
        "verification.html",
        "<h1>Verification Architecture</h1>",
        active_page="architecture",
        verification_profile=VERIFIED_EVIDENCE_CONTRACT,
    )


@router.get("/legal", tags=["Legal"], response_class=HTMLResponse)
@router.head("/legal", tags=["Legal"])
async def legal_page():
    """English legal notice pursuant to § 5 DDG / § 18 MStV."""
    return _render_public_template(
        "legal.html",
        "<h1>Legal Notice</h1><p>Synapse-Mesh Operator — mesh-direct [at] synapsemesh.dev</p>",
        active_page="legal",
    )


@router.get("/privacy", tags=["Legal"], response_class=HTMLResponse)
@router.head("/privacy", tags=["Legal"])
async def privacy_page():
    """English privacy policy pursuant to Art. 13/14 GDPR."""
    return _render_public_template(
        "privacy.html",
        "<h1>Privacy Policy</h1><p>Data-minimizing architecture.</p>",
        active_page="privacy",
    )


@router.get("/", tags=["System"])
@router.head("/", tags=["System"])
async def root(request: Request, format: Optional[str] = Query(None)):
    accept = request.headers.get("accept", "").lower()
    
    # Return JSON ONLY if explicitly asked via query param ?format=json or pure Accept: application/json without text/html
    if format == "json" or ("application/json" in accept and "text/html" not in accept and "*/*" not in accept):
        return {
            "message": "Welcome to Synapse-Mesh (Project Exocortex) - Evidence-First Compatibility Registry for Software Agents",
            "axiom": "Synapse does not try to be known by AIs. Synapse is built so that AIs can discover, understand, and immediately execute it as a tool.",
            "protocolVersion": settings.mcp_protocol_version,
            "version": settings.app_version,
            "registry": {
                "source": "curated-bundle-files",
                "bundleCount": len(load_all_golden_bundles()),
                "evidenceQualifiedCount": sum(
                    1 for bundle in load_all_golden_bundles() if bundle.get("status") == "VERIFIED"
                ),
                "legacySqliteVerifiedClaimsIncluded": False,
            },
            "executionPolicy": {
                "publicSubmissionsStoredAs": "DRAFT",
                "publicSubmissionCodeExecuted": False,
                "localReverificationRequiresExplicitExecution": True,
            },
            "autonomousMaintenance": {
                "scheduledDiscovery": settings.autonomous_mining_enabled,
                "requiresLlm": False,
                "selfModifiesApplicationCode": False,
                "selfPromotesGoldenEvidence": False,
            },
            "matchSemantics": {
                "VERIFIED_MATCH": "valid run-bound artifact and exact supplied version equals the observed release; reproduce before applying",
                "UNVERIFIED_MATCH": "no exact-version run evidence applies, including missing or ambiguous target versions; reproduce every stage before considering",
                "VERSION_MISMATCH": "outside declared affected range; do not apply",
                "NO_VERIFIED_MATCH": "no deterministic curated match; do not apply",
            },
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
                "legalNotice": "/legal",
                "privacyPolicy": "/privacy"
            }
        }

    # The public registry is deliberately sourced only from the curated,
    # read-only bundle directory. Historical SQLite recipe labels are not
    # evidence and must never be promoted into the homepage by a DB query.
    items = []
    curated_runtime = {}
    for bundle in sorted(load_all_golden_bundles(), key=lambda b: str(b.get("bundleId", ""))):
        bundle_id = str(bundle.get("bundleId", ""))
        if not bundle_id:
            continue
        scope = bundle.get("scope") or {}
        fingerprint = bundle.get("fingerprint") or {}
        patch = bundle.get("patch") or {}
        runtime = str(scope.get("runtime") or "unknown").lower()
        runtime = "nodejs" if runtime in ("javascript", "typescript") else runtime
        curated_runtime[runtime] = curated_runtime.get(runtime, 0) + 1
        evidence_qualified = bundle.get("status") == "VERIFIED"
        items.append({
            "id": bundle_id,
            "isGolden": True,
            "isEvidenceQualified": evidence_qualified,
            "runtime": runtime,
            "errorSignature": fingerprint.get("errorSignature") or bundle_id,
            "summary": bundle.get("description") or "",
            "diff": patch.get("unifiedDiff") or "",
            "pins": patch.get("pinnedDependencies") or {},
            "doNot": patch.get("doNot") or [],
            "status": bundle.get("status") or "UNVERIFIED",
            "reverify": "synapse reverify " + bundle_id,
            "detailUrl": None,
        })

    curated_count = len(items)
    evidence_count = sum(1 for item in items if item["isEvidenceQualified"])

    if INDEX_HTML_PATH.exists():
        template = PUBLIC_TEMPLATE_ENV.get_template("index.html")
        html_content = template.render(
            active_page="search",
            canonical_mcp_url=settings.canonical_mcp_url,
            verification_profile=VERIFIED_EVIDENCE_CONTRACT,
            total_verified=evidence_count,
            total_all=curated_count,
            pass_rate="NOT EXPOSED",
            count_python=curated_runtime.get("python", 0),
            count_nodejs=curated_runtime.get("nodejs", 0),
            count_docker=curated_runtime.get("docker", 0),
            initial_data_json=json.dumps(items).replace("<", "\\u003c")
        )
        return HTMLResponse(content=html_content)
            
    return HTMLResponse("<h1>Synapse-Mesh</h1>")
