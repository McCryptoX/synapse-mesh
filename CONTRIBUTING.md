# Contributing to Synapse-Mesh

Thank you for your interest in contributing to Synapse-Mesh. This guide outlines the development workflow, code standards, and the epistemic contract required for compatibility bundles.

---

## 1. Development Setup

### 1.1 Prerequisites
- Python 3.11+ (Python 3.12 recommended)
- Node.js 22 LTS (optional, for `@synapse-mesh/verify` CLI package)
- Docker (optional, for local verification sandbox runs)

### 1.2 Initial Setup
```bash
# Clone the repository
git clone https://github.com/McCryptoX/synapse-mesh.git
cd synapse-mesh

# Set up Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy development environment template
cp .env.example .env
```

---

## 2. Running Tests & Quality Checks

Always verify that all unit and regression tests pass before submitting a pull request:

```bash
# Run full pytest suite
pytest -v

# Run with coverage report
pytest --cov=app --cov=synapse_cli

# Test Node.js verification package (if modified)
cd packages/verify && npm test && cd ../..
```

---

## 3. The Compatibility Bundle Standard

Every new or updated compatibility bundle must adhere to the **Four-Stage Verification Contract** (`schemas/compatibility_bundle_v1.json`):

1. **Pre-Fail Script (`reproduction.script`):** A self-contained script that authentically reproduces the breaking change against the target package baseline and exits with a non-zero status code.
2. **Deterministic Patch (`solution.patchDiff`):** A strict unified diff modifying only the necessary call sites, with explicit version constraints (`solution.pinnedDependencies`).
3. **Post-Pass Suite (`reproduction.testSuite`):** A verification suite that passes (exit code 0) once the patch is applied.
4. **Mutant Rejection (`solution.doNot`):** Explicit negative test cases or known bad workarounds. At least two mutant diffs must fail the test suite.

### Rules for Bundle Authors:
- **No Puppet Oracles:** Never use handwritten mock classes (`class MockSession`, `MockModel`) to fake third-party dependencies in reproduction workspaces. Verification must execute against the genuine library.
- **Fail Closed:** Do not soften regex signatures or relax version ranges to force a passing test. If an environment or toolchain is unsupported, the bundle must remain `DRAFT` or `UNVERIFIED`.
- **Golden Directory Policy:** All autonomous or community proposals must be submitted as drafts under `bundles/drafts/`. Promotion to `bundles/golden/` requires manual review.

---

## 4. Security & Sensitive Data Guidelines

- **Zero Secrets:** Never commit API keys, tokens (`ghp_...`, `sk-...`), passwords, or private IP addresses.
- **No PII:** Ensure reproduction scripts do not contain personal usernames, private home paths (`/Users/...`), or real email addresses.
- **Data Minimization:** Keep all telemetry and logging data-minimizing by design.

---

## 5. Pull Request Workflow

1. Fork the repository and create a descriptive feature branch (e.g. `feat/pydantic-v2-migration` or `fix/fastapi-lifespan-bundle`).
2. Implement your changes, ensuring code is formatted cleanly and typed where applicable.
3. Verify that all 200+ unit tests pass locally without skipping or relaxing assertions.
4. Open a pull request against `main` with a clear description of the problem, affected package versions, and verification evidence.
