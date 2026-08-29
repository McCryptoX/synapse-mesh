# Phase 1 MVP Specification: Compatibility Evidence Registry

## 1. Objective

The MVP lets software agents discover Synapse-Mesh at runtime, search narrowly scoped compatibility evidence, inspect curated bundle records, and submit new candidates as non-executed drafts.

The MVP does not promise universal coverage, safe execution of arbitrary code, automatic golden promotion, an A2A peer-task service, or autonomous modification of the application.

## 2. Core record types

### Recipe projection

The REST recipe model is JSON-LD-compatible and contains:

```json
{
  "$schema": "https://synapsemesh.dev/schemas/v1/recipe.json",
  "@context": "https://schema.org",
  "@type": "TechArticle",
  "id": "rec_example_candidate_001",
  "problem": {
    "errorSignature": "Exact observed error text",
    "runtime": "python",
    "packages": {"example-package": ">=2,<3"},
    "description": "A scoped compatibility problem."
  },
  "solution": {
    "summary": "Candidate fix summary.",
    "codeDiff": "--- a/example.py\n+++ b/example.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
    "instructions": [],
    "pinnedDependencies": {"example-package": ">=2,<3"},
    "doNot": []
  },
  "reproduction": {
    "script": "# minimal reproduction",
    "testSuite": "# post-patch test"
  },
  "evidence": {
    "verificationStatus": "DRAFT",
    "evidenceContract": null,
    "verificationNote": "Public submission stored without server-side code execution; independent verification is required.",
    "sandboxExitCode": -1,
    "passedTests": 0,
    "totalTests": 0,
    "confidenceScore": 0.0,
    "preExit": -1,
    "postExit": -1,
    "mutationsKilled": "0/0",
    "toolchainVersions": {},
    "badges": [],
    "isolationProfile": {}
  }
}
```

A public submitter cannot select evidence fields. The server creates the conservative draft evidence object.

### Compatibility bundle

The curated bundle schema records scope, error fingerprint, a strict unified diff, dependency pins, negative guidance, workspace files, pre-fail reproduction, post-patch tests, at least two mutant diffs, and provenance.

`bundles/golden/` is a curated read-only input. A file's location or legacy `status` field is not sufficient for runtime `VERIFIED`; schema, real-dependency provenance, the declared evidence-contract gates, and a separate valid run artifact bound to the exact file bytes must all pass.

## 3. REST interface

### Recipe endpoints

- `GET /api/v1/recipes/stats` returns operational aggregate counts and coarse activity data without query text.
- `GET /api/v1/recipes` lists records, optionally filtered by status or runtime.
- `GET /api/v1/recipes/{recipe_id}` returns a recipe projection.
- `POST /api/v1/recipes/search` searches only evidence-qualified records and applies runtime, package, signature, exception-class, and version gates.
- `POST /api/v1/recipes/submit` validates and sanitises a candidate, assigns or validates a `rec_...` identifier, and inserts it as `DRAFT` without executing code.

Anonymous submission is insert-only. It cannot overwrite an existing recipe or use the reserved `bundle_...` namespace.

### Bundle endpoints

- `GET /api/v1/bundles` lists schema-valid curated files with runtime status downgrades where current evidence gates fail.
- `GET /api/v1/bundles/{bundle_id}` returns one curated bundle.
- `POST /api/v1/bundles/search` searches curated bundle metadata.
- `POST /api/v1/bundles/verify` requires an admin credential but currently returns `503`; server-side execution remains disabled until a dedicated isolated worker exists.

### Operational and public endpoints

- `GET /health` provides liveness and protocol metadata.
- `GET /openapi.json`, `/docs`, and `/redoc` expose the typed API contract.
- `/ops` provides a private, no-index operational view with password-hash and short-lived session controls.
- `/`, `/verification`, `/benchmark`, `/legal`, and `/privacy` are the public English pages.

## 4. MCP interface

The HTTP MCP endpoint is `/mcp`. MCP `2026-07-28` uses stateless `server/discover` and per-request protocol metadata; the legacy `2024-11-05` initialization handshake remains available for older clients. The primary tools are:

- `find_solution`: search for a qualified compatibility match and return an explicit miss when none exists;
- `submit_solution`: store a sanitised draft without executing it.

MCP validation failures are logged by event class and status only. Submitted source, query text, raw User-Agent strings, and client IP addresses are not telemetry fields.

Clients must inspect the returned status, evidence contract, declared versions, and evidence metadata rather than assuming that every result is verified.

## 5. Discovery

Implemented machine-discovery surfaces include:

- `/.well-known/mcp.json`;
- `/.well-known/agent.json`;
- `/.well-known/agent-card.json`;
- `/openapi.json`;
- `/llms.txt` and `/llms-full.txt`.

The agent documents describe MCP and REST capabilities. They do not advertise an A2A task endpoint because no such gateway is implemented.

## 6. Autonomous maintenance

One file-lock-elected worker runs an hourly no-LLM cycle. It fetches configured upstream metadata, deduplicates known-package candidates, applies deterministic synthesis, and retains all resulting material as unexecuted drafts.

All autonomous files go to `bundles/drafts/`. The worker does not write to `bundles/golden/`, modify source code, or deploy the service.

A separate daily host timer may refresh only exact repository-owned targets in the bounded reviewed allowlist. It uses a disposable network-disabled container plus an independent application-image publication gate. Any build, runtime, evidence, or gate failure publishes nothing. This path does not accept drafts, public submissions, or crawled code.

## 7. Privacy and security requirements

- Do not persist client IP addresses, raw User-Agent strings, query text, credentials, email addresses, or local paths.
- Discard Caddy access logs and run uvicorn without access logging.
- Retain only coarse telemetry for no more than 30 days.
- Store an operations password verifier, never a plaintext password, and store only digests of opaque session tokens.
- Reject unsafe identifiers, source URLs, workspace paths, oversized fields, and malformed diffs.
- Never execute public or crawled code in the API container.
- Treat sanitisation as defence in depth, not as a guarantee that arbitrary input is non-personal.

## 8. Evidence acceptance criteria

The MVP may expose a record as `VERIFIED` only when it carries `bundle-4-stage-v1` and the following were established on the same real-dependency workspace:

1. authentic non-zero pre-fail and matching exception class/signature;
2. strict unified-diff application;
3. zero-exit post-pass on the patched workspace;
4. rejection of at least two independent mutant diffs;
5. matching declared dependency and runtime versions;
6. no mock substitute for the dependency under test;
7. a valid run artifact bound to the exact bundle bytes, exact toolchains, source revision, image digest, stage outputs, mutation outcomes, and measured runner controls.

Missing evidence produces `DRAFT`, `UNVERIFIED`, `PROVISIONAL`, or an explicit no-match result. Isolation claims require separate measured attestation and are not implied by a verification pass.

## 9. MVP acceptance checklist

The MVP is acceptable when:

- public submit and MCP submit are non-executing and insert-only;
- curated and database retrieval fail closed on evidence status and version scope;
- the golden directory is read-only to the autonomous service;
- the hourly worker can refresh drafts without model calls or manual data entry;
- privacy migrations remove legacy query text and expire coarse telemetry;
- operations authentication has no repository default password and uses secure, short-lived cookies;
- public claims remain limited to the curated registry; the numeric `Suite v2-runtime-9` result stays withheld until a corrected, versioned suite passes the production-runtime gate;
- tests cover overwrite attempts, class-spoofed signatures, invalid versions, unsafe paths/diffs, privacy redaction, and dynamic downgrade of legacy puppet bundles;
- deployment preserves the production database and verifies the live security mounts.
