# Verify Compatibility Bundle action

This composite action validates a bundle, runs the four verification gates, and
uploads an unsigned verification evidence statement. The caller must install
the bundle's exact pinned dependencies before invoking the action.

```yaml
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4
        with:
          node-version: 22.23.2
      - id: python
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version: '3.12.13'
      - name: Install the Golden Bundle's exact declared Python closure
        env:
          PYTHON: ${{ steps.python.outputs.python-path }}
        run: |
          "$PYTHON" -m pip install --disable-pip-version-check --no-deps \
            httpx==0.28.1 httpcore==1.0.9 anyio==4.14.2 \
            certifi==2026.7.22 h11==0.16.0 idna==3.19 \
            typing_extensions==4.12.2
          "$PYTHON" -m pip check
      - uses: ./.github/actions/verify-compatibility
        with:
          bundle: bundles/golden/bundle_httpx_028_asgi_transport.json
          python: ${{ steps.python.outputs.python-path }}
```

The relative `uses:` path above is for this repository's own CI. External
maintainers should reference the public repository at an immutable commit, for
example `McCryptoX/synapse-mesh/.github/actions/verify-compatibility@<commit-sha>`.
Do not consume a mutable branch or tag in a release pipeline.

A composite action cannot declare a job matrix; the consuming workflow owns
the matrix, operating system, dependency installation, and container boundary.
Each bundle declares one exact runtime version, so a runtime matrix must route
each cell to a matching bundle. When a caller uses an OS or bundle matrix, it
must also pass a unique `artifact-name` per cell because
`actions/upload-artifact@v4` does not allow several jobs to upload to the same
artifact name.

For an HTTPS `bundle`, `expected-bundle-sha256` is mandatory. This binds both
schema validation and execution to reviewed bytes; the Action fetches the
bundle once and fails closed on a digest mismatch. Local, commit-bound bundles
may also pass this input. `total-timeout-ms` caps that single load, validation,
and execution run; the default is five minutes. The calling job should still
set `timeout-minutes` as an outer CI safety limit.

## Security

The action executes code embedded in the selected bundle. Use only reviewed
bundles and run third-party submissions in a disposable, network-restricted
job container. The emitted JSON follows the in-toto Statement envelope shape
but remains **unsigned evidence** until a separate trusted signing step signs
it. This action deliberately does not claim SLSA provenance or sign with the
workflow's identity. Raw phase output is excluded from the uploaded evidence;
only exit metadata, byte counts, and output digests are retained.
