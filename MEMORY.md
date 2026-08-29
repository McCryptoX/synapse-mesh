# Synapse-Mesh Project Memory

> **Snapshot:** 28 August 2026, repository and live-production state after the exact-run refresh, lifecycle, archive, and daily scheduling deployment. Production state must still be verified separately after every later deployment.
> **Product:** Synapse-Mesh (Project Exocortex), a narrow compatibility evidence registry for software agents.
> **Binding guardrails:** Read [GEMINI.md](GEMINI.md) before any change.

## 1. Durable product definition

Synapse-Mesh is not a general knowledge graph and does not promise a correct answer for every software problem. It exposes machine-readable compatibility records and distinguishes evidence-qualified matches from drafts and misses.

```text
problem signature + declared environment
                |
                v
       MCP or REST retrieval
                |
       +--------+---------+
       |                  |
evidence-qualified     no qualified match
record found           or version unknown
       |                  |
scoped patch and       explicit miss;
evidence metadata      optional draft submission
```

The public service can remain online and refresh candidate drafts without an LLM. It does not autonomously rewrite, review, or deploy its own application source.

## 2. Meaning of `VERIFIED`

`VERIFIED` is reserved for the explicit `bundle-4-stage-v1` evidence contract:

1. The unpatched workspace fails on the real declared package, compiler, or engine.
2. The observed exception class and declared signature match.
3. A strict unified diff applies to that same workspace.
4. The patched workspace passes the declared test suite.
5. At least two independent mutant diffs fail that suite.

The evidence is scoped to the recorded workspace, dependency versions, runtime, and toolchain. It is not a general warranty. Missing dependencies, ambiguous pins, malformed diffs, mock substitutes, absent mutants, and unknown isolation state fail closed. A structured bundle is only a declaration: public `VERIFIED` additionally requires a separate valid run artifact under `evidence/runs/` that binds the exact bundle bytes, exact toolchains, source revision, image digest, stage outputs, mutation outcomes, and measured runner controls.

Legacy split-script checks can produce no more than `PROVISIONAL`. Public submissions are stored as `DRAFT` and are not executed by the server.

## 3. Current trust stores

### Curated bundle directory

`bundles/golden/` contains 14 curated JSON files. The directory is read-only to autonomous workers and agents. Curated location is not sufficient evidence by itself: the runtime loader validates schema, applies a conservative real-dependency provenance gate, and requires a separate valid exact-run artifact.

At this snapshot, one of the 14 curated files has a valid exact-run artifact: `bundle_httpx_028_asgi_transport_001`, scoped to Python 3.12.13 and HTTPX 0.28.1. The live service dynamically exposes that record as `VERIFIED` and the other 13 as `UNVERIFIED`; the live aggregate is `bundleCount: 14` and `evidenceQualifiedCount: 1`. The source files remain unchanged because autonomous edits to the golden directory are prohibited.

The live run audited on 28 August 2026 completed at `2026-08-28T03:42:34.080662Z`. It is bound to bundle SHA-256 `aea793c600f9037e1d7b78efb26723f8c99df28c9804d1a3a8a32c66d8d3ae81`, canonical run-artifact SHA-256 `6421d144aea6a5ef7cdf2ccf852051af0f53cec7b7a2b37a2ec43bb0cd5c42e9`, and source revision `sha256:e85d35687f26ab455d3d232447c4b1babf03925f2a719e3591ef3410743c52a5`. It recorded authentic pre-fail exit 1 with signature and exception-class matches, strict unified-diff application, post-pass exit 0, and two of two declared mutants rejected. These values are a dated production snapshot, not permanent product constants.

### Draft directory

`bundles/drafts/` contains machine-generated candidates. A draft may be useful for review, but its location, source URL, or syntactic plausibility does not make it verified. Crawled release text remains unexecuted. Autonomous workers never promote a draft into `bundles/golden/`.

### SQLite recipe store

SQLite in WAL mode stores recipe projections, drafts, evidence metadata, minimal operational telemetry, and operations-dashboard state. Startup maintenance:

- clears legacy query snippets;
- deletes telemetry older than 30 days;
- downgrades historical `VERIFIED` rows that lack the explicit evidence contract;
- synchronises curated files using the current fail-closed eligibility gate.

Live row counts are operational state, not the public trust metric. Never copy a remembered production count into product copy without a fresh aggregate check.

## 4. Implemented interfaces

- MCP JSON-RPC over HTTP at `/mcp`, with discovery through `/.well-known/mcp.json`.
- Typed REST/OpenAPI endpoints for bundle lookup, recipe search, draft submission, health, and operations.
- Additional discovery documents at `/.well-known/agent.json`, `/.well-known/agent-card.json`, `llms.txt`, and `llms-full.txt`.
- Public HTML pages for the registry, verification boundary, benchmark scope, legal notice, and privacy notice.
- A local CLI for operator-controlled lookup and re-verification of code the operator trusts.

