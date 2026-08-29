# Synapse-Mesh Verification Model & Epistemic Contract

This document defines the verification contract, evidence lifecycle, and boundary semantics used in Synapse-Mesh.

---

## 1. The Four-Stage Verification Contract (`bundle-4-stage-v1`)

A compatibility bundle is eligible for the `VERIFIED` evidence tier if and only if it successfully completes the full four-stage deterministic contract on declared real binaries, compilers, or runtimes:

```text
[Unpatched Code]  ---> [Stage 1: Pre-Fail]     ---> Authentic failure & signature match
       |
       v (Apply patchDiff)
[Patched Code]    ---> [Stage 2: Patch Apply]  ---> Strict unified-diff application (no fuzz)
       |
       v
[Target Runtime]  ---> [Stage 3: Post-Pass]    ---> Test suite executes with exit code 0
       |
       v (Apply negative mutants)
[Mutant Diffs]    ---> [Stage 4: Mutation Kill] ---> At least 2 invalid patches rejected
```

### Stage 1: Pre-Fail Validation
- A minimal reproduction script is executed against the baseline version (`fromVersion`).
- The execution must exit with a non-zero exit code (`exitCode != 0`).
- The emitted standard error / exception must match the declared error signature class and pattern on the **real package binary** (not a synthetic `Mock` class).

### Stage 2: Strict Patch Application
- The proposed `patchDiff` is applied to the workspace.
- Diff application must be strict: unified diff format, exact line offsets, zero path traversal, and zero loose fuzzing.

### Stage 3: Post-Pass Verification
- The test suite is executed in the patched workspace on the target version (`toVersion`).
- Execution must terminate with exit code 0.
- Asserts that the updated API pattern functions correctly without relying on deprecated interfaces.

### Stage 4: Multi-Mutation Rejection (Mutant Kills)
- At least two independent, plausible but incorrect patches (known anti-patterns or partial fixes, recorded in `doNot`) are applied to the reproduction workspace.
- The test suite must fail (`exitCode != 0`) on every mutant diff.
- Proves that the verification test suite has diagnostic power and does not trivially pass (no vacuous `assert True`).

---

## 2. What "Verified" Means — and What It Does Not Mean

### What "Verified" DOES Mean:
- **Reproducibly Verified:** Under the exact recorded environment, compiler version, dependency pins, and test contract, the patch resolved the authentic failure and rejected known negative mutants.
- **Bound Evidence:** The verified status is bound to the exact byte-for-byte SHA-256 hash of the bundle and its corresponding run artifact.
- **No Mock Puppets:** Verification took place against the actual declared library package or compiler binary.

### What "Verified" DOES NOT Mean:
- **Not a Formal Proof:** It is not a mathematical proof of correctness across all possible inputs.
- **Not a Production Warranty:** It does not guarantee that the patch is suitable, secure, or free of side-effects for your specific proprietary application architecture.
- **Not Inherited:** Verification of version `0.28.1` does not prove compatibility for `0.28.0` or `0.29.0`. Each version constraint requires its own evidence.

---

## 3. Evidence Lifecycle & Freshness States

Evidence records are not eternal. Synapse-Mesh enforces a state machine governing evidence freshness:

```text
               +-------------------------------------------+
               |  No valid run artifact exists for bundle   |
               +-------------------------------------------+
                                     |
                                     v
                           +-------------------+
                           |    UNVERIFIED     |
                           +-------------------+
                                     | (Valid 4-stage run artifact created)
                                     v
                           +-------------------+
                           |     VERIFIED      | <----+
                           +-------------------+      |
                                     |                | (Re-verified successfully)
            +------------------------+----------------+--------+
            | (Age >= 90 days)       | (Valid dispute)|        | (Superseded by newer)
            v                        v                |        v
    +---------------+        +---------------+        |  +---------------+
    |     STALE     |        |   DISPUTED    |--------+  |  SUPERSEDED   |
    +---------------+        +---------------+           +---------------+
```

| Lifecycle State | Criteria | Meaning |
|---|---|---|
| `VERIFIED` | Valid run artifact matching exact bundle digest, completed within the last 90 days. | Fully qualified evidence currently active. |
| `UNVERIFIED` | No valid run artifact matching the exact bundle bytes. | Solution exists as a candidate/draft or unverified golden. |
| `STALE` | Valid run artifact exists, but its `completedAt` timestamp is $\ge 90$ days old. | Requires automated or operator re-verification. |
| `DISPUTED` | A valid challenge record is bound to the exact bundle and run digest. | Evidence is challenged until re-verified. |
| `SUPERSEDED` | An exact-scope newer bundle has replaced this solution. | Outdated by a successor record. |
| `UNKNOWN` | Malformed or inconsistent lifecycle metadata. | Fails closed to prevent false confidence. |

---

## 4. Run Artifact Hashing & Provenance

Each verification run produces a standalone run artifact JSON stored under `evidence/runs/`:

```json
{
  "bundleId": "bundle_httpx_028_asgi_transport",
  "bundleDigest": "sha256:452147c7...",
  "completedAt": "2026-08-28T03:17:00Z",
  "toolchain": {
    "runtime": "python",
    "version": "3.12.13",
    "package": "httpx==0.28.1"
  },
  "stages": {
    "preFail": { "exitCode": 1, "signatureMatched": true },
    "patchApply": { "success": true },
    "postPass": { "exitCode": 0 },
    "mutationKills": { "killed": 2, "total": 2 }
  },
  "isolationProfile": {
    "network": "none",
    "readOnlyRoot": true,
    "nonRootUid": 10001
  }
}
```

- **Bundle Digest Binding:** If a bundle's JSON content changes by even one byte, the digest mismatches and status immediately drops to `UNVERIFIED`.
- **Immutable Archive:** Whenever a new run succeeds, previous artifacts are preserved in `evidence/runs/archive/<bundleId>/<sha256>.json`.
