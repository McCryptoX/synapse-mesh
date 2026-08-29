'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { spawnSync } = require('node:child_process');

const {
  BundleValidationError,
  VerificationError,
  applyUnifiedDiff,
  createAttestation,
  isPublicNetworkAddress,
  loadJsonSource,
  sanitizeEvidenceSource,
  testRegexSafely,
  validateBundle,
  validateInstanceAgainstSchema,
  verifyBundle
} = require('../index.js');

function syntheticBundle() {
  return {
    schemaVersion: '1.0.0',
    bundleId: 'bundle_test_runtime_001',
    status: 'VERIFIED',
    scope: {
      package: 'example-package',
      fromVersion: '1.0.0',
      toVersion: '2.0.0',
      runtime: 'nodejs',
      runtimeVersion: '20.0.0',
      platform: 'all'
    },
    fingerprint: {
      errorSignature: 'EXAMPLE_OLD_BEHAVIOR',
      regex: 'EXAMPLE_OLD_BEHAVIOR',
      regexFlags: '',
      matchStream: 'combined'
    },
    patch: {
      targetFile: 'subject.js',
      unifiedDiff: [
        '--- a/subject.js',
        '+++ b/subject.js',
        '@@ -1,1 +1,1 @@',
        '-module.exports = () => "old";',
        '+module.exports = () => "new";',
        ''
      ].join('\n'),
      pinnedDependencies: { 'example-package': '2.0.0' },
      doNot: ['Return a value other than new']
    },
    verification: {
      scriptLanguage: 'javascript',
      workspaceFiles: { 'subject.js': 'module.exports = () => "old";\n' },
      reproductionScript: [
        "const value = require('../subject.js')();",
        "if (value === 'old') { console.error('EXAMPLE_OLD_BEHAVIOR'); process.exit(7); }",
        'process.exit(0);'
      ].join('\n'),
      testSuite: [
        "const assert = require('node:assert/strict');",
        "const value = require('../subject.js')();",
        "assert.equal(value, 'new');"
      ].join('\n'),
      mutations: [
        {
          id: 'unchanged-old-value',
          description: 'Leaves the behavior unchanged',
          unifiedDiff: [
            '--- a/subject.js',
            '+++ b/subject.js',
            '@@ -1,1 +1,1 @@',
            '-module.exports = () => "old";',
            '+module.exports = () => "old";',
            ''
          ].join('\n')
        },
        {
          id: 'wrong-value',
          description: 'Returns an unrelated value',
          unifiedDiff: [
            '--- a/subject.js',
            '+++ b/subject.js',
            '@@ -1,1 +1,1 @@',
            '-module.exports = () => "old";',
            '+module.exports = () => "wrong";',
            ''
          ].join('\n')
        }
      ],
      expectedPreExit: 7,
      expectedPostExit: 0,
      timeoutMs: 3000
    },
    provenance: {
      spdxLicense: 'MIT',
      primarySources: ['https://example.com/release-notes'],
      verifiedAt: '2026-08-25T00:00:00Z'
    }
  };
}

function createSyntheticNodeEnvironment(prefix = 'synapse-node-environment-') {
  const dependencyRoot = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const packageRoot = path.join(dependencyRoot, 'node_modules', 'example-package');
  fs.mkdirSync(packageRoot, { recursive: true });
  fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
  fs.writeFileSync(path.join(packageRoot, 'index.js'), 'module.exports = "installed";\n');
  const bundle = syntheticBundle();
  bundle.scope.runtimeVersion = process.versions.node;
  return { bundle, dependencyRoot };
}

function createFakeRustToolchain(prefix, packageVersions, metadataOverride = null) {
  const toolRoot = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const rustc = path.join(toolRoot, 'rustc');
  fs.writeFileSync(rustc, [
    '#!/bin/sh',
    'if [ "$1" = "--version" ]; then printf \'%s\\n\' \'rustc 1.85.0\'; exit 0; fi',
    'if [ "$1" = "--print" ] && [ "$2" = "sysroot" ]; then printf \'%s\\n\' "$PWD/nonexistent-sysroot"; exit 0; fi',
    'exit 2',
    ''
  ].join('\n'), { mode: 0o755 });
  const packages = packageVersions.map((version) => ({
    id: `path+file:///workspace#example-package@${version}`,
    name: 'example-package',
    version,
    source: null,
    manifest_path: 'Cargo.toml'
  }));
  const metadata = metadataOverride || {
    packages,
    resolve: {
      root: packages[packages.length - 1].id,
      nodes: packages.map((entry) => ({ id: entry.id, dependencies: [], deps: [], features: [] }))
    }
  };
  const cargo = path.join(toolRoot, 'cargo');
  fs.writeFileSync(cargo, [
    '#!/bin/sh',
    'if [ "$1" = "--version" ]; then printf \'%s\\n\' \'cargo 1.85.0\'; exit 0; fi',
    `if [ "$1" = "metadata" ]; then printf '%s\\n' '${JSON.stringify(metadata)}'; exit 0; fi`,
    'exit 2',
    ''
  ].join('\n'), { mode: 0o755 });
  return toolRoot;
}

test('applies a single-file unified diff with checked context', () => {
  const diff = [
    '--- a/example.txt',
    '+++ b/example.txt',
    '@@ -1,2 +1,2 @@',
    ' first',
    '-second',
    '+changed',
    ''
  ].join('\n');
  assert.equal(applyUnifiedDiff('first\nsecond\n', diff, 'example.txt'), 'first\nchanged\n');
  assert.throws(() => applyUnifiedDiff('different\nsecond\n', diff, 'example.txt'), VerificationError);
});