The agent descriptors are discovery metadata. There is no implemented A2A peer-task endpoint, and documentation must not imply one.

## 5. Retrieval behaviour

Retrieval is deliberately conservative:

- schema-valid curated bundles are considered before legacy database records;
- records advertised as verified require both relational status and the explicit evidence-contract marker;
- signature matching includes an exception-class gate;
- declared package versions must match; invalid or unknown version information does not silently pass;
- unsupported or weak matches return an explicit no-match response.

A canonical source link supports provenance but does not replace runtime evidence.

## 6. Autonomous maintenance

The FastAPI lifespan starts one logical hourly worker. Production intentionally runs one uvicorn process because legacy SSE queues are process-local; the file lock still prevents duplicate autonomous cycles after overlap or restart.

The hourly discovery cycle can run without model calls:

1. fetch release metadata from configured upstream registries and feeds;
2. normalise and deduplicate allowlisted package candidates;
3. synthesise deterministic compatibility drafts;
4. keep remote and crawled content unexecuted;
5. write all autonomous files to `bundles/drafts/`.

Separately, a host systemd timer runs an exact bounded target allowlist daily at 03:17 UTC with up to 30 minutes of randomized delay. It currently contains only the repository-owned HTTPX 0.28.1 fixture. The path uses no LLM, publishes nothing on any infrastructure or evidence-stage failure, and cannot write to `bundles/golden/`.

This is autonomous draft maintenance and bounded refresh of pre-approved evidence, not autonomous software development. Human or separately governed review remains necessary for golden promotion, target-list changes, and application changes.

## 7. Execution and isolation boundary

The internal runner uses a temporary workspace, a restricted environment, process groups, timeouts, output caps, and available POSIX resource limits. These controls reduce accidental impact. They do not form a security boundary for hostile code because the child still shares the API container's network, mount, and other namespaces.

Consequences for the embedded runner:

- public REST/MCP submissions never execute;
- crawled release-note code never executes;
- authenticated server verification endpoints remain disabled;
- local re-verification is for code the operator has chosen to trust;
- no response may claim `ATTESTED`, hermetic, network-denied, or kernel-isolated execution unless the exact run carries measured evidence for those properties.

The scheduled exact verifier is a separate disposable Docker job for trusted allowlisted repository fixtures. Its current published artifact records network mode `none`, read-only root, non-root execution, dropped capabilities, `no_new_privs`, private process/mount/cgroup namespaces, seccomp filtering, zero bind mounts, no Docker socket in the worker, no production data or credentials, and bounded memory, swap, PID, CPU, and workspace storage. A separate network-disabled application-image gate validates publication.

Those control fields are machine-validated observations from the exact run, not an independent external security attestation. The public bundle's isolation status remains `NOT_ATTESTED`.

The host orchestrator still needs Docker access and may retrieve pinned build inputs. The implemented path is not a public hostile-code intake service. General untrusted execution remains blocked pending a separately reviewed intake, build-supply-chain, queue, quarantine, abuse-control, and adversarial-testing boundary.

## 8. Benchmark truth boundary

`benchmark/hardened_cases.json` is a frozen 15-case manifest with SHA-256:

```text
a076cff87dcf201aaeb6bf7931f1d05ea77f0da64a4a6a95a166067071ef018a
```

Nine cases form the historical `Suite v2-runtime-9` primary runtime set. Six supplemental cases are semantic or toolchain oracles and use a separate denominator. The hardened production-image rerun now executes the Rust fixtures after narrowly increasing trusted compiler/linker file limits while retaining the outer container cgroup; targeted Rust cases R1, R2, and R3 passed. The frozen TypeScript case `N2_TYPESCRIPT_56_STRICT_MAP_LOOKUP` still fails its declared pre-fail fingerprint because `tsc` reports missing `Map` library support (`TS2583`) before the expected strict-nullability error (`TS2322`). The manifest must not be changed in place. The former public `9/9` result remains withdrawn and the numeric result stays withheld until a corrected, versioned suite passes every required real toolchain.

The repository does not currently contain a complete, reproducible A/B/C model comparison with frozen prompts, identical model snapshots, equal tools and budgets, raw transcripts, and hidden judging. Earlier pilot percentages and speed or token claims are withdrawn as product evidence.

Runtime-specific skips must be reported. A missing toolchain is not a pass.

During the final 28 August audit, the six locally skipped Python Golden smoke tests were rerun under their declared Python 3.12.0 or 3.12.13 runtime and declared top-level package pins in temporary network-disconnected execution containers: HTTPX, Pydantic, FastAPI, datetime, SQLAlchemy, and NumPy all passed the legacy four-stage client verifier. These ad hoc compatibility smokes are not locked, publishable run artifacts and do not upgrade the five additional records; only the scheduled HTTPX target currently satisfies the public evidence-publication contract.

