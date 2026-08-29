# Run-bound verification artifacts

This directory contains the current exact-run artifact for each
evidence-qualified bundle. A curated bundle file is not publishable as
`VERIFIED` merely because it records expected exits, test code, or mutation
definitions.

Each `<bundleId>.json` artifact must be bound to the exact bundle-file
SHA-256, exact runtime and dependency versions, source revision, immutable image
digest, and complete four-stage outcomes. The runtime validator in
`app/core/run_artifacts.py` rejects missing or ambiguous controls, infrastructure
failures used as mutation kills, non-exact toolchains, and artifacts copied to a
different bundle revision.

`<bundleId>.json` is the current pointer. Before it is replaced, both the
previous valid artifact and the validated incoming artifact are retained as
content-addressed, mode-`0444` files under
`archive/<bundleId>/<canonical-run-sha256>.json`. Archive creation is exclusive;
an existing digest path is accepted only when its deterministic bytes match.
Malformed current files, symlinks, and archive mismatches fail closed.

The repository currently includes one controlled passing artifact for the
HTTPX 0.28.1 ASGI transport bundle. Production may contain a newer scheduled
refresh of the same exact target; deployment must preserve the host's current
artifact and archive rather than overwrite them with the repository seed.

Public or crawled code must never be sent to this pipeline. It is limited to
trusted repository-owned fixtures.
