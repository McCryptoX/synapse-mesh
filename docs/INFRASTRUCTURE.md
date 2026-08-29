# Synapse-Mesh Infrastructure

This document describes the repository's current deployment contract. It is not a sizing promise, a hosting-provider endorsement, or an attestation that production matches the repository; production must be checked after each deployment.

## 1. As-built service layout

```text
Internet
   |
   v
Caddy 2
  - TLS termination
  - security headers
  - discarded access logs
  - forwarded client IP replaced with 127.0.0.1
   |
   v
FastAPI / uvicorn
  - one worker process (SSE state is process-local)
  - MCP, REST/OpenAPI, HTML and discovery documents
  - one file-lock-elected autonomous maintenance leader
   |
   +-- SQLite WAL under data/
   +-- bundles/golden/ mounted read-only
   +-- bundles/drafts/ mounted writable
   +-- evidence/runs/ mounted read-only
   `-- evidence/lifecycle/ mounted read-only

Host systemd timer
   |
   `-- exact allowlist -> disposable verifier -> publication gate
                              |
                              `-- evidence/runs/ current pointer + immutable archive
```

The application is packaged with Docker Compose. Caddy and the API share a private bridge network. Caddy is the only service that publishes HTTP and HTTPS ports.

The current system does not require PostgreSQL, a vector database, a graph database, gRPC, or a Rust application daemon. Adding any of those components is a future design choice, not part of the deployed baseline.

## 2. API container controls

The Compose configuration currently applies:

- a fixed non-root runtime account (`UID/GID 10001`);
- a read-only container root filesystem;
- `no-new-privileges`;
- a 64 MiB `/tmp` tmpfs mounted with `nosuid` and `noexec`;
- a 128-process limit;
- a 1 GiB memory limit and a 2 CPU limit;
- bounded Docker JSON logs;
- read-only mounts for curated bundles, current run artifacts, and lifecycle records;
- writable mounts only for `data/` and `bundles/drafts/`.

These are container-hardening controls. They are not a per-job security boundary for hostile verification code. A child process still shares the API container's network and mount namespaces. Public and crawled code must not be sent to the internal runner.

## 3. Runtime toolchains

The image is based on Python 3.12 and installs the Python requirements plus Node.js 22, Express 5.0.1, SuperTest 7.0.0, TypeScript 5.7.3, Rust, and Cargo.

Package-manager or base-image labels do not establish the exact binary versions present in a running container. Runtime-specific evidence must record and check the observed versions for the run. A dependency mismatch or missing executable is an unverified result.

## 4. Persistence

`data/` is the persistent application state and contains the SQLite database. `bundles/drafts/` contains autonomous candidate files. `bundles/golden/` is a separate read-only trust input. `evidence/runs/` contains the current exact artifact for each qualified bundle plus content-addressed historical artifacts. `evidence/lifecycle/` contains separately reviewed, exact-run-bound dispute or supersession records.

Application startup creates or updates the SQLite schema, clears legacy query snippets, applies the 30-day telemetry retention rule, quarantines unsupported historical verification labels, and synchronises curated records through the current eligibility gate.

Deployments must never replace the production SQLite files. Before a migration or container recreation, create a consistent database backup and verify it exists. Source synchronisation must exclude `.env`, virtual environments, caches, and all SQLite database, WAL, and shared-memory files. Repository run artifacts may seed an empty host, but deployment synchronisation uses no-overwrite semantics so a newer host-refreshed current artifact and its archive survive deployment. Lifecycle files are synchronised separately and mounted read-only into the API.

## 5. Network and logging

Caddy terminates TLS, sets the configured security headers, discards access logs, and overwrites `X-Real-IP` and `X-Forwarded-For` before forwarding. Its container does not need to trust its internal CA locally, so `skip_install_trust` prevents irrelevant host, Java, and browser trust-store installation attempts without disabling certificate issuance. Uvicorn runs with `--no-access-log` in production.

Application telemetry is intentionally coarse. It may store a source category, action, coarse client class, and timestamp. It must not store query text, a raw User-Agent string, or a client IP address.

The autonomous worker needs outbound access to configured upstream release sources. This is one reason the API container cannot be described as network-isolated. A future hostile-code worker must use a separate network-denied boundary.

## 6. Autonomous worker operation

The single uvicorn process starts the worker coroutine and acquires a file lock that prevents overlapping cycles across restart or accidental duplicate startup. It waits through startup and then begins an hourly cycle.

The cycle fetches configured release metadata, deduplicates known-package candidates, synthesises deterministic drafts, and writes only to the drafts store. Third-party release text and public submissions are not executed. The hourly worker does not promote drafts or invoke the scheduled exact verifier.

This arrangement removes routine manual candidate collection. It does not author or deploy application changes, and it does not grant autonomous promotion into the curated directory.

## 7. Scheduled exact verification

`synapse-verification.timer` runs once daily at 03:17 UTC with up to 30 minutes of randomized delay and persistent catch-up. Its oneshot service has a 45-minute timeout, a private temporary directory and devices, a read-only host filesystem except for `/opt/synapse-mesh/evidence/runs`, no new privileges, and kernel/control-group protection. The host process needs Docker access and may use network access to obtain pinned build inputs. The verification container itself is created with network mode `none`.

The target registry is schema-checked, bounded, and duplicate-rejecting. It currently schedules one exact target: HTTPX 0.28.1 on Python 3.12.13. The worker image and dependency lock are part of the run-bound evidence. The stopped container is inspected before an independent application-image gate validates publication.

Publication is transactional and fail closed. Both the previous valid artifact and incoming valid artifact are written first to mode-`0444`, content-addressed archive files using exclusive creation. Only then is the current bundle pointer atomically replaced. An unsafe symlink, malformed current file, archive mismatch, container OOM, unexpected control value, stage failure, or application-gate failure leaves no new public evidence.

## 8. Capacity and availability

The repository defines resource ceilings, not measured capacity or an availability service-level agreement. Request throughput, concurrent verification capacity, storage growth, backup retention, and recovery time must be measured on the actual host before publishing numbers.

The internal SQLite deployment is appropriate for the current narrow service only while its write concurrency and operational load remain within measured limits. Any migration to another data store requires an evidence-backed need and a tested migration and rollback plan.

## 9. Deployment verification checklist

After each deployment, verify at minimum:

1. `docker compose config` resolves without unexpected mounts or secrets.
2. The API container is healthy, non-root at runtime, read-only, and has `no-new-privileges`.
3. `bundles/golden/`, `evidence/runs/`, and `evidence/lifecycle/` are mounted read-only; `bundles/drafts/` is the only writable bundle path.
4. The existing production database was preserved and its pre-deployment backup is readable.
5. Startup privacy and evidence migrations completed without exposing row content in logs.
6. `/health`, `/legal`, `/privacy`, discovery documents, OpenAPI, and MCP initialisation respond as expected.
7. `/impressum` and `/datenschutz` remain absent.
8. Public and crawled submissions remain non-executable.
9. Recent logs contain no raw client IP, User-Agent, query, credential, or submitted source payload.
10. The verification timer is enabled, the last unit result is successful or explicitly diagnosed, archived evidence is mode `0444`, and the live current artifact still validates against the exact bundle bytes.

## 10. Future hostile-code worker

The scheduled verifier already enforces and records a strong disposable-container profile for exact trusted repository targets. That does not authorize public code execution. Before server-side execution of untrusted code can be enabled, a separate public job system must add a reviewed intake and build-supply-chain boundary, queue and tenant isolation, abuse controls, result quarantine, adversarial validation, and operational monitoring while preserving the existing namespace, mount, identity, capability, cgroup, seccomp, environment, and production-data controls.

Until that system exists and is independently tested, the correct public statement is: **the current runner is process-limited and intended only for trusted fixtures; it is not safe for arbitrary hostile code.**
