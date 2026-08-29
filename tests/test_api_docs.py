import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


EXTERNAL_ASSET_PATTERN = re.compile(
    r"<(?:script|link|img)\b[^>]*(?:src|href)=[\"'](?:https?:)?//",
    re.IGNORECASE,
)


@pytest.mark.asyncio
async def test_docs_are_server_rendered_from_openapi_without_external_assets():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Synapse-Mesh (Exocortex) API" in response.text
    assert "GET" in response.text
    assert "/health" in response.text
    assert 'href="/openapi.json"' in response.text
    assert EXTERNAL_ASSET_PATTERN.search(response.text) is None
    assert "cdn.jsdelivr.net" not in response.text
    assert "swagger-ui" not in response.text.lower()
    assert "redoc.standalone" not in response.text.lower()
    assert "<script" not in response.text.lower()
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_redoc_compatibility_route_stays_local():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/redoc")

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


@pytest.mark.asyncio
async def test_openapi_json_remains_available_and_excludes_docs_routes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/docs" not in paths
    assert "/redoc" not in paths
