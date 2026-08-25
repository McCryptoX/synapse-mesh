# Projekt-Gedächtnis & Vision: Synapse-Mesh (Exocortex)

> **Status:** Live-Produktion & Wissenschaftliche Benchmark-Vorbereitung (Suite v2)  
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

## 2. Der Gefrorene Benchmark-Kern: `Suite v2-runtime-9`
Kuratiert durch ChatGPT (Board of Advisors) und auditiert durch Grok (Red Team).  
**Manifest SHA-256:** `a076cff87dcf201aaeb6bf7931f1d05ea77f0da64a4a6a95a166067071ef018a`

### Die 9 freigegebenen Primär-Fälle (0 Mocks, echte Compiler/Engines):
1. **P1 (NumPy 2.0):** API-Alias-Entfernung (`np.NAN`) unter NumPy 2.5.2 C-Extension (1106 ms).
2. **P2 (HTTPX 0.28):** Starlette ASGI Transport Loopback (`httpx>=0.28.1`, `starlette>=0.37.2`) (1214 ms).
3. **P3 (Python 3.12):** `datetime.utcnow()` unter `-W error::DeprecationWarning` (85 ms).
4. **N1 (Node 22):** V8 Import Attributes (`with { type: 'json' }`) (190 ms).
5. **N2 (TypeScript):** `tsc --strict --noUncheckedIndexedAccess` Optional Map Lookups (2579 ms).
6. **N3 (Express 5.0.1):** path-to-regexp v8 Brace Wildcard Routing (`/{*splat}`) (985 ms).
7. **R1 (Cargo 1.80):** `build.rs` `cargo::rustc-check-cfg` deklarativer Cargo-Workspace (2522 ms).
8. **R3 (Rust 2024):** `rustc --edition 2024` Keyword Reservation `gen` (589 ms).
9. **S1 (DuckDB 0.10):** C++ Engine `duckdb.BinderException` bei Substring (723 ms).

### Ergänzende semantische Orakel (6 Fälle, separat ausgewiesen):
- **R2:** Cargo Lockfile v4 Format Invariant (`toolchain_syntax_oracle`).
- **S2:** MySQL 8.4 `caching_sha2_password` Invariant (`static_semantic_oracle`).
- **S3:** SQLite 3.45+ JSONB BLOB Native Representation (`static_semantic_oracle`).
- **D1:** Compose V2 Top-Level `version` Deprecation (`static_semantic_oracle`).
- **D2:** BuildKit Persistent Cache Mount Spec (`static_semantic_oracle`).
- **D3:** Ubuntu 24.04 PEP 668 Environment Policy (`static_semantic_oracle`).

---

## 3. Die Neue Positionierung: Verified Compatibility Layer
- **Top-10 Verified Golden Standards Live:** Die kuratierte Vertrauensbasis umfasst nun exakt 10 formal verifizierte Golden Bundles (HTTPX 0.28, Next.js 15, Pydantic v2, FastAPI 0.115, Python 3.12 UTC, SQLAlchemy 2.0, NumPy 2.0, Express 5.0, TypeScript 5.6, DuckDB 0.10) mit 100% 4-Stufen-Pass und 2/2 Mutant-Kills.
- **Public Live-Benchmark Dashboard (`/benchmark`):** Öffentliche Auswertung der A/B/C-Behandlungen (Gruppe A: Vanilla LLM mit 83.3% Fehlerquote vs. Gruppe B: Web Search mit 75% vs. Gruppe C: Synapse-Mesh MCP mit 100% Pass-Rate).
- **Dual Package Distribution Ready:** Node.js `@synapse-mesh/verify` in `packages/verify/` und Python `synapse-mesh` Wheel via `scripts/publish_packages.sh` bereitgestellt.
- **Codex Compatibility Suite & Standalone Verifier:** Standalone `@synapse-mesh/verify` CLI & Node.js 18-22 Engine (`packages/verify/`), GitHub Action (`.github/actions/verify-compatibility/`), Node-Matrix-Workflow (`.github/workflows/compatibility-verifier-node-matrix.yml`) und JSON-Schema v1 (`schemas/compatibility_bundle_v1.json`) integriert.
- **Hardened Upstream Mining & Golden Isolation:** `bundles/golden/` ist strikt schreibgeschützt und bleibt exklusiv für formal verifizierte, SHA-256-gefrorene Standards. Autonome Miner-Ergebnisse werden als `draft_*.json` mit Status `DRAFT`/`UNVERIFIED` in `bundles/drafts/` isoliert und erst nach echtem Durchlauf von `verify_golden_bundle()` validiert. `/api/v1/miner/run` ist strikt mit `X-Synapse-Admin-Key` abgesichert (keine unautorisierten Hintergrund-Schreibzugriffe).
- **Full Official Google Chrome WebMCP Standard (`developer.chrome.com/docs/ai/webmcp`):**
  - **Declarative WebMCP API:** HTML5-Formular-Annotationen (`toolname="find_solution"`, `tooldescription="..."`, `toolautosubmit`, `toolparamdescription="..."`, `required`), die KI-Agenten im Chromium-Browser autonom erkennen und ausführen können.
  - **Agent Event Lifecycle:** `submit`-Event-Handling mit Prüfung auf `e.agentInvoked` und direkter Übergabe über `e.respondWith(promise)`.
  - **Imperative WebMCP API:** Duale Registrierung über die offizielle Schnittstelle `document.modelContext.registerTool(...)` sowie `navigator.modelContext.registerTool(...)` mit striktem JSON-Schema.
  - **CSS Agent Feedback:** Unterstützung für Chrome WebMCP-Pseudoklassen `form:tool-form-active` und `input:tool-submit-active`.
