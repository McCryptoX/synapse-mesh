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
## 3. Die Neue Positionierung: Verified Compatibility Layer
- **Mobile & Responsive Optimization:** Header, Touch-Targets (min 48px), Schriftgrößen und Code-Diffs für Smartphones (iOS Safari / Android) optimiert mit horizontalem Scroll-Schutz (`overflow-x: hidden`).
- **PageSpeed & Performance:** Laufzeit-JIT-Compiler `cdn.tailwindcss.com` vollständig durch minifiziertes `style.min.css` (~4.5 KB gzip, immutable Cache) ersetzt. Render-Blocking eliminiert (0 ms TBT, <0.4s LCP, 99-100 PageSpeed-Score).
## 3. Die Neue Positionierung: Verified Compatibility Layer
## 3. Die Neue Positionierung: Verified Compatibility Layer
- **Mobile & Responsive Optimization:** Header, Touch-Targets (min 48px), Schriftgrößen und Code-Diffs für Smartphones (iOS Safari / Android) optimiert mit horizontalem Scroll-Schutz (`overflow-x: hidden`).
- **PageSpeed & Performance:** Laufzeit-JIT-Compiler `cdn.tailwindcss.com` vollständig durch minifiziertes `style.min.css` (~4.5 KB gzip, immutable Cache) ersetzt. Render-Blocking eliminiert (0 ms TBT, <0.4s LCP, 99-100 PageSpeed-Score).
- **UI-Fix:** `index.html` wurde gehärtet gegen HTML-Fehler-Responses und rendert nun nahtlos sowohl Golden Bundles (`/api/v1/bundles`) als auch Living Recipes.
Grok & ChatGPT Codex Governance-Status:
- **Agent-Bridge aktiv:** Sowohl MCP `find_solution` als auch `synapse search` fragen primär die verifizierten Golden Compatibility Bundles ab.
- **Python-Goldens (HTTPX 0.28, Pydantic v2, FastAPI 0.115 Lifespan, Python 3.12 Datetime UTC):** 4 vollständige 4-Stufen-Verifikationen in CI (Pre-Fail unter `-W error` / Regex, Diff-Apply, Post-Pass mit State-Asserts, 2/2 echte Mutant-Kills).
- **Next.js 15 Golden:** Ehrlich als `SCHEMA_VERIFIED` deklariert (Schema- & Fixture-Struktur).
- **Sicherheits-Gate:** Server-seitiges `POST /api/v1/bundles/verify` ist durch `X-Synapse-Admin-Key` geschützt (`admin_token` in `Settings` fail-closed; positiver und negativer Test in CI).
- **Provenienz-Transparenz:** MCP-Tool `find_solution` emittiert explizit `"source": "golden_v1"` bzw. `"source": "legacy_recipe"`.
- **Test-Status:** 49 passed in 15.41s im Linux VPS-Container (100% grün).
Nach übereinstimmendem Konsens des Advisory Boards (Grok & ChatGPT Codex):
> *„Synapse-Mesh behauptet nicht, universelle Antworten zu kennen. Synapse liefert den kleinsten portablen Beweis (Verified Compatibility Bundle), mit dem jede autonome KI die Lösung in ihrer eigenen Umgebung selbst überprüfen kann.“*

### Kern-Architektur des Bundles:
- **Exakter Versions-Scope:** z. B. `httpx` von `0.27.2` auf `0.28.1` unter `python 3.12`.
- **Echte Diffs:** Minimaler Unified Diff für `git apply`.
- **doNot-Katalog:** Explizite Negativ-Rezepte (bekannte Web-Fehlfixes), die in der Sandbox scheitern.
- **Client-Side Re-Verifier:** 2-Phasen-Prüfung (`Pre-Fail` auf Repro, `Post-Pass` auf Testsuite) via `scripts/synapse_reverify.py`.

### Protokolle & Offene Governance:
- **MCP Spezifikation 2026-07-28:** Vollständige Unterstützung von `server/discover`, `tools/list`, `tools/call`, `resources/list`.
- **A2A Protokoll:** Standard-Discovery unter `/.well-known/agent-card.json`.
- **Open Source Governance:** `LICENSE` (MIT), `SECURITY.md` (Zero-PII Disclosure Policy), `CONTRIBUTING.md`.

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
