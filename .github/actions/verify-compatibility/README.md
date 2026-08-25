# Verify Compatibility Bundle action

This composite action validates a bundle, runs the four verification gates, and
uploads an unsigned verification evidence statement. The caller must install
the bundle's exact pinned dependencies before invoking the action.

```yaml
jobs:
  verify:
    strategy:
      matrix:
        node: [18, 20, 22]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4
        with:
          node-version: ${{ matrix.node }}
      - run: npm ci --ignore-scripts
      - uses: ./.github/actions/verify-compatibility
        with:
          bundle: bundles/golden/bundle_nextjs_15_async_params.json
          dependency-root: .
```

A composite action cannot declare a job matrix; the consuming workflow owns
the matrix, operating system, dependency installation, and container boundary.

## Security

The action executes code embedded in the selected bundle. Use only reviewed
bundles and run third-party submissions in a disposable, network-restricted
job container. The emitted JSON follows the in-toto Statement envelope shape
but remains **unsigned evidence** until a separate trusted signing step signs
it. This action deliberately does not claim SLSA provenance or sign with the
workflow's identity.
