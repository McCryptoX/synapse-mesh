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

> Open, verifiable compatibility and verification layer for AI software agents (MCP Spec 2026-07-28 & A2A protocol).

Synapse-Mesh delivers portable, execution-verified compatibility bundles: exact package pins, clean unified git diffs, negative recipes (doNot), and a 4-stage client verifier that every AI can prove in its own workspace.

## Documentation
- [Architecture & Verification](https://synapsemesh.dev/verification): The 4-stage isolated sandbox verification contract and epistemic hierarchy.
- [OpenAPI Specification](https://docs.synapsemesh.dev): Complete interactive API documentation and schemas.
- [A2A Agent Card Standard](https://synapsemesh.dev/.well-known/agent-card.json): Autonomous Agent-to-Agent discovery manifest.
- [MCP Discovery Manifest](https://synapsemesh.dev/.well-known/mcp.json): Model Context Protocol server capabilities and tool descriptor.
- [One-Line CLI Installer](https://synapsemesh.dev/install.sh): Bash script to install Synapse CLI and configure Cursor, Claude, and Codex.

## Verified Compatibility Bundles
- [HTTPX 0.28 ASGI Transport](https://synapsemesh.dev/api/v1/bundles/bundle_httpx_028_asgi_transport_001): Migration for explicit ASGITransport in-process testing.
- [Pydantic v2 Model Validator](https://synapsemesh.dev/api/v1/bundles/bundle_pydantic_v2_model_validator_001): Migration from root_validator to model_validator(mode="before").
- [FastAPI Lifespan Context](https://synapsemesh.dev/api/v1/bundles/bundle_fastapi_0115_lifespan_context_001): Migration from on_event to asynccontextmanager lifespan handlers.
- [Python 3.12 UTC Datetime](https://synapsemesh.dev/api/v1/bundles/bundle_python_312_datetime_utc_aware_001): Migration from naive utcnow() to timezone-aware datetime.now(timezone.utc).

## Optional
- [Full Context Documentation](https://synapsemesh.dev/llms-full.txt): Complete uncompressed documentation stream for LLMs.
- [GitHub Repository](https://github.com/McCryptoX/synapse-mesh): Open source source code, CLI tooling, and test suites.
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
