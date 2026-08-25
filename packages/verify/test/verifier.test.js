'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  BundleValidationError,
  VerificationError,
  applyUnifiedDiff,
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
      pinnedDependencies: { node: '20.0.0' },
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

test('validates the contract against the shipped Draft 2020-12 schema subset', () => {
  const schema = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../schemas/compatibility_bundle_v1.json'), 'utf8'));
  const bundle = syntheticBundle();
  assert.deepEqual(validateInstanceAgainstSchema(bundle, schema), { valid: true, errors: [] });

  bundle.status = 'STALE';
  const stale = validateInstanceAgainstSchema(bundle, schema);
  assert.equal(stale.valid, false);
  assert.match(stale.errors.join('\n'), /statusReason/);

  bundle.statusReason = 'Upstream released a replacement';
  assert.equal(validateInstanceAgainstSchema(bundle, schema).valid, true);

  bundle.patch.pinnedDependencies.node = '>=20';
  const rangedPin = validateInstanceAgainstSchema(bundle, schema);
  assert.equal(rangedPin.valid, false);
});

test('requires explicit code-execution authorization', async () => {
  await assert.rejects(() => verifyBundle(syntheticBundle()), VerificationError);
});

test('fails closed when the exact runtime preflight does not match', async () => {
  const bundle = syntheticBundle();
  bundle.scope.runtimeVersion = '0.0.1';
  const result = await verifyBundle(bundle, { allowCodeExecution: true });
  assert.equal(result.verified, false);
  assert.match(result.failureReason, /Environment preflight failed/);
  assert.equal(result.phases.preFail, null);
});

test('passes all four gates and rejects both mutations', async () => {
  const result = await verifyBundle(syntheticBundle(), { allowCodeExecution: true, skipEnvironmentCheck: true });
  assert.equal(result.verified, true, result.failureReason);
  assert.equal(result.preExit, 7);
  assert.equal(result.postExit, 0);
  assert.equal(result.signatureMatched, true);
  assert.equal(result.mutantsKilled, '2/2');
  assert.equal(result.phases.mutations.every((mutation) => mutation.killed), true);
});

test('does not leave verifier workspaces behind after a normal run', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-verify-test-parent-'));
  try {
    await verifyBundle(syntheticBundle(), { allowCodeExecution: true, skipEnvironmentCheck: true, tempRoot: parent });
    assert.deepEqual(fs.readdirSync(parent), []);
  } finally {
    fs.rmSync(parent, { recursive: true, force: true });
  }
});
