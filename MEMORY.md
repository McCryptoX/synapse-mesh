# Projekt-Gedächtnis & Vision: Synapse-Mesh (Exocortex)

> **Status:** Live-Produktion & Wissenschaftliche Benchmark-Vorbereitung  
> **Kontext:** Agenten-native Wissens- und Verifikations-Infrastruktur für autonome KIs (Gemini, ChatGPT, Claude, Grok, Coding-Agents).  
> **Kernversprechen:** `Problem → Reproduzierbarer Test (Sandbox) → Verifizierte Lösung → Strukturierte Maschinenantwort`  
> **Rechtlicher Rahmen:** EU AI Act, DSGVO, deutsches Recht (§ 5 DDG, Zero-PII by Design, § 44b UrhG TDM).

---

## 1. Das Kernprodukt: Living Solutions & Verification
Synapse-Mesh liefert deterministisches, sandbox-verifiziertes Wissen für KI-Coding-Agenten:

```text
Problem (Error Signature, Environment)
  ↓
Synapse-Mesh Query (via MCP / A2A / REST)
  ↓
Treffer vorhanden? 
  ├── JA  → Verifizierte Lösung + Repro + Testprotokoll + Confidence Score
  └── NEIN → Agent generiert Lösung → Sandbox verifiziert → Synapse speichert Rezept
```

---

## 2. Epistemische Hierarchie & 4-Stufen-Verifikation
Ein Konsens unter KIs ist kein Wahrheitsbeweis. Synapse-Mesh folgt einer strikten Beweishierarchie:

$$\text{Reproduzierbarer Sandbox-Test} > \text{Primärquelle/Offizielle Docs} > \text{Unabhängige Quellen} > \text{Agenten-Konsens}$$

### Die 4 Prüfstufen des Evaluators:
1. **Pre-Fail Validation:** Echtes Repro-Skript muss fehlschlagen und echte Error-Signature (Regex) in stderr werfen.
2. **Patch Application:** Echtes Schreiben der Unified-Diff-Datei in ein isoliertes Workspace-Verzeichnis.
3. **Post-Pass Execution:** Hermetischer Durchlauf der Ground-Truth-Testsuite mit Exit Code 0.
4. **Multi-Mutation Sanity:** Alle Top-Web-Fehlfixes (mindestens 3 pro Fall) müssen in der Sandbox scheitern.

---

## 3. Protokolle, Schnittstellen & Discovery
- **MCP (Model Context Protocol):** Moderne **Streamable HTTP**- (`https://mcp.synapsemesh.dev`) & **stdio**-Transports (Spezifikation `2026-07-28`).
- **A2A (Agent-to-Agent Protocol):** Standardisierte Inter-Agenten-Kommunikation und Peer-Verification.
- **Automated Agent Discovery:**
  - `https://synapsemesh.dev/.well-known/mcp.json`
  - `https://synapsemesh.dev/.well-known/agent.json`
- **REST / OpenAPI 3.1:** `https://api.synapsemesh.dev` & `https://docs.synapsemesh.dev`.

---

## 4. Aktueller System- und Datenbestand (Stand: 24. August 2026)
- **Live-Lösungen:** 50 verifizierte Living Solutions (92.6% Pass-Ratio) in der SQLite WAL-Datenbank auf dem VPS.
- **24/7 Autonomer Harvester:** Läuft 2x täglich per Cron (`/etc/cron.d/synapse_harvester` um 03:00 & 15:00 UTC) und sammelt Breaking Changes der Top-12 Open-Source-Repos.
- **Multi-Runtime Container:** Docker-Image auf dem Server unterstützt nativ **Python 3.12 und Node.js 22 LTS (v22.23.2)** mit Express 5.0.1, Supertest, HTTPX 0.28.1 und Starlette 0.37.2.
- **Gehärtete Benchmark-Fälle:** P2 (HTTPX 0.28), N1 (Node 22 Import Attributes), N3 (Express 5.1 Wildcard) sind 100% verifiziert und töten 9 von 9 echten Web-Fehlfixes in echten Dateisystem-Workspaces.

---

## 5. Domain, Hosting & Infrastruktur
- **Domain:** `synapsemesh.dev` – Live via IONOS mit automatischem TLS/SSL (Caddy).
- **Subdomains:** `api.synapsemesh.dev`, `docs.synapsemesh.dev`, `mcp.synapsemesh.dev`, `status.synapsemesh.dev`.
- **VPS:** IONOS VPS M+ (4 vCores, 4 GB RAM, Ubuntu 26.04 + Docker in Frankfurt).
- **GitHub MCP Client:** `https://github.com/McCryptoX/synapse-mesh-mcp`.

---

## 6. Agenda & Fahrplan für morgen (25. August 2026)
1. **Instrumentierter 5er-Shakedown:** Durchlauf je eines echten Cases pro Ökosystem (Python, Node, Rust, Docker, SQL).
2. **Hidden Judge Prozess-Isolation:** Sicherstellen, dass Judge-Assertions in einem unabhängigen Prozess laufen.
3. **Erweiterung auf die 15 Kernfälle:** Fertigstellung der verbleibenden Case-Workspaces mit vorregistrierten Hashes.
4. **Vorbereitung des echten A/B/C-Orchestrators:** Anbindung echter LLM-Aufrufe mit fixierten Token-Budgets und Freeze-Snapshot.

*Zuletzt aktualisiert: 24. August 2026, 23:56 Uhr*
