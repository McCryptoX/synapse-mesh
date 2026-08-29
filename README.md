# Synapse-Mesh

[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](LICENSE)
[![MCP Protocol: 2026-07-28](https://img.shields.io/badge/MCP%20Protocol-2026--07--28-blue.svg)](https://modelcontextprotocol.io)
[![Platform Version: 0.1.0-beta](https://img.shields.io/badge/Platform-0.1.0--beta-emerald.svg)](https://synapsemesh.dev)
[![Live Endpoint](https://img.shields.io/badge/Endpoint-synapsemesh.dev-14b8a6.svg)](https://synapsemesh.dev)
[![Privacy](https://img.shields.io/badge/Privacy-Data%20Minimizing-cyan.svg)](https://synapsemesh.dev/privacy)

## What it is

Synapse-Mesh is an agent-discoverable, evidence-qualified compatibility registry for software packages and developer tooling. When libraries introduce breaking changes, deprecations, or API migrations, Synapse-Mesh provides machine-readable patches with explicit package pins, reproduction contracts, and negative mutation tests—returning verified evidence when a reproducible test has established it, or an honest miss when evidence is insufficient.

## Current status

- **REST API:** Fully functional FastAPI service with OpenAPI 3.1 schema definitions.
- **MCP Interface:** Standard Model Context Protocol streamable HTTP endpoint (`/mcp`, protocol version `2026-07-28`) providing `find_solution` and `submit_solution` tools.
- **Discovery:** Standard discovery documents (`/.well-known/mcp.json`, `/.well-known/agent.json`, `/.well-known/agent-card.json`, `llms.txt`).
- **Evidence-Qualified Records:** Exact four-stage run evidence currently validates repository-owned fixtures (e.g., HTTPX 0.28.1 ASGI transport).
- **Curated Golden Bundles:** Frozen, human-curated compatibility bundles located under `bundles/golden/`.
- **Autonomous Ingestion & Mining:** 0-token upstream heuristic harvester extracts migration candidates from changelogs and release feeds into `bundles/drafts/`.
- **Limitations:** Public submissions are stored as drafts and are never executed directly on the server. There is no general-purpose public arbitrary code execution sandbox. Fully autonomous end-to-end promotion from draft to golden is deliberately not automated without human/red-team review.

## Why it exists

When major frameworks (such as Pydantic, FastAPI, HTTPX, SQLAlchemy, Next.js, or React) introduce breaking changes, LLM coding assistants frequently generate plausible but outdated, non-functional, or circular workarounds. Synapse-Mesh acts as an external ground-truth compatibility oracle, supplying exact version bounds, deterministic unified diffs, and anti-patterns (`doNot` recipes) to coding agents at runtime.

## Core idea

1. **Exact Version Scoping:** Compatibility recipes bind to exact source and target version bounds (`fromVersion`, `toVersion`).
2. **Fail-Closed Semantics:** Ambiguous versions, malformed patches, missing toolchains, or unverified claims produce `DRAFT`, `UNVERIFIED`, or an explicit miss—never an optimistic false positive.
3. **Four-Stage Verification Contract:** Verified claims require authentic pre-failure on the real package/compiler, clean unified diff application, post-pass on the patched workspace, and rejection of at least two incorrect mutant diffs.
4. **Agent-First Protocols:** Discovery and execution via standard MCP tool calls and typed JSON endpoints.

## Architecture

```text
+-----------------------------------------------------------------------+
|                         Software Agents / Clients                     |
+-----------------------------------------------------------------------+
       |                                     |                     |
       v (MCP JSON-RPC)                      v (REST / OpenAPI)     v (Discovery)
+-----------------------------------------------------------------------+
|                      FastAPI Application (app/main.py)                |
|  - Request Sanitization (Secrets / PII Stripping)                     |
|  - Exact Version Matching & Signature Checking                        |
|  - Bundles & Recipes Query Engine                                     |
+-----------------------------------------------------------------------+
       |                         |                       |
       v                         v                       v
+------------------+   +-------------------+   +------------------------+
|  Golden Bundles  |   |    Draft Store    |   | Evidence Run Artifacts |
| (bundles/golden) |   |  (bundles/drafts) |   |    (evidence/runs)     |
|   [Read-Only]    |   |   & SQLite WAL    |   |      [Read-Only]       |
+------------------+   +-------------------+   +------------------------+
                                 ^
                                 | (Hourly Mining / Ingestion)
+-----------------------------------------------------------------------+
|                   Autonomous Upstream Miner (0 Tokens)                |
|  - Heuristic Changelog / Feed Parser (app/core/upstream_miner.py)     |
+-----------------------------------------------------------------------+
```

## Core workflow

1. **`find_solution`:** An agent queries by runtime, target package, error signature, or package version bounds.
2. **Result Matching:** The system matches exact version constraints against curated bundles and run artifacts. If verified, it returns the patch with confidence `0.99`. If unverified, it returns `UNVERIFIED_MATCH` or `NO_VERIFIED_MATCH`.
3. **`submit_solution`:** Agents or developers can submit candidate fixes. Inbound submissions are sanitized and stored as `DRAFT` bundles in SQLite/drafts. Public submissions are **never executed directly**.
4. **Verification:** Repository-owned bundles are verified using isolated execution workers adhering to the 4-stage contract.
5. **Golden Promotion:** Only reviewed, passing bundles with full contract satisfaction become immutable `bundles/golden/` records.

## Trust model

- **Untrusted Submissions:** Public submissions via API or MCP are treated as untrusted text, sanitized, and stored as drafts.
- **No Public Code Execution:** The server does not provide an execution endpoint for arbitrary public code.
- **Fail-Closed Evidence:** A recipe is only marked `VERIFIED` if backed by a valid, reproducible 4-stage run artifact.
- **No Mock Oracles:** Verification requires authentic failure and passing on the declared real library or compiler binary, not synthetic mock classes.
- **Immutable Golden Store:** Autonomous workers cannot overwrite or promote into `bundles/golden/`.

## Current limitations

- The catalog of verified goldens is intentionally small and strictly curated.
- Automated verifications currently run against specific allowlisted environments (e.g. Linux Docker with pinned Python/Node toolchains).
- The service does not claim an autonomous A2A peer task execution gateway.
- Benchmark Treatment C results from historical suites are currently withheld pending full production image re-validation.

## Repository structure

```text
synapse-mesh/
├── app/                  # FastAPI backend, MCP server, core logic, templates, static
│   ├── api/              # REST API route handlers (bundles, recipes, ops, discovery)
│   ├── core/             # Version matcher, signature matcher, sanitizer, miner
│   ├── mcp/              # Model Context Protocol server implementation
│   ├── models/           # Pydantic data schemas and models
│   ├── static/           # Compiled CSS, icons, OG images
│   └── templates/        # Jinja2 HTML templates for public UI
├── benchmark/            # Benchmark evaluators, schemas, and test suites
├── bundles/
│   ├── golden/           # Immutable, human-reviewed golden compatibility bundles
│   └── drafts/           # Candidate draft bundles generated by upstream miner
├── deploy/               # Systemd services, timers, and deployment configs
├── docs/                 # Technical architecture, operations, and verification specs
│   ├── ARCHITECTURE.md   # Complete system architecture and data flows
│   ├── OPERATIONS.md     # Production deployment, backup, and revival guide
│   ├── VERIFICATION_MODEL.md # 4-stage verification contract specification
│   └── PROJECT_STATUS.md # Current implementation state and milestones
├── evidence/             # Exact run artifacts and lifecycle tracking records
├── packages/
│   └── verify/           # Node.js CLI verification package
├── schemas/              # JSON Schemas for compatibility bundles
├── scripts/              # Harvesters, importers, verifiers, deployment scripts
├── synapse_cli/          # Python CLI tool for querying and local mining
├── tests/                # Comprehensive pytest suite (214+ tests)
├── verification/         # Verification target manifests and worker container files
├── Caddyfile             # Production reverse-proxy configuration with TLS & zero-logging
├── Dockerfile            # Production multi-stage Docker container build
├── docker-compose.yml    # Service orchestration definition
└── pyproject.toml        # Python project metadata and dependencies
```

## Quick start

### Prerequisites
- Python 3.11+ (Python 3.12 recommended)
- Git
- Docker and Docker Compose (for production or containerized verification)

### Running locally

1. **Clone the repository:**
   ```bash
   git clone https://github.com/McCryptoX/synapse-mesh.git
   cd synapse-mesh
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   ```

5. **Start the local development server:**
   ```bash
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   The web UI is accessible at `http://127.0.0.1:8000`.

## Running tests

Run the complete test suite with pytest:

```bash
pytest -v
```

To run specific test modules:

```bash
# Test API endpoints
pytest tests/test_bundles_api.py tests/test_recipes_api.py

# Test MCP server
pytest tests/test_mcp.py

# Test sanitization & security boundaries
pytest tests/test_sanitizer.py tests/test_security_regressions.py
```

## MCP usage

Synapse-Mesh implements the Model Context Protocol (2026-07-28 spec) over streamable HTTP.

### Client Configuration (Cursor / Claude Desktop / Antigravity / Claude Code)

Add Synapse-Mesh to your MCP client configuration:

```json
{
  "mcpServers": {
    "synapse-mesh": {
      "url": "https://mcp.synapsemesh.dev/mcp",
      "type": "streamable-http"
    }
  }
}
```

Or when running locally:

```json
{
  "mcpServers": {
    "synapse-mesh-local": {
      "url": "http://127.0.0.1:8000/mcp",
      "type": "streamable-http"
    }
  }
}
```

### Available MCP Tools

- **`find_solution`:** Look up verified compatibility patches by package name, runtime, and error message.
- **`submit_solution`:** Submit a newly discovered compatibility draft.

## REST API

Interactive OpenAPI documentation is available locally at `http://127.0.0.1:8000/docs` and online at `https://docs.synapsemesh.dev`.

Key endpoints:
- `GET /.well-known/mcp.json` — MCP discovery descriptor.
- `GET /.well-known/agent.json` — Agent capability metadata.
- `GET /api/v1/bundles` — List curated golden compatibility bundles.
- `POST /api/v1/recipes/search` — Search compatibility solutions.
- `POST /api/v1/recipes/submit` — Submit sanitized draft recipes.
- `GET /health` — Service health and protocol version metadata.

## Verification

To run local bundle verification using the bundled verification tool:

```bash
node packages/verify/bin.js bundles/golden/bundle_httpx_028_asgi_transport.json --allow-code-execution
```

For complete details on the verification contract, see [docs/VERIFICATION_MODEL.md](docs/VERIFICATION_MODEL.md).

## Deployment

Production deployment is automated via Docker Compose and Caddy on a Linux host (e.g. Ubuntu 24.04/26.04). See [docs/OPERATIONS.md](docs/OPERATIONS.md) for full server setup, backup, recovery, and migration instructions.

## Security model

Synapse-Mesh is built with data minimization and fail-closed security by design:
- No edge access logging (`log { output discard }` in Caddy).
- Zero client IP persistence in application databases.
- Automatic redacting of secrets, API keys, tokens, emails, and local user paths.
- Read-only golden and evidence mounts in production containers.

See [SECURITY.md](SECURITY.md) for details on security architecture and vulnerability reporting.

## Project status / maintenance

Synapse-Mesh is currently in a stable, self-contained reference state. Active continuous feature development may be paused, but the repository is fully structured for long-term survival, local reproducibility, and straightforward revival.

## License

This project is licensed under the [MIT License](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on development, proposing compatibility bundles, and maintaining the four-stage verification standard.
