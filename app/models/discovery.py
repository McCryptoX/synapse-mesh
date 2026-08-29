from pydantic import BaseModel, Field
from typing import List, Dict, Any

from app.config import settings


def _mcp_transport() -> Dict[str, str]:
    return {
        "type": "streamable-http",
        "endpoint": settings.canonical_mcp_url,
    }


def _agent_endpoints() -> Dict[str, str]:
    return {
        "mcp": settings.canonical_mcp_url,
        "rest": "https://api.synapsemesh.dev/api/v1",
        "docs": "https://docs.synapsemesh.dev",
    }


class McpManifest(BaseModel):
    name: str = "Synapse-Mesh"
    description: str = "Agent-native compatibility evidence registry with fail-closed draft intake"
    version: str = "0.1.0-beta"
    protocolVersion: str = "2026-07-28"
    transport: Dict[str, str] = Field(default_factory=_mcp_transport)
    capabilities: Dict[str, List[str]] = {
        "tools": ["find_solution", "submit_solution"],
        "resources": ["recipes://{recipeId}"]
    }
    resultSemantics: Dict[str, str] = {
        "VERIFIED_MATCH": "Exact run-bound artifact validated and supplied package version equals the observed release; reproduce in the target project before applying",
        "UNVERIFIED_MATCH": "No exact-version run evidence applies to the supplied environment, including missing or ambiguous target versions; reproduce every stage before considering",
        "VERSION_MISMATCH": "Requested version lies outside the declared affected range; do not apply",
        "NO_VERIFIED_MATCH": "No curated record passed the deterministic match gates; do not apply",
    }
    publicSubmissionPolicy: str = "Sanitized and stored as an unexecuted DRAFT"


class AgentManifest(BaseModel):
    agentName: str = "Synapse-Mesh-Exocortex"
    version: str = "0.1.0-beta"
    protocols: List[str] = ["MCP/2026-07-28", "REST/OpenAPI3.1"]
    endpoints: Dict[str, str] = Field(default_factory=_agent_endpoints)
    supportedRuntimes: List[str] = ["python", "nodejs"]
    evidenceFirst: bool = True
    dataMinimising: bool = True
    verifiedRequiresRunArtifact: bool = True
    publicSubmissionCodeExecuted: bool = False
    autonomousMaintenanceRequiresLlm: bool = False
    axiom: str = "Synapse is built to be discovered, understood and used at runtime, with proof or an honest miss."
