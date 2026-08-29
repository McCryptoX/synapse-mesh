from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape


router = APIRouter(include_in_schema=False)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
)

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
DOCS_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _endpoint_groups(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a deterministic, presentation-only projection of OpenAPI routes."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return []

    for path, path_item in sorted(paths.items(), key=lambda item: str(item[0])):
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags")
            group_name = str(tags[0]) if isinstance(tags, list) and tags else "Other"
            summary = operation.get("summary") or operation.get("operationId") or "Endpoint"
            grouped[group_name].append(
                {
                    "method": method.upper(),
                    "path": str(path),
                    "summary": str(summary),
                    "deprecated": operation.get("deprecated") is True,
                }
            )

    return [
        {"name": name, "endpoints": grouped[name]}
        for name in sorted(grouped, key=str.casefold)
    ]


@router.get("/docs", response_class=HTMLResponse)
@router.head("/docs")
async def api_docs(request: Request) -> HTMLResponse:
    """Render API reference metadata without third-party browser resources."""
    schema = request.app.openapi()
    info = schema.get("info") if isinstance(schema.get("info"), dict) else {}
    groups = _endpoint_groups(schema)
    template = jinja_env.get_template("api_docs.html")
    return HTMLResponse(
        template.render(
            active_page="docs",
            api_title=str(info.get("title") or "Synapse-Mesh API"),
            api_version=str(info.get("version") or "unknown"),
            api_description=str(info.get("description") or ""),
            groups=groups,
            endpoint_count=sum(len(group["endpoints"]) for group in groups),
        ),
        headers=DOCS_SECURITY_HEADERS,
    )


@router.get("/redoc", response_class=RedirectResponse)
@router.head("/redoc")
async def redoc_compatibility_redirect() -> RedirectResponse:
    """Keep existing bookmarks working without loading ReDoc from a CDN."""
    return RedirectResponse(url="/docs", status_code=307, headers=DOCS_SECURITY_HEADERS)
