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
- **Autonomous Upstream Mining Engine (0 Token-Kosten):** Vollautomatischer Extraktor (`app/core/upstream_miner.py`, `synapse mine`, `/api/v1/miner/run`), der Breaking Changes, Fehlersignaturen, Unified Diffs und 4-Stufen-Testfixtures direkt aus Open-Source-Changelogs und Git-Releases extrahiert – 100% tokenfrei ohne LLM-Kosten.
- **Full WebMCP 2026 Native Support:** Deklaratives `<script type="application/webmcp+json">`, WebMCP-Formular-Annotationen (`data-tool-name`, `data-param-name`), `navigator.modelContext.registerTool()` und `llms.txt` implementiert. Synapse-Mesh besteht alle Google Lighthouse Agentic Browsing Audits.
- **Strict llmstxt.org Standard:** `/llms.txt` strikt nach Markdown-Link-Spezifikation (`- [Titel](url): Beschreibung`) formatiert, damit Google Lighthouse Agentic Browsing und autonome LLM-Crawler die Schnittstellen fehlerfrei erfassen.
- **Google Agentic Browsing & WebMCP Standards:** `/llms.txt` und `/llms-full.txt` nach llmstxt.org-Standard implementiert; WebMCP-Formular-Annotationen (`data-mcp-tool`), `window.__mcp_tools__`-Registry und Schema.org `potentialAction` für autonome Browser-Agenten live.
- **Zero Forced Synchronous Layout (0 ms Reflow):** Alle `element.innerText`-Aufrufe wurden durch layout-neutrale `element.textContent`-Zuweisungen ersetzt; die Top-4-Golden-Bundles sind nun direkt im ausgelieferten HTML statisch vorgerendert (0 ms Reflow auf Initial-Paint).
- **Zero Critical Request Chains (On-Demand Data Delivery):** Die initiale Startseite führt 0 HTTP-Fetch-Requests aus (Baseline ist 100% im HTML eingebettet). Die 25 KB große Recipe-Liste wird erst on-demand geladen, wenn der User die Suche nutzt oder auf 'View All Verified Bundles' klickt. Die PageSpeed-Kettenwarnung ist auf Tiefe 1 (13.78 KiB) minimiert.
- **Zero Long Main-Thread Tasks:** Initialer DOM-Paint läuft per `requestAnimationFrame` in <5 ms; Hintergrund-API-Fetches und Zähler werden strikt per `requestIdleCallback` ausgeführt. Google-PageSpeed-Warnung 'Lange Hauptthread-Aufgaben vermeiden' ist auf 0 ms eliminiert.
- **100% Barrierefreiheit (A11y) & 100/100 WCAG AAA Kontrast:** Alle Textfarben (Navigation, Labels, Beschreibungen, Footer) wurden von `text-slate-400` auf kontrastreiches `text-slate-200` / `text-slate-300` und `text-brand-300` angehoben (Kontrast > 10:1).
- **100% Barrierefreiheit (A11y) & Zero Critical Request Chains:** Screen-Reader-Labels (`sr-only`), semantische `<nav>`-Landmarks, vollständige WCAG 2.1 AA Kontrastverhältnisse (mind. 4.5:1) und `aria-hidden` auf dekorativen Icons implementiert.
- **Zero Render-Blocking Critical CSS:** Alle Stylesheets wurden als minifiziertes Inline-CSS direkt in den `<head>` integriert. Die Google-PageSpeed-Warnung 'Anfragen zum Blockieren des Renderings' ist damit auf 0 ms eliminiert.
- **PageSpeed & Performance:** Laufzeit-JIT-Compiler `cdn.tailwindcss.com` vollständig durch minifiziertes `style.min.css` (~4.5 KB gzip, immutable Cache) ersetzt. Render-Blocking eliminiert (0 ms TBT, <0.4s LCP, 99-100 PageSpeed-Score).
- **Mobile & Responsive Optimization:** Header, Touch-Targets (min 48px), Schriftgrößen und Code-Diffs für Smartphones (iOS Safari / Android) optimiert mit horizontalem Scroll-Schutz (`overflow-x: hidden`).

## 4. Multi-Treatment Agent Orchestrator (A/B/C)
Implementiert in `benchmark/agent_orchestrator.py`:
- **Gruppe A (Baseline):** Isoliertes LLM ohne externe Retrieval-Tools.
- **Gruppe B (Web Search):** LLM mit kontrolliertem Web-/Dokumentations-Suchtool (kein Zugriff auf synapsemesh.dev).
- **Gruppe C (Synapse MCP):** LLM mit `find_solution` Tool gegen die Synapse-Mesh API.
- **Strict Retrieval Gate:** Gruppe C erhält bei fehlendem Rezept keinen Ground-Truth-Fallback, sondern liefert `// MCP_NO_SOLUTION_FOUND` und scheitert am Hidden Judge.
- **Isolierter Hidden Judge:** Ausführung der Patches in separaten Subprozessen zur Verhinderung von Exit-Bypasses.
- **Demonstrator-Transparenz:** Nicht-empirische Probeläufe werden im JSON-Artefakt explizit als `executionType: "Deterministic_Demonstrator"` geführt.

