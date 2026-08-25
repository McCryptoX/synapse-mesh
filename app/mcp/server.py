from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json
import logging
from typing import Dict, Any, List
from app.models.recipe import (
    RecipeSearchRequest,
    RecipeSubmitRequest,
    ProblemDefinition,
    SolutionDefinition,
    ReproductionDefinition
)
from app.api.recipes import search_recipes, submit_recipe, get_recipe_by_id, list_recipes
from app.database import get_db_connection
from app.config import settings

logger = logging.getLogger("synapse_mesh.mcp")
router = APIRouter(prefix="/mcp", tags=["Model Context Protocol (MCP)"])

MCP_TOOLS = [
    {
        "name": "find_solution",
        "description": "Searches Synapse-Mesh for reproducibly verified bug fixes, compatibility recipes and CI/CD tested code patches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "errorSignature": {
                    "type": "string",
                    "description": "The exact error message, exception type, or traceback snippet"
                },
                "runtime": {
                    "type": "string",
                    "description": "Optional runtime or language (e.g. 'python', 'nodejs', 'rust')"
                },
                "packages": {
                    "type": "object",
                    "description": "Optional key-value pairs of packages and version strings e.g. {'fastapi': '>=0.100.0'}"
                }
            },
            "required": ["errorSignature"]
        }
    },
    {
        "name": "submit_solution",
        "description": "Submits a reproducible problem, code fix, and test suite for automated isolated sandbox verification.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "runtime": { "type": "string", "description": "Language or runtime e.g. 'python'" },
                "errorSignature": { "type": "string", "description": "The exact error signature resolved" },
                "description": { "type": "string", "description": "Description of why the error occurs" },
                "summary": { "type": "string", "description": "Summary of the solution fix" },
                "codeDiff": { "type": "string", "description": "Unified git diff of the patch" },
                "reproScript": { "type": "string", "description": "Minimal script triggering the error" },
                "testSuite": { "type": "string", "description": "Test code asserting the fix works" },
                "primarySource": { "type": "string", "description": "Official docs / release notes link" }
            },
            "required": ["runtime", "errorSignature", "description", "summary", "reproScript", "testSuite"]
        }
    }
]


def summarize_user_agent(ua: str) -> str:
    if not ua:
        return "Unknown-Agent"
    ua_lower = ua.lower()
    if "claude" in ua_lower:
        return "Claude-Client"
    if "cursor" in ua_lower:
        return "Cursor-IDE"
    if "chatgpt" in ua_lower or "openai" in ua_lower:
        return "ChatGPT-Action"
    if "python" in ua_lower or "httpx" in ua_lower or "requests" in ua_lower:
        return "Python-Agent"
    if "curl" in ua_lower:
        return "CLI-Curl"
    if "mozilla" in ua_lower or "chrome" in ua_lower or "safari" in ua_lower:
        return "Web-Browser"
    return ua[:40]


async def log_agent_access(source_type: str, action: str, query: str, request: Request):
    try:
        ua_summary = summarize_user_agent(request.headers.get("user-agent", ""))
        db = await get_db_connection()
        await db.execute(
            "INSERT INTO access_logs (source_type, action, query_snippet, user_agent_summary) VALUES (?, ?, ?, ?)",
            (source_type, action, (query or "")[:100], ua_summary)
        )
        await db.commit()
        await db.close()
    except Exception as e:
        logger.warning(f"Failed to log agent access: {e}")


@router.get("")
async def mcp_get_info(request: Request):
    """Information endpoint for MCP Streamable HTTP (Spec 2026-07-28)."""
    await log_agent_access("discovery", "mcp_info", "", request)
    return {
        "status": "ready",
        "protocol": f"MCP/{settings.mcp_protocol_version}",
        "server": settings.app_name,
        "endpoint": settings.canonical_mcp_url,
        "toolsAvailable": [t["name"] for t in MCP_TOOLS]
    }