- **llms.txt & llms-full.txt Standard:**
  - `https://synapsemesh.dev/llms.txt` und `https://synapsemesh.dev/llms-full.txt` (RFC-konforme LLM-Dokumentations-Standards) mit deterministischen Maschinenlese-Routen.
  - Verweist ausschließlich auf das öffentliche MCP-Gateway `https://github.com/McCryptoX/synapse-mesh-mcp` (Zero-Leakage für das private Kern-Repository).

---

## 4. Live-Plattform & Infrastruktur (Stand: 25. August 2026)
- **Live-Lösungen:** 96 Datensätze (81 `VERIFIED`, 84.4% Verified-Ratio) auf der SQLite WAL-Datenbank des VPS.
- **Frontend & UI:** Mission-Control Dashboard auf `https://synapsemesh.dev/` mit Top-5-Vorschau, geräumiger Suchleiste (`/`-Shortcut), 100% balancierter HTML5-Struktur und englischer Benutzeroberfläche.
- **Anti-Leakage (Go-Gate 10):** Rohtext-Suchabfragen wurden aus den öffentlichen Telemetrie-Endpunkten (`/api/v1/recipes/stats`) entfernt.
- **Produktiv-Toolchain im Docker-Container:**
  - Python 3.12.14 mit NumPy 2.5.2 & DuckDB 1.5.5
  - Node.js 22 LTS (v22.23.2) mit TypeScript (`tsc 7.0.2`), Express 5.0.1, Supertest
  - Rust 1.85.0 & Cargo 1.85.0
- **Hosting & Domains:** IONOS VPS M+ (IP `217.160.170.209`), automatische TLS-Zertifikate via Caddy, Domain `synapsemesh.dev`.

---

## 5. Die 12 Verbindlichen Go-Gates
1. [x] **Suite v2 Preregistration:** `benchmark/hardened_cases.json` gehasht (`a076cff8...`).
2. [x] **Echte Runtimes (Primary Core):** 9 Fälle laufen über native Compiler/Engines (0 Mocks).
3. [x] **Reproduzierbare Umgebungen:** Toolchain-Versionen im Docker-Image gepinnt.
4. [x] **Authentischer Pre-Fail:** Fehlersignaturen werden direkt von den Compilern emittiert.
5. [x] **Isolierter Hidden Judge:** Subprozess-Isolation gegen Exit-Code-0-Bypasses.
6. [x] **Kuratierte Mutation Kill Rate (27/27 im Primary Core):** Alle Web-Fehlfixes deterministisch abgewiesen.
7. [x] **Harter CI-Check:** Parametrisierte Pytest-Suite mit expliziten Skips (65/65 Tests bestanden).
8. [x] **Multi-Treatment Orchestrator:** Dry-Run Demonstrator und Live-LLM-Harness implementiert.
9. [x] **Eingefrorener Index & Retrieval-Snapshot:** `data/benchmark_results/run_primary_*.json`.
10. [x] **Zero-Leakage Garantie:** Keine Query-Leaks in öffentlichen Endpunkten.
11. [x] **Append-Only Logging:** Maschinenlesbare JSON-Artefakte mit Platform- und Tool-Versionen.
12. [x] **Präregistrierter Auswertungsplan:** *First Hidden-Judge Submission Pass Rate*.

---

