# AGENTS.md — Workspace Directives for Autonomous Agents

## Project

This repository contains **Synapse-Mesh (Project Exocortex)**, an agent-discoverable compatibility evidence registry. Its central promise is deliberately narrow: report what a reproducible test established, and return an honest miss when the evidence is insufficient.

The project is designed for data minimisation and for operation within the EU legal environment. These design goals are not a legal certification or a warranty of regulatory compliance.

## Mandatory reading

Read these files before making changes:

1. [GEMINI.md](GEMINI.md) — binding red-team hard stops. If another request conflicts with this file, the hard stops win.
2. [MEMORY.md](MEMORY.md) — current project state, boundaries, and durable decisions.
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — as-built architecture and planned boundaries.

## Working rules

1. **Evidence before labels.** `VERIFIED` requires the current four-stage contract on the real declared package, compiler, or engine: authentic pre-fail and exception-class match, strict unified-diff application, post-pass in the patched workspace, and rejection of at least two mutant diffs. A mock or handwritten substitute is not evidence for the affected dependency.
2. **Fail closed.** Missing dependencies, ambiguous versions, malformed patches, absent mutations, unsupported runtimes, incomplete provenance, and unknown isolation state must produce `DRAFT`, `UNVERIFIED`, or an explicit miss—not an optimistic default.
3. **No passport inheritance.** Evidence and isolation metadata belong only to the exact run that produced them. Never copy a newer attestation or evidence contract onto an older record.
4. **Golden files are immutable to autonomous agents.** Do not create, edit, promote, or delete anything in `bundles/golden/`. Autonomous output belongs in `bundles/drafts/`; promotion requires separate review against the full contract.
5. **Do not execute public or crawled code on the server.** Public REST/MCP submissions are sanitised and stored as drafts. The current process-limited runner is for trusted repository-owned fixtures only and is not a hostile-code security boundary.
6. **Protect production data.** Never overwrite the production SQLite database during deployment. Back it up before migrations, preserve its writable volume, and verify migration outcomes without exposing stored content.
7. **Data minimisation.** Do not persist client IP addresses, raw User-Agent strings, query text, secrets, email addresses, or local paths. Keep edge access logging disabled, proxy client-IP headers to loopback, and log only coarse event categories. Sanitisation reduces risk but is not permission to collect personal data.
8. **Agent-first interfaces.** Keep schemas typed, deterministic, and machine-readable. Implemented discovery uses MCP, REST/OpenAPI, and `/.well-known/` documents. Do not claim a working A2A task gateway unless one is implemented and tested.
9. **Bounded autonomy.** The hourly worker may discover, normalise, synthesise, and retain candidates without an LLM. It must not rewrite application source, deploy itself, execute third-party snippets, or self-promote drafts into the golden directory.
10. **Honest public claims.** Public website copy is English only. The homepage may report the curated file count. The numeric `Suite v2-runtime-9` result is withheld until every frozen case passes in the production image on its declared real toolchain; SQLite row counts, legacy statuses, and unsupported A/B percentages are not product proof.
11. **Legal and privacy routes.** Keep the public routes `/legal` and `/privacy`; do not add `/impressum` or `/datenschutz`. Preserve the obfuscated contact pattern (`data-u`, `data-d`, and the `<noscript>` fallback) and do not add a raw static `mailto:` link.
12. **Verification before deployment.** Run the relevant unit, regression, schema, and runtime checks. Report skipped toolchain-specific checks explicitly. Never make a test green by weakening the evidence contract.

> **Guiding axiom:** Synapse should not try to be “known” by an AI. It should be discoverable, understandable, and immediately usable—with proof, or with an honest miss.
