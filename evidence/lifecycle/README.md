# Evidence lifecycle records

This directory is intentionally empty until a reviewed lifecycle event exists.

`STALE` is derived automatically when the latest valid run artifact is older
than 90 days. `BROKEN`, `DISPUTED`, and `SUPERSEDED` require a machine-readable
record bound to both the exact bundle SHA-256 and a `synapse-json-v1` canonical
run-artifact SHA-256. A malformed, symlinked, future-dated, or mismatched record
fails closed as `UNKNOWN`; only a valid challenge record may assert `DISPUTED`.
`BROKEN` additionally requires a validated semantic recheck-failure artifact and
is not accepted from a lifecycle marker alone. Lifecycle records never modify or
promote `bundles/golden/`.