test('rejects unsafe paths and malformed mutation contracts', () => {
  const bundle = syntheticBundle();
  bundle.patch.targetFile = '../subject.js';
  assert.throws(() => validateBundle(bundle), BundleValidationError);
});

test('binds an exact scope target to the pinned scoped package', () => {
  const bundle = syntheticBundle();
  bundle.patch.pinnedDependencies['example-package'] = '2.0.1';
  assert.throws(
    () => validateBundle(bundle),
    (error) => error instanceof BundleValidationError && /exact target 2\.0\.0/.test(error.errors.join('\n'))
  );
});

test('requires mutation patches and resulting fixtures to be distinct', () => {
  const bundle = syntheticBundle();
  bundle.verification.mutations[1].unifiedDiff = bundle.verification.mutations[0].unifiedDiff;
  assert.throws(
    () => validateBundle(bundle),
    (error) => error instanceof BundleValidationError && /duplicate mutation patch/.test(error.errors.join('\n'))
  );
});

test('uses the bundled schema by default and keeps it byte-for-byte synchronized', () => {
  const canonicalPath = path.resolve(__dirname, '../../../schemas/compatibility_bundle_v1.json');
  const bundledPath = path.resolve(__dirname, '../schema/compatibility_bundle_v1.json');
  assert.equal(fs.readFileSync(bundledPath, 'utf8'), fs.readFileSync(canonicalPath, 'utf8'));
  const canonicalSchema = JSON.parse(fs.readFileSync(canonicalPath, 'utf8'));
  assert.doesNotThrow(() => validateBundle(syntheticBundle(), canonicalSchema));

  const incomplete = syntheticBundle();
  delete incomplete.schemaVersion;
  delete incomplete.status;
  assert.throws(
    () => validateBundle(incomplete),
    (error) => error instanceof BundleValidationError && /missing required property/.test(error.errors.join('\n'))
  );
  assert.throws(
    () => validateBundle(incomplete, {}),
    (error) => error instanceof BundleValidationError && /missing required property/.test(error.errors.join('\n'))
  );
});

test('rejects unsupported or synchronously dangerous custom schema keywords', () => {
  const bundle = syntheticBundle();
  assert.throws(
    () => validateBundle(bundle, { not: {} }),
    (error) => error instanceof BundleValidationError && /unsupported JSON Schema keyword not/.test(error.message)
  );
  assert.throws(
    () => validateBundle(bundle, { $ref: '' }),
    (error) => error instanceof BundleValidationError && /local JSON Pointer/.test(error.message)
  );
  assert.throws(
    () => validateBundle(bundle, { type: '' }),
    (error) => error instanceof BundleValidationError && /type declaration/.test(error.message)
  );
  assert.throws(
    () => validateBundle(bundle, { properties: { bundleId: { pattern: '.*' } } }),
    (error) => error instanceof BundleValidationError && /pattern is not supported in custom schema overlays/.test(error.message)
  );
});

test('honors boolean overlays, ref siblings, conditionals, and own-property JSON Pointers', () => {
  const bundle = syntheticBundle();
  assert.throws(
    () => validateBundle(bundle, false),
    (error) => error instanceof BundleValidationError && /value is forbidden/.test(error.errors.join('\n'))
  );
  assert.throws(
    () => validateBundle(bundle, {
      $defs: { permissive: true },
      $ref: '#/$defs/permissive',
      required: ['missing-ref-sibling']
    }),
    (error) => error instanceof BundleValidationError && /missing-ref-sibling/.test(error.errors.join('\n'))
  );
  assert.throws(
    () => validateBundle(bundle, { if: true, then: false }),
    (error) => error instanceof BundleValidationError && /value is forbidden/.test(error.errors.join('\n'))
  );
  assert.throws(
    () => validateBundle(bundle, { $ref: '#/__proto__' }),
    (error) => error instanceof BundleValidationError && /Unresolved JSON Schema reference/.test(error.message)
  );
  assert.throws(
    () => validateBundle(bundle, {
      $defs: { loop: { $ref: '#/$defs/loop' } },
      $ref: '#/$defs/loop'
    }),
    (error) => error instanceof BundleValidationError && /maximum reference depth/.test(error.message)
  );
  assert.throws(
    () => validateBundle(bundle, { required: ['toString'] }),
    (error) => error instanceof BundleValidationError && /toString/.test(error.errors.join('\n'))
  );
  assert.throws(
    () => validateBundle(bundle, { dependentRequired: { bundleId: ['toString'] } }),
    (error) => error instanceof BundleValidationError && /toString/.test(error.errors.join('\n'))
  );
  const prototypeKey = validateInstanceAgainstSchema(
    JSON.parse('{"__proto__":1}'),
    { type: 'object', properties: {}, additionalProperties: false }
  );
  assert.equal(prototypeKey.valid, false);
  assert.match(prototypeKey.errors.join('\n'), /additional property is not allowed/);
  assert.equal(validateInstanceAgainstSchema([1], { items: false }).valid, false);
  assert.equal(validateInstanceAgainstSchema({ key: 1 }, { propertyNames: false }).valid, false);
  let deeplyNested = true;
  for (let index = 0; index < 300; index += 1) deeplyNested = { items: deeplyNested };
  assert.throws(
    () => validateBundle(bundle, deeplyNested),
    (error) => error instanceof BundleValidationError && /nesting exceeds/.test(error.message)
  );
});

