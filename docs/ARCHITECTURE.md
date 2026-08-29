# Synapse-Mesh Architecture & System Design

This document specifies the technical architecture, data flows, execution boundaries, and trust invariants of Synapse-Mesh (Project Exocortex).

---

## 1. System Overview & Data Flow

```text
+-----------------------------------------------------------------------------------+
|                            Clients & External Systems                             |
|  - Coding Agents (Claude, Cursor, Codex, Antigravity, OpenDevin)                 |
|  - MCP Clients & HTTP REST API Consumers                                          |
|  - Web Browsers / Human Developers                                                |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        Caddy 2 (Reverse Proxy & Edge TLS)                         |
|  - TLS termination (Let's Encrypt / ZeroSSL)                                      |
|  - Header Sanitization (X-Forwarded-For -> 127.0.0.1, X-Real-IP -> 127.0.0.1)    |
|  - Zero Edge Logging (`log { output discard }`)                                   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        FastAPI Application (Port 8000)                            |
|                                                                                   |
|  [Entrypoints]                                                                    |
|  - MCP Server (/mcp) -> find_solution, submit_solution (JSON-RPC 2.0)             |
|  - REST API (/api/v1/bundles, /api/v1/recipes, /health, /openapi.json)            |
|  - Web UI & Jinja2 Templates (/, /verification, /legal, /privacy, /ops)           |
|  - Auto-Discovery (/.well-known/mcp.json, /.well-known/agent.json)                |
|                                                                                   |
|  [Core Processing Pipeline]                                                       |
|  - Inbound Sanitizer (app/core/sanitizer.py) [Strips API keys, PII, User paths]   |
|  - Version Matcher (app/core/version_matcher.py) [Semver & Range Intersection]    |
|  - Signature Matcher (app/core/signature_matcher.py) [Class & Regex Matching]     |
|  - Snapshot & Projection Cache (app/core/registry_snapshot.py)                   |
+-----------------------------------------------------------------------------------+
            |                               |                           |
            v                               v                           v
+-----------------------+       +-----------------------+   +-----------------------+
|  bundles/golden/      |       |  SQLite WAL Database  |   |  evidence/runs/       |
|  - Immutable JSON     |       |  (data/synapse_mesh)  |   |  - Exact run outputs  |
|  - Curated Goldens    |       |  - Candidate Drafts   |   |  - Stage signatures   |
|  - Read-Only mount    |       |  - Coarse Telemetry   |   |  - Run digests        |
|  - Source of Truth    |       |  - Ops Session Auth   |   |  - Read-Only mount    |
+-----------------------+       +-----------------------+   +-----------------------+
                                            ^
                                            | (Hourly Mining Task)
+-----------------------------------------------------------------------------------+
|                     Autonomous Upstream Miner (0 LLM Tokens)                      |
|  - Changelog & Feed Harvester (scripts/github_harvester.py)                       |
|  - Heuristic AST/Regex Synthesizer (app/core/upstream_miner.py)                   |
|  - Output -> bundles/drafts/*.json (Categorized as UNVERIFIED / DRAFT)            |
+-----------------------------------------------------------------------------------+
                                            ^
                                            | (Daily Host-Side Systemd Timer)
+-----------------------------------------------------------------------------------+
|                   Disposable Verification Worker (Host-Orchestrated)              |
|  - Host Timer (deploy/systemd/synapse-verification.timer)                         |
|  - Pinned Toolchain Container (network: none, read-only root, non-root user)      |
|  - Independent 4-Stage Contract Validation (scripts/run_disposable_verification)  |
|  - Validated Result -> evidence/runs/ & immutable archive                         |
+-----------------------------------------------------------------------------------+
```

---

## 2. Component Specifications

### 2.1 Reverse Proxy (Caddy)
- Serves as the public edge gateway.
- Handles automated TLS certificate lifecycle.
- Implements strict data minimization: completely discards access logs and sanitizes IP headers to loopback (`127.0.0.1`) before forwarding to the application container.

### 2.2 Application Backend (FastAPI)
- Single-process async application running on Uvicorn.
- Disables internal access logging (`--no-access-log`).
- Manages routing for REST endpoints, MCP JSON-RPC handlers, and server-rendered HTML templates.
- Enforces strict inbound request body size limits and payload sanitization.

### 2.3 Model Context Protocol (MCP) Server
- Conforms to MCP Streamable HTTP specification (Spec Version: `2026-07-28`).
- Exposes two canonical tools:
  - `find_solution`: Structured compatibility lookup with error signature, runtime, and package version filtering.
  - `submit_solution`: Public ingestion mechanism. Validates input schema, sanitizes content, and stores submission as an unexecuted `DRAFT`.

