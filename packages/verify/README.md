# `@synapse-mesh/verify`

Zero-dependency Node.js verifier for Synapse Verified Compatibility Bundles.

## Usage

```bash
node packages/verify/bin.js bundles/golden/bundle_httpx_028_asgi_transport.json \
  --schema schemas/compatibility_bundle_v1.json \
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
