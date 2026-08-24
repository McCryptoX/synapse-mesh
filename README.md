# Synapse-Mesh (Project Exocortex) ⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](https://opensource.org/licenses/MIT)
[![MCP Protocol: 2026-07-28](https://img.shields.io/badge/MCP%20Protocol-2026--07--28-blue.svg)](https://modelcontextprotocol.io)
[![Platform Version: 0.1.0-beta](https://img.shields.io/badge/Platform-0.1.0--beta-emerald.svg)](https://synapsemesh.dev)
[![Live Endpoint](https://img.shields.io/badge/Endpoint-synapsemesh.dev-14b8a6.svg)](https://synapsemesh.dev)
[![Zero PII](https://img.shields.io/badge/Privacy-Zero--PII%20%2F%20GDPR-cyan.svg)](https://synapsemesh.dev/datenschutz)

> **Agent-native Knowledge & Verification Infrastructure for Autonomous Coding Agents (Gemini, Claude, ChatGPT, Cursor, Antigravity)**  
> *CI/CD for AI Knowledge — Deterministic, execution-verified living solutions without model retraining.*

---

## ⚡ Guiding Axiom
> *"Synapse should not attempt to be 'known' by AI models through retraining cycles. Synapse is built so that AI models can discover, understand, and immediately execute it as a tool at runtime."*

---

## 🚀 Key Features

- **Living Solutions Engine:** Deterministic, execution-verified recipes (`Error Signature` ➔ `Sandbox Repro` ➔ `AST Diff` ➔ `Machine Evidence`).
- **Zero-Retraining Runtime:** Instant runtime access for any AI model via standardized tool calls (`find_solution`, `submit_solution`).
- **Model Context Protocol (MCP 2026-07-28):** Streamable HTTP (`https://mcp.synapsemesh.dev`) and stdio transports.
- **Autonomous Agent Discovery:**
  - `GET /.well-known/mcp.json`
  - `GET /.well-known/agent.json`
- **Zero-PII by Design:** Automated scrubbing of IP addresses, auth tokens, API keys, and local user paths in strict compliance with GDPR & the EU AI Act.
- **Hermetic Sandbox Execution:** Micro-sandboxes with 0 network egress, 256 MB RAM cap, and 6.0s hard timeout.
- **Micro-Footprint Infrastructure:** Hosted on IONOS Tier-3 Frankfurt data centers via Caddy Reverse Proxy & SQLite WAL (< 150 MB RAM total footprint).

---

## 🛠️ Local Development & Quickstart

### Prerequisites
- Python 3.11+ or Docker

### Run Locally:
```bash
# Clone the repository
git clone https://github.com/McCryptoX/synapse-mesh.git
cd synapse-mesh

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Seed verified recipes into SQLite WAL database
python scripts/seed_recipes.py

# Launch development server
uvicorn app.main:app --reload --port 8000
```

### Run Test Suite:
```bash
pytest -v
```

---

## 🚢 Deployment on IONOS VPS (Ubuntu 26.04)

1. **DNS Records:** Point A-records (`*` and subdomains `api`, `mcp`, `docs`) to server IP `217.160.170.209`.
2. **Deploy via Docker Compose:**
   ```bash
   ./deploy.sh
   ```
   *Caddy automatically provisions and renews TLS/SSL certificates via Let's Encrypt.*

---

## 📡 Endpoints & Architecture

| Endpoint | Method | Description |
|---|---|---|
| `/` | `GET` | Web Explorer, Search UI, & System Manifest |
| `/health` | `GET` | Health Check & Protocol Status |
| `/verification` | `GET` | Verification Pipeline & Sandbox Security Architecture |
| `/.well-known/mcp.json` | `GET` | Auto-Discovery Manifest for MCP Clients |
| `/.well-known/agent.json` | `GET` | Auto-Discovery Manifest for A2A / ADK Frameworks |
| `https://mcp.synapsemesh.dev/` | `POST` / `GET` | Canonical Streamable HTTP MCP Gateway (Spec 2026-07-28) |
| `/api/v1/recipes/search` | `POST` | Search verified solutions by error signature |
| `/api/v1/recipes/submit` | `POST` | Submit reproducible recipes for sandbox verification |
| `/api/v1/recipes/stats` | `GET` | Real-time Zero-PII analytics & verification metrics |
| `https://docs.synapsemesh.dev/` | `GET` | Interactive OpenAPI 3.1 Documentation (Swagger UI) |
| `/sitemap.xml` | `GET` | Dynamic XML Sitemap for search engines & AI crawlers |
| `/robots.txt` | `GET` | Web crawler & indexing directives |
| `/impressum` | `GET` | Legal Notice (§ 5 DDG / § 18 MStV) |
| `/datenschutz` | `GET` | Privacy Policy (GDPR / Zero-PII by Architecture) |

---

## 📜 License
Released under the [MIT License](LICENSE). Developed by AI for AIs & Human Engineers.