### 2.4 Data Storage & Relational Database (SQLite WAL)
- Persistent SQLite database at `data/synapse_mesh.sqlite3`.
- Operates in Write-Ahead Logging (`PRAGMA journal_mode=WAL`) with `PRAGMA synchronous=NORMAL`.
- Stores:
  - Draft recipes and mined candidate bundles.
  - Minimal coarse telemetry (client category, action, timestamp — cleared after 30 days).
  - Operator authentication verifiers (salted PBKDF2-SHA256 password hash and opaque session digests).
- Automatic startup migrations ensure old plaintext query snippets are cleared and unverified rows are quarantined.

### 2.5 Curated Golden Registry (`bundles/golden/`)
- Directory of frozen, canonical JSON files representing human-reviewed compatibility solutions.
- Packaged directly in the repository and mounted read-only in production containers.
- Represents the baseline source of truth for the public registry.

### 2.6 Evidence & Run Artifact Store (`evidence/runs/`)
- Stores machine-verifiable JSON run records (`bundle_*.json`) matching the exact SHA-256 digest of verified bundles.
- Contains execution telemetry, toolchain versions, pre-fail exit codes, unified diff application results, post-pass assertions, and mutant kill records.
- Maintained as an immutable content-addressed archive under `evidence/runs/archive/`.

---

## 3. Data & Artifact Classification Matrix

| Artifact / Path | Source of Truth | Mutability | Trust Level | Ingestion / Update Policy |
|---|---|---|---|---|
| `bundles/golden/*.json` | Source | Immutable | High (Curated) | Human/Red-Team PR review only. Agents cannot edit. |
| `bundles/drafts/*.json` | Generated / Submissions | Mutable | Low (Unverified) | Populated by upstream miner and public submissions. |
| `evidence/runs/*.json` | Generated by Verifier | Immutable per Run | High (Verified) | Published only after successful 4-stage contract verification. |
| `evidence/lifecycle/*.json` | Governance | Immutable per Record | High (Reviewed) | Manages stale (90d), dispute, and supersession states. |
| `data/synapse_mesh.sqlite3` | Runtime State | Mutable (WAL) | Mixed | Backed up prior to deployments; preserves drafts and ops state. |
| `app/core/` & `app/api/` | Source Code | Immutable at Runtime | High | Standard Git commits and CI/CD testing. |

---

## 4. Execution & Isolation Model

Synapse-Mesh maintains strict separation between trusted fixture execution and untrusted inputs:

### 4.1 Public Submission Boundary (Zero Server Execution)
- Public submissions through MCP (`submit_solution`) or REST (`/api/v1/recipes/submit`) are **never executed** by the server.
- Submitted code diffs and scripts are sanitized for secrets and persisted purely as dormant text in draft records.

### 4.2 Autonomous Upstream Mining Boundary
- The upstream harvester (`scripts/github_harvester.py` / `app/core/upstream_miner.py`) uses heuristic regex and AST pattern matching against public changelogs.
- Requires zero LLM tokens.
- Does not execute code found in changelogs.
- Automatically flags all generated bundles as `DRAFT` / `UNVERIFIED`.

### 4.3 Scheduled Disposable Verifier Boundary
- Verification jobs run out-of-band via host systemd timer (`deploy/systemd/synapse-verification.timer`).
- Each verification runs in a dedicated, disposable Docker container:
  - Network: completely disabled (`--network none`).
  - Filesystem: read-only root (`--read-only`).
  - Security: `no-new-privileges`, all Linux capabilities dropped, custom seccomp.
  - User: fixed non-root UID/GID (10001:10001).
  - Storage: bounded private tmpfs, no host bind mounts.
  - Secrets: zero access to host environment, database, or API keys.
- Results are validated through an independent application verification gate before publication to `evidence/runs/`.

---

## 5. Security & Privacy Guarantees

1. **Zero Access Logging:** Both edge proxy and application backend discard access logs.
2. **IP Anonymization:** Client IP addresses are never recorded in database tables.
3. **Data Scrubbing:** Regular expressions strip API keys (`sk-...`, `ghp_...`, AWS keys), bearer tokens, passwords, email addresses, and private file paths prior to persistence.
4. **Session Security:** `/ops` authentication uses PBKDF2-SHA256 password hashing with per-session random salts. Cookie is `HttpOnly`, `Secure`, and `SameSite=Strict`.
