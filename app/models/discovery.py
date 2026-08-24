from pydantic import BaseModel, Field
from typing import List, Dict, Any


class McpManifest(BaseModel):
    name: str = "Synapse-Mesh"
    description: str = "CI/CD for AI Knowledge - Agent-native verified living solutions registry"
    version: str = "0.1.0-beta"
    protocolVersion: str = "2026-07-28"
    transport: Dict[str, str] = {
        "type": "streamable-http",
        "endpoint": "https://mcp.synapsemesh.dev"
    }
    capabilities: Dict[str, List[str]] = {
        "tools": ["find_solution", "submit_solution"],
        "resources": ["recipes://{recipeId}"]
    }


class AgentManifest(BaseModel):
    agentName: str = "Synapse-Mesh-Exocortex"
    version: str = "0.1.0-beta"
    protocols: List[str] = ["MCP/2026-07-28", "A2A/1.0", "REST/OpenAPI3.1"]
    endpoints: Dict[str, str] = {
        "mcp": "https://mcp.synapsemesh.dev",
        "rest": "https://api.synapsemesh.dev/api/v1",
        "docs": "https://docs.synapsemesh.dev",
        "a2a": "https://api.synapsemesh.dev/a2a"
    }
    supportedRuntimes: List[str] = ["python", "nodejs", "rust", "go"]
    evidenceFirst: bool = True
    zeroPii: bool = True
    axiom: str = "Synapse soll nicht versuchen, von KIs 'gekannt' zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können."