## 9. Privacy and security posture

- Caddy discards access logs.
- Caddy overwrites forwarded client-IP headers with loopback values.
- Uvicorn runs without access logging in production.
- Minimal application telemetry contains only a source category, action, coarse client class, and timestamp.
- Query text, raw User-Agent strings, and client IP addresses must not be persisted.
- Public pages use no tracking or analytics cookies.
- Ops authentication uses a PBKDF2-SHA-256 password verifier and an opaque one-hour session cookie; only the session-token digest is stored.
- No default operations password exists in the repository.
- Sanitisation removes common secret, email, IP-address, and local-path patterns before draft persistence.

Pattern-based sanitisation is risk reduction, not an absolute guarantee. Clients are instructed not to submit personal data, credentials, or proprietary source code.

## 10. Public language and legal pages

Public website copy and current normative documentation use English. The operator is based in Germany, so the public legal notice and privacy information are written for an EU/German context, but neither the repository nor its software constitutes legal advice or a compliance certification. Historical review artifacts may retain quoted source-language material and are not current product claims.

Durable UI rules:

- Legal notice: `/legal`.
- Privacy notice: `/privacy`.
- Do not add `/impressum` or `/datenschutz` aliases.
- Keep the contact address assembled from `data-u` and `data-d`, with the `<noscript>` fallback `mesh-direct [at] synapsemesh.dev`.
- Do not publish a static raw `mailto:` address.
- Do not claim use of the former EU Online Dispute Resolution platform; that platform was discontinued in 2025.
- Qualify `VERIFIED` as evidence within a declared test scope, not a warranty, security audit, or production guarantee.

## 11. Deployment facts and rules

The deployed design uses Caddy and a one-worker FastAPI container. Persistent state is under `data/`; curated bundles, current run artifacts, and lifecycle records are mounted read-only, while drafts are mounted separately as writable. The API container uses a read-only root filesystem, a fixed non-root service account, `no-new-privileges`, a bounded non-executable `/tmp`, and container-level CPU, memory, and PID limits. Production currently has one current passing HTTPX artifact plus content-addressed immutable history under `evidence/runs/archive/`.

Deployment source synchronisation does not overwrite production-refreshed run artifacts. A repository artifact may seed an empty host, while lifecycle records use a separate narrow synchronisation path. The API cannot write either evidence mount.

Those container controls harden the service but do not transform the internal fixture runner into a per-job hostile-code sandbox.

Deployment rules:

1. run the complete relevant test suite and record skips;
2. validate the Compose configuration;
3. create a consistent production SQLite backup;
4. synchronise source while excluding `.env`, virtual environments, caches, and every production SQLite file;
5. rebuild and recreate the API container when its image or mount contract changed;
6. verify health, legal/privacy routes, discovery, modern MCP stateless calls plus legacy initialization, runtime bundle statuses, privacy migration aggregates, mounts, and recent logs.

Last verified live deployment for this snapshot: 28 August 2026. Pre-deployment SQLite backups were created before container recreation. Health, database `PRAGMA quick_check`, zero persisted query text, legal/privacy routes and absent German aliases, modern MCP exact/prerelease/unknown-version behavior, the current HTTPX evidence artifact, timer state, non-root/read-only/one-worker container controls, evidence mounts, and recent logs were checked. The exact live HTTPX call returned `VERIFIED_MATCH`; prerelease and missing-version calls remained unverified and did not inherit its verification profile.

## 12. Legal and operational limits

- The project is provided under its repository licence and without a production warranty.
- A source licence of `NOASSERTION` means the licence still requires review; it is not permission to redistribute third-party code.
- EU AI Act classification depends on the actual intended purpose and deployment context and can change as the product changes.
- GDPR/data-minimisation controls require operational verification; documentation alone does not establish compliance.
- No paid tier, certification, grant award, request quota, or cost-recovery result should be presented as active unless it has actually been implemented and documented.

## 13. Near-term priorities

1. Keep public and crawled code out of both execution paths; independently review any future untrusted-code intake before implementation.
2. Add new scheduled verification targets only as exact, reviewed allowlist entries with pinned real toolchains and immutable run-bound evidence.
3. Implement the separately validated semantic recheck artifact required before `BROKEN` can become an active lifecycle state.
4. Create a versioned replacement for the frozen TypeScript N2 fixture instead of altering Suite v2 in place; keep the numeric runtime result withheld until every required case passes.
5. Replace or separately review the five legacy curated puppet/static workspaces without editing them through an autonomous path.
6. Run a genuinely preregistered, blind comparative agent evaluation before publishing model-performance claims.
7. Keep the service useful through precise misses and narrowly scoped evidence rather than catalog volume.

---

*Last updated: 28 August 2026.*
