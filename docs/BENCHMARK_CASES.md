# Frozen Verification Corpus: Suite v2

`benchmark/hardened_cases.json` is a frozen fixture manifest for checking the repository's verification machinery. It is not a representative sample of all software failures and is not, by itself, a comparative evaluation of coding models.

**Manifest SHA-256:** `a076cff87dcf201aaeb6bf7931f1d05ea77f0da64a4a6a95a166067071ef018a`

## 1. Historical primary runtime set: `Suite v2-runtime-9`

The frozen manifest contains exactly nine preregistered cases marked `primary_runtime_core` and `compiler_runtime`. This describes the case set, not a currently valid public score.

| ID | Declared dependency scope | Compatibility claim under test |
|---|---|---|
| `P1_NUMPY_2_0_ABI_REMOVALS` | `numpy>=2.0.0` | Removed NumPy aliases such as `np.NAN` |
| `P2_HTTPX_0_28_STARLETTE` | `httpx>=0.28.0` | Replacement of the removed `Client(app=...)` path with an ASGI transport |
| `P3_PYTHON_312_DATETIME_UTC_AWARE` | `python>=3.12.0` | Replacement of deprecated `datetime.utcnow()` with a timezone-aware UTC value |
| `N1_NODE_22_IMPORT_ATTRIBUTES` | `node>=22.0.0` | JSON import attributes using `with { type: "json" }` |
| `N2_TYPESCRIPT_56_STRICT_MAP_LOOKUP` | `typescript>=5.6.0` | Safe handling of optional `Map.get()` results under strict compiler checks |
| `N3_EXPRESS_5_1_WILDCARD` | `express>=5.0.0` | Express 5 wildcard route syntax under the relevant path matcher |
| `R1_CARGO_1_80_CHECK_CFG` | `rustc>=1.80.0` | Declaration of custom `cfg` names for Cargo/rustc checks |
| `R3_RUST_EDITION_2024_GEN_KEYWORD` | `rustc>=1.85.0` | Migration from the Rust 2024 reserved `gen` identifier |
| `S1_DUCKDB_0_10_IMPLICIT_CASTING` | `duckdb>=0.10.0` | Explicit casting after removal of DuckDB's implicit substring conversion |

For each case, the checked-in evaluator requires a non-zero pre-fail, declared signature match, zero-exit post-pass for the supplied valid solution, and rejection of every supplied incorrect mutation. The current case manifest supplies at least three mutations per case.

The former website `9/9` statement is withdrawn. The hardened production-image rerun now executes the Rust fixtures after a narrowly marked compiler/linker file-size allowance was added; targeted R1, R2, and R3 checks pass under the outer container limits. The frozen TypeScript case `N2_TYPESCRIPT_56_STRICT_MAP_LOOKUP` still does not establish its declared fingerprint: the real `tsc` invocation reports `TS2583` because the fixture does not select a library containing `Map`, so compilation stops before the expected `TS2322` strict-nullability error. A corrected suite requires a new version and digest rather than an in-place manifest edit. Until every required real-toolchain case passes, the numeric result is withheld. A skip or infrastructure workaround is never a pass.

## 2. Supplemental oracles

Six additional manifest entries are intentionally excluded from any future corrected primary-runtime denominator:

| ID | Declared dependency scope | Mode | Claim under test |
|---|---|---|---|
| `R2_CARGO_LOCKFILE_V4_FORMAT` | `cargo>=1.84.0` | `toolchain_syntax_oracle` | Cargo lockfile v4 format |
| `S2_MYSQL_8_4_AUTH_PLUGIN` | `mysql-server>=8.4.0` | `static_semantic_oracle` | MySQL authentication-plugin migration invariant |
| `S3_SQLITE_345_JSONB_FUNCTIONS` | `sqlite3>=3.45.0` | `static_semantic_oracle` | SQLite JSONB representation invariant |
| `D1_DOCKER_COMPOSE_V2_SPEC` | `docker-compose>=2.20.0` | `static_semantic_oracle` | Compose v2 top-level `version` deprecation |
| `D2_DOCKER_BUILDKIT_CACHE_MOUNTS` | `docker-buildx>=0.12.0` | `static_semantic_oracle` | BuildKit cache-mount syntax |
| `D3_UBUNTU_24_04_PEP668` | `python3-pip>=24.0` | `static_semantic_oracle` | PEP 668 externally managed environment policy |

These cases exercise syntax, configuration, or semantic checks. They must be reported separately from the primary real-runtime denominator and must not be presented as equivalent live dependency execution.

## 3. What the fixture gate tests

```text
frozen case
   |
   +-- run pre-patch reproduction
   |       `-- require non-zero exit and fingerprint match
   |
   +-- place the manifest's valid implementation in the target workspace
   |       `-- require the declared post-patch suite to pass
   |
   `-- place each supplied incorrect implementation in a clean workspace
           `-- require every mutation to fail the same suite
```

This gate tests whether the checked-in case, valid solution, and negative mutations behave as declared in the available toolchain. The benchmark evaluator uses temporary process-limited workspaces. It is not a hostile-code sandbox, and the cases are repository-owned fixtures.

The golden-bundle re-verifier has an additional strict unified-diff application step. Do not infer that every benchmark manifest field is itself a promoted golden bundle or carries an isolation attestation.

## 4. Reproduction

From the repository root:

```sh
shasum -a 256 benchmark/hardened_cases.json
pytest -q tests/test_benchmark_evaluator.py
```

A valid report records:

- the manifest hash;
- case IDs and tier;
- observed runtime, compiler, and dependency versions;
- pass, fail, unverified, and skip outcomes separately;
- pre-fail, fingerprint, post-pass, and mutation results;
- the exact source revision and execution environment.

Timing from a single local run is diagnostic telemetry, not a general performance claim.

## 5. Change control

Do not edit the frozen manifest in place and continue using the same suite name or hash. A changed case set requires a new version, a new digest, a documented rationale, and results reported separately from Suite v2.

The frozen fixture gate must also remain separate from any future model comparison. A comparative experiment requires its own preregistration, prompts, model snapshots, tool policies, budgets, hidden judge, and raw artifacts as specified in [BENCHMARK_METHODOLOGY.md](BENCHMARK_METHODOLOGY.md).
