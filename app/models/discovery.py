from pydantic import BaseModel, Field
from typing import List, Dict, Any


class McpManifest(BaseModel):
    name: str = "Synapse-Mesh"
    description: str = "Agent-native verified living solutions & sandbox test runner"
    version: str = "1.0.0"
    transport: Dict[str, str] = {
        "type": "streamable-http",
        "endpoint": "https://synapsemesh.dev/mcp"
    }
    capabilities: Dict[str, List[str]] = {
        "tools": ["find_solution", "submit_solution"],
        "resources": ["recipes://{recipeId}"]
    }


class AgentManifest(BaseModel):
    agentName: str = "Synapse-Mesh-Exocortex"
    protocols: List[str] = ["MCP/2026", "A2A/1.0", "REST/OpenAPI3.1"]
    endpoints: Dict[str, str] = {
        "mcp": "https://synapsemesh.dev/mcp",
        "rest": "https://synapsemesh.dev/api/v1",
        "a2a": "https://synapsemesh.dev/a2a"
    }
    supportedRuntimes: List[str] = ["python", "nodejs", "rust", "go"]
    evidenceFirst: bool = True
    zeroPii: bool = True
    axiom: str = "Synapse soll nicht versuchen, von KIs 'gekannt' zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können."
