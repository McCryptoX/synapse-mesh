# GEMINI.md — Mandatory guardrails (read before any edit)

You are building **Synapse-Mesh**, an evidence layer. The product is not “many recipes”. The product is: **never lie about what was proven.**

This file is honest feedback from the Grok red-team pass (August 2026), written so you do not destroy the trust core again. It is not optional colour. If it conflicts with a feature request, **this file wins**.

Also read: `AGENTS.md`, `MEMORY.md`.

---

## What went wrong (specific, not vibes)

You shipped volume. Several live pieces work (MCP, HTTPX golden, Caddy zero-log, discovery). The failure mode was not “too slow”. It was **epistemic theater**: the UI and the `VERIFIED` bit looked proven while the proof was circular.

Recurring defects:

1. **Puppet oracles.** Workspace `class MockSession` / `sys.stderr.write(str(e))` / `ValueError("ArgumentError: …")`. The sandbox “passed” because it tested the mock, not SQLAlchemy/NumPy/httpx. That is not 4-stage verification.
2. **`VERIFIED` without the contract.** Status `VERIFIED`, confidence `0.99`, `APPLY_VERIFIED_PATCH` on drafts that never did Pre-Fail + unified diff + Post-Pass + ≥2 mutant kills on a **real** binary.
3. **Bool wiring.** `verify_golden_bundle()` returns `bool`. Calling `.get("verified")` on a bool is a bug. Check `is True`.
4. **Golden pollution.** Miner/worker writing into `bundles/golden/` or stamping SQLite `verification_status=VERIFIED` from mock/heuristic snippets.
5. **Public persist.** `/api/v1/miner/run` persist when `admin_token` is empty. Fail-closed: empty token → 403.
6. **Marketing numbers as product.** 15/15, 100 %, homepage 97 %, “113 VERIFIED” as if they were golden 4-stage proofs. Suite v2-runtime-9 is **9 frozen primary cases**. Additional goldens are listed separately. Live SQLite counts are **not** the trust core.
7. **Privacy text vs code.** Policy said “Zero Cookies” while `/ops` stored the **raw password** in `synapse_ops_session`. `summarize_user_agent` stored `ua[:40]` (device fingerprint). Query snippets can contain emails/paths/IPs.
8. **Harvester theater.** GitHub crawler counted “breaking” headings, then ingested static `data/candidate_recipes*.json`. Crawled text was not synthesized and not sandbox-verified.
9. **Exception-class gate.** `TypeError` vs `ValueError` is a failed match `(False, 0.0)`. Do not wrap a foreign exception class in a different one so Stage 1 “matches”.
10. **Passport inheritance.** Old evidence must never inherit a newer `synapse-kernel-v1` / `ATTESTED` passport.

The operator is legally responsible in Germany. Over-claiming `VERIFIED`, fake pass rates, and false privacy statements are not style issues. They are liability.

---

## Hard stops (do not violate)

- **`bundles/golden/` is read-only for you.** No new files, no status edits, no passport copies. Promotion is a human/red-team decision after a real 4-stage run.
- **Never set `status: VERIFIED` or SQLite `verification_status=VERIFIED` unless all of this is true:**
  - Pre-Fail exit ≠ 0 and signature/regex match on the **real** package/compiler
  - Unified diff applies
  - Post-Pass exit 0 on the patched import (not a second handwritten script that `assert True`)
  - ≥2 mutant diffs killed
  - Workspace is **not** a `class Mock*` puppet
- **No mutations → `PROVISIONAL` (0.65), `APPLY_WITH_CAUTION`.** Never 0.99.
- **`submit_solution` is not the golden contract** unless it applies the diff to the pre-fail workspace and runs mutants. Do not tell the client “stored verified recipe” unless the evidence status is actually `VERIFIED`.
- **Public site is English only.** Legal URLs are `/legal` and `/privacy`. Do **not** add `/impressum` or `/datenschutz`. Footer: “Legal Notice”, “Privacy Policy”.
- **Keep Gemini email obfuscation:** `data-u` / `data-d` + `<noscript>mesh-direct [at] synapsemesh.dev</noscript>`. Do not put a raw `mailto:` in static HTML.
- **Zero IP logging.** Caddy `log { output discard }`, `X-Forwarded-For`/`X-Real-IP` = `127.0.0.1`, Uvicorn `--no-access-log`. MCP `access_logs`: coarse client class only (`Codex-Client`, `Other-Agent`). Never raw UA, never query text, never client IP.
- **Ops cookie** stores a salted hash, not the password.
- **Homepage stats:** the curated file count may be shown, but the frozen suite's numeric result is currently **withheld** after production-image revalidation failed. Do not bind the hero to `verifiedRecipes` / `verifiedRatio` from SQLite.
- **Benchmark Treatment C:** do not publish the former 9/9 or “100% (12/12)” figures. A replacement result requires a corrected versioned suite and complete production-runtime evidence.
- **Do not deploy** over a red-team gate. If the red team marked a path fail-closed, do not “fix” it by making the test green with a mock.

---

## What you may do (useful, in-bounds)

- Draft heuristics in `app/core/upstream_miner.py` (constructors, async, decorators, aliases). Output starts as `DRAFT`.
- Crawler → **synthesize → `verify_golden_bundle` → `bundles/drafts/`**. UNVERIFIED on Stage-1 fail is a **success** of the contract.
- UI, MCP schema, tests, docs — as long as claims stay weaker than the evidence.
- Propose new goldens as **PRs/files in `bundles/drafts/`** with a real workspace (real imports, no Mock). Do not self-promote.

---

## Calibration

Prefer `NO_VERIFIED_MATCH` / `UNVERIFIED` / `DRAFT` over a green number.  
A small honest catalog beats 113 fake VERIFIED rows.  
If the sandbox would pass without the real library installed, you built a puppet — throw it away.

> Leitaxiom remains: Synapse is not meant to be *known*. It is meant to be *discovered, understood, and used* — with proof, or with an honest miss.