test('rejects impossible RFC 3339 calendar dates', () => {
  const bundle = syntheticBundle();
  bundle.provenance.verifiedAt = '2026-02-30T00:00:00Z';
  assert.throws(
    () => validateBundle(bundle),
    (error) => error instanceof BundleValidationError && /RFC 3339 date-time/.test(error.errors.join('\n'))
  );
  bundle.provenance.verifiedAt = '2024-02-29T23:59:59+01:00';
  assert.doesNotThrow(() => validateBundle(bundle));
});

test('checks patch.sha256 even when the integrity object is absent', () => {
  const bundle = syntheticBundle();
  bundle.patch.sha256 = '0'.repeat(64);
  assert.throws(
    () => validateBundle(bundle),
    (error) => error instanceof BundleValidationError && /patch\/sha256/.test(error.errors.join('\n'))
  );
});

test('validates the contract against the shipped Draft 2020-12 schema subset', () => {
  const schema = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../schemas/compatibility_bundle_v1.json'), 'utf8'));
  const lifecycleStatuses = [
    'DRAFT', 'CANDIDATE', 'UNVERIFIED', 'PROVISIONAL', 'VERIFIED',
    'STALE', 'BROKEN', 'DISPUTED', 'SUPERSEDED', 'REVOKED'
  ];
  const reasonRequiredStatuses = new Set(['STALE', 'BROKEN', 'DISPUTED', 'SUPERSEDED', 'REVOKED']);
  assert.deepEqual(schema.properties.status.enum, lifecycleStatuses);

  for (const status of lifecycleStatuses) {
    const bundle = syntheticBundle();
    bundle.status = status;
    const withoutReason = validateInstanceAgainstSchema(bundle, schema);
    if (reasonRequiredStatuses.has(status)) {
      assert.equal(withoutReason.valid, false, status);
      assert.match(withoutReason.errors.join('\n'), /statusReason/, status);
      bundle.statusReason = `${status} lifecycle reason`;
    }
    assert.equal(validateInstanceAgainstSchema(bundle, schema).valid, true, status);
  }

  const unknown = syntheticBundle();
  unknown.status = 'UNKNOWN';
  assert.equal(validateInstanceAgainstSchema(unknown, schema).valid, false);

  const rangedBundle = syntheticBundle();
  rangedBundle.patch.pinnedDependencies.node = '>=20';
  const rangedPin = validateInstanceAgainstSchema(rangedBundle, schema);
  assert.equal(rangedPin.valid, false);
});

test('time-boxes fingerprint regex evaluation in a worker', async () => {
  const normal = await testRegexSafely('BREAKING_CHANGE', '', 'prefix BREAKING_CHANGE suffix', 500);
  assert.deepEqual(normal, { matched: true, timedOut: false, error: null });

  const pathological = await testRegexSafely('^(a+)+$', '', `${'a'.repeat(100_000)}!`, 25);
  assert.equal(pathological.matched, false);
  assert.equal(pathological.timedOut, true);
});

test('rejects private and metadata-service addresses for HTTPS retrieval', () => {
  for (const address of ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1', 'fc00::1']) {
    assert.equal(isPublicNetworkAddress(address), false, address);
  }
  assert.equal(isPublicNetworkAddress('8.8.8.8'), true);
  assert.equal(isPublicNetworkAddress('2606:4700:4700::1111'), true);
});

test('refuses an HTTPS bundle URL that resolves to loopback', async () => {
  await assert.rejects(
    () => loadJsonSource('https://127.0.0.1/private-bundle.json', { fetchTimeoutMs: 1000 }),
    (error) => error instanceof BundleValidationError && /non-public network address/.test(error.message)
  );
});

test('fails source retrieval when the absolute total deadline is exhausted', async () => {
  await assert.rejects(
    () => loadJsonSource('https://example.com/bundle.json', { deadlineMs: Date.now() - 1 }),
    (error) => error instanceof BundleValidationError && /Total source-loading time budget exceeded/.test(error.message)
  );
});

