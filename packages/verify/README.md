# `@synapse-mesh/verify`

Zero-dependency Node.js verifier for Synapse Verified Compatibility Bundles.

## Usage

```bash
node packages/verify/bin.js bundles/golden/bundle_httpx_028_asgi_transport.json \
  --python .venv/bin/python \
  --allow-code-execution \
  --attestation compatibility-attestation.json
```

Validate without executing bundle-provided code:

```bash
node packages/verify/bin.js path/to/bundle.json \
  --schema schemas/compatibility_bundle_v1.json \
  --validate-only
```

The package carries an exact copy of Compatibility Bundle Schema v1 and always
applies it. `--schema` adds a second, potentially stricter overlay using the
verifier's documented zero-dependency schema subset; unsupported keywords and
custom regex keywords fail closed. The overlay can never weaken or disable the
bundled Draft 2020-12 v1 contract.
The schema `$id` is an identifier, not a runtime dependency: verification never
fetches a schema from the network.

Custom overlays support local `$ref`/`$defs`, type/enum/const constraints,
object and array cardinality, required/dependent properties, numeric and string
limits, the `allOf`/`anyOf`/`oneOf` and `if`/`then`/`else` applicators, and the
`date-time`, `uri`, and `uri-reference` formats. `pattern`,
`patternProperties`, remote references, and all unknown keywords are rejected
for overlays; the canonical bundled schema remains the sole reviewed source of
regex constraints. Passing an exact parsed copy of that canonical schema via
`--schema` is accepted for Action and CLI interoperability.

The module exports `validateBundle`, `applyUnifiedDiff`, `verifyBundle`,
`verifySource`, and `createAttestation`.

## Security boundary

Compatibility bundles contain executable reproduction and test programs. The
verifier uses fresh temporary workspaces, rejects unsafe paths, invokes
interpreters without a shell, limits runtime and captured output, and removes
the workspaces after use. These controls improve determinism but **do not form
an operating-system security sandbox**. Bundle code can otherwise exercise the
permissions of the verifier process.

Run untrusted bundles inside a disposable container or micro-VM with no network
egress, a read-only host filesystem, an unprivileged user, and external CPU,
memory, process, and disk limits. `--allow-code-execution` is deliberately
required for non-validation runs.

## Execution model

1. The pre-fail script runs against an untouched fixture and must return the
   declared non-zero exit code with a matching error fingerprint.
2. The valid unified diff is applied to a fresh fixture and the post-pass test
   must exit `0`.
3. Every mutation diff is independently applied to another fresh fixture; the
   same post-pass test must reject it.

The verifier never installs dependencies. A caller must provide the exact
dependencies declared by `patch.pinnedDependencies` in the surrounding
container, virtual environment, or CI job. For Node.js bundles,
`--dependency-root` identifies the directory containing `node_modules`; the
verifier exposes that tree to each disposable workspace through an internal
symlink. The surrounding container remains the security boundary.

Publishers should include a package-manager lockfile through
`patch.dependencyLock`. The verifier binds its byte digest to both the bundle
fixture and the external dependency root. Declared package versions are
checked independently. The caller must materialize the dependency tree from
that lockfile in frozen/offline mode; lockfile equality alone does not prove
that an arbitrary pre-existing installation matches every transitive entry.
The verifier fingerprints file content, type, and POSIX mode in the installed
Node tree or Python site-packages tree before execution and verifies that
fingerprint after every phase. Dependency symlinks that resolve outside that
tree and multiply linked files are rejected before bundle code runs; contained
package-manager links are fingerprinted together with their in-tree targets.
Python `.pth`/`.egg-link` files, site customization modules, and virtual
environments that enable system site-packages are also rejected because they
can redirect imports outside the fingerprinted tree. A changed shared
dependency environment therefore fails closed.
Python bytecode is included in the fingerprint, and verification subprocesses
set `PYTHONDONTWRITEBYTECODE=1` so ordinary imports do not alter that baseline.

Node dependency discovery and hashing run in a terminable worker and enforce
file-count, aggregate-byte, and package-metadata limits. These verifier limits
bound its own evidence pass; the surrounding container or VM must still apply
filesystem and resource quotas to bundle code itself.

The environment preflight checks the exact runtime, the declared host platform,
and all pinned packages before running the pre-fail gate. Rust verification
requires `cargo metadata --locked --offline` to succeed, resolves crate pins
from that result, binds its normalized resolve graph, fingerprints every
resolved external crate source tree together with its package identity, and
binds the invoked Cargo/rustc executable bytes (plus selected toolchain
binaries when discoverable). `rustc` and `cargo` may also be declared as exact
toolchain pins. External registries still belong in the caller's read-only
container boundary. `STALE` and `REVOKED` bundles are refused by default.
The CLI and `verifySource` apply a fail-closed five-minute wall-clock budget to
source/schema retrieval plus execution; `verifyBundle` applies it to execution
because the caller has already supplied parsed bytes. `--total-timeout-ms`
selects a bounded replacement.

## Evidence privacy

Raw stdout and stderr are not included in results by default. Instead each
phase records byte counts and SHA-256 digests. `--include-output` is an
explicit local debugging option, but `createAttestation` always removes raw
phase output before producing persistent evidence. Source locations are
reduced to `local-file` or `https-url`, and free-form failure messages are
replaced by stable failure classes so filesystem paths cannot leak through
persistent evidence.

For HTTPS sources, use `--expected-sha256`; the reusable Action requires it.
This prevents a mutable URL from serving different bytes between review and
execution. HTTPS resolution also rejects loopback, private, link-local,
documentation, multicast, and other non-public address ranges to prevent the
bundle loader from becoming an internal-network request primitive. Use a local
file for intentionally private sources.
