#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {
  BundleValidationError,
  VerificationError,
  createAttestation,
  loadJsonSource,
  validateBundle,
  verifySource
} = require('./index.js');

function usage() {
  return [
    'Usage:',
    '  synapse-verify <bundle-path-or-https-url> --allow-code-execution [options]',
    '  synapse-verify <bundle-path-or-https-url> --validate-only [options]',
    '',
    'Options:',
    '  --schema <path>          Validate against an explicit JSON Schema.',
    '  --attestation <path>     Write an in-toto Statement-shaped JSON artifact.',
    '  --python <executable>    Python interpreter for Python verification scripts.',
    '  --dependency-root <path> Root containing preinstalled Node node_modules.',
    '  --timeout-ms <number>    Cap each phase timeout.',
    '  --keep-workspaces        Preserve temporary workspaces for debugging.',
    '  --allow-code-execution   Required acknowledgement for executing bundle code.',
    '  --validate-only          Validate JSON and semantics without executing code.',
    '  --help                   Show this help.',
    '',
    'Security: the verifier creates an ephemeral workspace but is not an OS security sandbox.',
    'Run untrusted bundles only inside a disposable, network-restricted container or VM.'
  ].join('\n');
}

function parseArguments(argv) {
  const parsed = {
    source: null,
    schemaPath: null,
    attestationPath: null,
    pythonBinary: null,
    dependencyRoot: null,
    timeoutMs: null,
    keepWorkspaces: false,
    allowCodeExecution: false,
    validateOnly: false,
    help: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h') parsed.help = true;
    else if (argument === '--keep-workspaces') parsed.keepWorkspaces = true;
    else if (argument === '--allow-code-execution') parsed.allowCodeExecution = true;
    else if (argument === '--validate-only') parsed.validateOnly = true;
    else if (['--schema', '--attestation', '--python', '--dependency-root', '--timeout-ms'].includes(argument)) {
      const value = argv[index + 1];
      if (!value || value.startsWith('--')) throw new BundleValidationError(`Missing value for ${argument}`);
      index += 1;
      if (argument === '--schema') parsed.schemaPath = value;
      if (argument === '--attestation') parsed.attestationPath = value;
      if (argument === '--python') parsed.pythonBinary = value;
      if (argument === '--dependency-root') parsed.dependencyRoot = value;
      if (argument === '--timeout-ms') {
        parsed.timeoutMs = Number(value);
        if (!Number.isInteger(parsed.timeoutMs) || parsed.timeoutMs < 100 || parsed.timeoutMs > 300_000) {
          throw new BundleValidationError('--timeout-ms must be an integer between 100 and 300000');
        }
      }
    } else if (argument.startsWith('-')) {
      throw new BundleValidationError(`Unknown option: ${argument}`);
    } else if (parsed.source === null) {
      parsed.source = argument;
    } else {
      throw new BundleValidationError(`Unexpected positional argument: ${argument}`);
    }
  }
  return parsed;
}

function writeJson(destination, value) {
  const absolute = path.resolve(destination);
  fs.mkdirSync(path.dirname(absolute), { recursive: true });
  fs.writeFileSync(absolute, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

async function main() {
  let args;
  try {
    args = parseArguments(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n\n${usage()}\n`);
    return 2;
  }

  if (args.help) {
    process.stdout.write(`${usage()}\n`);
    return 0;
  }
  if (!args.source) {
    process.stderr.write(`${usage()}\n`);
    return 2;
  }
  if (!args.validateOnly && !args.allowCodeExecution) {
    process.stderr.write('Refusing to execute bundle code without --allow-code-execution.\n');
    return 2;
  }

  let result;
  try {
    if (args.validateOnly) {
      const source = await loadJsonSource(args.source);
      const schema = args.schemaPath ? (await loadJsonSource(args.schemaPath)).value : null;
      validateBundle(source.value, schema);
      result = {
        verified: false,
        validationOnly: true,
        validationPassed: true,
        bundleId: source.value.bundleId,
        bundleVersion: source.value.schemaVersion,
        bundleSha256: source.sha256,
        failureReason: null,
        verifier: { name: '@synapse-mesh/verify', version: '0.1.0' }
      };
    } else {
      result = await verifySource(args.source, {
        schemaPath: args.schemaPath,
        allowCodeExecution: true,
        keepWorkspaces: args.keepWorkspaces,
        pythonBinary: args.pythonBinary,
        dependencyRoot: args.dependencyRoot,
        timeoutMs: args.timeoutMs || undefined
      });
    }
  } catch (error) {
    result = {
      verified: false,
      validationOnly: Boolean(args.validateOnly),
      validationPassed: false,
      bundleId: null,
      bundleSha256: null,
      failureReason: error.message,
      validationErrors: error instanceof BundleValidationError ? error.errors : [],
      errorType: error instanceof VerificationError || error instanceof BundleValidationError ? error.name : 'UnexpectedError',
      verifier: { name: '@synapse-mesh/verify', version: '0.1.0' }
    };
  }

  const attestation = createAttestation(result, args.source);
  if (args.attestationPath) writeJson(args.attestationPath, attestation);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  return (result.validationOnly && result.validationPassed) || result.verified ? 0 : 1;
}

main()
  .then((exitCode) => { process.exitCode = exitCode; })
  .catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 2;
  });
