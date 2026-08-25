# Empirical Benchmark Specification: Suite v1 & Suite v2 (2024–2026)

> **Ground Truth & Scientific Benchmark Registry**  
> *Kuratiert durch ChatGPT (Board of Advisors) und auditiert durch Grok (Red Team).*

---

## 1. Versionierung & Suite-Differenzen (Audit Trail)

| Fall-ID | Suite v1 (Entwurf / Konzeption) | Suite v2 (Gehärtetes & Kompiliertes Orakel) | Typ / Klassifikation | Echte Runtime / Toolchain |
|---|---|---|---|---|
| **P1** | NumPy 2.0 ABI / Pandas C-Extension | NumPy 2.0 Removal of Deprecated Aliases (`np.NAN`, `np.bool8`, `np.core`) | Breaking Change | Python 3.12 + NumPy 2.5.2 (C-Extension) |
| **P2** | HTTPX 0.28 `Client(app=...)` removal | HTTPX 0.28 `ASGITransport` & Starlette Route Test | Breaking Change | Python 3.12 + HTTPX 0.28.1 + Starlette 0.37.2 |
| **P3** | pip 24.1 / OmegaConf Hashed Index | Python 3.12 `datetime.utcnow()` Deprecation in favor of UTC-aware objects | Syntax Deprecation | Python 3.12 (`-W error::DeprecationWarning`) |
| **N1** | Node 22 Import Attributes (`assert` -> `with`) | Node 22 Import Attributes (`with { type: 'json' }`) | Breaking Syntax | Node.js 22 LTS (V8 12.4 Engine) |
| **N2** | TypeScript 5.6 Iterator Semantics | TypeScript 5.6 Strict Map Lookup (`--strict --noUncheckedIndexedAccess`) | Type Breaking | TypeScript 5.6+ Compiler (`tsc`) |
| **N3** | Express 5.1 Wildcard Routing | Express 5.0.1 / path-to-regexp v8 Brace Wildcard (`/{*splat}`) | Breaking Routing | Node.js 22 + Express 5.0.1 + SuperTest |
| **R1** | Cargo 1.80 `check-cfg` | Cargo 1.80 `cargo::rustc-check-cfg` Invariant Declaration in `build.rs` | Breaking Compiler Lint | Rust 1.93 Compiler (`rustc` / `cargo`) |
| **R2** | Cargo.lock v4 vs MSRV 1.77.2 | Cargo Lockfile v4 Format and Checksum Verification (`cargo check --locked`) | Toolchain Breaking | Cargo 1.84+ (`cargo check --locked`) |
| **R3** | Rust 1.96 Wasm Linker | Rust Edition 2024 `gen` Keyword Reservation (`rustc --edition 2024`) | Breaking Language Keyword | Rust 1.93 Compiler (`rustc --edition 2024`) |
| **S1** | DuckDB 0.10 Substring Casting | DuckDB 0.10 Removal of Implicit Type Casting (`substring(INTEGER)`) | Breaking SQL Engine | Python 3.12 + DuckDB 0.10.0 (C++ Engine) |
| **S2** | MySQL 8.4 `mysql_native_password` | MySQL 8.4 Deprecation & Removal of `mysql_native_password` -> `caching_sha2_password` | Security Breaking | SQL Engine Parser & Auth Invariant |
| **S3** | PostgreSQL 17 `pg_dump` | SQLite 3.45+ JSONB Native Representation Migration (`jsonb()` -> `json()`) | Engine Storage Format | SQLite 3.45+ Engine |
| **D1** | Docker Engine 26 `ContainerConfig` | Docker Compose V2 Top-Level `version` Key Deprecation | Specification Change | Docker Compose V2 Parser |
| **D2** | Docker Engine API 1.44 | Docker BuildKit Persistent Package Cache Mounts (`--mount=type=cache`) | Build Performance | Dockerfile / BuildKit Syntax Engine |
| **D3** | Ubuntu 24.04 PEP 668 | Ubuntu 24.04 / Debian 12 PEP 668 `externally-managed-environment` | Packaging Policy | Ubuntu 24.04 System `pip` |

---

## 2. Die 12 Verbindlichen Go-Gates für den A/B/C-Agentenlauf

Bevor der empirische Vergleichslauf mit LLM-Tokens startet, müssen alle 12 Tore nachweisbar geschlossen sein:

1. **Suite v2 Preregistration & Freeze:** `benchmark/hardened_cases.json` ist mit SHA-256 gehasht und unveränderlich.
2. **Echte Runtimes (0 Mocks):** Alle 15 Fälle laufen über echte Compiler/Engines (`tsc`, `rustc`, `cargo`, `duckdb`, `numpy 2.0`, `node 22`, `pip`).
3. **Reproduzierbare Umgebungen:** Alle Docker-Images, Python-Wheels und Toolchains sind mit fixierten Versionen gepinnt.
4. **Authentischer Pre-Fail:** Die Fehlersignatur im unreparierten Zustand wird direkt vom jeweiligen Tool erzeugt (kein `sys.stderr.write`).
5. **Isolierter Hidden Judge:** Testausführung erfolgt in einem getrennten Prozess mit striktem Timeouts- und Assertion-Guard.
6. **Kuratierte Mutation Kill Rate (45/45):** Mindestens 3 typische Web-Fehlfixes pro Fall werden deterministisch abgelehnt.
7. **Harter Exit bei Runtime-Mangel:** Fehlende Binaries führen zu sofortigem CI-Fehlschlag (`UNVERIFIED` / Exit Code != 0).
8. **Multi-Treatment Orchestrator:** Kontrollierte Ausführung von Gruppe A (Baseline), Gruppe B (Web) und Gruppe C (Synapse MCP).
9. **Eingefrorener Index & Retrieval-Snapshot:** Die Synapse-Mesh-Datenbank und der Web-Suchindex sind vor dem Lauf statisch fixiert.
10. **Zero-Leakage Garantie:** Keine Query-Historie in öffentlichen Telemetrie-Endpunkten; Gruppe B hat keinen Zugriff auf lokale Benchmark-Lösungen.
11. **Append-Only Logging:** Alle Prompts, Tool-Calls, generierten Patches, Compiler-Outputs und Token-Zähler werden unveränderlich protokolliert.
12. **Präregistrierter Auswertungsplan:** Primärmetrik ist *First Hidden-Judge Submission Pass Rate*.
