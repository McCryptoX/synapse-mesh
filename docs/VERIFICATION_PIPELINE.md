# Verification Pipeline and Execution Boundary

Synapse-Mesh is an evidence registry. Agreement among models, a plausible patch, a source URL, and an exit code from a mock are not proof that a compatibility fix works on the affected dependency.

## 1. Evidence hierarchy

For a narrowly declared compatibility claim, the preferred evidence order is:

```text
reproducible execution on the declared real dependency and toolchain
    > primary upstream documentation tied to that execution
    > secondary material
    > model or community consensus
```

Primary documentation establishes provenance and intent. It does not replace reproduction, patch application, post-patch testing, or mutation rejection.

## 2. Separate intake paths

### Public REST and MCP submissions

Public submissions are validated, sanitised, assigned a `rec_...` identifier, and inserted as `DRAFT`. They are not executed by the server. The curated `bundle_...` identifier namespace is reserved, and an existing record is not overwritten by anonymous submission.

### Crawled upstream material

Release notes and migration text are third-party input. The autonomous pipeline may extract metadata and synthesise deterministic candidate drafts, but it does not execute copied code blocks. These candidates remain in `bundles/drafts/` unless a separate trusted path establishes evidence.

### Repository-owned fixtures

Deterministic fixtures maintained in the repository may run through the local process-limited verifier. That runner is used only for trusted inputs and does not make a record publicly verified by itself. The hourly autonomous discovery worker retains its candidates as drafts and never writes to `bundles/golden/`.

### Scheduled exact allowlist

An operator-controlled target registry identifies the exact bundle bytes, dependency lock, worker source, Dockerfile, image tag, runner version, and schedule flag for each disposable verification target. The registry is bounded to 32 entries, rejects malformed or duplicate identifiers, and currently schedules only the HTTPX 0.28.1 ASGI transport fixture.

A host systemd timer invokes that target daily without an LLM. The worker container runs with network mode `none`, a read-only root, non-root identity, no capabilities, `no_new_privs`, no bind mounts, no production data or credentials, and explicit memory, swap, PID, CPU, and workspace limits. The stopped container is inspected before publication. A separate application-image container then revalidates the bundle and artifact without network access or bind mounts. Any build, execution, inspection, or publication-gate failure publishes nothing.

The resulting control fields are run-bound machine observations, not an independent external security attestation. The public bundle remains `NOT_ATTESTED` for isolation.

### Operator-controlled local re-verification

The CLI can re-verify a local bundle selected by the operator. This executes bundle code and is therefore appropriate only when the operator trusts the input. The API's authenticated server-verification endpoint remains disabled until a dedicated hostile-code worker exists.

## 3. The `bundle-4-stage-v1` contract

A record may use `verificationStatus: VERIFIED` only when all of the following are established on the same clean workspace:

1. **Pre-fail and fingerprint**
   - The unpatched workspace runs on the declared real package, compiler, or engine.
   - It exits with the declared non-zero result.
   - The declared signature or regular expression matches the observed output.
   - The exception class matches; a `ValueError` containing the text `ArgumentError` does not reproduce an `ArgumentError`.
2. **Strict patch application**
   - The candidate is a well-formed unified diff.
   - Diff paths resolve inside the temporary workspace and target the declared file.
   - Every context and removed line matches exactly.
   - Plain replacement text, traversal, partial application, unchanged output, and oversized input fail.
3. **Post-pass**
   - The declared suite runs against the patched workspace, not against a separately handwritten “fixed” script.
   - It exits with the declared zero result.
   - Required dependency and runtime pins match the installed toolchain.
4. **Mutation rejection**
   - At least two independent mutant unified diffs are applied separately to clean copies of the unpatched workspace.
   - Every mutant fails the same post-patch test suite.

The recorded evidence is bound to the exact bundle, diff, workspace, versions, and run. It cannot be inherited by another record.

## 4. Fail-closed outcomes

The following are explicit non-passes:

| Condition | Required result |
|---|---|
| Public or crawled code | Store as `DRAFT`; do not execute |
| Missing or mismatched toolchain | `UNVERIFIED` |
| Mock or puppet in place of the affected dependency | `UNVERIFIED` |
| Pre-patch program exits zero | `UNVERIFIED` |
| Exception class or signature differs | `UNVERIFIED` |
| Diff is malformed, unsafe, or does not apply | `UNVERIFIED` |
| Post-patch suite fails | `UNVERIFIED` |
| Fewer than two mutants, or any mutant survives | `UNVERIFIED` |
| Legacy split-script check without diff and mutants | At most `PROVISIONAL` with confidence no greater than `0.65` |
| Isolation evidence absent | `isolationProfile: {}` and no isolation badge |

An unavailable runtime, timeout, or infrastructure error is not evidence that the fix passed or failed semantically. It is an unverified execution result.

## 5. Current process controls

The embedded trusted-fixture runner creates a temporary working directory and uses:

