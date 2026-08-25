'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const https = require('node:https');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const VERIFIER_NAME = '@synapse-mesh/verify';
const VERIFIER_VERSION = '0.1.0';
const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_MAX_OUTPUT_BYTES = 1_000_000;
const DEFAULT_MAX_BUNDLE_BYTES = 2_000_000;
const MAX_REDIRECTS = 3;
const RESERVED_DIRECTORY = '.synapse-verifier';

class BundleValidationError extends Error {
  constructor(message, errors = []) {
    super(message);
    this.name = 'BundleValidationError';
    this.errors = errors;
  }
}

class VerificationError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'VerificationError';
    this.details = details;
  }
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map((entry) => stableStringify(entry)).join(',')}]`;
  }
  if (isPlainObject(value)) {
    const entries = Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value);
}

function jsonPointerGet(rootSchema, reference) {
  if (!reference.startsWith('#/')) {
    throw new BundleValidationError(`Only local JSON Schema references are supported: ${reference}`);
  }
  return reference
    .slice(2)
    .split('/')
    .map((token) => token.replace(/~1/g, '/').replace(/~0/g, '~'))
    .reduce((current, token) => {
      if (!isPlainObject(current) || !(token in current)) {
        throw new BundleValidationError(`Unresolved JSON Schema reference: ${reference}`);
      }
      return current[token];
    }, rootSchema);
}

function valueTypeMatches(value, expectedType) {
  switch (expectedType) {
    case 'null': return value === null;
    case 'array': return Array.isArray(value);
    case 'object': return isPlainObject(value);
    case 'integer': return Number.isInteger(value);
    case 'number': return typeof value === 'number' && Number.isFinite(value);
    case 'string': return typeof value === 'string';
    case 'boolean': return typeof value === 'boolean';
    default: throw new BundleValidationError(`Unsupported JSON Schema type: ${expectedType}`);
  }
}

function isValidDateTime(value) {
  return (
    typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function isValidUri(value) {
  try {
    const parsed = new URL(value);
    return Boolean(parsed.protocol);
  } catch {
    return false;
  }
}

function validateInstanceAgainstSchema(instance, schema, options = {}) {
  const rootSchema = options.rootSchema || schema;
  const errors = [];

  function addError(instancePath, message) {
    errors.push(`${instancePath || '/'}: ${message}`);
  }

  function visit(value, rule, instancePath) {
    if (rule === true) return;
    if (rule === false) {
      addError(instancePath, 'value is forbidden by schema');
      return;
    }
    if (!isPlainObject(rule)) {
      throw new BundleValidationError('Invalid JSON Schema node encountered');
    }

    if (rule.$ref) {
      visit(value, jsonPointerGet(rootSchema, rule.$ref), instancePath);
      return;
    }

    if (Array.isArray(rule.allOf)) {
      for (const branch of rule.allOf) visit(value, branch, instancePath);
    }
    if (Array.isArray(rule.anyOf)) {
      const branchResults = rule.anyOf.map((branch) => {
        const before = errors.length;
        visit(value, branch, instancePath);
        const branchErrors = errors.splice(before);
        return branchErrors;
      });
      if (!branchResults.some((branchErrors) => branchErrors.length === 0)) {
        addError(instancePath, 'must match at least one anyOf branch');
      }
    }
    if (Array.isArray(rule.oneOf)) {
      let matches = 0;
      for (const branch of rule.oneOf) {
        const before = errors.length;
        visit(value, branch, instancePath);
        const branchErrors = errors.splice(before);
        if (branchErrors.length === 0) matches += 1;
      }
      if (matches !== 1) addError(instancePath, `must match exactly one oneOf branch (matched ${matches})`);
    }
    if (isPlainObject(rule.if)) {
      const before = errors.length;
      visit(value, rule.if, instancePath);
      const conditionErrors = errors.splice(before);
      if (conditionErrors.length === 0 && rule.then) visit(value, rule.then, instancePath);
      if (conditionErrors.length > 0 && rule.else) visit(value, rule.else, instancePath);
    }

    if ('const' in rule && stableStringify(value) !== stableStringify(rule.const)) {
      addError(instancePath, `must equal ${JSON.stringify(rule.const)}`);
    }
    if (Array.isArray(rule.enum) && !rule.enum.some((entry) => stableStringify(entry) === stableStringify(value))) {
      addError(instancePath, `must be one of ${rule.enum.map((entry) => JSON.stringify(entry)).join(', ')}`);
    }

    if (rule.type) {
      const expectedTypes = Array.isArray(rule.type) ? rule.type : [rule.type];
      if (!expectedTypes.some((expectedType) => valueTypeMatches(value, expectedType))) {
        addError(instancePath, `must have type ${expectedTypes.join(' or ')}`);
        return;
      }
    }

    if (typeof value === 'string') {
      if (Number.isInteger(rule.minLength) && value.length < rule.minLength) {
        addError(instancePath, `must have at least ${rule.minLength} characters`);
      }
      if (Number.isInteger(rule.maxLength) && value.length > rule.maxLength) {
        addError(instancePath, `must have at most ${rule.maxLength} characters`);
      }
      if (rule.pattern) {
        let expression;
        try {
          expression = new RegExp(rule.pattern, 'u');
        } catch (error) {
          throw new BundleValidationError(`Invalid pattern in JSON Schema: ${error.message}`);
        }
        if (!expression.test(value)) addError(instancePath, `must match pattern ${rule.pattern}`);
      }
      if (rule.format === 'date-time' && !isValidDateTime(value)) {
        addError(instancePath, 'must be an RFC 3339 date-time');
      }
      if ((rule.format === 'uri' || rule.format === 'uri-reference') && !isValidUri(value)) {
        addError(instancePath, `must be a valid ${rule.format}`);
      }
    }

    if (typeof value === 'number' && Number.isFinite(value)) {
      if (typeof rule.minimum === 'number' && value < rule.minimum) addError(instancePath, `must be >= ${rule.minimum}`);
      if (typeof rule.maximum === 'number' && value > rule.maximum) addError(instancePath, `must be <= ${rule.maximum}`);
      if (typeof rule.exclusiveMinimum === 'number' && value <= rule.exclusiveMinimum) {
        addError(instancePath, `must be > ${rule.exclusiveMinimum}`);
      }
      if (typeof rule.exclusiveMaximum === 'number' && value >= rule.exclusiveMaximum) {
        addError(instancePath, `must be < ${rule.exclusiveMaximum}`);
      }
    }

    if (Array.isArray(value)) {
      if (Number.isInteger(rule.minItems) && value.length < rule.minItems) {
        addError(instancePath, `must contain at least ${rule.minItems} items`);
      }
      if (Number.isInteger(rule.maxItems) && value.length > rule.maxItems) {
        addError(instancePath, `must contain at most ${rule.maxItems} items`);
      }
      if (rule.uniqueItems) {
        const serialized = value.map((entry) => stableStringify(entry));
        if (new Set(serialized).size !== serialized.length) addError(instancePath, 'must contain unique items');
      }
      if (rule.items) {
        value.forEach((entry, index) => visit(entry, rule.items, `${instancePath}/${index}`));
      }
    }

    if (isPlainObject(value)) {
      const properties = isPlainObject(rule.properties) ? rule.properties : {};
      const patternProperties = isPlainObject(rule.patternProperties) ? rule.patternProperties : {};
      const required = Array.isArray(rule.required) ? rule.required : [];

      for (const key of required) {
        if (!(key in value)) addError(instancePath, `missing required property ${JSON.stringify(key)}`);
      }

      if (Number.isInteger(rule.minProperties) && Object.keys(value).length < rule.minProperties) {
        addError(instancePath, `must contain at least ${rule.minProperties} properties`);
      }
      if (Number.isInteger(rule.maxProperties) && Object.keys(value).length > rule.maxProperties) {
        addError(instancePath, `must contain at most ${rule.maxProperties} properties`);
      }
      if (rule.propertyNames) {
        for (const key of Object.keys(value)) {
          visit(key, rule.propertyNames, `${instancePath}/<property:${key}>`);
        }
      }
      if (isPlainObject(rule.dependentRequired)) {
        for (const [trigger, dependencies] of Object.entries(rule.dependentRequired)) {
          if (!(trigger in value)) continue;
          for (const dependency of dependencies) {
            if (!(dependency in value)) {
              addError(instancePath, `property ${JSON.stringify(trigger)} requires ${JSON.stringify(dependency)}`);
            }
          }
        }
      }

      for (const [key, entry] of Object.entries(value)) {
        const childPath = `${instancePath}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`;
        let matched = false;
        if (key in properties) {
          visit(entry, properties[key], childPath);
          matched = true;
        }
        for (const [pattern, patternRule] of Object.entries(patternProperties)) {
          if (new RegExp(pattern, 'u').test(key)) {
            visit(entry, patternRule, childPath);
            matched = true;
          }
        }
        if (!matched) {
          if (rule.additionalProperties === false) {
            addError(childPath, 'additional property is not allowed');
          } else if (isPlainObject(rule.additionalProperties)) {
            visit(entry, rule.additionalProperties, childPath);
          }
        }
      }
    }
  }

  visit(instance, schema, '');
  return { valid: errors.length === 0, errors };
}

function assertSafeRelativePath(candidate, label = 'path') {
  if (typeof candidate !== 'string' || candidate.length === 0) {
    throw new BundleValidationError(`${label} must be a non-empty string`);
  }
  if (candidate.length > 240 || candidate.includes('\0') || candidate.includes('\\')) {
    throw new BundleValidationError(`${label} contains unsupported characters or is too long: ${candidate}`);
  }
  if (path.posix.isAbsolute(candidate) || /^[A-Za-z]:/.test(candidate)) {
    throw new BundleValidationError(`${label} must be relative: ${candidate}`);
  }
  const normalized = path.posix.normalize(candidate);
  if (normalized !== candidate || normalized === '..' || normalized.startsWith('../')) {
    throw new BundleValidationError(`${label} escapes or is not normalized: ${candidate}`);
  }
  if (normalized === RESERVED_DIRECTORY || normalized.startsWith(`${RESERVED_DIRECTORY}/`)) {
    throw new BundleValidationError(`${label} uses the verifier-reserved directory: ${candidate}`);
  }
  return normalized;
}

function parseDiffPath(headerLine, prefix) {
  if (!headerLine.startsWith(prefix)) throw new VerificationError(`Expected unified diff header ${prefix.trim()}`);
  const rawPath = headerLine.slice(prefix.length).split('\t', 1)[0].trim();
  if (rawPath === '/dev/null') throw new VerificationError('File creation and deletion are not supported in bundle v1 patches');
  const withoutPrefix = rawPath.startsWith('a/') || rawPath.startsWith('b/') ? rawPath.slice(2) : rawPath;
  return assertSafeRelativePath(withoutPrefix, 'unified diff path');
}

function inspectUnifiedDiff(unifiedDiff) {
  if (typeof unifiedDiff !== 'string' || unifiedDiff.length === 0) {
    throw new BundleValidationError('patch.unifiedDiff must be a non-empty string');
  }
  const lines = unifiedDiff.replace(/\r\n/g, '\n').split('\n');
  const oldHeaderIndex = lines.findIndex((line) => line.startsWith('--- '));
  if (oldHeaderIndex < 0 || oldHeaderIndex + 1 >= lines.length || !lines[oldHeaderIndex + 1].startsWith('+++ ')) {
    throw new BundleValidationError('Unified diff must contain adjacent --- and +++ file headers');
  }
  const oldPath = parseDiffPath(lines[oldHeaderIndex], '--- ');
  const newPath = parseDiffPath(lines[oldHeaderIndex + 1], '+++ ');
  if (oldPath !== newPath) throw new BundleValidationError('Bundle v1 patches cannot rename files');
  if (lines.slice(oldHeaderIndex + 2).some((line) => line.startsWith('--- '))) {
    throw new BundleValidationError('Bundle v1 accepts exactly one patched file');
  }
  if (!lines.slice(oldHeaderIndex + 2).some((line) => line.startsWith('@@ '))) {
    throw new BundleValidationError('Unified diff must contain at least one hunk');
  }
  return { targetFile: oldPath };
}

function validateBundle(bundle, schema = null) {
  const errors = [];
  if (!isPlainObject(bundle)) {
    throw new BundleValidationError('Bundle must be a JSON object');
  }

  if (schema) {
    const schemaResult = validateInstanceAgainstSchema(bundle, schema);
    errors.push(...schemaResult.errors);
  }

  const requiredObjects = ['scope', 'fingerprint', 'patch', 'verification', 'provenance'];
  for (const key of requiredObjects) {
    if (!isPlainObject(bundle[key])) errors.push(`/${key}: must be an object`);
  }
  if (errors.length > 0) throw new BundleValidationError('Bundle schema validation failed', errors);

  try {
    assertSafeRelativePath(bundle.patch.targetFile, 'patch.targetFile');
    const patchInspection = inspectUnifiedDiff(bundle.patch.unifiedDiff);
    if (patchInspection.targetFile !== bundle.patch.targetFile) {
      errors.push(`/patch/targetFile: ${bundle.patch.targetFile} does not match diff path ${patchInspection.targetFile}`);
    }

    const workspaceFiles = bundle.verification.workspaceFiles;
    if (!isPlainObject(workspaceFiles) || Object.keys(workspaceFiles).length === 0) {
      errors.push('/verification/workspaceFiles: must contain at least one file');
    } else {
      for (const [filePath, content] of Object.entries(workspaceFiles)) {
        assertSafeRelativePath(filePath, 'verification.workspaceFiles key');
        if (typeof content !== 'string') errors.push(`/verification/workspaceFiles/${filePath}: content must be a string`);
      }
      if (!(bundle.patch.targetFile in workspaceFiles)) {
        errors.push(`/verification/workspaceFiles: missing patch target ${bundle.patch.targetFile}`);
      }
    }

    const flags = bundle.fingerprint.regexFlags || '';
    if (!/^[dgimsuvy]*$/.test(flags) || new Set(flags).size !== flags.length) {
      errors.push('/fingerprint/flags: contains invalid or duplicate JavaScript RegExp flags');
    } else {
      try {
        // Compilation is the validation; the expression is evaluated against bounded process output later.
        new RegExp(bundle.fingerprint.regex, flags);
      } catch (error) {
        errors.push(`/fingerprint/regex: invalid regular expression: ${error.message}`);
      }
    }

    if (!['javascript', 'python'].includes(bundle.verification.scriptLanguage)) {
      errors.push('/verification/scriptLanguage: must be javascript or python');
    }
    if (bundle.verification.expectedPreExit === 0) {
      errors.push('/verification/expectedPreExit: must be non-zero');
    }
    if (bundle.verification.expectedPostExit !== 0) {
      errors.push('/verification/expectedPostExit: must equal zero');
    }
    if (!Array.isArray(bundle.verification.mutations) || bundle.verification.mutations.length < 2) {
      errors.push('/verification/mutations: at least two mutations are required');
    } else {
      const mutationIds = new Set();
      for (const [index, mutation] of bundle.verification.mutations.entries()) {
        if (!isPlainObject(mutation)) {
          errors.push(`/verification/mutations/${index}: must be an object`);
          continue;
        }
        if (mutationIds.has(mutation.id)) errors.push(`/verification/mutations/${index}/id: duplicate mutation id`);
        mutationIds.add(mutation.id);
        try {
          const mutationInspection = inspectUnifiedDiff(mutation.unifiedDiff);
          if (mutationInspection.targetFile !== bundle.patch.targetFile) {
            errors.push(`/verification/mutations/${index}: diff target must equal patch.targetFile`);
          }
        } catch (error) {
          errors.push(`/verification/mutations/${index}/unifiedDiff: ${error.message}`);
        }
        if (mutation.expectedErrorRegex) {
          try { new RegExp(mutation.expectedErrorRegex); } catch (error) {
            errors.push(`/verification/mutations/${index}/expectedErrorRegex: ${error.message}`);
          }
        }
      }
    }

    if (bundle.integrity) {
      const patchDigest = sha256(Buffer.from(bundle.patch.unifiedDiff, 'utf8'));
      if (bundle.integrity.patchSha256 !== patchDigest) {
        errors.push('/integrity/patchSha256: digest does not match patch.unifiedDiff');
      }
      if (bundle.patch.sha256 && bundle.patch.sha256 !== patchDigest) {
        errors.push('/patch/sha256: digest does not match patch.unifiedDiff');
      }
      if (bundle.integrity.workspaceSha256) {
        const workspaceDigest = sha256(stableStringify(bundle.verification.workspaceFiles));
        if (bundle.integrity.workspaceSha256 !== workspaceDigest) {
          errors.push('/integrity/workspaceSha256: digest does not match workspaceFiles');
        }
      }
      if (bundle.integrity.bundleSha256) {
        const clone = JSON.parse(JSON.stringify(bundle));
        delete clone.integrity.bundleSha256;
        const bundleDigest = sha256(stableStringify(clone));
        if (bundle.integrity.bundleSha256 !== bundleDigest) {
          errors.push('/integrity/bundleSha256: digest does not match canonical bundle without integrity.bundleSha256');
        }
      }
    }
  } catch (error) {
    errors.push(error.message);
  }

  if (errors.length > 0) throw new BundleValidationError('Bundle semantic validation failed', errors);
  return { valid: true, errors: [] };
}

function applyUnifiedDiff(sourceText, unifiedDiff, expectedTargetFile = null) {
  const inspection = inspectUnifiedDiff(unifiedDiff);
  if (expectedTargetFile && inspection.targetFile !== expectedTargetFile) {
    throw new VerificationError(`Diff targets ${inspection.targetFile}, expected ${expectedTargetFile}`);
  }

  const diffLines = unifiedDiff.replace(/\r\n/g, '\n').split('\n');
  const firstHeader = diffLines.findIndex((line) => line.startsWith('--- '));
  let index = firstHeader + 2;
  const sourceLines = sourceText.replace(/\r\n/g, '\n').split('\n');
  const output = [];
  let sourceCursor = 0;
  let hunksApplied = 0;

  while (index < diffLines.length) {
    const line = diffLines[index];
    if (line === '') {
      index += 1;
      continue;
    }
    const headerMatch = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/.exec(line);
    if (!headerMatch) throw new VerificationError(`Unexpected unified diff line outside a hunk: ${line}`);

    const oldStart = Number(headerMatch[1]);
    const oldCountExpected = headerMatch[2] === undefined ? 1 : Number(headerMatch[2]);
    const newCountExpected = headerMatch[4] === undefined ? 1 : Number(headerMatch[4]);
    const oldIndex = oldStart === 0 ? 0 : oldStart - 1;
    if (oldIndex < sourceCursor || oldIndex > sourceLines.length) {
      throw new VerificationError(`Hunk starts at invalid or overlapping source line ${oldStart}`);
    }
    output.push(...sourceLines.slice(sourceCursor, oldIndex));
    sourceCursor = oldIndex;
    index += 1;

    let oldCount = 0;
    let newCount = 0;
    while (index < diffLines.length && !diffLines[index].startsWith('@@ ')) {
      const hunkLine = diffLines[index];
      if (hunkLine.startsWith('--- ')) throw new VerificationError('Multiple files in a single bundle diff are not supported');
      if (hunkLine === '\\ No newline at end of file') {
        index += 1;
        continue;
      }
      const marker = hunkLine[0];
      const content = hunkLine.slice(1);
      if (marker === ' ') {
        if (sourceLines[sourceCursor] !== content) {
          throw new VerificationError(`Context mismatch at source line ${sourceCursor + 1}`);
        }
        output.push(content);
        sourceCursor += 1;
        oldCount += 1;
        newCount += 1;
      } else if (marker === '-') {
        if (sourceLines[sourceCursor] !== content) {
          throw new VerificationError(`Removal mismatch at source line ${sourceCursor + 1}`);
        }
        sourceCursor += 1;
        oldCount += 1;
      } else if (marker === '+') {
        output.push(content);
        newCount += 1;
      } else if (hunkLine === '' && index === diffLines.length - 1) {
        index += 1;
        break;
      } else {
        throw new VerificationError(`Invalid unified diff hunk marker: ${JSON.stringify(marker)}`);
      }
      index += 1;
    }
    if (oldCount !== oldCountExpected || newCount !== newCountExpected) {
      throw new VerificationError(
        `Hunk line counts do not match header: expected -${oldCountExpected}/+${newCountExpected}, got -${oldCount}/+${newCount}`
      );
    }
    hunksApplied += 1;
  }

  if (hunksApplied === 0) throw new VerificationError('Unified diff did not contain an applicable hunk');
  output.push(...sourceLines.slice(sourceCursor));
  return output.join('\n');
}

function writeWorkspace(root, workspaceFiles) {
  for (const [relativePath, content] of Object.entries(workspaceFiles)) {
    const safePath = assertSafeRelativePath(relativePath, 'workspace file');
    const destination = path.join(root, ...safePath.split('/'));
    fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    fs.writeFileSync(destination, content, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
  }
}

function applyPatchInWorkspace(root, targetFile, unifiedDiff) {
  const safeTarget = assertSafeRelativePath(targetFile, 'patch target');
  const targetPath = path.join(root, ...safeTarget.split('/'));
  const stat = fs.lstatSync(targetPath);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new VerificationError(`Patch target is not a regular file: ${safeTarget}`);
  const source = fs.readFileSync(targetPath, 'utf8');
  const patched = applyUnifiedDiff(source, unifiedDiff, safeTarget);
  fs.writeFileSync(targetPath, patched, { encoding: 'utf8', mode: 0o600, flag: 'w' });
}

function buildChildEnvironment(extraEnvironment = {}) {
  const allowedNames = [
    'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR',
    'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'NODE_PATH', 'PYTHONPATH'
  ];
  const environment = {
    SYNAPSE_VERIFY: '1',
    NO_COLOR: '1'
  };
  for (const name of allowedNames) {
    if (typeof process.env[name] === 'string') environment[name] = process.env[name];
  }
  for (const [name, value] of Object.entries(extraEnvironment)) {
    if (!/^[A-Z_][A-Z0-9_]*$/.test(name) || typeof value !== 'string') {
      throw new BundleValidationError(`Invalid verifier environment override: ${name}`);
    }
    environment[name] = value;
  }
  return environment;
}

function resolveScriptCommand(scriptLanguage, scriptPath, options = {}) {
  if (scriptLanguage === 'javascript') return { command: process.execPath, args: [scriptPath] };
  if (scriptLanguage === 'python') {
    const command = options.pythonBinary || process.env.SYNAPSE_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    return { command, args: [scriptPath] };
  }
  throw new BundleValidationError(`Unsupported verification.scriptLanguage: ${scriptLanguage}`);
}

function terminateChild(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  try {
    if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, 'SIGKILL');
    else child.kill('SIGKILL');
  } catch {
    try { child.kill('SIGKILL'); } catch { /* already gone */ }
  }
}

function runScript(workspaceRoot, scriptLanguage, source, phaseName, options = {}) {
  const scriptDirectory = path.join(workspaceRoot, RESERVED_DIRECTORY);
  fs.mkdirSync(scriptDirectory, { recursive: true, mode: 0o700 });
  const extension = scriptLanguage === 'python' ? 'py' : 'cjs';
  const scriptPath = path.join(scriptDirectory, `${phaseName}.${extension}`);
  fs.writeFileSync(scriptPath, source, { encoding: 'utf8', mode: 0o600, flag: 'wx' });

  const { command, args } = resolveScriptCommand(scriptLanguage, scriptPath, options);
  const timeoutMs = options.timeoutMs || DEFAULT_TIMEOUT_MS;
  const maxOutputBytes = options.maxOutputBytes || DEFAULT_MAX_OUTPUT_BYTES;
  const started = process.hrtime.bigint();
  const childEnvironment = buildChildEnvironment(options.environment);
  if (scriptLanguage === 'python') {
    childEnvironment.PYTHONPATH = childEnvironment.PYTHONPATH
      ? `${workspaceRoot}${path.delimiter}${childEnvironment.PYTHONPATH}`
      : workspaceRoot;
  }

  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: workspaceRoot,
      detached: process.platform !== 'win32',
      env: childEnvironment,
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true
    });

    const stdoutChunks = [];
    const stderrChunks = [];
    let outputBytes = 0;
    let timedOut = false;
    let outputLimitExceeded = false;
    let spawnError = null;

    const capture = (chunks) => (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes <= maxOutputBytes) chunks.push(chunk);
      if (outputBytes > maxOutputBytes && !outputLimitExceeded) {
        outputLimitExceeded = true;
        terminateChild(child);
      }
    };
    child.stdout.on('data', capture(stdoutChunks));
    child.stderr.on('data', capture(stderrChunks));
    child.on('error', (error) => { spawnError = error; });

    const timer = setTimeout(() => {
      timedOut = true;
      terminateChild(child);
    }, timeoutMs);

    child.on('close', (exitCode, signal) => {
      clearTimeout(timer);
      const durationMs = Number(process.hrtime.bigint() - started) / 1_000_000;
      const stderr = Buffer.concat(stderrChunks).toString('utf8');
      resolve({
        exitCode: Number.isInteger(exitCode) ? exitCode : null,
        signal: signal || null,
        stdout: Buffer.concat(stdoutChunks).toString('utf8'),
        stderr: spawnError ? `${stderr}${stderr ? '\n' : ''}${spawnError.message}` : stderr,
        durationMs: Math.round(durationMs * 100) / 100,
        timedOut,
        outputLimitExceeded
      });
    });
  });
}

function phasePassedWithoutHarnessFailure(result) {
  return !result.timedOut && !result.outputLimitExceeded && result.exitCode !== null;
}

function summarizePhase(result) {
  return {
    exitCode: result.exitCode,
    signal: result.signal,
    durationMs: result.durationMs,
    timedOut: result.timedOut,
    outputLimitExceeded: result.outputLimitExceeded,
    stdout: result.stdout,
    stderr: result.stderr
  };
}

function redactStrings(value, replacements) {
  if (typeof value === 'string') {
    return replacements.reduce((current, [needle, replacement]) => {
      if (!needle) return current;
      return current.split(needle).join(replacement);
    }, value);
  }
  if (Array.isArray(value)) return value.map((entry) => redactStrings(entry, replacements));
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, redactStrings(entry, replacements)]));
  }
  return value;
}

function locateNodePackageVersion(packageName, dependencyRoot) {
  const segments = packageName.split('/');
  const direct = path.join(dependencyRoot, 'node_modules', ...segments, 'package.json');
  const candidates = [direct];
  try {
    candidates.unshift(require.resolve(`${packageName}/package.json`, { paths: [dependencyRoot] }));
  } catch { /* package exports may intentionally hide package.json */ }
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (typeof parsed.version === 'string') return parsed.version;
    } catch { /* try the next deterministic location */ }
  }
  return null;
}

async function probeExecutionEnvironment(bundle, workspaceRoot, options = {}) {
  const expectedRuntime = bundle.scope.runtimeVersion;
  const expectedPackages = bundle.patch.pinnedDependencies;
  const actualPackages = {};
  let actualRuntime = null;
  let probeResult = null;

  if (bundle.scope.runtime === 'nodejs') {
    actualRuntime = process.versions.node;
    const dependencyRoot = path.resolve(options.dependencyRoot || process.cwd());
    for (const packageName of Object.keys(expectedPackages)) {
      actualPackages[packageName] = locateNodePackageVersion(packageName, dependencyRoot);
    }
  } else if (bundle.scope.runtime === 'python') {
    const packageNames = Object.keys(expectedPackages);
    const source = [
      'import importlib.metadata',
      'import json',
      'import platform',
      `names = ${JSON.stringify(packageNames)}`,
      'versions = {}',
      'for name in names:',
      '    try:',
      '        versions[name] = importlib.metadata.version(name)',
      '    except importlib.metadata.PackageNotFoundError:',
      '        versions[name] = None',
      'print(json.dumps({"runtimeVersion": platform.python_version(), "packages": versions}, sort_keys=True))'
    ].join('\n');
    probeResult = await runScript(workspaceRoot, 'python', source, 'environment-probe', {
      ...options,
      timeoutMs: Math.min(options.timeoutMs || DEFAULT_TIMEOUT_MS, 10_000)
    });
    if (probeResult.exitCode === 0) {
      try {
        const parsed = JSON.parse(probeResult.stdout.trim());
        actualRuntime = parsed.runtimeVersion;
        Object.assign(actualPackages, parsed.packages);
      } catch {
        // Reported as a failed probe below.
      }
    }
  } else if (bundle.scope.runtime === 'rust') {
    const source = [
      "const { spawnSync } = require('node:child_process');",
      "const result = spawnSync('rustc', ['--version'], { encoding: 'utf8', shell: false });",
      "if (result.error) { console.error(result.error.message); process.exit(127); }",
      "process.stdout.write(result.stdout || '');",
      'process.exit(result.status === null ? 125 : result.status);'
    ].join('\n');
    probeResult = await runScript(workspaceRoot, 'javascript', source, 'environment-probe', {
      ...options,
      timeoutMs: Math.min(options.timeoutMs || DEFAULT_TIMEOUT_MS, 10_000)
    });
    const match = probeResult.stdout.match(/^rustc\s+(\d+\.\d+\.\d+)/);
    if (probeResult.exitCode === 0 && match) actualRuntime = match[1];
    for (const packageName of Object.keys(expectedPackages)) actualPackages[packageName] = null;
  }

  const mismatches = [];
  if (actualRuntime !== expectedRuntime) {
    mismatches.push(`runtime ${bundle.scope.runtime}: expected ${expectedRuntime}, got ${actualRuntime || 'unavailable'}`);
  }
  for (const [packageName, expectedVersion] of Object.entries(expectedPackages)) {
    const actualVersion = actualPackages[packageName] ?? null;
    if (actualVersion !== expectedVersion) {
      mismatches.push(`package ${packageName}: expected ${expectedVersion}, got ${actualVersion || 'unavailable'}`);
    }
  }
  return {
    passed: mismatches.length === 0,
    runtime: { name: bundle.scope.runtime, expected: expectedRuntime, actual: actualRuntime },
    packages: Object.fromEntries(Object.entries(expectedPackages).map(([name, expected]) => [
      name,
      { expected, actual: actualPackages[name] ?? null, matched: actualPackages[name] === expected }
    ])),
    mismatches,
    probe: probeResult ? summarizePhase(probeResult) : null
  };
}

async function verifyBundle(bundle, options = {}) {
  if (!options.allowCodeExecution) {
    throw new VerificationError(
      'Bundle verification executes untrusted code. Pass allowCodeExecution: true only inside an appropriate isolated environment.'
    );
  }
  validateBundle(bundle, options.schema || null);

  const started = process.hrtime.bigint();
  const temporaryRoot = fs.mkdtempSync(path.join(options.tempRoot || os.tmpdir(), 'synapse-verify-'));
  const createdWorkspaces = [];
  const timeoutMs = Math.min(bundle.verification.timeoutMs || DEFAULT_TIMEOUT_MS, options.timeoutMs || Number.MAX_SAFE_INTEGER);
  const dependencyRoot = path.resolve(options.dependencyRoot || process.cwd());
  const executionEnvironment = { ...(options.environment || {}), SYNAPSE_DEPENDENCY_ROOT: dependencyRoot };
  if (bundle.scope.runtime === 'nodejs') {
    const dependencyNodeModules = path.join(dependencyRoot, 'node_modules');
    executionEnvironment.NODE_PATH = executionEnvironment.NODE_PATH
      ? `${dependencyNodeModules}${path.delimiter}${executionEnvironment.NODE_PATH}`
      : dependencyNodeModules;
  }
  const scriptOptions = {
    timeoutMs,
    maxOutputBytes: options.maxOutputBytes || DEFAULT_MAX_OUTPUT_BYTES,
    pythonBinary: options.pythonBinary &&
      !path.isAbsolute(options.pythonBinary) &&
      /[\\/]/.test(options.pythonBinary)
      ? path.resolve(options.pythonBinary)
      : options.pythonBinary,
    environment: executionEnvironment,
    dependencyRoot
  };

  const createFreshWorkspace = (name) => {
    const workspace = path.join(temporaryRoot, name);
    fs.mkdirSync(workspace, { recursive: false, mode: 0o700 });
    writeWorkspace(workspace, bundle.verification.workspaceFiles);
    if (bundle.scope.runtime === 'nodejs') {
      const dependencyTree = path.join(dependencyRoot, 'node_modules');
      if (fs.existsSync(dependencyTree)) {
        fs.symlinkSync(
          dependencyTree,
          path.join(workspace, 'node_modules'),
          process.platform === 'win32' ? 'junction' : 'dir'
        );
      }
    }
    createdWorkspaces.push(workspace);
    return workspace;
  };

  let preResult;
  let postResult;
  let environmentResult;
  const mutationResults = [];
  let failureReason = null;
  let signatureMatched = false;

  try {
    const environmentWorkspace = createFreshWorkspace('environment');
    environmentResult = options.skipEnvironmentCheck
      ? { passed: true, skipped: true, mismatches: [] }
      : await probeExecutionEnvironment(bundle, environmentWorkspace, scriptOptions);
    if (!environmentResult.passed) {
      failureReason = `Environment preflight failed: ${environmentResult.mismatches.join('; ')}`;
    }

    const preWorkspace = createFreshWorkspace('pre-fail');
    if (!failureReason) preResult = await runScript(
      preWorkspace,
      bundle.verification.scriptLanguage,
      bundle.verification.reproductionScript,
      'reproduction',
      scriptOptions
    );
    const preOutput = !preResult ? '' : bundle.fingerprint.matchStream === 'stdout'
      ? preResult.stdout
      : bundle.fingerprint.matchStream === 'stderr'
        ? preResult.stderr
        : `${preResult.stderr}\n${preResult.stdout}`;
    const expression = new RegExp(bundle.fingerprint.regex, bundle.fingerprint.regexFlags || '');
    const preExitMatches = preResult ? preResult.exitCode === bundle.verification.expectedPreExit : false;
    signatureMatched = preResult ? expression.test(preOutput) : false;
    const prePassed = preResult ? phasePassedWithoutHarnessFailure(preResult) && preExitMatches && signatureMatched : false;

    if (!failureReason && !prePassed) {
      failureReason = `Pre-fail gate failed (exit=${preResult.exitCode}, expected=${bundle.verification.expectedPreExit}, signatureMatched=${signatureMatched})`;
    } else if (!failureReason) {
      const postWorkspace = createFreshWorkspace('post-pass');
      applyPatchInWorkspace(postWorkspace, bundle.patch.targetFile, bundle.patch.unifiedDiff);
      postResult = await runScript(
        postWorkspace,
        bundle.verification.scriptLanguage,
        bundle.verification.testSuite,
        'post-pass',
        scriptOptions
      );
      const postPassed = phasePassedWithoutHarnessFailure(postResult) && postResult.exitCode === bundle.verification.expectedPostExit;
      if (!postPassed) failureReason = `Post-pass gate failed (exit=${postResult.exitCode})`;

      if (postPassed) {
        for (const [index, mutation] of bundle.verification.mutations.entries()) {
          const mutationWorkspace = createFreshWorkspace(`mutation-${String(index + 1).padStart(2, '0')}`);
          applyPatchInWorkspace(mutationWorkspace, bundle.patch.targetFile, mutation.unifiedDiff);
          const mutationResult = await runScript(
            mutationWorkspace,
            bundle.verification.scriptLanguage,
            bundle.verification.testSuite,
            `mutation-${index + 1}`,
            scriptOptions
          );
          const mutationOutput = `${mutationResult.stderr}\n${mutationResult.stdout}`;
          const expectedErrorMatched = mutation.expectedErrorRegex
            ? new RegExp(mutation.expectedErrorRegex).test(mutationOutput)
            : null;
          const killed = phasePassedWithoutHarnessFailure(mutationResult) &&
            mutationResult.exitCode !== 0 &&
            (expectedErrorMatched === null || expectedErrorMatched);
          mutationResults.push({
            id: mutation.id,
            description: mutation.description,
            killed,
            expectedErrorMatched,
            ...summarizePhase(mutationResult)
          });
        }
        const surviving = mutationResults.filter((mutation) => !mutation.killed);
        if (surviving.length > 0) failureReason = `Mutation sanity gate failed; survivors: ${surviving.map((item) => item.id).join(', ')}`;
      }
    }

    const durationMs = Number(process.hrtime.bigint() - started) / 1_000_000;
    const result = {
      verified: failureReason === null,
      bundleId: bundle.bundleId,
      bundleVersion: bundle.schemaVersion,
      bundleSha256: options.bundleSha256 || sha256(stableStringify(bundle)),
      preExit: preResult ? preResult.exitCode : null,
      postExit: postResult ? postResult.exitCode : null,
      signatureMatched,
      mutantsKilled: `${mutationResults.filter((item) => item.killed).length}/${bundle.verification.mutations.length}`,
      durationMs: Math.round(durationMs * 100) / 100,
      failureReason,
      phases: {
        environment: environmentResult,
        preFail: preResult ? summarizePhase(preResult) : null,
        postPass: postResult ? summarizePhase(postResult) : null,
        mutations: mutationResults
      },
      executionEnvironment: {
        nodeVersion: process.version,
        platform: process.platform,
        architecture: process.arch,
        isolation: 'ephemeral-workspace-only'
      },
      verifier: {
        name: VERIFIER_NAME,
        version: VERIFIER_VERSION
      }
    };
    return redactStrings(result, [
      [temporaryRoot, '$VERIFIER_TEMP'],
      [dependencyRoot, '$DEPENDENCY_ROOT'],
      [process.cwd(), '$CALLER_WORKSPACE']
    ]);
  } finally {
    if (!options.keepWorkspaces) {
      fs.rmSync(temporaryRoot, { recursive: true, force: true, maxRetries: 2 });
    }
  }
}

function readHttps(url, options = {}, redirectsRemaining = MAX_REDIRECTS) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') {
      reject(new BundleValidationError('Only HTTPS bundle URLs are permitted'));
      return;
    }
    if (parsed.username || parsed.password) {
      reject(new BundleValidationError('Bundle URLs must not contain credentials'));
      return;
    }

    const request = https.get(parsed, {
      headers: { Accept: 'application/json', 'User-Agent': `${VERIFIER_NAME}/${VERIFIER_VERSION}` },
      timeout: options.fetchTimeoutMs || 10_000
    }, (response) => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
        response.resume();
        if (redirectsRemaining <= 0 || !response.headers.location) {
          reject(new BundleValidationError('Too many or invalid HTTPS redirects while loading bundle'));
          return;
        }
        let destination;
        try { destination = new URL(response.headers.location, parsed); } catch (error) {
          reject(new BundleValidationError(`Invalid redirect URL: ${error.message}`));
          return;
        }
        if (destination.protocol !== 'https:') {
          reject(new BundleValidationError('HTTPS bundle retrieval cannot redirect to a non-HTTPS URL'));
          return;
        }
        readHttps(destination, options, redirectsRemaining - 1).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new BundleValidationError(`HTTPS bundle request returned HTTP ${response.statusCode}`));
        return;
      }
      const chunks = [];
      let bytes = 0;
      const maxBytes = options.maxBundleBytes || DEFAULT_MAX_BUNDLE_BYTES;
      response.on('data', (chunk) => {
        bytes += chunk.length;
        if (bytes > maxBytes) {
          request.destroy(new BundleValidationError(`Bundle exceeds ${maxBytes} bytes`));
          return;
        }
        chunks.push(chunk);
      });
      response.on('end', () => resolve(Buffer.concat(chunks)));
    });
    request.on('timeout', () => request.destroy(new BundleValidationError('HTTPS bundle request timed out')));
    request.on('error', reject);
  });
}

async function loadJsonSource(source, options = {}) {
  let bytes;
  if (/^https:\/\//i.test(source)) {
    bytes = await readHttps(source, options);
  } else if (/^[a-z][a-z0-9+.-]*:\/\//i.test(source)) {
    throw new BundleValidationError('Only local paths and HTTPS URLs are supported');
  } else {
    const stat = fs.statSync(source);
    const maxBytes = options.maxBundleBytes || DEFAULT_MAX_BUNDLE_BYTES;
    if (!stat.isFile()) throw new BundleValidationError(`JSON source is not a regular file: ${source}`);
    if (stat.size > maxBytes) throw new BundleValidationError(`JSON source exceeds ${maxBytes} bytes`);
    bytes = fs.readFileSync(source);
  }

  let value;
  try {
    value = JSON.parse(bytes.toString('utf8'));
  } catch (error) {
    throw new BundleValidationError(`Invalid JSON in ${source}: ${error.message}`);
  }
  return { value, sha256: sha256(bytes), bytes };
}

function createAttestation(result, source) {
  return {
    _type: 'https://in-toto.io/Statement/v1',
    subject: result.bundleSha256 ? [{
      name: result.bundleId || source || 'unknown-bundle',
      digest: { sha256: result.bundleSha256 }
    }] : [],
    predicateType: 'https://synapsemesh.dev/attestations/compatibility-verification/v1',
    predicate: {
      generatedAt: new Date().toISOString(),
      source: source || null,
      verified: Boolean(result.verified),
      validationOnly: Boolean(result.validationOnly),
      validationPassed: result.validationPassed === undefined ? null : Boolean(result.validationPassed),
      failureReason: result.failureReason || null,
      preExit: result.preExit ?? null,
      postExit: result.postExit ?? null,
      signatureMatched: Boolean(result.signatureMatched),
      mutantsKilled: result.mutantsKilled || null,
      durationMs: result.durationMs ?? null,
      phases: result.phases || null,
      executionEnvironment: result.executionEnvironment || {
        nodeVersion: process.version,
        platform: process.platform,
        architecture: process.arch,
        isolation: 'ephemeral-workspace-only'
      },
      verifier: result.verifier || { name: VERIFIER_NAME, version: VERIFIER_VERSION }
    }
  };
}

async function verifySource(source, options = {}) {
  const bundleSource = await loadJsonSource(source, options);
  let schema = options.schema || null;
  if (!schema && options.schemaPath) schema = (await loadJsonSource(options.schemaPath, options)).value;
  validateBundle(bundleSource.value, schema);
  return verifyBundle(bundleSource.value, {
    ...options,
    schema,
    bundleSha256: bundleSource.sha256
  });
}

module.exports = {
  BundleValidationError,
  VerificationError,
  applyUnifiedDiff,
  createAttestation,
  inspectUnifiedDiff,
  loadJsonSource,
  sha256,
  stableStringify,
  validateBundle,
  validateInstanceAgainstSchema,
  verifyBundle,
  verifySource
};
