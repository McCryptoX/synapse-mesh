from fastapi import APIRouter
from app.models.discovery import McpManifest, AgentManifest

router = APIRouter()


@router.get("/.well-known/mcp.json", tags=["Discovery"], response_model=McpManifest)
async def get_mcp_manifest():
    """Agent discovery manifest for automatic MCP client integration."""
    return McpManifest()


@router.get("/.well-known/agent-card.json", tags=["Discovery"], response_model=AgentManifest)
@router.get("/.well-known/agent.json", tags=["Discovery"], response_model=AgentManifest)
async def get_agent_manifest():
    """A2A (Agent-to-Agent) discovery descriptor conforming to A2A standard."""
    return AgentManifest()

from fastapi.responses import PlainTextResponse
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


@router.get("/install.sh", tags=["Agent Tooling"], response_class=PlainTextResponse)
async def get_install_script():
    """One-command bash installer for Cursor, Claude Desktop, and Antigravity."""
    install_file = SCRIPTS_DIR / "install.sh"
    if install_file.exists():
        return PlainTextResponse(install_file.read_text(encoding="utf-8"), media_type="text/x-shellscript")
    return PlainTextResponse("#!/usr/bin/env bash\necho 'Installer not found'\nexit 1\n", status_code=404)


LLMS_TXT_CONTENT = """# Synapse-Mesh

> The Open, Verified Compatibility Layer for AI Software Agents (Cursor, Claude Code, Codex, Grok, Gemini, Antigravity).

Synapse-Mesh delivers portable, execution-verified compatibility bundles: exact package pins, clean unified git diffs, negative recipes (`doNot`), and a 4-stage client-side verifier (`synapse reverify <bundle_id>`).

## Machine Endpoints
- Canonical MCP Gateway: `https://mcp.synapsemesh.dev/mcp`
- MCP Discovery Manifest: `https://synapsemesh.dev/.well-known/mcp.json`
- A2A Agent Card Standard: `https://synapsemesh.dev/.well-known/agent-card.json`
- Golden Compatibility Bundles v1.0 API: `https://synapsemesh.dev/api/v1/bundles`
- OpenAPI Specification: `https://docs.synapsemesh.dev/openapi.json`

## Golden Compatibility Bundles (4-Stage Execution Verified)
- `bundle_httpx_028_asgi_transport_001`: HTTPX 0.28 explicit `ASGITransport(app=app)` migration.
- `bundle_pydantic_v2_model_validator_001`: Pydantic v2 `@model_validator(mode="before")` migration.
- `bundle_fastapi_0115_lifespan_context_001`: FastAPI `@asynccontextmanager lifespan(app)` context handler migration.
- `bundle_python_312_datetime_utc_aware_001`: Python 3.12 `datetime.now(timezone.utc)` timezone-aware timestamps.

## CLI & Hermetic Re-Verification
- Install: `curl -fsSL https://synapsemesh.dev/install.sh | bash`
- Search: `synapse search "model_validator"`
- Re-Verify: `synapse reverify bundle_httpx_028_asgi_transport_001`
"""


@router.get("/llms.txt", tags=["Discovery"], response_class=PlainTextResponse)
@router.get("/.well-known/llms.txt", tags=["Discovery"], response_class=PlainTextResponse)
async def get_llms_txt():
    """Conforms to llmstxt.org specification for LLM crawler discovery."""
    return PlainTextResponse(LLMS_TXT_CONTENT, media_type="text/markdown; charset=utf-8")


@router.get("/llms-full.txt", tags=["Discovery"], response_class=PlainTextResponse)
async def get_llms_full_txt():
    """Full context file for LLMs conforming to llmstxt.org."""
    return PlainTextResponse(LLMS_TXT_CONTENT, media_type="text/markdown; charset=utf-8")