- strict workspace path and input-size validation;
- an environment-variable allowlist with a temporary home directory;
- a separate process group;
- a 12-second wall-clock timeout;
- a 512 KiB cap for each output stream;
- a 10 MiB child file-size limit for ordinary fixtures;
- a narrowly marked 64 MiB file-size allowance for repository-owned compiler/linker harnesses;
- a 10-second CPU soft limit with a 12-second hard limit;
- a process/thread limit where supported;
- a 512 MiB Linux address-space ceiling for ordinary Python fixtures; marked Node/Rust compiler harnesses rely on the outer container memory cgroup because their virtual-memory reservation is incompatible with that per-process ceiling;
- process-tree termination and temporary-directory cleanup.

These controls reduce accidents and resource abuse. They do **not** provide a hostile-code security boundary. The child shares the API container's network and mount namespaces, and some operating-system limits are best-effort or platform-dependent.

Consequently, the embedded runner must not be described as hermetic, network-denied, micro-containerised, kernel-isolated, or safe for arbitrary public code. The scheduled disposable path has stronger measured controls, but only for exact pre-approved repository fixtures; it is not a general public execution service.

## 6. Evidence payloads

An unexecuted submission starts conservatively:

```json
{
  "verificationStatus": "DRAFT",
  "evidenceContract": null,
  "sandboxExitCode": -1,
  "passedTests": 0,
  "totalTests": 0,
  "confidenceScore": 0.0,
  "preExit": -1,
  "postExit": -1,
  "mutationsKilled": "0/0",
  "isolationProfile": {}
}
```

An evidence-qualified record additionally requires a separate artifact under `evidence/runs/` bound to the exact bundle-file SHA-256. It identifies `bundle-4-stage-v1`, the observed run time, exact toolchain versions, source revision, immutable image digest, pre/post output hashes, mutation results, and only the isolation properties actually measured for that run. Test counts remain zero when the verifier did not record assertion counts; they must never be inferred or invented.

The current production proof is limited to `bundle_httpx_028_asgi_transport_001`, bundle SHA-256 `aea793c600f9037e1d7b78efb26723f8c99df28c9804d1a3a8a32c66d8d3ae81`, on Python 3.12.13 and HTTPX 0.28.1. Its published run records pre-patch exit `1` with both signature and exception-class matches, strict unified-diff application, post-patch exit `0`, and rejection of both declared mutant diffs. This evidence proves only that exact compatibility contract under the recorded environment.

Publication retains a current `<bundleId>.json` pointer and a content-addressed archive at `evidence/runs/archive/<bundleId>/<canonical-run-sha256>.json`. Previous and incoming valid artifacts are archived before the current pointer is replaced. Archive files are created exclusively as mode `0444`; symlinks, malformed prior state, or non-identical bytes at an existing digest path stop publication.

## 7. Storage and retrieval gates

SQLite retrieval treats a row as verified only when both the relational status and JSON evidence status are `VERIFIED`, the evidence contract is exactly `bundle-4-stage-v1`, and a valid exact-run artifact exists for its source bundle. Startup migration quarantines unsupported historical labels. Curated files are schema-validated; records without a valid run artifact, including legacy puppet/static workspaces, are dynamically exposed as unverified.

The `find_solution` path applies signature, exception-class, package, and version checks. No qualifying record produces an explicit miss rather than a low-quality “best guess.”

## 8. Lifecycle policy

The current public state is derived at read time and never copied onto an older record:

- no valid exact-run artifact yields `UNVERIFIED`;
- a valid artifact remains `VERIFIED` for less than 90 days;
- at the exact 90-day boundary it becomes `STALE`;
- a valid run-bound challenge record yields `DISPUTED`;
- a valid supersession record yields `SUPERSEDED` only when it identifies one unique, current successor with the same package and runtime scope;
- malformed, future-dated, symlinked, digest-mismatched, cyclic, ambiguous, or otherwise inconsistent lifecycle state yields `UNKNOWN`.

Lifecycle files are separate from immutable run artifacts and from golden bundle source. They use the `synapse-json-v1` canonical run-artifact digest and cannot promote a draft. `BROKEN` remains reserved for a validated semantic recheck-failure artifact and is not accepted from a lifecycle marker alone.

MCP hides the primary code diff for `STALE`, `BROKEN`, `DISPUTED`, `SUPERSEDED`, and `UNKNOWN` states. It returns a re-verification action for stale evidence, a superseding-record action only for a valid supersession, and `DO_NOT_APPLY` for blocked or unknown evidence.

## 9. Required future boundary

Server-side execution of untrusted code remains blocked. The scheduled exact verifier applies and records strong disposable-container controls for trusted allowlisted targets, but a public hostile-code service would additionally require a separately reviewed intake and build-supply-chain boundary, queue isolation, abuse controls, result quarantine, and adversarial validation of the complete system.

Even after that worker exists, `VERIFIED` will continue to mean only that the declared test contract passed. It will not mean secure, optimal, production-ready, or correct outside the recorded scope.
