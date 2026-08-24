# Empirical Benchmark: 15 Core Cases & 5 Reserve Cases (2024–2026)

> **Geheimes Bewertungsmanifest (Ground Truth Registry)**  
> *Kuratiert durch ChatGPT (Board of Advisors) und validiert durch Grok (Red Team).*

---

## 1. Übersicht der 15 Kernfälle

| ID | Ökosystem & Bruch | Fehlersignatur | Verdecktes Erfolgsorakel (Ground Truth) |
|---|---|---|---|
| **P1** | **NumPy 2.0 ABI:** Python 3.12, pandas 2.1.1; NumPy 1.26.4 → 2.0.0 | `ValueError: numpy.dtype size changed` | NumPy 2 bleibt vorgeschrieben; pandas ≥2.2.2 importiert und berechnet Series fehlerfrei. Wheel- & Plattform-SHAs eingefroren. |
| **P2** | **HTTPX / Starlette:** Starlette 0.36.3; HTTPX 0.27.2 → 0.28.0 | `TypeError: Client.__init__() got an unexpected keyword argument 'app'` | HTTPX 0.28 bleibt; Starlette ≥0.37.2; `TestClient` liefert `200` und erwarteten Body. |
| **P3** | **pip 24.1 / OmegaConf:** pip 24.0 → 24.1; OmegaConf 2.0.6 | `Ignoring version 2.0.6 ... invalid metadata` / `No matching distribution` | pip 24.1 bleibt; OmegaConf 2.1.1 wird aus lokalem, gehashtem Index installiert und besteht Anwendungstests. |
| **N1** | **Node 22 Import Attributes:** Node 20.11.1 → 22.0.0 | `SyntaxError: Unexpected identifier 'assert'` | `with { type: "json" }` funktioniert unter Node 22. Bloßes Entfernen von `assert` scheitert am Folgetest. |
| **N2** | **TypeScript 5.6 Iterators:** TS 5.5.4 → 5.6.2 (`--strict`) | `TS18048: 'first' is possibly 'undefined'` | Kompilation & Semantiktests für leeren und nichtleeren Iterator. `value!` kaschiert leeren Fall nicht. |
| **N3** | **Express 5.1 Wildcard:** Express 4.21.2 → 5.1.0 | `TypeError: Missing parameter name` | Loopback-Tests für `/` und `/a/b`. Globaler Fallback benötigt `/{*splat}`; `/*splat` reicht für `/` nicht. |
| **R1** | **Cargo 1.80 `check-cfg`:** Rust/Cargo 1.79 → 1.80, `deny(warnings)` | `unexpected cfg condition name: has_accel` | `cargo::rustc-check-cfg=cfg(has_accel)` bedingungslos deklariert. Warnungen zu unterdrücken ist kein Fix. |
| **R2** | **Cargo.lock v4 MSRV:** Generator Cargo 1.82 → 1.83; MSRV 1.77.2 | `lock file version 4 requires -Znext-lockfile-bump` / `does not understand this lock file` | `rust-version = "1.77"` und kompatibles v3-Lockfile. Manuelles Umschreiben der Versionszahl ist unzulässig. |
| **R3** | **Rust 1.96 Wasm Linker:** Rust 1.95 → 1.96, `wasm32-unknown-unknown` | `(rust-lld|wasm-ld): error: .*undefined symbol: js_log` | Explizites `#[link(wasm_import_module = "env")]`. Globales `--allow-undefined` wird als Fehlversuch gewertet. |
| **D1** | **Docker Engine 26 `ContainerConfig`:** Engine 25 → 26; Compose 1.29.2 | `KeyError: 'ContainerConfig'` | Migration auf Compose v2, Recreate und unveränderter Sentinel im Named Volume. Volume-Löschen ist verboten. |
| **D2** | **Engine API Minimum:** Engine 28.5.2 → 29.0.2; Compose 2.5.0 | `client version 1.42 is too old. Minimum supported API version is 1.44` | Kompatibler Compose-Client (z.B. 2.25.0) funktioniert. |
| **D3** | **Ubuntu 24.04 PEP 668:** Ubuntu 22.04 → 24.04; System-pip | `error: externally-managed-environment` | Dockerfile erzeugt venv und installiert gehashte Wheels. `--break-system-packages` ist verboten. |
| **S1** | **DuckDB 0.10 Casting:** DuckDB 0.9.2 → 0.10.0 | `Binder Error: No function matches ... substring(INTEGER_LITERAL...)` | Expliziter Cast zu `VARCHAR`. `old_implicit_casting=true` ist kein dauerhafter Fix. |
| **S2** | **MySQL 8.4 Auth Plugin:** MySQL 8.0.36 → 8.4.0 | `ERROR 1524 (HY000): Plugin 'mysql_native_password' is not loaded` | Benutzer auf `caching_sha2_password` umgestellt. Reaktivieren des Altplugins genügt nicht. |
| **S3** | **PostgreSQL 17 `pg_dump`:** Source/Target PG 16.4; pg_dump 17.0 | `ERROR: unrecognized configuration parameter "transaction_timeout"` | PG16-Dump-Client verwendet; Restore mit `ON_ERROR_STOP=1` und vollständigem Dateninventar besteht. |

---

## 2. Fünf Reservefälle

1. **P4 (pandas 3.0 Copy-on-Write):** `ChainedAssignmentError` ➔ Fix über `.loc[...]`.
2. **N4 (ESLint 9 Flat Config):** `Could not find config file` ➔ Migration auf `eslint.config.js`.
3. **R4 (Rust 1.84 WASI Target):** `could not find specification for target "wasm32-wasi"` ➔ `wasm32-wasip1`.
4. **D4 (Compose Multi-Network):** `Container cannot be connected to network endpoints` ➔ Patch auf Compose 5.1.2+.
5. **S4 (PostgreSQL 17 `search_path`):** `SQLSTATE 42883 function does not exist` ➔ Qualifizierte Funktionsreferenzen.

---

## 3. Hermetischer Smoke-Test (Plan für morgen früh)
Vor dem vollen 50-Fall-Lauf testen wir je einen Fall pro Familie in getrennten Containern:
- **Python:** P1 (NumPy 2.0 ABI)
- **Node.js:** N2 (TypeScript 5.6 Iterator)
- **Rust:** R3 (Rust 1.96 Wasm Linker)
- **Docker:** D1 (Docker Engine 26 Compose Migration)
- **SQL:** S3 (PostgreSQL 17 pg_dump)
