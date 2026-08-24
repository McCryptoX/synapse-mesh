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
