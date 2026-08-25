from fastapi import APIRouter
from app.models.discovery import McpManifest, AgentManifest

router = APIRouter()


@router.get("/.well-known/mcp.json", tags=["Discovery"], response_model=McpManifest)
async def get_mcp_manifest():
    """Agent discovery manifest for automatic MCP client integration."""
    return McpManifest()


@router.get("/.well-known/agent.json", tags=["Discovery"], response_model=AgentManifest)
async def get_agent_manifest():
    """A2A (Agent-to-Agent) discovery descriptor."""
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