test('redacts local paths and remote URL details from attestation metadata', () => {
  assert.equal(sanitizeEvidenceSource('/sensitive/source/bundle.json'), 'local-file');
  assert.equal(sanitizeEvidenceSource('https://example.com/private/bundle.json?token=secret'), 'https-url');
  const statement = createAttestation({
    bundleId: 'bundle_test_runtime_001',
    bundleSha256: 'a'.repeat(64),
    verified: false,
    failureReason: 'Unable to read /sensitive/source/bundle.json',
    errorType: 'UnexpectedError',
    phases: {
      environment: {
        passed: false,
        mismatches: ['/sensitive/dependency-root does not match']
      },
      preFail: {
        stdout: 'SENSITIVE_OUTPUT_MARKER',
        stderr: '/sensitive/dependency/file.py',
        stdoutSha256: 'b'.repeat(64),
        stderrSha256: 'c'.repeat(64)
      }
    }
  }, '/sensitive/source/bundle.json');
  assert.equal(statement.predicate.source, 'local-file');
  assert.equal(statement.predicate.failureReason, 'VERIFICATION_FAILED');
  assert.doesNotMatch(JSON.stringify(statement), /\/sensitive\//);
  assert.doesNotMatch(JSON.stringify(statement), /SENSITIVE_OUTPUT_MARKER/);
  assert.equal(statement.predicate.phases.preFail.stdoutSha256, 'b'.repeat(64));
});

test('validate-only CLI exits non-zero for an invalid bundle', () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-verify-cli-test-'));
  try {
    const invalidPath = path.join(parent, 'invalid.json');
    const invalid = syntheticBundle();
    invalid.patch.pinnedDependencies['example-package'] = '>=2';
    fs.writeFileSync(invalidPath, JSON.stringify(invalid));
    const attestationPath = path.join(parent, 'failure-evidence.json');
    const result = spawnSync(process.execPath, [
      path.resolve(__dirname, '../bin.js'),
      invalidPath,
      '--schema', path.resolve(__dirname, '../../../schemas/compatibility_bundle_v1.json'),
      '--validate-only',
      '--attestation', attestationPath
    ], { encoding: 'utf8', shell: false });
    assert.equal(result.status, 1, result.stderr);
    const output = JSON.parse(result.stdout);
    assert.equal(output.validationOnly, true);
    assert.equal(output.validationPassed, false);
    const statement = JSON.parse(fs.readFileSync(attestationPath, 'utf8'));
    assert.equal(statement.subject[0].digest.sha256, output.bundleSha256);
    assert.equal(statement.predicate.failureReason, 'BUNDLE_VALIDATION_FAILED');
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('binds CLI validation to an expected bundle digest', () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-verify-digest-test-'));
  try {
    const bundlePath = path.join(parent, 'bundle.json');
    const attestationPath = path.join(parent, 'failure-evidence.json');
    fs.writeFileSync(bundlePath, JSON.stringify(syntheticBundle()));
    const result = spawnSync(process.execPath, [
      path.resolve(__dirname, '../bin.js'),
      bundlePath,
      '--expected-sha256', '0'.repeat(64),
      '--validate-only',
      '--attestation', attestationPath
    ], { encoding: 'utf8', shell: false });
    assert.equal(result.status, 1, result.stderr);
    const output = JSON.parse(result.stdout);
    const statement = JSON.parse(fs.readFileSync(attestationPath, 'utf8'));
    assert.match(output.bundleSha256, /^[a-f0-9]{64}$/);
    assert.equal(statement.subject[0].digest.sha256, output.bundleSha256);
    assert.equal(statement.predicate.failureReason, 'BUNDLE_VALIDATION_FAILED');
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('preserves every valid lifecycle status in validation evidence', () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-verify-status-test-'));
  try {
    const bundlePath = path.join(parent, 'bundle.json');
    const attestationPath = path.join(parent, 'evidence.json');
    const lifecycleStatuses = [
      'DRAFT', 'CANDIDATE', 'UNVERIFIED', 'PROVISIONAL', 'VERIFIED',
      'STALE', 'BROKEN', 'DISPUTED', 'SUPERSEDED', 'REVOKED'
    ];
    const reasonRequiredStatuses = new Set(['STALE', 'BROKEN', 'DISPUTED', 'SUPERSEDED', 'REVOKED']);
    for (const status of lifecycleStatuses) {
      const bundle = syntheticBundle();
      bundle.status = status;
      if (reasonRequiredStatuses.has(status)) bundle.statusReason = `${status} lifecycle reason`;
      fs.writeFileSync(bundlePath, JSON.stringify(bundle));
      const result = spawnSync(process.execPath, [
        path.resolve(__dirname, '../bin.js'),
        bundlePath,
        '--validate-only',
        '--attestation', attestationPath
      ], { encoding: 'utf8', shell: false });
      assert.equal(result.status, 0, `${status}: ${result.stderr}`);
      const output = JSON.parse(result.stdout);
      const statement = JSON.parse(fs.readFileSync(attestationPath, 'utf8'));
      assert.equal(output.bundleStatus, status);
      assert.equal(statement.predicate.bundleStatus, status);
    }
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('requires explicit code-execution authorization', async () => {
  await assert.rejects(() => verifyBundle(syntheticBundle()), VerificationError);
});

test('refuses stale lifecycle state by default but permits an explicit re-verification', async () => {
  const bundle = syntheticBundle();
  bundle.status = 'STALE';
  bundle.statusReason = 'Evidence freshness window elapsed';
  await assert.rejects(
    () => verifyBundle(bundle, { allowCodeExecution: true }),
    (error) => error instanceof VerificationError && /STALE/.test(error.message)
  );

  bundle.scope.runtimeVersion = process.versions.node;
  const result = await verifyBundle(bundle, { allowCodeExecution: true, allowStale: true });
  assert.equal(result.bundleStatus, 'STALE');
  assert.equal(result.verified, false);
  assert.match(result.failureReason, /Environment preflight failed/);
});

test('always refuses non-executable lifecycle states even when allowStale is set', async () => {
  for (const status of ['BROKEN', 'DISPUTED', 'SUPERSEDED', 'REVOKED']) {
    const bundle = syntheticBundle();
    bundle.status = status;
    bundle.statusReason = 'Superseded or withdrawn';
    await assert.rejects(
      () => verifyBundle(bundle, { allowCodeExecution: true, allowStale: true }),
      (error) => error instanceof VerificationError && new RegExp(status).test(error.message)
    );
  }
});

test('fails closed when the exact runtime preflight does not match', async () => {
  const bundle = syntheticBundle();
  bundle.scope.runtimeVersion = '0.0.1';
  const result = await verifyBundle(bundle, { allowCodeExecution: true });
  assert.equal(result.verified, false);
  assert.match(result.failureReason, /Environment preflight failed/);
  assert.equal(result.phases.preFail, null);
});

test('does not let a stale pnpm-store copy override the resolved package version', async () => {
  const dependencyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-pnpm-resolution-'));
  try {
    const directRoot = path.join(dependencyRoot, 'node_modules', 'example-package');
    const staleRoot = path.join(
      dependencyRoot,
      'node_modules',
      '.pnpm',
      'example-package@2.0.0',
      'node_modules',
      'example-package'
    );
    fs.mkdirSync(directRoot, { recursive: true });
    fs.mkdirSync(staleRoot, { recursive: true });
    fs.writeFileSync(path.join(directRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '1.0.0' }));
    fs.writeFileSync(path.join(directRoot, 'index.js'), 'module.exports = "resolved-1.0.0";\n');
    fs.writeFileSync(path.join(staleRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.packages['example-package'].actual, '1.0.0');
    assert.equal(result.phases.environment.packages['example-package'].matched, false);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('does not treat an unlinked pnpm-store package as installed', async () => {
  const dependencyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-pnpm-unlinked-'));
  try {
    const staleRoot = path.join(
      dependencyRoot,
      'node_modules',
      '.pnpm',
      'example-package@2.0.0',
      'node_modules',
      'example-package'
    );
    fs.mkdirSync(staleRoot, { recursive: true });
    fs.writeFileSync(path.join(staleRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.packages['example-package'].actual, null);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('does not resolve a scoped package from an ancestor node_modules directory', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-node-ancestor-'));
  try {
    const dependencyRoot = path.join(parent, 'project');
    const ancestorPackage = path.join(parent, 'node_modules', 'example-package');
    fs.mkdirSync(path.join(dependencyRoot, 'node_modules'), { recursive: true });
    fs.mkdirSync(ancestorPackage, { recursive: true });
    fs.writeFileSync(path.join(ancestorPackage, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
    fs.writeFileSync(path.join(ancestorPackage, 'index.js'), 'module.exports = "ancestor";\n');

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.packages['example-package'].actual, null);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('rejects a package symlink whose target escapes dependencyRoot', async (context) => {
  if (process.platform === 'win32') {
    context.skip('symlink fixture requires POSIX link semantics');
    return;
  }
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-node-external-link-'));
  try {
    const dependencyRoot = path.join(parent, 'project');
    const externalPackage = path.join(parent, 'external-package');
    fs.mkdirSync(path.join(dependencyRoot, 'node_modules'), { recursive: true });
    fs.mkdirSync(externalPackage, { recursive: true });
    fs.writeFileSync(path.join(externalPackage, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
    fs.writeFileSync(path.join(externalPackage, 'index.js'), 'module.exports = "external";\n');
    fs.symlinkSync(externalPackage, path.join(dependencyRoot, 'node_modules', 'example-package'));

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.packages['example-package'].actual, null);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('rejects multiply linked files in a Node dependency tree', async (context) => {
  if (process.platform === 'win32') {
    context.skip('hard-link fixture requires POSIX filesystem semantics');
    return;
  }
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-node-hard-link-'));
  try {
    const dependencyRoot = path.join(parent, 'dependencies');
    const packageRoot = path.join(dependencyRoot, 'node_modules', 'example-package');
    const externalFile = path.join(parent, 'external-index.js');
    fs.mkdirSync(packageRoot, { recursive: true });
    fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
    fs.writeFileSync(externalFile, 'module.exports = "external";\n');
    fs.linkSync(externalFile, path.join(packageRoot, 'index.js'));

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.match(result.failureReason, /Environment preflight failed/);
    assert.equal(result.phases.environment.dependencyTreeSha256, null);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('repeats Rust toolchain and Cargo.lock integrity probes without collisions', async (context) => {
  if (process.platform === 'win32') {
    context.skip('POSIX executable fixture');
    return;
  }
  const toolRoot = createFakeRustToolchain('synapse-rust-probe-', ['2.0.0']);
  try {
    const bundle = syntheticBundle();
    bundle.scope.runtime = 'rust';
    bundle.scope.runtimeVersion = '1.85.0';
    bundle.verification.workspaceFiles['Cargo.toml'] = [
      '[package]',
      'name = "example-package"',
      'version = "2.0.0"',
      'edition = "2021"',
      ''
    ].join('\n');
    bundle.verification.workspaceFiles['Cargo.lock'] = [
      'version = 4',
      '',
      '[[package]]',
      'name = "example-package"',
      'version = "2.0.0"',
      ''
    ].join('\n');
    const result = await verifyBundle(bundle, {
      allowCodeExecution: true,
      environment: { PATH: `${toolRoot}${path.delimiter}${process.env.PATH || ''}` }
    });
    assert.equal(result.verified, true, result.failureReason);
    assert.equal(result.phases.environment.dependencyIntegrityKind, 'rust-toolchain-and-resolved-source-tree');
    assert.equal(result.phases.dependencyIntegrity.length, 4);
    assert.equal(result.phases.dependencyIntegrity.every((entry) => entry.matched), true);
  } finally {
    fs.rmSync(toolRoot, { recursive: true, force: true });
  }
});

test('binds each resolved Rust source digest to its Cargo package identity', async (context) => {
  if (process.platform === 'win32') {
    context.skip('POSIX executable fixture');
    return;
  }
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-rust-source-binding-'));
  let toolRoot = null;
  try {
    const sourceA = path.join(parent, 'source-a');
    const sourceB = path.join(parent, 'source-b');
    fs.mkdirSync(sourceA);
    fs.mkdirSync(sourceB);
    for (const sourceRoot of [sourceA, sourceB]) {
      fs.writeFileSync(path.join(sourceRoot, 'Cargo.toml'), '[package]\nname = "placeholder"\nversion = "1.0.0"\n');
    }
    const payloadA = path.join(sourceA, 'payload.rs');
    const payloadB = path.join(sourceB, 'payload.rs');
    fs.writeFileSync(payloadA, 'pub const VALUE: &str = "A";\n');
    fs.writeFileSync(payloadB, 'pub const VALUE: &str = "B";\n');

    const workspaceId = 'path+file:///workspace#example-package@2.0.0';
    const dependencyAId = 'registry+https://example.invalid/index#dep-a@1.0.0';
    const dependencyBId = 'registry+https://example.invalid/index#dep-b@1.0.0';
    const metadata = {
      packages: [
        { id: workspaceId, name: 'example-package', version: '2.0.0', source: null, manifest_path: 'Cargo.toml' },
        { id: dependencyAId, name: 'dep-a', version: '1.0.0', source: 'registry+https://example.invalid/index', manifest_path: path.join(sourceA, 'Cargo.toml') },
        { id: dependencyBId, name: 'dep-b', version: '1.0.0', source: 'registry+https://example.invalid/index', manifest_path: path.join(sourceB, 'Cargo.toml') }
      ],
      resolve: {
        root: workspaceId,
        nodes: [
          {
            id: workspaceId,
            dependencies: [dependencyAId, dependencyBId],
            deps: [
              { name: 'dep_a', pkg: dependencyAId, dep_kinds: [{ kind: null, target: null }] },
              { name: 'dep_b', pkg: dependencyBId, dep_kinds: [{ kind: null, target: null }] }
            ],
            features: []
          },
          { id: dependencyAId, dependencies: [], deps: [], features: [] },
          { id: dependencyBId, dependencies: [], deps: [], features: [] }
        ]
      }
    };
    toolRoot = createFakeRustToolchain('synapse-rust-source-binding-tools-', ['2.0.0'], metadata);
    const bundle = syntheticBundle();
    bundle.scope.runtime = 'rust';
    bundle.scope.runtimeVersion = '1.85.0';
    bundle.verification.workspaceFiles['Cargo.toml'] = '[package]\nname = "example-package"\nversion = "2.0.0"\n';
    bundle.verification.reproductionScript = [
      "const fs = require('node:fs');",
      `const first = ${JSON.stringify(payloadA)};`,
      `const second = ${JSON.stringify(payloadB)};`,
      "const firstBytes = fs.readFileSync(first);",
      "fs.writeFileSync(first, fs.readFileSync(second));",
      "fs.writeFileSync(second, firstBytes);",
      "console.error('EXAMPLE_OLD_BEHAVIOR');",
      'process.exit(7);'
    ].join('\n');
    const result = await verifyBundle(bundle, {
      allowCodeExecution: true,
      environment: { PATH: `${toolRoot}${path.delimiter}${process.env.PATH || ''}` }
    });
    assert.equal(result.verified, false);
    assert.equal(result.phases.dependencyIntegrity.length, 1);
    assert.equal(result.phases.dependencyIntegrity[0].phase, 'pre-fail');
    assert.equal(result.phases.dependencyIntegrity[0].matched, false);
  } finally {
    if (toolRoot) fs.rmSync(toolRoot, { recursive: true, force: true });
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('fails closed when Cargo.lock contains multiple versions of a pinned crate', async (context) => {
  if (process.platform === 'win32') {
    context.skip('POSIX executable fixture');
    return;
  }
  const toolRoot = createFakeRustToolchain('synapse-rust-ambiguous-lock-', ['1.0.0', '2.0.0']);
  try {
    const bundle = syntheticBundle();
    bundle.scope.runtime = 'rust';
    bundle.scope.runtimeVersion = '1.85.0';
    bundle.verification.workspaceFiles['Cargo.toml'] = [
      '[package]',
      'name = "example-package"',
      'version = "2.0.0"',
      'edition = "2021"',
      ''
    ].join('\n');
    bundle.verification.workspaceFiles['Cargo.lock'] = [
      'version = 4',
      '',
      '[[package]]',
      'name = "example-package"',
      'version = "1.0.0"',
      '',
      '[[package]]',
      'name = "example-package"',
      'version = "2.0.0"',
      ''
    ].join('\n');
    const result = await verifyBundle(bundle, {
      allowCodeExecution: true,
      environment: { PATH: `${toolRoot}${path.delimiter}${process.env.PATH || ''}` }
    });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.packages['example-package'].actual, '1.0.0,2.0.0');
    assert.equal(result.phases.environment.packages['example-package'].matched, false);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(toolRoot, { recursive: true, force: true });
  }
});

test('isolates the trusted Python preflight from workspace module shadowing', async () => {
  const bundle = syntheticBundle();
  bundle.scope.runtime = 'python';
  bundle.scope.runtimeVersion = '9.9.9';
  bundle.verification.scriptLanguage = 'python';
  bundle.verification.workspaceFiles['platform.py'] = 'def python_version():\n    return "9.9.9"\n';
  bundle.verification.workspaceFiles['json.py'] = [
    'def dumps(value, sort_keys=False):',
    '    return \'{"runtimeVersion":"9.9.9","packages":{"example-package":"2.0.0"}}\''
  ].join('\n');
  const result = await verifyBundle(bundle, { allowCodeExecution: true });
  assert.equal(result.verified, false);
  assert.equal(result.phases.environment.passed, false);
  assert.notEqual(result.phases.environment.runtime.actual, '9.9.9');
});

test('rejects Python site-packages links that escape the dependency tree', async (context) => {
  if (process.platform === 'win32') {
    context.skip('symlink fixture requires POSIX link semantics');
    return;
  }
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-python-external-link-'));
  try {
    const venvRoot = path.join(parent, 'venv');
    const created = spawnSync('python3', ['-m', 'venv', venvRoot], { encoding: 'utf8', shell: false });
    if (created.error || created.status !== 0) {
      context.skip('python3 venv support is unavailable');
      return;
    }
    const pythonBinary = path.join(venvRoot, 'bin', 'python');
    const runtimeProbe = spawnSync(pythonBinary, ['-I', '-c', 'import platform; print(platform.python_version())'], {
      encoding: 'utf8',
      shell: false
    });
    const purelibProbe = spawnSync(pythonBinary, ['-I', '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], {
      encoding: 'utf8',
      shell: false
    });
    assert.equal(runtimeProbe.status, 0, runtimeProbe.stderr);
    assert.equal(purelibProbe.status, 0, purelibProbe.stderr);
    const purelib = purelibProbe.stdout.trim();
    const externalModule = path.join(parent, 'example_package.py');
    fs.writeFileSync(externalModule, 'VALUE = "external"\n');
    fs.symlinkSync(externalModule, path.join(purelib, 'example_package.py'));
    const distInfo = path.join(purelib, 'example_package-2.0.0.dist-info');
    fs.mkdirSync(distInfo, { recursive: true });
    fs.writeFileSync(
      path.join(distInfo, 'METADATA'),
      'Metadata-Version: 2.1\nName: example-package\nVersion: 2.0.0\n'
    );

    const bundle = syntheticBundle();
    bundle.scope.runtime = 'python';
    bundle.scope.runtimeVersion = runtimeProbe.stdout.trim();
    bundle.verification.scriptLanguage = 'python';
    const result = await verifyBundle(bundle, { allowCodeExecution: true, pythonBinary });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.probe.exitCode, 86);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('rejects Python .pth path injection before executing bundle phases', async (context) => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-python-pth-path-'));
  try {
    const venvRoot = path.join(parent, 'venv');
    const created = spawnSync('python3', ['-m', 'venv', venvRoot], { encoding: 'utf8', shell: false });
    if (created.error || created.status !== 0) {
      context.skip('python3 venv support is unavailable');
      return;
    }
    const pythonBinary = process.platform === 'win32'
      ? path.join(venvRoot, 'Scripts', 'python.exe')
      : path.join(venvRoot, 'bin', 'python');
    const runtimeProbe = spawnSync(pythonBinary, ['-I', '-c', 'import platform; print(platform.python_version())'], {
      encoding: 'utf8',
      shell: false
    });
    const purelibProbe = spawnSync(pythonBinary, ['-I', '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], {
      encoding: 'utf8',
      shell: false
    });
    assert.equal(runtimeProbe.status, 0, runtimeProbe.stderr);
    assert.equal(purelibProbe.status, 0, purelibProbe.stderr);
    const purelib = purelibProbe.stdout.trim();
    const externalRoot = path.join(parent, 'external');
    fs.mkdirSync(externalRoot, { recursive: true });
    fs.writeFileSync(path.join(externalRoot, 'example_package.py'), 'VALUE = "external"\n');
    fs.writeFileSync(path.join(purelib, 'example-external.pth'), `${externalRoot}\n`);
    const distInfo = path.join(purelib, 'example_package-2.0.0.dist-info');
    fs.mkdirSync(distInfo, { recursive: true });
    fs.writeFileSync(
      path.join(distInfo, 'METADATA'),
      'Metadata-Version: 2.1\nName: example-package\nVersion: 2.0.0\n'
    );

    const bundle = syntheticBundle();
    bundle.scope.runtime = 'python';
    bundle.scope.runtimeVersion = runtimeProbe.stdout.trim();
    bundle.verification.scriptLanguage = 'python';
    const result = await verifyBundle(bundle, { allowCodeExecution: true, pythonBinary });
    assert.equal(result.verified, false);
    assert.equal(result.phases.environment.probe.exitCode, 86);
    assert.equal(result.phases.preFail, null);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});

test('enforces timeout when a descendant keeps inherited output pipes open', async () => {
  const { bundle, dependencyRoot } = createSyntheticNodeEnvironment('synapse-timeout-environment-');
  try {
    bundle.verification.timeoutMs = 100;
    bundle.verification.reproductionScript = [
      "const { spawn } = require('node:child_process');",
      "spawn(process.execPath, ['-e', 'setTimeout(() => {}, 2000)'], { stdio: ['ignore', 'inherit', 'inherit'] });",
      "console.error('EXAMPLE_OLD_BEHAVIOR');",
      'process.exit(7);'
    ].join('\n');
    const started = Date.now();
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    const elapsedMs = Date.now() - started;
    assert.equal(result.verified, false);
    assert.equal(result.phases.preFail.timedOut, true);
    assert.ok(elapsedMs < 1_000, `verification exceeded bounded termination grace: ${elapsedMs}ms`);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('enforces a fail-closed total verification time budget', async () => {
  const { bundle, dependencyRoot } = createSyntheticNodeEnvironment('synapse-total-timeout-environment-');
  try {
    bundle.verification.timeoutMs = 3000;
    bundle.verification.maxTotalDurationMs = 1000;
    bundle.verification.reproductionScript = [
      "setTimeout(() => { console.error('EXAMPLE_OLD_BEHAVIOR'); process.exit(7); }, 2000);"
    ].join('\n');
    const started = Date.now();
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    const elapsedMs = Date.now() - started;
    assert.equal(result.verified, false);
    assert.match(result.failureReason, /Total verification time budget exceeded/);
    assert.ok(elapsedMs < 1_500, `total budget exceeded bounded grace: ${elapsedMs}ms`);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('bounds dependency hashing when a phase creates an oversized sparse file', async () => {
  const dependencyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-dependency-size-limit-'));
  try {
    const packageRoot = path.join(dependencyRoot, 'node_modules', 'example-package');
    fs.mkdirSync(packageRoot, { recursive: true });
    fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
    fs.writeFileSync(path.join(packageRoot, 'index.js'), 'module.exports = "original";\n');

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    bundle.verification.maxTotalDurationMs = 1000;
    bundle.verification.reproductionScript = [
      "const fs = require('node:fs');",
      "const path = require('node:path');",
      "const located = path.join(process.env.SYNAPSE_DEPENDENCY_ROOT, 'node_modules', 'oversized.bin');",
      "const descriptor = fs.openSync(located, 'w');",
      'fs.ftruncateSync(descriptor, 8 * 1024 * 1024 * 1024);',
      'fs.closeSync(descriptor);',
      "console.error('EXAMPLE_OLD_BEHAVIOR');",
      'process.exit(7);'
    ].join('\n');
    const started = Date.now();
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    const elapsedMs = Date.now() - started;
    assert.equal(result.verified, false);
    assert.match(result.failureReason, /Dependency integrity/);
    assert.ok(elapsedMs < 1_500, `dependency hash limit did not bound execution: ${elapsedMs}ms`);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('fails closed when a phase mutates the shared Node dependency tree', async () => {
  const dependencyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-dependency-integrity-'));
  try {
    const packageRoot = path.join(dependencyRoot, 'node_modules', 'example-package');
    fs.mkdirSync(packageRoot, { recursive: true });
    fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
    fs.writeFileSync(path.join(packageRoot, 'index.js'), 'module.exports = "original";\n');

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    bundle.verification.reproductionScript = [
      "const fs = require('node:fs');",
      "const dependency = require.resolve('example-package');",
      "fs.writeFileSync(dependency, 'module.exports = \\\"poisoned\\\";\\n');",
      "console.error('EXAMPLE_OLD_BEHAVIOR');",
      'process.exit(7);'
    ].join('\n');
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.match(result.failureReason, /Dependency integrity gate failed after pre-fail/);
    assert.equal(result.phases.postPass, null);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('fails closed when a phase changes Node dependency permission bits', async (context) => {
  if (process.platform === 'win32') {
    context.skip('permission-bit fixture requires POSIX filesystem semantics');
    return;
  }
  const dependencyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-dependency-mode-'));
  try {
    const packageRoot = path.join(dependencyRoot, 'node_modules', 'example-package');
    fs.mkdirSync(packageRoot, { recursive: true });
    fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify({ name: 'example-package', version: '2.0.0' }));
    fs.writeFileSync(path.join(packageRoot, 'index.js'), 'module.exports = "original";\n', { mode: 0o600 });

    const bundle = syntheticBundle();
    bundle.scope.runtimeVersion = process.versions.node;
    bundle.verification.reproductionScript = [
      "const fs = require('node:fs');",
      "const dependency = require.resolve('example-package');",
      'fs.chmodSync(dependency, 0o777);',
      "console.error('EXAMPLE_OLD_BEHAVIOR');",
      'process.exit(7);'
    ].join('\n');
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, false);
    assert.match(result.failureReason, /Dependency integrity gate failed after pre-fail/);
    assert.equal(result.phases.postPass, null);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('passes all four gates and rejects both mutations', async () => {
  const { bundle, dependencyRoot } = createSyntheticNodeEnvironment('synapse-four-gates-environment-');
  try {
    const result = await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot });
    assert.equal(result.verified, true, result.failureReason);
    assert.equal(result.preExit, 7);
    assert.equal(result.postExit, 0);
    assert.equal(result.signatureMatched, true);
    assert.equal(result.mutantsKilled, '2/2');
    assert.equal(result.phases.mutations.every((mutation) => mutation.killed), true);
    assert.equal(result.phases.dependencyIntegrity.length, 4);
    assert.equal(result.phases.dependencyIntegrity.every((entry) => entry.matched), true);
    assert.equal('stdout' in result.phases.preFail, false);
    assert.match(result.phases.preFail.stderrSha256, /^[a-f0-9]{64}$/);
  } finally {
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});

test('does not leave verifier workspaces behind after a normal run', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-verify-test-parent-'));
  const { bundle, dependencyRoot } = createSyntheticNodeEnvironment('synapse-cleanup-environment-');
  try {
    await verifyBundle(bundle, { allowCodeExecution: true, dependencyRoot, tempRoot: parent });
    assert.deepEqual(fs.readdirSync(parent), []);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
    fs.rmSync(dependencyRoot, { recursive: true, force: true });
  }
});