## 6. Webserver-Datenschutz & Rechtssicherheit
- **Zero-Log & IP-Anonymization Webserver-Härtung:**
  - Caddy Edge Reverse-Proxy läuft mit `log { output discard }` (keine Speicherung von Zugriffs-Logfiles oder Client-IPs auf der Festplatte).
  - Upstream-Proxy-Header werden auf Loopback (`127.0.0.1`) anonymisiert.
  - Python Backend (Uvicorn) läuft mit `--no-access-log` (kein Logging von Client-Verbindungsmetadaten).
  - Datenschutzerklärung (`/datenschutz`) und Impressum (`/impressum`) vollständig nach DSGVO / § 5 DDG mit technischen und organisatorischen Maßnahmen (TOMs) synchronisiert.

---

## 7. Private Operations & Pipeline Observatory (`/ops`)
- **Passwortschutz & In-Browser-Passwortänderung:** Das Dashboard unter `https://synapsemesh.dev/ops` ist durch ein sicheres Passwort-Gate geschützt (Initial: `synapse-ops-2026`). Über den Button `🔑 Change Password` kann das Passwort direkt im Browser geändert werden; es wird persistent als gesalzener SHA-256-Hash in der `system_config`-Tabelle der SQLite-Datenbank hinterlegt.
- **Nahtloser Direktzugriff & Sessions:** Schneller Zugriff ist via URL-Key `https://synapsemesh.dev/ops?key=<passwort>` oder Login-Maske (mit sicherem 30-Tage-Session-Cookie `synapse_ops_session` und Logout-Funktion) möglich.
- **Echtzeit-Transparenz:** Zeigt in Echtzeit alle registrierten Rezepte, Candidate Drafts, 4-Stage-Sandbox-Exit-Codes, Confidence Scores und Diff-Vorschauen an (`robots: noindex, nofollow`).
- **Interaktiver Sweep-Trigger:** Manueller Button `⚡ Run Verification Sweep` oben rechts stößt die 4-Stufen-Sandbox-Prüfung über alle Candidate-Batches direkt im Browser an und liefert sofortiges Feedback.
- **Autonome 4-Stunden-Pipeline:** Der Worker in `app/main.py` pollt kontinuierlich alle 4 Stunden PyPI, npm, crates.io und GitHub Releases, generiert Drafts und führt sie durch die Sandbox.

---

## 8. OpenAI / ChatGPT Remote MCP Connector Kompatibilität
- **Modern Stateless Discovery Probe (`server/discover`):** Implementiert das offizielle MCP-Discovery-Schema mit `supportedVersions: ["2024-11-05", "2024-10-07", "2026-07-28"]`, `capabilities`, `serverInfo` und `_meta["io.modelcontextprotocol/serverInfo"]`.
- **Legacy & Modern Handshake (`initialize` + `tools/list`):** Automatische Protokoll-Aushandlung für ChatGPT, Claude und Cursor.
- **Dual-Transport:** Volle Unterstützung für Direct Streamable HTTP JSON-RPC 2.0 sowie Server-Sent Events (SSE) unter `https://mcp.synapsemesh.dev/mcp` und `https://synapsemesh.dev/mcp`.

---

## 9. ChatGPT Architectural Directives & Evidence Tiers (Verified Compatibility Layer)
- **Leitaxiom:** *„Synapse-Mesh soll keine weitere Coding-Wissensdatenbank sein. Es ist die verlässlichste Evidence-Schicht für autonome Coding-Agenten.“*
- **Typisierte Evidence-Stufen:**
  1. `VERIFIED_REAL_RUNTIME`: 100% verifiziert auf echten Compilern/Engines mit nativen Binaries (`numpy 2.5.2`, `sqlalchemy 2.0`, `starlette 0.37`, `node 22`, `cargo 1.85`).
  2. `VERIFIED_SYNTHETIC_AST`: Syntaktisch und strukturell validierte AST-Diffs.
  3. `COMMUNITY_SUBMITTED`: Von Entwicklern/Agenten eingereichte Repro-Lösungen.
  4. `CANDIDATE_DRAFT`: Unverifizierte Upstream-Mining-Kandidaten in der Warteschlange.
- **Search Precision & Canonical Clustering (Top 1–2):** 
  - Stopword-Filterung und strikte Paket-Token-Gewichtung (keine themenfremden Beifänge).
  - Maximale Relevanz für den Coding-Agenten: Direkte Ausgabe von `problem -> minimal_fix -> diff -> doNot -> environment -> confidence -> primary_source`.
- **Negative Evidence (`doNot`):** Dokumentiert deterministisch, welche naheliegenden Web-Workarounds und Halluzinationen in der Sandbox abgewiesen wurden.

*Zuletzt aktualisiert: 25. August 2026, 19:00 Uhr*
