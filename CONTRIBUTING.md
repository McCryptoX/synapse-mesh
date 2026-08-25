# Contributing to Synapse-Mesh

Thank you for contributing to Synapse-Mesh!

## The Epistemic Standard for Verified Compatibility Bundles
Every contribution to the living solutions database or benchmark suite must follow the 4-Stage Verification Contract:
1. **Pre-Fail Validation:** A minimal reproduction script that reliably fails with the target error signature.
2. **Deterministic Patch:** A clean unified diff (`patchDiff`) with explicit package pins (`fromVersion`, `toVersion`).
3. **Post-Pass Verification:** An automated test suite executing with exit code 0 on the patched workspace.
4. **Multi-Mutation Rejection:** Proof that known web-fehlfixes (`doNot`) are actively rejected.

## Code Standards
- Python: Formatted with Ruff / Black, typed with strict Pydantic v2 schemas.
- TypeScript / Node: Standard strict ESM and Node 22 LTS compatibility.
- Zero-PII: No personal identifiable information, local username paths, or private credentials.
