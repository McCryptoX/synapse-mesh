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
        "description": "Searches Synapse-Mesh for verified bug fixes, compatibility recipes and reproducible test suites.",
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
        "description": "Submits a verified bug fix, reproduction script, and test suite to Synapse-Mesh.",
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
    """Information endpoint for MCP Streamable HTTP."""
    await log_agent_access("discovery", "mcp_info", "", request)
    return {
        "status": "ready",
        "protocol": "MCP/2026-Streamable-HTTP",
        "server": settings.app_name,
        "toolsAvailable": [t["name"] for t in MCP_TOOLS]
    }


@router.post("")
async def mcp_json_rpc(request: Request):
    """MCP JSON-RPC 2.0 Streamable HTTP Endpoint."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC payload")

    msg_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    if not method:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": "Missing method"}})

    # Method Dispatch
    if method == "initialize":
        await log_agent_access("mcp_call", "initialize", "", request)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False}
                },
                "serverInfo": {
                    "name": "Synapse-Mesh-Exocortex",
                    "version": settings.app_version
                }
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
        tool_name = params.get("name")
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
                content_text = f"No verified recipes found in Synapse-Mesh matching query '{search_req.errorSignature}'."
            else:
                formatted = []
                for r in recipes:
                    formatted.append(
                        f"### Verified Recipe: {r.id} (Confidence: {r.evidence.confidenceScore*100:.0f}%)\n"
                        f"- **Runtime:** {r.problem.runtime}\n"
                        f"- **Error:** {r.problem.errorSignature}\n"
                        f"- **Summary:** {r.solution.summary}\n"
                        f"- **Verification Status:** {r.evidence.verificationStatus} (Exit Code {r.evidence.sandboxExitCode})\n"
                        f"```diff\n{r.solution.codeDiff or 'N/A'}\n```\n"
                        f"- **Source:** {r.evidence.primarySource or 'Synapse Sandbox'}\n"
                    )
                content_text = "\n\n".join(formatted)

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
                            "text": f"Successfully stored verified recipe '{created.id}' (Status: {created.evidence.verificationStatus})."
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