@router.post("")
async def mcp_json_rpc(request: Request):
    """MCP JSON-RPC 2.0 Streamable HTTP Endpoint (Spec 2026-07-28)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC payload")

    msg_id = body.get("id")
    # Support both body method and MCP 2026-07-28 Mcp-Method header
    method = body.get("method") or request.headers.get("mcp-method")
    params = body.get("params", {})

    if not method:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": "Missing method"}})

    # Method Dispatch
    if method in ("initialize", "server/discover"):
        await log_agent_access("mcp_call", method.replace("/", "_"), "", request)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": settings.mcp_protocol_version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False}
                },
                "serverInfo": {
                    "name": "Synapse-Mesh-Exocortex",
                    "version": settings.app_version
                },
                "tools": MCP_TOOLS
            }
        }

    elif method == "notifications/initialized":
        return JSONResponse(content={"jsonrpc": "2.0", "result": {}})

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    elif method == "tools/list":
        await log_agent_access("mcp_call", "tools_list", "", request)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": MCP_TOOLS
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name") or request.headers.get("mcp-name")
        arguments = params.get("arguments", {})

        if tool_name == "find_solution":
            error_sig = arguments.get("errorSignature", "")
            await log_agent_access("mcp_call", "find_solution", error_sig, request)

            search_req = RecipeSearchRequest(
                errorSignature=error_sig,
                runtime=arguments.get("runtime"),
                packages=arguments.get("packages")
            )
            recipes = await search_recipes(search_req)
            
            if not recipes:
                content_text = json.dumps({
                    "status": "NO_RECIPE_FOUND",
                    "errorSignature": search_req.errorSignature,
                    "suggestion": "Submit a minimal reproduction to Synapse-Mesh for sandbox verification."
                }, indent=2)
            else:
                # Ultra-token-dense machine payload (< 800 tokens)
                payloads = []
                for r in recipes:
                    payloads.append({
                        "recipeId": r.id,
                        "runtime": r.problem.runtime,
                        "errorSignature": r.problem.errorSignature,
                        "pinnedDependencies": r.solution.pinnedDependencies or r.problem.packages,
                        "summary": r.solution.summary,
                        "diff": r.solution.codeDiff or r.solution.patchDiff,
                        "doNot": r.solution.doNot,
                        "reverify": {
                            "testSuite": r.reproduction.testSuite
                        },
                        "evidence": {
                            "status": r.evidence.verificationStatus,
                            "preExit": r.evidence.preExit,
                            "postExit": r.evidence.postExit,
                            "mutationsKilled": r.evidence.mutationsKilled,
                            "confidence": r.evidence.confidenceScore
                        },
                        "canonicalUrl": f"https://synapsemesh.dev/recipes/{r.id}"
                    })
                content_text = json.dumps(payloads if len(payloads) > 1 else payloads[0], indent=2)

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {"type": "text", "text": content_text}
                    ]
                }
            }

        elif tool_name == "submit_solution":
            error_sig = arguments.get("errorSignature", "")
            await log_agent_access("mcp_call", "submit_solution", error_sig, request)

            submit_req = RecipeSubmitRequest(
                problem=ProblemDefinition(
                    errorSignature=error_sig,
                    runtime=arguments.get("runtime", "unknown"),
                    description=arguments.get("description", "")
                ),
                solution=SolutionDefinition(
                    summary=arguments.get("summary", ""),
                    codeDiff=arguments.get("codeDiff"),
                    instructions=[]
                ),
                reproduction=ReproductionDefinition(
                    script=arguments.get("reproScript", ""),
                    testSuite=arguments.get("testSuite", "")
                ),
                primarySource=arguments.get("primarySource")
            )
            created = await submit_recipe(submit_req)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Successfully stored verified recipe '{created.id}' (Status: {created.evidence.verificationStatus}). Link: https://synapsemesh.dev/recipes/{created.id}"
                        }
                    ]
                }
            }

        else:
            return JSONResponse(
                status_code=404,
                content={"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}}
            )

    elif method == "resources/list":
        recipes = await list_recipes(limit=20)
        resources = [
            {
                "uri": f"synapse://recipes/{r.id}",
                "name": f"Recipe: {r.id}",
                "description": r.problem.errorSignature,
                "mimeType": "application/json"
            }
            for r in recipes
        ]
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"resources": resources}
        }

    else:
        return JSONResponse(
            status_code=404,
            content={"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}
        )