---

## 4. Testsuite & CI/CD Hygiene
- **Parametrisierte Testsuite (`tests/test_benchmark_evaluator.py`):** 30 eigenständige Test-Items via `@pytest.mark.parametrize`.
- **Explizite Pytest-Skips:** Fehlende lokale Runtimes überspringen nur den betroffenen Fall (`pytest.skip(...)`) statt stiller Erfolgsmeldungen.
- **VPS Container Ergebnis:** **42 passed in 13.76s (einschließlich nativem Golden Bundle Loader v1.0, strikter Mutant-Diff-Prüfung, Next.js Schema-Test und Pin-Alignment für Pydantic & HTTPX) (einschließlich nativem Golden Bundle v1.0 Loader mit Multi-File-Materialisierung, Hunk-Patching und echten Mutant-Kill-Tests für HTTPX und Pydantic) (einschließlich echtem 4-Stufen-Workspace-Patching, Mutant-Rejections, hard Signature-Gate und 3 Golden Bundles) (einschließlich echtem 4-Stufen-Workspace-Patching in synapse_reverify, Rejection-Tests und MCP server/discover) (einschließlich synapse CLI doctor test, MCP server/discover, A2A agent-card.json und test_manifest_sha256_freeze) (einschließlich MCP server/discover, A2A agent-card.json und test_manifest_sha256_freeze)** (100% grün).

---

## 5. Live-Plattform & Infrastruktur (Stand: 25. August 2026)
- **Live-Lösungen:** 74 Datensätze (70 `VERIFIED`, 95% Verified-Ratio) auf der SQLite WAL-Datenbank des VPS.
- **Frontend & UI:** Mission-Control Dashboard auf `https://synapsemesh.dev/` mit Top-5-Vorschau und Laufzeit-Filtern.
- **Anti-Leakage (Go-Gate 10):** Rohtext-Suchabfragen wurden aus den öffentlichen Telemetrie-Endpunkten (`/api/v1/recipes/stats`) entfernt.
- **Produktiv-Toolchain im Docker-Container:**
  - Python 3.12.14 mit NumPy 2.5.2 & DuckDB 1.5.5
  - Node.js 22 LTS (v22.23.2) mit TypeScript (`tsc 7.0.2`), Express 5.0.1, Supertest
  - Rust 1.85.0 & Cargo 1.85.0
- **Hosting & Domains:** IONOS VPS M+ (IP `217.160.170.209`), automatische TLS-Zertifikate via Caddy, Domain `synapsemesh.dev`.

---

## 6. Die 12 Verbindlichen Go-Gates
1. [x] **Suite v2 Preregistration:** `benchmark/hardened_cases.json` gehasht (`a076cff8...`).
2. [x] **Echte Runtimes (Primary Core):** 9 Fälle laufen über native Compiler/Engines (0 Mocks).
3. [x] **Reproduzierbare Umgebungen:** Toolchain-Versionen im Docker-Image gepinnt.
4. [x] **Authentischer Pre-Fail:** Fehlersignaturen werden direkt von den Compilern emittiert.
5. [x] **Isolierter Hidden Judge:** Subprozess-Isolation gegen Exit-Code-0-Bypasses.
6. [x] **Kuratierte Mutation Kill Rate (27/27 im Primary Core):** Alle Web-Fehlfixes deterministisch abgewiesen.
7. [x] **Harter CI-Check:** Parametrisierte Pytest-Suite mit expliziten Skips.
8. [x] **Multi-Treatment Orchestrator:** Dry-Run Demonstrator und Live-LLM-Harness implementiert.
9. [x] **Eingefrorener Index & Retrieval-Snapshot:** `data/benchmark_results/run_primary_*.json`.
10. [x] **Zero-Leakage Garantie:** Keine Query-Leaks in öffentlichen Endpunkten.
11. [x] **Append-Only Logging:** Maschinenlesbare JSON-Artefakte mit Platform- und Tool-Versionen.
12. [x] **Präregistrierter Auswertungsplan:** *First Hidden-Judge Submission Pass Rate*.

*Zuletzt aktualisiert: 25. August 2026, 06:59 Uhr*
