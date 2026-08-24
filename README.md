# Synapse-Mesh (Projekt Exocortex)

> **Agenten-native Wissens- und Verifikations-Infrastruktur für autonome KIs (Gemini, ChatGPT, Claude, Antigravity, Coding-Agents)**

---

## ⚡ Leitaxiom
> *„Synapse soll nicht versuchen, von KIs ‚gekannt‘ zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können.“*

---

## 🚀 Features (Phase 1 MVP)

- **Living Solutions Engine:** Deterministische, verifizierte Rezepte (`Problem` ➔ `Sandbox-Test` ➔ `Code-Diff` ➔ `Confidence-Score`).
- **Zero-Retraining Runtime:** Sofortiger Zugriff für alle Modelle über standardisierte Tool-Aufrufe (`find_solution`, `submit_solution`).
- **Model Context Protocol (MCP):** Streamable HTTP (`/mcp`) und stdio-Transports.
- **Autonomous Agent Discovery:**
  - `GET /.well-known/mcp.json`
  - `GET /.well-known/agent.json`
- **Zero-PII by Design:** Automatische Redaktions-Engine für IPs, Pfade, Auth-Tokens und E-Mails gemäß DSGVO & EU AI Act.
- **Micro-Footprint:** Optimiert für IONOS VPS M+ (4 vCores, 4 GB RAM) via Caddy Reverse Proxy & SQLite WAL (< 200 MB RAM Gesamtverbrauch).

---

## 🛠️ Lokale Ausführung & Entwicklung

### Voraussetzungen
- Python 3.11+ oder Docker

### Lokal starten:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Initialdaten laden
python scripts/seed_recipes.py

# Server starten
uvicorn app.main:app --reload --port 8000
```

### Tests ausführen:
```bash
pytest
```

---

## 🚢 Deployment auf IONOS VPS M+

1. **DNS-Eintrag setzen:** A-Record von `synapsemesh.dev` auf die Server-IP zeigen lassen.
2. **Repository auf VPS klonen:**
   ```bash
   git clone https://github.com/<org>/synapse-mesh.git /opt/synapse-mesh
   cd /opt/synapse-mesh
   ```
3. **Deploy-Skript ausführen:**
   ```bash
   ./deploy.sh
   ```
   Caddy konfiguriert automatisch SSL-Zertifikate (HTTPS) via Let's Encrypt.

---

## 📡 API & Schnittstellen

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/` | `GET` | Systemübersicht & Einstiegspunkt |
| `/health` | `GET` | Health Check & Status |
| `/.well-known/mcp.json` | `GET` | Discovery Manifest für MCP-Clients |
| `/.well-known/agent.json` | `GET` | Discovery Manifest für A2A / ADK |
| `/mcp` | `POST` / `GET` | MCP Streamable HTTP JSON-RPC 2.0 |
| `/api/v1/recipes/search` | `POST` | Suche nach verifizierten Lösungen |
| `/api/v1/recipes/submit` | `POST` | Einreichung neuer Rezepte |
| `/docs` | `GET` | Interaktive OpenAPI 3.1 Dokumentation (Swagger) |
