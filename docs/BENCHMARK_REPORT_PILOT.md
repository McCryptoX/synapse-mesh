# Withdrawn Pilot Benchmark Report

## Status: not product evidence

An earlier version of this file presented a five-case A/B/C comparison with percentages, token counts, timing, tool-call counts, and broad conclusions. The repository does not contain the complete raw artifacts needed to reproduce or audit those numbers under a fair matched protocol.

The earlier quantitative claims are therefore withdrawn. They must not be copied into the website, README, sales material, legal text, funding applications, or evidence records.

## What can currently be stated

- `benchmark/hardened_cases.json` is a frozen 15-case fixture manifest.
- Nine entries form the primary `Suite v2-runtime-9` release gate.
- Six supplemental semantic or toolchain oracles use a separate denominator.
- The former `9/9` fixture result is withdrawn. Rust R1/R2/R3 now execute successfully in the hardened production image, but frozen TypeScript case N2 reaches `tsc` without a library that defines `Map` and produces `TS2583` before its declared `TS2322` fingerprint; the current numeric result is therefore withheld.
- The fixture gate tests checked-in reproductions, valid solutions, and negative mutations in available runtimes.
- It does not compare model-only, web-enabled, and Synapse-enabled agents.
- It does not establish a general first-try solve rate, token saving, speedup, or absence of incorrect patches.

## Conditions for a replacement report

A new comparative report may replace this notice only after the experiment satisfies [BENCHMARK_METHODOLOGY.md](BENCHMARK_METHODOLOGY.md), including:

1. an immutable preregistration and holdout manifest;
2. identical model snapshots, prompts, budgets, and non-treatment tools;
3. a frozen Synapse snapshot;
4. a dedicated hidden-judge environment isolated from production;
5. raw prompts, outputs, tool transcripts, submitted patches, and judge results;
6. explicit handling of retries, skips, timeouts, and infrastructure errors;
7. a script that regenerates every published table from the raw artifact.

Until then, the honest comparative result is: **not measured reproducibly.**
