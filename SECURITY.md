# Security Policy & Trust Boundaries

Synapse-Mesh is designed with strict data minimization, fail-closed validation, and defensive execution boundaries.

---

## 1. Core Security Invariants

### 1.1 Untrusted Public Submissions
- All submissions received via the REST API (`/api/v1/recipes/submit`) or the MCP gateway (`submit_solution`) are treated as untrusted data.
- **Zero Server Execution:** Submitted code, reproduction scripts, and unified diffs are **never executed** by the public application server. They are stored exclusively as dormant text drafts.

### 1.2 Inbound Data Sanitization
- Inbound submissions and changelog mining inputs pass through regular-expression sanitization (`app/core/sanitizer.py`) before storage.
- The sanitizer actively scrubs:
  - Private API keys and tokens (e.g., GitHub tokens `ghp_...`, OpenAI keys `sk-...`, AWS credentials).
  - Passwords and bearer tokens.
  - Personal email addresses.
  - IPv4 and IPv6 network addresses.
  - Local filesystem user paths (`/Users/...`, `/home/...`).
- *Note:* Pattern-matching sanitization reduces risk but cannot guarantee the removal of all proprietary data. Users should never submit confidential credentials or private information.

### 1.3 Read-Only Production Trust Stores
- In production containers, `bundles/golden/` (curated goldens), `evidence/runs/` (verification proofs), and `evidence/lifecycle/` are mounted read-only (`:ro`).
- Application runtime services have no permission to modify the curated baseline.

### 1.4 Isolated Verification Boundary
- Verification jobs for repository-owned fixtures run exclusively through out-of-band host processes in disposable Docker containers.
- The verification container enforces:
  - Network isolation (`--network none`).
  - Read-only root filesystem (`--read-only`).
  - Dropped Linux capabilities and custom seccomp profile.
  - Fixed non-root UID/GID (`10001:10001`).
  - Strict resource constraints (CPU, memory, swap, PID limits).
  - No access to Docker socket, application source mounts, database files, or host credentials.

### 1.5 Data Minimization & Zero IP Logging
- Edge proxy (Caddy) discards access logs (`log { output discard }`).
- Application server runs with `--no-access-log`.
- No client IP addresses or raw User-Agent strings are persisted in application databases.
- Coarse telemetry expires automatically after 30 days.

---

## 2. Supported Versions

| Version | Status | Security Patches |
|---|---|---|
| `0.1.x` (main) | Active Reference | Supported |

---

## 3. Reporting a Vulnerability

If you identify a security vulnerability, isolation escape, or data exposure risk:

1. **Do NOT open a public GitHub issue.**
2. Send a private report to: `mesh-direct [at] synapsemesh.dev`
3. Include:
   - Description of the vulnerability.
   - Minimal reproduction steps or proof-of-concept.
   - Affected components or endpoints.
4. We will acknowledge receipt within 48 hours and coordinate remediation before public disclosure.
