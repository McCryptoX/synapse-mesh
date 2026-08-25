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

> Portable, execution-verified compatibility and bug-fix layer for AI software agents (MCP Spec 2026-07-28 & A2A protocol).

Synapse-Mesh delivers deterministically proven code patches, exact package pins, negative recipes (`doNot`), and a 4-stage client verifier that every AI agent can independently re-verify in its own workspace.

## Agent-Native Tooling & Integration
- [MCP Gateway](https://mcp.synapsemesh.dev/mcp): Streamable HTTP JSON-RPC 2.0 MCP endpoint exposing `find_solution` and `submit_solution`.
- [MCP Discovery Manifest](https://synapsemesh.dev/.well-known/mcp.json): Model Context Protocol server capabilities and schema descriptor.
- [A2A Agent Card](https://synapsemesh.dev/.well-known/agent-card.json): Autonomous Agent-to-Agent discovery manifest.
- [One-Line CLI Installer](https://synapsemesh.dev/install.sh): Bash script to install `synapse` CLI and auto-configure Claude Desktop, Cursor, and Codex.

## System Architecture & Benchmarks
- [4-Stage Verification Contract](https://synapsemesh.dev/verification): Epistemic specification (Pre-Fail Exit 1 -> AST Diff -> Post-Pass Exit 0 -> Mutation Sanity).
- [Empirical Benchmark](https://synapsemesh.dev/benchmark): Controlled evaluation of 4-stage contracts vs ungrounded LLM code generation.
- [Interactive OpenAPI Docs](https://docs.synapsemesh.dev): Complete REST API documentation and interactive Swagger UI.

## Verified Compatibility Bundles (Python)
- [HTTPX 0.28 ASGI Transport](https://synapsemesh.dev/api/v1/bundles/bundle_httpx_028_asgi_transport_001): Fixes `TypeError: AsyncClient.__init__() got unexpected keyword 'app'` via `ASGITransport`.
- [Pydantic v2 Model Validator](https://synapsemesh.dev/api/v1/bundles/bundle_pydantic_v2_model_validator_001): Migrates deprecated `@root_validator` to `@model_validator(mode='before')`.
- [FastAPI Lifespan Context](https://synapsemesh.dev/api/v1/bundles/bundle_fastapi_0115_lifespan_context_001): Replaces deprecated `@app.on_event` with `@asynccontextmanager` lifespan.
- [Python 3.12 UTC Datetime](https://synapsemesh.dev/api/v1/bundles/bundle_python_312_datetime_utc_aware_001): Replaces deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.
- [SQLAlchemy 2.0 Select Scalars](https://synapsemesh.dev/api/v1/bundles/bundle_sqlalchemy_20_select_scalars_001): Fixes removed `Query.get()` with `session.get()` or `session.execute(select(...)).scalars()`.
- [NumPy 2.0 Scalar Aliases](https://synapsemesh.dev/api/v1/bundles/bundle_numpy_20_nan_alias_removal_001): Migrates removed `np.NAN`, `np.Inf`, and `np.bool` to standard `np.nan`, `np.inf`, and `bool`.
- [DuckDB 0.10 Substring Types](https://synapsemesh.dev/api/v1/bundles/bundle_duckdb_010_substring_casting_001): Resolves strict type binding in SQL function signatures for numeric offsets.
- [LangChain 0.3 Runnable Invoke](https://synapsemesh.dev/api/v1/bundles/bundle_langchain_03_runnable_invoke_001): Migrates legacy `LLMChain.run()` to canonical `Runnable.invoke()`.

## Verified Compatibility Bundles (Node.js & TypeScript)
- [TypeScript 5.6 Map Lookup](https://synapsemesh.dev/api/v1/bundles/bundle_typescript_56_strict_map_lookup_001): Resolves TS2532 `Map.get()` undefined indexing under `--noUncheckedIndexedAccess`.
- [Next.js 15 Async Params](https://synapsemesh.dev/api/v1/bundles/bundle_nextjs_15_async_params_001): Updates dynamic App Router page params to async Promise handling.
- [React 19 useActionState](https://synapsemesh.dev/api/v1/bundles/bundle_react_19_use_action_state_001): Migrates deprecated `useFormState` to standard React 19 `useActionState`.
- [Express 5.0 Route Regex](https://synapsemesh.dev/api/v1/bundles/bundle_express_50_path_to_regexp_001): Updates wildcard routes to named parameter syntax (`/{*splat}`) for path-to-regexp v8.

## Full Context & API Access
- [Full LLM Context (llms-full.txt)](https://synapsemesh.dev/llms-full.txt): Complete uncompressed documentation stream with tool schemas, diffs, and verification rules.
- [Direct API Gateway](https://api.synapsemesh.dev): High-performance HTTP/3 API access and living solution endpoints.
"""

LLMS_FULL_TXT_CONTENT = """# Synapse-Mesh: Complete Technical Reference for AI Agents

> Open, verifiable compatibility and verification layer for AI software agents (MCP Spec 2026-07-28 & A2A protocol).

## 1. Executive Summary & Epistemic Axiom

Synapse-Mesh does not claim universal answers. It delivers portable, execution-verified compatibility bundles: exact package pins, clean unified diffs, negative recipes (`doNot`), and a 4-stage client verifier that every AI can prove in its own workspace.

**Axiom:** *"Synapse does not try to be known by AIs. Synapse is built so that AIs can discover, understand, and immediately execute it as a tool."*

---

## 2. MCP Tools Specification (JSON-RPC 2.0)

Endpoint: `POST https://mcp.synapsemesh.dev/mcp`

### Tool: `find_solution`
Searches Synapse-Mesh for reproducibly verified bug fixes and CI/CD-tested code patches.
```json
{
  "name": "find_solution",
  "parameters": {
    "type": "object",
    "properties": {
      "errorSignature": {
        "type": "string",
        "description": "The exact error message, exception type, or traceback snippet"
      },
      "runtime": {
        "type": "string",
        "enum": ["all", "python", "nodejs", "docker"],
        "description": "Optional runtime filter"
      },
      "packages": {
        "type": "object",
        "description": "Optional key-value pairs of packages and version strings e.g. {'fastapi': '>=0.100.0'}"
      }
    },
    "required": ["errorSignature"]
  }
}
```

### Tool: `submit_solution`
Submits a reproducible problem, unified diff fix, and test suite for automated isolated sandbox verification.
```json
{
  "name": "submit_solution",
  "parameters": {
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
```

---

## 3. The 4-Stage Verification Contract

Every bundle in Synapse-Mesh must pass all 4 stages in an isolated, hermetic container:
1. **Stage 1 (Pre-Fail Validation):** Reproduction script executes unpatched -> Must exit with code 1 and match error regex.
2. **Stage 2 (Unified Diff Application):** Clean, AST-compliant git patch is applied to isolated workspace.
3. **Stage 3 (Post-Pass Execution):** Test suite executes on patched workspace -> Must exit with code 0 in native compiler/engine.
4. **Stage 4 (Mutation Sanity):** Known web-fehlfixes and hallucinated partial fixes are injected -> Must be rejected 100%.

---

## 4. Golden Bundle Catalog & Diffs

### bundle_httpx_028_asgi_transport_001
- **Runtime:** Python
- **Error:** `TypeError: AsyncClient.__init__() got an unexpected keyword argument 'app'`
- **Fix:** Use `httpx.ASGITransport(app=app)` and pass `transport=transport` to `AsyncClient`.
- **doNot:** `["Do not pin httpx<0.28 indefinitely", "Do not instantiate ASGITransport without app kwarg"]`

### bundle_pydantic_v2_model_validator_001
- **Runtime:** Python
- **Error:** `PydanticDeprecatedSince20: Pydantic V1 style @root_validator validators are deprecated.`
- **Fix:** Replace `@root_validator(pre=True)` with `@model_validator(mode='before') @classmethod`.
- **doNot:** `["Do not use mode='after' when parsing raw unparsed dicts", "Do not omit @classmethod decorator"]`

### bundle_fastapi_0115_lifespan_context_001
- **Runtime:** Python
- **Error:** `DeprecationWarning: on_event is deprecated, use lifespan event handlers instead.`
- **Fix:** Wrap startup/shutdown logic into an `@asynccontextmanager async def lifespan(app: FastAPI)` generator.
- **doNot:** `["Do not mix legacy on_event handlers with lifespan handlers"]`

### bundle_typescript_56_strict_map_lookup_001
- **Runtime:** Node.js / TypeScript
- **Error:** `TS2532: Object is possibly 'undefined' when accessing Map.get() result property`
- **Fix:** Add optional chaining `map.get(id)?.role ?? 'GUEST'` or explicit undefined check.
- **doNot:** `["Do not disable noUncheckedIndexedAccess globally as a workaround"]`

### bundle_nextjs_15_async_params_001
- **Runtime:** Node.js
- **Error:** `Error: Route dynamic params must be awaited in Next.js 15 App Router`
- **Fix:** Type `params` as `Promise<{ id: string }>` and execute `const { id } = await params`.
- **doNot:** `["Do not access params.id synchronously in Next.js 15 components"]`

---

## 5. CLI Verification Tool

Install CLI:
```bash
curl -fsSL https://synapsemesh.dev/install.sh | bash
```

Run independent client-side verification:
```bash
synapse reverify bundle_httpx_028_asgi_transport_001
```
"""


@router.get("/llms.txt", tags=["Discovery"], response_class=PlainTextResponse)
@router.get("/.well-known/llms.txt", tags=["Discovery"], response_class=PlainTextResponse)
async def get_llms_txt():
    """Conforms to llmstxt.org specification for LLM crawler discovery."""
    return PlainTextResponse(LLMS_TXT_CONTENT, media_type="text/markdown; charset=utf-8")


@router.get("/llms-full.txt", tags=["Discovery"], response_class=PlainTextResponse)
async def get_llms_full_txt():
    """Full context file for LLMs conforming to llmstxt.org."""
    return PlainTextResponse(LLMS_FULL_TXT_CONTENT, media_type="text/markdown; charset=utf-8")
