# Repository Privacy & Data Sanitization Record

This document outlines the privacy design, historical sanitization policies, and exclusion rules applied to the public Synapse-Mesh source tree.

---

## 1. Clean History & Sanitization Standard

The public Git repository contains all source code, verification contracts, schemas, fixtures, deployment templates, and documentation necessary to understand, build, test, and operate Synapse-Mesh.

To maintain strict data minimization:
- **Private Development Artifacts:** AI prompt working files, internal review memos, debug screenshots, and non-canonical PDFs have been removed from source control and are excluded via `.gitignore`.
- **Zero Real Credentials:** No production passwords, admin tokens, or private keys are stored in Git history. All configuration templates (`.env.example`) use generic placeholders.
- **No Production Databases:** SQLite database files, WAL logs, and snapshots remain strictly local and are never committed.
- **Anonymized Authorship:** Public commit history reflects generic maintainer identities (`Synapse-Mesh Contributor`) rather than private local hostnames or personal accounts.
- **No Private System Paths:** Hardcoded local filesystem paths (`/Users/...`, `/home/...`) have been sanitized in favor of repository-relative paths.

---

## 2. Invariant Policies

1. Any future pull request must not introduce personal identifying information, real API tokens, or unredacted system logs.
2. Inbound contributions to `bundles/drafts/` are sanitized via automated pipelines before persistence.
3. Curated records under `bundles/golden/` and `evidence/runs/` remain reproducible and verifiable under open, public toolchains.
