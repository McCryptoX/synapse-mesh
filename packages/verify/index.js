'use strict';

const crypto = require('node:crypto');
const dns = require('node:dns');
const fs = require('node:fs');
const https = require('node:https');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { Worker, isMainThread, parentPort, workerData } = require('node:worker_threads');

const VERIFIER_NAME = '@synapse-mesh/verify';
const VERIFIER_VERSION = '0.1.0';
const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_TOTAL_TIMEOUT_MS = 300_000;
const DEFAULT_MAX_OUTPUT_BYTES = 1_000_000;
const DEFAULT_MAX_BUNDLE_BYTES = 2_000_000;
const MAX_NODE_DEPENDENCY_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_NODE_DEPENDENCY_ENTRIES = 250_000;
const MAX_NODE_PACKAGE_JSON_BYTES = 1_000_000;
const MAX_REDIRECTS = 3;
const RESERVED_DIRECTORY = '.synapse-verifier';
const REGEX_TIMEOUT_MS = 500;
const TERMINATION_GRACE_MS = 250;
const BUNDLED_SCHEMA_PATH = path.join(__dirname, 'schema', 'compatibility_bundle_v1.json');
let bundledSchemaCache = null;
const NON_PUBLIC_IPV4_ADDRESSES = new net.BlockList();
const NON_PUBLIC_IPV6_ADDRESSES = new net.BlockList();
for (const [network, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
  ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24],
  ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4]
]) NON_PUBLIC_IPV4_ADDRESSES.addSubnet(network, prefix, 'ipv4');
for (const [network, prefix] of [
  ['::', 128], ['::1', 128], ['::ffff:0:0', 96], ['64:ff9b::', 96],
  ['100::', 64], ['2001:db8::', 32], ['fc00::', 7], ['fe80::', 10], ['ff00::', 8]
]) NON_PUBLIC_IPV6_ADDRESSES.addSubnet(network, prefix, 'ipv6');

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

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key);
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

function loadBundledSchema() {
  if (bundledSchemaCache === null) {
    try {
      bundledSchemaCache = JSON.parse(fs.readFileSync(BUNDLED_SCHEMA_PATH, 'utf8'));
    } catch (error) {
      throw new BundleValidationError(
        `Bundled Compatibility Bundle schema is unavailable or invalid (${error.code || error.name || 'unknown error'})`
      );
    }
  }
  return bundledSchemaCache;
}

function normalizedHostPlatform() {
  const operatingSystem = process.platform === 'win32' ? 'windows' : process.platform;
  const architecture = {
    x64: 'x86_64',
    ia32: 'x86',
    arm: 'arm',
    arm64: 'arm64',
    ppc64: 'ppc64',
    s390x: 's390x'
  }[process.arch] || process.arch;
  return `${operatingSystem}-${architecture}`;
}

function assertSupportedNodeRuntime() {
  const major = Number(process.versions.node.split('.')[0]);
  if (!Number.isInteger(major) || major < 18 || major > 22) {
    throw new VerificationError(`Unsupported verifier runtime Node.js ${process.versions.node}; expected major 18 through 22`);
  }
}

function isPublicNetworkAddress(address) {
  const family = net.isIP(address);
  if (family === 4) return !NON_PUBLIC_IPV4_ADDRESSES.check(address, 'ipv4');
  if (family === 6) return !NON_PUBLIC_IPV6_ADDRESSES.check(address, 'ipv6');
  return false;
}

function safeHttpsLookup(hostname, lookupOptions, callback) {
  dns.lookup(hostname, { all: true, verbatim: true }, (error, addresses) => {
    if (error) {
      callback(error);
      return;
    }
    if (!Array.isArray(addresses) || addresses.length === 0) {
      callback(new BundleValidationError('HTTPS bundle hostname did not resolve'));
      return;
    }
    if (addresses.some((entry) => !isPublicNetworkAddress(entry.address))) {
      callback(new BundleValidationError('HTTPS bundle hostname resolves to a non-public network address'));
      return;
    }
    if (lookupOptions && typeof lookupOptions === 'object' && lookupOptions.all) {
      callback(null, addresses);
    } else {
      callback(null, addresses[0].address, addresses[0].family);
    }
  });
}

function testRegexSafely(pattern, flags, input, timeoutMs = REGEX_TIMEOUT_MS) {
  return new Promise((resolve) => {
    let settled = false;
    let terminationRequested = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const worker = new Worker(
      [
        "'use strict';",
        "const { parentPort, workerData } = require('node:worker_threads');",
        'try {',
        '  const expression = new RegExp(workerData.pattern, workerData.flags);',
        '  parentPort.postMessage({ matched: expression.test(workerData.input), timedOut: false, error: null });',
        '} catch (error) {',
        '  parentPort.postMessage({ matched: false, timedOut: false, error: error.message });',
        '}'
      ].join('\n'),
      {
        eval: true,
        workerData: { pattern, flags, input },
        resourceLimits: { maxOldGenerationSizeMb: 32, stackSizeMb: 4 }
      }
    );
    const timer = setTimeout(() => {
      terminationRequested = true;
      worker.terminate()
        .then(() => finish({ matched: false, timedOut: true, error: 'regular expression evaluation timed out' }))
        .catch((error) => finish({ matched: false, timedOut: true, error: error.message }));
    }, timeoutMs);
    worker.once('message', finish);
    worker.once('error', (error) => finish({ matched: false, timedOut: false, error: error.message }));
    worker.once('exit', (code) => {
      if (!settled && terminationRequested) {
        finish({ matched: false, timedOut: true, error: 'regular expression evaluation timed out' });
      } else if (!settled && code !== 0) {
        finish({ matched: false, timedOut: false, error: `regex worker exited with code ${code}` });
      }
    });
  });
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
      if (!isPlainObject(current) || !hasOwn(current, token)) {
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
  if (typeof value !== 'string') return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[9] === undefined ? 0 : Number(match[9]);
  const offsetMinute = match[10] === undefined ? 0 : Number(match[10]);
  if (month < 1 || month > 12 || hour > 23 || minute > 59 || second > 60 || offsetHour > 23 || offsetMinute > 59) {
    return false;
  }
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (day < 1 || day > daysInMonth[month - 1]) return false;
  if (second !== 60) return true;

  // RFC 3339 permits second 60 only at an inserted UTC leap second. Normalize
  // the represented local 23:59:59 to UTC and require the end of June/December.
  let local = Date.UTC(year, month - 1, day, hour, minute, 59);
  if (year >= 0 && year <= 99) {
    const adjusted = new Date(local);
    adjusted.setUTCFullYear(year);
    local = adjusted.getTime();
  }
  const offsetSign = match[8] === '-' ? -1 : 1;
  const utc = new Date(local - offsetSign * (offsetHour * 60 + offsetMinute) * 60_000);
  return (
    utc.getUTCHours() === 23 &&
    utc.getUTCMinutes() === 59 &&
    ((utc.getUTCMonth() === 5 && utc.getUTCDate() === 30) ||
      (utc.getUTCMonth() === 11 && utc.getUTCDate() === 31))
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

function isValidUriReference(value) {
  try {
    new URL(value, 'https://schema.invalid/');
    return typeof value === 'string';
  } catch {
    return false;
  }
}

function assertSupportedSchemaSubset(schema, options = {}) {
  const allowPattern = options.allowPattern !== false;
  const supportedKeywords = new Set([
    '$schema', '$id', '$ref', '$defs', '$comment',
    'title', 'description', 'default', 'examples', 'deprecated', 'readOnly', 'writeOnly',
    'type', 'enum', 'const', 'allOf', 'anyOf', 'oneOf', 'if', 'then', 'else',
    'properties', 'patternProperties', 'additionalProperties', 'required', 'propertyNames',
    'dependentRequired', 'minProperties', 'maxProperties',
    'items', 'minItems', 'maxItems', 'uniqueItems',
    'minLength', 'maxLength', 'pattern', 'format',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'
  ]);
  const validTypes = new Set(['null', 'array', 'object', 'integer', 'number', 'string', 'boolean']);
  const numericKeywords = [
    'minProperties', 'maxProperties', 'minItems', 'maxItems', 'minLength', 'maxLength',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'
  ];
  const nonnegativeIntegerKeywords = new Set([
    'minProperties', 'maxProperties', 'minItems', 'maxItems', 'minLength', 'maxLength'
  ]);

  const visitSchema = (rule, schemaPath, depth = 0) => {
    if (depth > 256) throw new BundleValidationError(`${schemaPath}: schema nesting exceeds the supported depth`);
    if (typeof rule === 'boolean') return;
    if (!isPlainObject(rule)) throw new BundleValidationError(`${schemaPath}: schema node must be an object or boolean`);
    for (const keyword of Object.keys(rule)) {
      if (!supportedKeywords.has(keyword)) {
        throw new BundleValidationError(`${schemaPath}: unsupported JSON Schema keyword ${keyword}`);
      }
    }
    if (hasOwn(rule, '$schema') && rule.$schema !== 'https://json-schema.org/draft/2020-12/schema') {
      throw new BundleValidationError(`${schemaPath}: only JSON Schema Draft 2020-12 is supported`);
    }
    if (hasOwn(rule, '$id') && (typeof rule.$id !== 'string' || !isValidUriReference(rule.$id))) {
      throw new BundleValidationError(`${schemaPath}: $id must be a URI reference`);
    }
    if (hasOwn(rule, '$ref') && (typeof rule.$ref !== 'string' || !rule.$ref.startsWith('#/'))) {
      throw new BundleValidationError(`${schemaPath}: only local JSON Pointer $ref values are supported`);
    }
    for (const keyword of ['$comment', 'title', 'description']) {
      if (hasOwn(rule, keyword) && typeof rule[keyword] !== 'string') {
        throw new BundleValidationError(`${schemaPath}: ${keyword} must be a string`);
      }
    }
    for (const keyword of ['deprecated', 'readOnly', 'writeOnly']) {
      if (hasOwn(rule, keyword) && typeof rule[keyword] !== 'boolean') {
        throw new BundleValidationError(`${schemaPath}: ${keyword} must be boolean`);
      }
    }
    if (hasOwn(rule, 'examples') && !Array.isArray(rule.examples)) {
      throw new BundleValidationError(`${schemaPath}: examples must be an array`);
    }
    if (hasOwn(rule, 'type')) {
      const types = Array.isArray(rule.type) ? rule.type : [rule.type];
      if (
        types.length === 0 ||
        types.some((entry) => typeof entry !== 'string' || !validTypes.has(entry)) ||
        new Set(types).size !== types.length
      ) {
        throw new BundleValidationError(`${schemaPath}: unsupported or malformed type declaration`);
      }
    }
    if (hasOwn(rule, 'enum') && (
      !Array.isArray(rule.enum) ||
      rule.enum.length === 0 ||
      new Set(rule.enum.map((entry) => stableStringify(entry))).size !== rule.enum.length
    )) {
      throw new BundleValidationError(`${schemaPath}: enum must be a non-empty array of unique values`);
    }
    for (const keyword of numericKeywords) {
      if (!hasOwn(rule, keyword)) continue;
      const value = rule[keyword];
      const requiresInteger = nonnegativeIntegerKeywords.has(keyword);
      if (typeof value !== 'number' || !Number.isFinite(value) || (requiresInteger && (!Number.isInteger(value) || value < 0))) {
        throw new BundleValidationError(`${schemaPath}: ${keyword} has an invalid numeric value`);
      }
    }
    if (hasOwn(rule, 'uniqueItems') && typeof rule.uniqueItems !== 'boolean') {
      throw new BundleValidationError(`${schemaPath}: uniqueItems must be boolean`);
    }
    if (hasOwn(rule, 'format') && !['date-time', 'uri', 'uri-reference'].includes(rule.format)) {
      throw new BundleValidationError(`${schemaPath}: unsupported format ${rule.format}`);
    }
    if (hasOwn(rule, 'pattern')) {
      if (!allowPattern) throw new BundleValidationError(`${schemaPath}: pattern is not supported in custom schema overlays`);
      if (typeof rule.pattern !== 'string') throw new BundleValidationError(`${schemaPath}: pattern must be a string`);
      try { new RegExp(rule.pattern, 'u'); } catch (error) {
        throw new BundleValidationError(`${schemaPath}: invalid pattern (${error.message})`);
      }
    }
    for (const keyword of ['required']) {
      if (hasOwn(rule, keyword) && (
        !Array.isArray(rule[keyword]) ||
        rule[keyword].some((entry) => typeof entry !== 'string') ||
        new Set(rule[keyword]).size !== rule[keyword].length
      )) {
        throw new BundleValidationError(`${schemaPath}: ${keyword} must be an array of unique strings`);
      }
    }
    if (hasOwn(rule, 'dependentRequired')) {
      if (!isPlainObject(rule.dependentRequired) || Object.values(rule.dependentRequired).some(
        (entries) => !Array.isArray(entries) || entries.some((entry) => typeof entry !== 'string') || new Set(entries).size !== entries.length
      )) throw new BundleValidationError(`${schemaPath}: dependentRequired must map names to unique string arrays`);
    }
    for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
      if (!hasOwn(rule, keyword)) continue;
      if (!Array.isArray(rule[keyword]) || rule[keyword].length === 0) {
        throw new BundleValidationError(`${schemaPath}: ${keyword} must be a non-empty schema array`);
      }
      rule[keyword].forEach((branch, index) => visitSchema(branch, `${schemaPath}/${keyword}/${index}`, depth + 1));
    }
    for (const keyword of ['if', 'then', 'else', 'items', 'propertyNames']) {
      if (hasOwn(rule, keyword)) visitSchema(rule[keyword], `${schemaPath}/${keyword}`, depth + 1);
    }
    if (hasOwn(rule, 'additionalProperties')) visitSchema(rule.additionalProperties, `${schemaPath}/additionalProperties`, depth + 1);
    for (const keyword of ['$defs', 'properties', 'patternProperties']) {
      if (!hasOwn(rule, keyword)) continue;
      if (!isPlainObject(rule[keyword])) throw new BundleValidationError(`${schemaPath}: ${keyword} must be an object`);
      if (keyword === 'patternProperties' && !allowPattern) {
        throw new BundleValidationError(`${schemaPath}: patternProperties is not supported in custom schema overlays`);
      }
      for (const [name, child] of Object.entries(rule[keyword])) {
        if (keyword === 'patternProperties') {
          try { new RegExp(name, 'u'); } catch (error) {
            throw new BundleValidationError(`${schemaPath}: invalid patternProperties key (${error.message})`);
          }
        }
        visitSchema(child, `${schemaPath}/${keyword}/${name}`, depth + 1);
      }
    }
  };

  visitSchema(schema, '#');
}

function validateInstanceAgainstSchema(instance, schema, options = {}) {
  assertSupportedSchemaSubset(schema, { allowPattern: options.allowPattern !== false });
  const rootSchema = options.rootSchema ?? schema;
  const errors = [];

  function addError(instancePath, message) {
    errors.push(`${instancePath || '/'}: ${message}`);
  }

  let evaluationDepth = 0;
  function visit(value, rule, instancePath) {
    if (evaluationDepth >= 256) {
      throw new BundleValidationError('JSON Schema evaluation exceeded the maximum reference depth');
    }
    evaluationDepth += 1;
    try {
    if (rule === true) return;
    if (rule === false) {
      addError(instancePath, 'value is forbidden by schema');
      return;
    }
    if (!isPlainObject(rule)) {
      throw new BundleValidationError('Invalid JSON Schema node encountered');
    }

    if (hasOwn(rule, '$ref')) {
      visit(value, jsonPointerGet(rootSchema, rule.$ref), instancePath);
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
    if (hasOwn(rule, 'if')) {
      const before = errors.length;
      visit(value, rule.if, instancePath);
      const conditionErrors = errors.splice(before);
      if (conditionErrors.length === 0 && hasOwn(rule, 'then')) visit(value, rule.then, instancePath);
      if (conditionErrors.length > 0 && hasOwn(rule, 'else')) visit(value, rule.else, instancePath);
    }

    if (hasOwn(rule, 'const') && stableStringify(value) !== stableStringify(rule.const)) {
      addError(instancePath, `must equal ${JSON.stringify(rule.const)}`);
    }
    if (Array.isArray(rule.enum) && !rule.enum.some((entry) => stableStringify(entry) === stableStringify(value))) {
      addError(instancePath, `must be one of ${rule.enum.map((entry) => JSON.stringify(entry)).join(', ')}`);
    }

    if (hasOwn(rule, 'type')) {
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
      if (hasOwn(rule, 'pattern')) {
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
      if (rule.format === 'uri' && !isValidUri(value)) addError(instancePath, 'must be a valid uri');
      if (rule.format === 'uri-reference' && !isValidUriReference(value)) {
        addError(instancePath, 'must be a valid uri-reference');
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
      if (hasOwn(rule, 'items')) {
        value.forEach((entry, index) => visit(entry, rule.items, `${instancePath}/${index}`));
      }
    }

    if (isPlainObject(value)) {
      const properties = isPlainObject(rule.properties) ? rule.properties : {};
      const patternProperties = isPlainObject(rule.patternProperties) ? rule.patternProperties : {};
      const required = Array.isArray(rule.required) ? rule.required : [];

      for (const key of required) {
        if (!hasOwn(value, key)) addError(instancePath, `missing required property ${JSON.stringify(key)}`);
      }

      if (Number.isInteger(rule.minProperties) && Object.keys(value).length < rule.minProperties) {
        addError(instancePath, `must contain at least ${rule.minProperties} properties`);
      }
      if (Number.isInteger(rule.maxProperties) && Object.keys(value).length > rule.maxProperties) {
        addError(instancePath, `must contain at most ${rule.maxProperties} properties`);
      }
      if (hasOwn(rule, 'propertyNames')) {
        for (const key of Object.keys(value)) {
          visit(key, rule.propertyNames, `${instancePath}/<property:${key}>`);
        }
      }
      if (isPlainObject(rule.dependentRequired)) {
        for (const [trigger, dependencies] of Object.entries(rule.dependentRequired)) {
          if (!hasOwn(value, trigger)) continue;
          for (const dependency of dependencies) {
            if (!hasOwn(value, dependency)) {
              addError(instancePath, `property ${JSON.stringify(trigger)} requires ${JSON.stringify(dependency)}`);
            }
          }
        }
      }

      for (const [key, entry] of Object.entries(value)) {
        const childPath = `${instancePath}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`;
        let matched = false;
        if (hasOwn(properties, key)) {
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
    } finally {
      evaluationDepth -= 1;
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

  const bundledSchema = loadBundledSchema();
  const schemas = [{ value: bundledSchema, allowPattern: true }];
  if (schema !== null && schema !== undefined) {
    // The CLI and reusable Action may explicitly pass the shipped canonical
    // schema. Its reviewed regex constraints are safe to apply a second time;
    // every genuinely custom overlay remains subject to the regex-free subset.
    const isCanonicalSchema = JSON.stringify(schema) === JSON.stringify(bundledSchema);
    schemas.push({ value: schema, allowPattern: isCanonicalSchema });
  }
  for (const activeSchema of schemas) {
    const schemaResult = validateInstanceAgainstSchema(bundle, activeSchema.value, {
      allowPattern: activeSchema.allowPattern
    });
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
      if (!hasOwn(workspaceFiles, bundle.patch.targetFile)) {
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
    const pinnedDependencies = bundle.patch.pinnedDependencies;
    if (!isPlainObject(pinnedDependencies) || !hasOwn(pinnedDependencies, bundle.scope.package)) {
      errors.push(`/patch/pinnedDependencies: must pin the scoped package ${bundle.scope.package}`);
    } else if (pinnedDependencies[bundle.scope.package] !== bundle.scope.toVersion) {
      errors.push(
        `/scope/toVersion: exact target ${bundle.scope.toVersion} must equal patch.pinnedDependencies[${bundle.scope.package}]`
      );
    }
    if (bundle.patch.dependencyLock) {
      const lockPath = assertSafeRelativePath(bundle.patch.dependencyLock.path, 'patch.dependencyLock.path');
      const lockContent = bundle.verification.workspaceFiles[lockPath];
      if (typeof lockContent !== 'string') {
        errors.push(`/patch/dependencyLock/path: workspaceFiles is missing ${lockPath}`);
      } else if (sha256(Buffer.from(lockContent, 'utf8')) !== bundle.patch.dependencyLock.sha256) {
        errors.push('/patch/dependencyLock/sha256: digest does not match the workspace lockfile');
      }
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
      const mutationDiffDigests = new Set();
      const mutationResultDigests = new Set();
      for (const [index, mutation] of bundle.verification.mutations.entries()) {
        if (!isPlainObject(mutation)) {
          errors.push(`/verification/mutations/${index}: must be an object`);
          continue;
        }
        if (mutationIds.has(mutation.id)) errors.push(`/verification/mutations/${index}/id: duplicate mutation id`);
        mutationIds.add(mutation.id);
        const mutationDiffDigest = sha256(Buffer.from(mutation.unifiedDiff, 'utf8'));
        if (mutationDiffDigests.has(mutationDiffDigest)) {
          errors.push(`/verification/mutations/${index}/unifiedDiff: duplicate mutation patch`);
        }
        mutationDiffDigests.add(mutationDiffDigest);
        try {
          const mutationInspection = inspectUnifiedDiff(mutation.unifiedDiff);
          if (mutationInspection.targetFile !== bundle.patch.targetFile) {
            errors.push(`/verification/mutations/${index}: diff target must equal patch.targetFile`);
          }
          const mutationResult = applyUnifiedDiff(
            bundle.verification.workspaceFiles[bundle.patch.targetFile],
            mutation.unifiedDiff,
            bundle.patch.targetFile
          );
          const mutationResultDigest = sha256(Buffer.from(mutationResult, 'utf8'));
          if (mutationResultDigests.has(mutationResultDigest)) {
            errors.push(`/verification/mutations/${index}/unifiedDiff: produces a duplicate mutated fixture`);
          }
          mutationResultDigests.add(mutationResultDigest);
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

    const patchDigest = sha256(Buffer.from(bundle.patch.unifiedDiff, 'utf8'));
    if (bundle.patch.sha256 && bundle.patch.sha256 !== patchDigest) {
      errors.push('/patch/sha256: digest does not match patch.unifiedDiff');
    }
    if (bundle.integrity) {
      if (bundle.integrity.patchSha256 !== patchDigest) {
        errors.push('/integrity/patchSha256: digest does not match patch.unifiedDiff');
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
    'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL'
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
    if (options.pythonNoSite) return { command, args: ['-I', '-S', scriptPath] };
    return { command, args: options.pythonIsolated ? ['-I', scriptPath] : [scriptPath] };
  }
  throw new BundleValidationError(`Unsupported verification.scriptLanguage: ${scriptLanguage}`);
}

function terminateChild(child) {
  let processGroupSignalled = false;
  try {
    if (process.platform !== 'win32' && child.pid) {
      process.kill(-child.pid, 'SIGKILL');
      processGroupSignalled = true;
    }
  } catch { /* the direct child may already have exited while descendants remain */ }
  if (!processGroupSignalled && child.exitCode === null && child.signalCode === null) {
    try { child.kill('SIGKILL'); } catch { /* already gone */ }
  }
  if (child.stdout) child.stdout.destroy();
  if (child.stderr) child.stderr.destroy();
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
    childEnvironment.PYTHONNOUSERSITE = '1';
    childEnvironment.PYTHONDONTWRITEBYTECODE = '1';
    childEnvironment.PYTHONPATH = workspaceRoot;
  }

  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.workingDirectory || workspaceRoot,
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
    let settled = false;
    let timer = null;
    let terminationTimer = null;

    const finish = (exitCode, signal) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (terminationTimer) clearTimeout(terminationTimer);
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
    };

    const requestTermination = () => {
      terminateChild(child);
      if (!terminationTimer) {
        terminationTimer = setTimeout(
          () => finish(child.exitCode, child.signalCode || (timedOut ? 'SIGKILL' : null)),
          TERMINATION_GRACE_MS
        );
      }
    };

    const capture = (chunks) => (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes <= maxOutputBytes) chunks.push(chunk);
      if (outputBytes > maxOutputBytes && !outputLimitExceeded) {
        outputLimitExceeded = true;
        requestTermination();
      }
    };
    child.stdout.on('data', capture(stdoutChunks));
    child.stderr.on('data', capture(stderrChunks));
    child.on('error', (error) => { spawnError = error; });

    timer = setTimeout(() => {
      timedOut = true;
      requestTermination();
    }, timeoutMs);

    child.on('close', (exitCode, signal) => {
      // A phase may spawn descendants and then exit. Kill the original process
      // group before moving to the next independent workspace so ordinary
      // descendants cannot continue mutating shared dependencies in the
      // background. A real container/VM remains required against deliberately
      // detached processes.
      terminateChild(child);
      finish(exitCode, signal);
    });
  });
}

function phasePassedWithoutHarnessFailure(result) {
  return !result.timedOut && !result.outputLimitExceeded && result.exitCode !== null;
}

function summarizePhase(result, options = {}) {
  const stdout = result.stdout || '';
  const stderr = result.stderr || '';
  const summary = {
    exitCode: result.exitCode,
    signal: result.signal,
    durationMs: result.durationMs,
    timedOut: result.timedOut,
    outputLimitExceeded: result.outputLimitExceeded,
    stdoutBytes: Buffer.byteLength(stdout),
    stderrBytes: Buffer.byteLength(stderr),
    stdoutSha256: sha256(Buffer.from(stdout, 'utf8')),
    stderrSha256: sha256(Buffer.from(stderr, 'utf8'))
  };
  if (options.includeOutput) {
    summary.stdout = stdout;
    summary.stderr = stderr;
  }
  return summary;
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

function hashFileTree(rootPath) {
  let rootStat;
  let realRoot;
  try {
    rootStat = fs.lstatSync(rootPath);
    realRoot = fs.realpathSync(rootPath);
  } catch {
    return null;
  }
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) return null;

  const digest = crypto.createHash('sha256');
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  let unsafeLink = false;
  let entryCount = 0;
  let totalFileBytes = 0;
  digest.update(`ROOT\0${rootStat.mode & 0o7777}\0`);
  const walk = (absoluteDirectory, relativeDirectory) => {
    for (const name of fs.readdirSync(absoluteDirectory).sort()) {
      entryCount += 1;
      if (entryCount > MAX_NODE_DEPENDENCY_ENTRIES) {
        throw new VerificationError('Node dependency tree exceeds the entry limit');
      }
      const absolute = path.join(absoluteDirectory, name);
      const relative = relativeDirectory ? `${relativeDirectory}/${name}` : name;
      const stat = fs.lstatSync(absolute);
      if (stat.isSymbolicLink()) {
        digest.update(`L\0${relative}\0${stat.mode & 0o7777}\0${fs.readlinkSync(absolute)}\0`);
        try {
          const target = fs.realpathSync(absolute);
          const targetRelative = path.relative(realRoot, target);
          if (
            targetRelative === '..' ||
            targetRelative.startsWith(`..${path.sep}`) ||
            path.isAbsolute(targetRelative)
          ) unsafeLink = true;
        } catch {
          unsafeLink = true;
        }
      } else if (stat.isDirectory()) {
        digest.update(`D\0${relative}\0${stat.mode & 0o7777}\0`);
        walk(absolute, relative);
      } else if (stat.isFile()) {
        if (stat.nlink > 1) {
          throw new VerificationError('Node dependency tree contains a multiply linked file');
        }
        totalFileBytes += stat.size;
        if (totalFileBytes > MAX_NODE_DEPENDENCY_BYTES) {
          throw new VerificationError('Node dependency tree exceeds the byte limit');
        }
        digest.update(`F\0${relative}\0${stat.mode & 0o7777}\0${stat.size}\0`);
        const descriptor = fs.openSync(absolute, 'r');
        try {
          let bytesRead;
          do {
            bytesRead = fs.readSync(descriptor, buffer, 0, buffer.length, null);
            if (bytesRead > 0) digest.update(buffer.subarray(0, bytesRead));
          } while (bytesRead > 0);
        } finally {
          fs.closeSync(descriptor);
        }
        digest.update('\0');
      } else {
        digest.update(`O\0${relative}\0${stat.mode & 0o7777}\0`);
      }
    }
  };
  walk(rootPath, '');
  return unsafeLink ? null : digest.digest('hex');
}

function readPackageVersion(candidate) {
  try {
    const stat = fs.statSync(candidate);
    if (!stat.isFile() || stat.size > MAX_NODE_PACKAGE_JSON_BYTES) return null;
    const parsed = JSON.parse(fs.readFileSync(candidate, 'utf8'));
    return typeof parsed.version === 'string' ? parsed.version : null;
  } catch {
    return null;
  }
}

function isPathContained(rootPath, candidatePath) {
  try {
    const realRoot = fs.realpathSync(rootPath);
    const realCandidate = fs.realpathSync(candidatePath);
    const relative = path.relative(realRoot, realCandidate);
    return relative !== '' && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative);
  } catch {
    return false;
  }
}

function listTopLevelNodePackageBases(dependencyModulesRoot) {
  const bases = [];
  const addPackageBase = (packageRoot) => {
    const manifest = path.join(packageRoot, 'package.json');
    if (!isPathContained(dependencyModulesRoot, manifest) || readPackageVersion(manifest) === null) return;
    try {
      bases.push(fs.realpathSync(packageRoot));
    } catch { /* a concurrently removed or broken link is not authoritative */ }
  };

  try {
    for (const entry of fs.readdirSync(dependencyModulesRoot).sort()) {
      if (entry.startsWith('.')) continue;
      const packageRoot = path.join(dependencyModulesRoot, entry);
      if (entry.startsWith('@')) {
        try {
          for (const child of fs.readdirSync(packageRoot).sort()) {
            addPackageBase(path.join(packageRoot, child));
          }
        } catch { /* malformed or concurrently removed scope directory */ }
      } else {
        addPackageBase(packageRoot);
      }
    }
  } catch { /* dependencyRoot may not contain node_modules */ }
  return [...new Set(bases)];
}

function locateNodePackageVersion(packageName, dependencyRoot) {
  const segments = packageName.split('/');
  const dependencyModulesRoot = path.join(dependencyRoot, 'node_modules');
  const direct = path.join(dependencyModulesRoot, ...segments, 'package.json');
  const authoritativeCandidates = new Set();
  if (isPathContained(dependencyModulesRoot, direct)) authoritativeCandidates.add(direct);

  // A package is authoritative only when it is top-level or resolvable from a
  // contained top-level package. This admits linked pnpm dependencies used at
  // runtime while excluding raw/unlinked .pnpm store entries and ancestors.
  const resolutionBases = [dependencyRoot, ...listTopLevelNodePackageBases(dependencyModulesRoot)];
  for (const base of resolutionBases) {
    try {
      const resolved = require.resolve(`${packageName}/package.json`, { paths: [base] });
      if (isPathContained(dependencyModulesRoot, resolved)) authoritativeCandidates.add(resolved);
    } catch { /* exports may hide package.json; fail closed unless directly readable */ }
  }

  const discoveredVersions = [];
  for (const candidate of authoritativeCandidates) {
    const version = readPackageVersion(candidate);
    if (version !== null && !discoveredVersions.includes(version)) discoveredVersions.push(version);
  }
  if (discoveredVersions.length === 1) return discoveredVersions[0];
  // Multiple reachable versions are ambiguous and therefore fail exact match.
  if (discoveredVersions.length > 1) return discoveredVersions.sort().join(',');
  return null;
}

function nodeDependencyProbeSync(packageNames, dependencyRoot) {
  const packages = {};
  for (const packageName of packageNames) {
    packages[packageName] = locateNodePackageVersion(packageName, dependencyRoot);
  }
  return {
    packages,
    dependencyTreeSha256: hashFileTree(path.join(dependencyRoot, 'node_modules'))
  };
}

function probeNodeDependenciesSafely(packageNames, dependencyRoot, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const worker = new Worker(__filename, {
      workerData: {
        synapseVerifierTask: 'node-dependency-probe',
        packageNames,
        dependencyRoot
      },
      resourceLimits: { maxOldGenerationSizeMb: 128, stackSizeMb: 8 }
    });
    const timer = setTimeout(() => {
      worker.terminate().catch(() => {});
      finish({ packages: {}, dependencyTreeSha256: null, timedOut: true, error: 'dependency probe timed out' });
    }, Math.max(1, timeoutMs));
    worker.once('message', (result) => finish({ ...result, timedOut: false, error: result.error || null }));
    worker.once('error', (error) => {
      finish({ packages: {}, dependencyTreeSha256: null, timedOut: false, error: error.message });
    });
    worker.once('exit', (code) => {
      if (!settled && code !== 0) {
        finish({ packages: {}, dependencyTreeSha256: null, timedOut: false, error: `dependency probe worker exited with code ${code}` });
      }
    });
  });
}

async function probeExecutionEnvironment(bundle, workspaceRoot, options = {}) {
  const expectedRuntime = bundle.scope.runtimeVersion;
  const expectedPackages = bundle.patch.pinnedDependencies;
  const actualPackages = {};
  let actualRuntime = null;
  let probeResult = null;
  let dependencyTreeSha256 = null;
  let dependencyIntegrityKind = null;
  let dependencyIntegrityTimedOut = false;
  let dependencyIntegrityError = null;
  const dependencyRoot = path.resolve(options.dependencyRoot || process.cwd());

  if (bundle.scope.runtime === 'nodejs') {
    actualRuntime = process.versions.node;
    const nodeProbe = await probeNodeDependenciesSafely(
      Object.keys(expectedPackages),
      dependencyRoot,
      options.timeoutMs || DEFAULT_TIMEOUT_MS
    );
    Object.assign(actualPackages, nodeProbe.packages);
    dependencyTreeSha256 = nodeProbe.dependencyTreeSha256;
    dependencyIntegrityKind = 'node-modules-tree';
    dependencyIntegrityTimedOut = nodeProbe.timedOut;
    dependencyIntegrityError = nodeProbe.error;
  } else if (bundle.scope.runtime === 'python') {
    const packageNames = Object.keys(expectedPackages);
    const source = [
      'import hashlib',
      'import importlib.metadata',
      'import json',
      'import os',
      'import platform',
      'import re',
      'import stat',
      'import sys',
      'import sysconfig',
      `names = ${JSON.stringify(packageNames)}`,
      'unsafe_configuration = []',
      'venv_root = os.path.dirname(os.path.dirname(sys.executable))',
      'venv_config = os.path.join(venv_root, "pyvenv.cfg")',
      'discovered_roots = set()',
      'if os.path.isfile(venv_config):',
      '    root_vars = {"base": venv_root, "platbase": venv_root}',
      '    for scheme in ("posix_prefix", "posix_local", "nt", "posix_home", *sysconfig.get_scheme_names()):',
      '        try:',
      '            discovered_roots.add(sysconfig.get_path("purelib", scheme=scheme, vars=root_vars))',
      '            discovered_roots.add(sysconfig.get_path("platlib", scheme=scheme, vars=root_vars))',
      '        except (KeyError, ValueError, AttributeError):',
      '            pass',
      '    lib_dir = os.path.join(venv_root, "lib")',
      '    if os.path.isdir(lib_dir):',
      '        for entry in os.listdir(lib_dir):',
      '            for sub in ("site-packages", "dist-packages"):',
      '                target_sub = os.path.join(lib_dir, entry, sub)',
      '                if os.path.isdir(target_sub):',
      '                    discovered_roots.add(target_sub)',
      '    with open(venv_config, "r", encoding="utf-8", errors="replace") as handle:',
      '        if re.search(r"(?im)^include-system-site-packages\\s*=\\s*true\\s*$", handle.read()):',
      '            unsafe_configuration.append("pyvenv.cfg:include-system-site-packages")',
      'else:',
      '    discovered_roots.update({sysconfig.get_paths().get("purelib"), sysconfig.get_paths().get("platlib")})',
      'roots = sorted({r for r in discovered_roots if r and os.path.isdir(r)})',
      'canonical = lambda value: re.sub(r"[-_.]+", "-", value).lower()',
      'available = {}',
      'for distribution in importlib.metadata.distributions(path=roots):',
      '    distribution_name = distribution.metadata.get("Name")',
      '    if distribution_name:',
      '        available.setdefault(canonical(distribution_name), []).append(distribution.version)',
      'versions = {}',
      'for name in names:',
      '    candidates = sorted(set(available.get(canonical(name), [])))',
      '    versions[name] = candidates[0] if len(candidates) == 1 else ",".join(candidates) if candidates else None',
      'tree = hashlib.sha256()',
      'unsafe_links = []',
      'unsafe_hardlinks = []',
      'for root_index, root in enumerate(roots):',
      '    if not os.path.isdir(root):',
      '        continue',
      '    real_root = os.path.realpath(root)',
      '    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):',
      '        directory_relative = os.path.relpath(directory, root).replace("\\\\", "/")',
      '        directory_mode = stat.S_IMODE(os.stat(directory, follow_symlinks=False).st_mode)',
      '        tree.update(str(root_index).encode("ascii") + b"\\0D\\0" + directory_relative.encode("utf-8") + b"\\0" + str(directory_mode).encode("ascii") + b"\\0")',
      '        child_directories = sorted(directory_names)',
      '        directory_names[:] = []',
      '        for child_name in child_directories:',
      '            child_path = os.path.join(directory, child_name)',
      '            if os.path.islink(child_path):',
      '                child_relative = os.path.relpath(child_path, root).replace("\\\\", "/")',
      '                try:',
      '                    if os.path.commonpath([real_root, os.path.realpath(child_path)]) != real_root:',
      '                        unsafe_links.append(child_relative)',
      '                except (OSError, ValueError):',
      '                    unsafe_links.append(child_relative)',
      '                child_mode = stat.S_IMODE(os.lstat(child_path).st_mode)',
      '                tree.update(str(root_index).encode("ascii") + b"\\0DL\\0" + child_relative.encode("utf-8") + b"\\0" + str(child_mode).encode("ascii") + b"\\0" + os.readlink(child_path).encode("utf-8") + b"\\0")',
      '            else:',
      '                directory_names.append(child_name)',
      '        for file_name in sorted(file_names):',
      '            located = os.path.join(directory, file_name)',
      '            relative = os.path.relpath(located, root).replace("\\\\", "/")',
      '            located_stat = os.lstat(located)',
      '            located_mode = stat.S_IMODE(located_stat.st_mode)',
      '            lowered = file_name.lower()',
      '            if lowered.endswith((".pth", ".egg-link")) or lowered in ("sitecustomize.py", "usercustomize.py"):',
      '                unsafe_configuration.append(relative)',
      '            tree.update(str(root_index).encode("ascii") + b"\\0" + relative.encode("utf-8") + b"\\0" + str(located_mode).encode("ascii") + b"\\0")',
      '            if os.path.islink(located):',
      '                try:',
      '                    if os.path.commonpath([real_root, os.path.realpath(located)]) != real_root:',
      '                        unsafe_links.append(relative)',
      '                except (OSError, ValueError):',
      '                    unsafe_links.append(relative)',
      '                tree.update(b"L\\0" + os.readlink(located).encode("utf-8") + b"\\0")',
      '                continue',
      '            if stat.S_ISREG(located_stat.st_mode) and located_stat.st_nlink > 1:',
      '                unsafe_hardlinks.append(relative)',
      '                continue',
      '            if not os.path.isfile(located):',
      '                tree.update(b"OTHER\\0")',
      '                continue',
      '            with open(located, "rb") as handle:',
      '                while True:',
      '                    chunk = handle.read(1024 * 1024)',
      '                    if not chunk:',
      '                        break',
      '                    tree.update(chunk)',
      '            tree.update(b"\\0")',
      'if unsafe_links or unsafe_hardlinks or unsafe_configuration:',
      '    print("Refusing unsafe site-packages path configuration", file=sys.stderr)',
      '    raise SystemExit(86)',
      'print(json.dumps({"runtimeVersion": platform.python_version(), "packages": versions, "dependencyTreeSha256": tree.hexdigest()}, sort_keys=True))'
    ].join('\n');
    probeResult = await runScript(workspaceRoot, 'python', source, options.probePhaseName || 'environment-probe', {
      ...options,
      timeoutMs: Math.min(options.timeoutMs || DEFAULT_TIMEOUT_MS, 10_000),
      pythonNoSite: true,
      workingDirectory: os.tmpdir()
    });
    if (probeResult.exitCode === 0) {
      try {
        const parsed = JSON.parse(probeResult.stdout.trim());
        actualRuntime = parsed.runtimeVersion;
        Object.assign(actualPackages, parsed.packages);
        dependencyTreeSha256 = parsed.dependencyTreeSha256 || null;
        dependencyIntegrityKind = 'python-site-packages-tree';
      } catch {
        // Reported as a failed probe below.
      }
    }
  } else if (bundle.scope.runtime === 'rust') {
    const source = [
      "'use strict';",
      "const crypto = require('node:crypto');",
      "const fs = require('node:fs');",
      "const path = require('node:path');",
      "const { spawnSync } = require('node:child_process');",
      "const MAX_BYTES = 2 * 1024 * 1024 * 1024;",
      "const MAX_ENTRIES = 250000;",
      "const MAX_TOOL_BYTES = 512 * 1024 * 1024;",
      "const run = (command, args) => spawnSync(command, args, { cwd: process.cwd(), encoding: 'utf8', shell: false, maxBuffer: 8 * 1024 * 1024 });",
      "function resolveExecutable(name) {",
      "  const extensions = process.platform === 'win32' ? (process.env.PATHEXT || '.EXE;.CMD;.BAT').split(';') : [''];",
      "  for (const directory of (process.env.PATH || '').split(path.delimiter)) {",
      "    if (!directory) continue;",
      "    for (const extension of extensions) {",
      "      const candidate = path.join(directory, process.platform === 'win32' ? `${name}${extension}` : name);",
      "      try { fs.accessSync(candidate, fs.constants.X_OK); return fs.realpathSync(candidate); } catch { /* continue */ }",
      "    }",
      "  }",
      "  throw new Error(`unable to resolve executable ${name}`);",
      "}",
      "function hashRegularFile(fileName, maximumBytes = MAX_TOOL_BYTES) {",
      "  const real = fs.realpathSync(fileName);",
      "  const stat = fs.lstatSync(real);",
      "  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink > 1 || stat.size > maximumBytes) throw new Error('unsafe toolchain file');",
      "  const digest = crypto.createHash('sha256');",
      "  digest.update(`F\\0${stat.mode & 0o7777}\\0${stat.size}\\0`);",
      "  const descriptor = fs.openSync(real, 'r');",
      "  const buffer = Buffer.allocUnsafe(1024 * 1024);",
      "  try { let count; do { count = fs.readSync(descriptor, buffer, 0, buffer.length, null); if (count) digest.update(buffer.subarray(0, count)); } while (count); } finally { fs.closeSync(descriptor); }",
      "  return digest.digest('hex');",
      "}",
      "function hashTree(root, limits) {",
      "  const realRoot = fs.realpathSync(root);",
      "  const rootStat = fs.lstatSync(realRoot);",
      "  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) throw new Error('unsafe resolved crate root');",
      "  const digest = crypto.createHash('sha256');",
      "  digest.update(`ROOT\\0${rootStat.mode & 0o7777}\\0`);",
      "  const buffer = Buffer.allocUnsafe(1024 * 1024);",
      "  const walk = (directory, relativeDirectory) => {",
      "    for (const name of fs.readdirSync(directory).sort()) {",
      "      limits.entries += 1; if (limits.entries > MAX_ENTRIES) throw new Error('resolved crate tree exceeds entry limit');",
      "      const absolute = path.join(directory, name);",
      "      const relative = relativeDirectory ? `${relativeDirectory}/${name}` : name;",
      "      const stat = fs.lstatSync(absolute);",
      "      if (stat.isSymbolicLink()) {",
      "        const target = fs.realpathSync(absolute); const targetRelative = path.relative(realRoot, target);",
      "        if (targetRelative === '..' || targetRelative.startsWith(`..${path.sep}`) || path.isAbsolute(targetRelative)) throw new Error('resolved crate symlink escapes source root');",
      "        digest.update(`L\\0${relative}\\0${stat.mode & 0o7777}\\0${fs.readlinkSync(absolute)}\\0`);",
      "      } else if (stat.isDirectory()) {",
      "        digest.update(`D\\0${relative}\\0${stat.mode & 0o7777}\\0`); walk(absolute, relative);",
      "      } else if (stat.isFile()) {",
      "        if (stat.nlink > 1) throw new Error('resolved crate tree contains a multiply linked file');",
      "        limits.bytes += stat.size; if (limits.bytes > MAX_BYTES) throw new Error('resolved crate tree exceeds byte limit');",
      "        digest.update(`F\\0${relative}\\0${stat.mode & 0o7777}\\0${stat.size}\\0`);",
      "        const descriptor = fs.openSync(absolute, 'r');",
      "        try { let count; do { count = fs.readSync(descriptor, buffer, 0, buffer.length, null); if (count) digest.update(buffer.subarray(0, count)); } while (count); } finally { fs.closeSync(descriptor); }",
      "        digest.update('\\0');",
      "      } else { throw new Error('unsupported resolved crate filesystem entry'); }",
      "    }",
      "  };",
      "  walk(realRoot, ''); return digest.digest('hex');",
      "}",
      "const rustc = run('rustc', ['--version']);",
      "const cargo = run('cargo', ['--version']);",
      "if (rustc.error || cargo.error) { console.error((rustc.error || cargo.error).message); process.exit(127); }",
      "if (rustc.status !== 0 || cargo.status !== 0) { process.stderr.write(rustc.stderr || cargo.stderr || ''); process.exit(rustc.status || cargo.status || 125); }",
      "const rustcMatch = (rustc.stdout || '').match(/^rustc\\s+(\\d+\\.\\d+\\.\\d+)/);",
      "const cargoMatch = (cargo.stdout || '').match(/^cargo\\s+(\\d+\\.\\d+\\.\\d+)/);",
      "if (!rustcMatch || !cargoMatch) { console.error('unable to parse Rust toolchain versions'); process.exit(86); }",
      "const metadataResult = run('cargo', ['metadata', '--locked', '--offline', '--format-version', '1']);",
      "if (metadataResult.error || metadataResult.status !== 0) { process.stderr.write(metadataResult.stderr || 'cargo metadata --locked --offline failed'); process.exit(metadataResult.status || 87); }",
      "let metadata; try { metadata = JSON.parse(metadataResult.stdout); } catch { console.error('invalid cargo metadata output'); process.exit(88); }",
      "if (!Array.isArray(metadata.packages)) { console.error('cargo metadata did not return packages'); process.exit(89); }",
      "const workspaceRoot = fs.realpathSync(process.cwd());",
      "const versions = {}; const sourceRoots = new Map(); const packageIdentities = new Map();",
      "for (const item of metadata.packages) {",
      "  if (!item || typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.version !== 'string' || typeof item.manifest_path !== 'string' || !(item.source === null || typeof item.source === 'string')) throw new Error('malformed cargo metadata package');",
      "  if (!versions[item.name]) versions[item.name] = []; if (!versions[item.name].includes(item.version)) versions[item.name].push(item.version);",
      "  const manifest = fs.realpathSync(item.manifest_path); const root = path.dirname(manifest); const relativeRoot = path.relative(workspaceRoot, root); const relativeManifest = path.relative(workspaceRoot, manifest);",
      "  const outsideWorkspace = relativeRoot === '..' || relativeRoot.startsWith(`..${path.sep}`) || path.isAbsolute(relativeRoot);",
      "  const location = item.source !== null ? `source:${item.source}` : outsideWorkspace ? `external-path:${crypto.createHash('sha256').update(root).digest('hex')}` : `workspace:${relativeManifest.split(path.sep).join('/')}`;",
      "  const identity = `${item.name}@${item.version}|${location}`;",
      "  if (packageIdentities.has(item.id) || [...packageIdentities.values()].includes(identity)) throw new Error('ambiguous cargo package identity');",
      "  packageIdentities.set(item.id, identity);",
      "  if (item.source !== null || outsideWorkspace) { if (!sourceRoots.has(root)) sourceRoots.set(root, new Set()); sourceRoots.get(root).add(identity); }",
      "}",
      "for (const name of Object.keys(versions)) versions[name].sort();",
      "const orderedVersions = Object.fromEntries(Object.keys(versions).sort().map((name) => [name, versions[name]]));",
      "if (!metadata.resolve || !Array.isArray(metadata.resolve.nodes)) throw new Error('cargo metadata did not return a resolve graph');",
      "const stableId = (id) => { if (!packageIdentities.has(id)) throw new Error('resolve graph references an unknown package'); return packageIdentities.get(id); };",
      "const resolveNodes = metadata.resolve.nodes.map((node) => {",
      "  if (!node || typeof node.id !== 'string' || !Array.isArray(node.dependencies) || !Array.isArray(node.deps) || !Array.isArray(node.features)) throw new Error('malformed cargo resolve node');",
      "  const dependencies = node.dependencies.map(stableId).sort();",
      "  const deps = node.deps.map((dependency) => {",
      "    if (!dependency || typeof dependency.name !== 'string' || typeof dependency.pkg !== 'string' || !Array.isArray(dependency.dep_kinds)) throw new Error('malformed cargo dependency edge');",
      "    const depKinds = dependency.dep_kinds.map((kind) => ({ kind: kind && typeof kind.kind === 'string' ? kind.kind : null, target: kind && typeof kind.target === 'string' ? kind.target : null })).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));",
      "    return { name: dependency.name, pkg: stableId(dependency.pkg), depKinds };",
      "  }).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));",
      "  return { id: stableId(node.id), dependencies, deps, features: [...node.features].sort() };",
      "}).sort((left, right) => left.id.localeCompare(right.id));",
      "const resolveGraph = { root: metadata.resolve.root === null ? null : stableId(metadata.resolve.root), nodes: resolveNodes };",
      "const limits = { entries: 0, bytes: 0 }; const sourceBindings = [];",
      "for (const root of [...sourceRoots.keys()].sort()) sourceBindings.push({ packages: [...sourceRoots.get(root)].sort(), sha256: hashTree(root, limits) });",
      "sourceBindings.sort((left, right) => JSON.stringify(left.packages).localeCompare(JSON.stringify(right.packages)));",
      "const rustcExecutableSha256 = hashRegularFile(resolveExecutable('rustc'));",
      "const cargoExecutableSha256 = hashRegularFile(resolveExecutable('cargo'));",
      "let rustcToolchainSha256 = null; let cargoToolchainSha256 = null; const sysrootResult = run('rustc', ['--print', 'sysroot']);",
      "if (!sysrootResult.error && sysrootResult.status === 0) {",
      "  const rustcCandidate = path.join(sysrootResult.stdout.trim(), 'bin', process.platform === 'win32' ? 'rustc.exe' : 'rustc');",
      "  const cargoCandidate = path.join(sysrootResult.stdout.trim(), 'bin', process.platform === 'win32' ? 'cargo.exe' : 'cargo');",
      "  if (fs.existsSync(rustcCandidate)) rustcToolchainSha256 = hashRegularFile(rustcCandidate);",
      "  if (fs.existsSync(cargoCandidate)) cargoToolchainSha256 = hashRegularFile(cargoCandidate);",
      "}",
      "const continuity = { rustcVersion: rustcMatch[1], cargoVersion: cargoMatch[1], versions: orderedVersions, resolveGraph, sourceBindings, rustcExecutableSha256, cargoExecutableSha256, rustcToolchainSha256, cargoToolchainSha256 };",
      "const dependencyTreeSha256 = crypto.createHash('sha256').update(JSON.stringify(continuity)).digest('hex');",
      "process.stdout.write(JSON.stringify({ ...continuity, dependencyTreeSha256 }));"
    ].join('\n');
    probeResult = await runScript(workspaceRoot, 'javascript', source, options.probePhaseName || 'environment-probe', {
      ...options,
      timeoutMs: Math.min(options.timeoutMs || DEFAULT_TIMEOUT_MS, 10_000)
    });
    let cargoVersion = null;
    let resolvedVersions = {};
    if (probeResult.exitCode === 0) {
      try {
        const parsed = JSON.parse(probeResult.stdout.trim());
        actualRuntime = parsed.rustcVersion;
        cargoVersion = parsed.cargoVersion;
        resolvedVersions = isPlainObject(parsed.versions) ? parsed.versions : {};
        dependencyTreeSha256 = typeof parsed.dependencyTreeSha256 === 'string' ? parsed.dependencyTreeSha256 : null;
        dependencyIntegrityKind = 'rust-toolchain-and-resolved-source-tree';
      } catch {
        // Reported as a failed probe below.
      }
    }
    for (const packageName of Object.keys(expectedPackages)) {
      if (packageName === 'rustc') actualPackages[packageName] = actualRuntime;
      else if (packageName === 'cargo') actualPackages[packageName] = cargoVersion;
      else {
        const candidates = Array.isArray(resolvedVersions[packageName]) ? resolvedVersions[packageName] : [];
        actualPackages[packageName] = candidates.length === 1
          ? candidates[0]
          : candidates.length > 1 ? [...candidates].sort().join(',') : null;
      }
    }
  }

  const mismatches = [];
  let dependencyLock = null;
  if (bundle.patch.dependencyLock) {
    const relativeLockPath = assertSafeRelativePath(bundle.patch.dependencyLock.path, 'patch.dependencyLock.path');
    const externalLockPath = path.join(dependencyRoot, ...relativeLockPath.split('/'));
    const expectedLockSize = Buffer.byteLength(bundle.verification.workspaceFiles[relativeLockPath], 'utf8');
    let actualDigest = null;
    try {
      const lockStat = fs.lstatSync(externalLockPath);
      if (
        lockStat.isFile() &&
        !lockStat.isSymbolicLink() &&
        lockStat.size === expectedLockSize &&
        isPathContained(dependencyRoot, externalLockPath)
      ) {
        actualDigest = sha256(fs.readFileSync(externalLockPath));
      }
    } catch { /* reported as unavailable below */ }
    dependencyLock = {
      path: relativeLockPath,
      expectedSha256: bundle.patch.dependencyLock.sha256,
      actualSha256: actualDigest,
      matched: actualDigest === bundle.patch.dependencyLock.sha256
    };
    if (!dependencyLock.matched) {
      mismatches.push(
        `dependency lock ${relativeLockPath}: expected ${bundle.patch.dependencyLock.sha256}, got ${actualDigest || 'unavailable'}`
      );
    }
  }
  const hostPlatform = normalizedHostPlatform();
  if (!dependencyTreeSha256) {
    const detail = dependencyIntegrityTimedOut ? 'timed out' : dependencyIntegrityError ? 'probe failed' : 'unavailable or unsafe';
    mismatches.push(`dependency integrity ${dependencyIntegrityKind || bundle.scope.runtime}: ${detail}`);
  }
  if (bundle.scope.platform !== 'all' && bundle.scope.platform !== hostPlatform) {
    mismatches.push(`platform: expected ${bundle.scope.platform}, got ${hostPlatform}`);
  }
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
    dependencyLock,
    dependencyTreeSha256,
    dependencyIntegrityKind,
    dependencyIntegrityTimedOut,
    platform: { expected: bundle.scope.platform, actual: hostPlatform },
    runtime: { name: bundle.scope.runtime, expected: expectedRuntime, actual: actualRuntime },
    packages: Object.fromEntries(Object.entries(expectedPackages).map(([name, expected]) => [
      name,
      { expected, actual: actualPackages[name] ?? null, matched: actualPackages[name] === expected }
    ])),
    mismatches,
    probe: probeResult ? summarizePhase(probeResult, options) : null
  };
}

async function probeDependencyIntegrity(bundle, workspaceRoot, options, baselineSha256, phaseName) {
  const probe = await probeExecutionEnvironment(bundle, workspaceRoot, {
    ...options,
    probePhaseName: `dependency-integrity-${phaseName.replace(/[^A-Za-z0-9_-]/g, '-')}`
  });
  const actualSha256 = probe.dependencyTreeSha256 || null;
  return {
    phase: phaseName,
    matched: probe.passed && Boolean(baselineSha256) && actualSha256 === baselineSha256,
    skipped: false,
    timedOut: Boolean(probe.dependencyIntegrityTimedOut),
    kind: probe.dependencyIntegrityKind || null,
    sha256: actualSha256
  };
}

async function verifyBundle(bundle, options = {}) {
  assertSupportedNodeRuntime();
  if (!options.allowCodeExecution) {
    throw new VerificationError(
      'Bundle verification executes untrusted code. Pass allowCodeExecution: true only inside an appropriate isolated environment.'
    );
  }
  validateBundle(bundle, options.schema || null);
  if (bundle.status === 'REVOKED' || (bundle.status === 'STALE' && !options.allowStale)) {
    throw new VerificationError(
      `Refusing to execute a ${bundle.status} compatibility bundle`,
      { bundleId: bundle.bundleId, status: bundle.status }
    );
  }

  const started = process.hrtime.bigint();
  const temporaryRoot = fs.mkdtempSync(path.join(options.tempRoot || os.tmpdir(), 'synapse-verify-'));
  const timeoutMs = Math.min(bundle.verification.timeoutMs || DEFAULT_TIMEOUT_MS, options.timeoutMs || Number.MAX_SAFE_INTEGER);
  const totalTimeoutMs = Math.min(
    bundle.verification.maxTotalDurationMs || DEFAULT_TOTAL_TIMEOUT_MS,
    options.maxTotalDurationMs || Number.MAX_SAFE_INTEGER
  );
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
    dependencyRoot,
    includeOutput: Boolean(options.includeOutput)
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
    return workspace;
  };

  let preResult;
  let postResult;
  let environmentResult;
  const mutationResults = [];
  const dependencyIntegrityResults = [];
  let failureReason = null;
  let signatureMatched = false;
  let fingerprintMatchResult = null;
  const nextScriptOptions = () => {
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1_000_000;
    const remainingMs = Math.floor(totalTimeoutMs - elapsedMs);
    if (remainingMs <= 0) return null;
    return { ...scriptOptions, timeoutMs: Math.max(1, Math.min(timeoutMs, remainingMs)) };
  };

  try {
    const environmentWorkspace = createFreshWorkspace('environment');
    const environmentOptions = nextScriptOptions();
    if (!environmentOptions) {
      environmentResult = { passed: false, skipped: false, mismatches: ['total time budget exhausted'] };
      failureReason = 'Total verification time budget exceeded before environment preflight';
    } else {
      environmentResult = await probeExecutionEnvironment(bundle, environmentWorkspace, environmentOptions);
    }
    if (environmentResult.dependencyIntegrityTimedOut) {
      failureReason ||= 'Dependency integrity hashing timed out during environment preflight';
    } else if (!environmentResult.passed) {
      failureReason ||= `Environment preflight failed: ${environmentResult.mismatches.join('; ')}`;
    }

    const preWorkspace = createFreshWorkspace('pre-fail');
    if (!failureReason) {
      const preOptions = nextScriptOptions();
      if (!preOptions) failureReason = 'Total verification time budget exceeded before pre-fail';
      else preResult = await runScript(
        preWorkspace,
        bundle.verification.scriptLanguage,
        bundle.verification.reproductionScript,
        'reproduction',
        preOptions
      );
    }
    const preOutput = !preResult ? '' : bundle.fingerprint.matchStream === 'stdout'
      ? preResult.stdout
      : bundle.fingerprint.matchStream === 'stderr'
        ? preResult.stderr
        : `${preResult.stderr}\n${preResult.stdout}`;
    const preExitMatches = preResult ? preResult.exitCode === bundle.verification.expectedPreExit : false;
    if (preResult) {
      const fingerprintOptions = nextScriptOptions();
      if (!fingerprintOptions) {
        failureReason ||= 'Total verification time budget exceeded before fingerprint evaluation';
        fingerprintMatchResult = { matched: false, timedOut: true, error: 'total time budget exhausted' };
      } else {
        fingerprintMatchResult = await testRegexSafely(
          bundle.fingerprint.regex,
          bundle.fingerprint.regexFlags || '',
          preOutput,
          Math.max(1, Math.min(REGEX_TIMEOUT_MS, fingerprintOptions.timeoutMs))
        );
      }
    } else {
      fingerprintMatchResult = null;
    }
    signatureMatched = fingerprintMatchResult ? fingerprintMatchResult.matched : false;
    const prePassed = preResult ? phasePassedWithoutHarnessFailure(preResult) && preExitMatches && signatureMatched : false;

    if (!failureReason && preResult) {
      const integrityOptions = nextScriptOptions();
      if (!integrityOptions) failureReason = 'Total verification time budget exceeded after pre-fail';
      else {
        const integrity = await probeDependencyIntegrity(
          bundle,
          environmentWorkspace,
          integrityOptions,
          environmentResult.dependencyTreeSha256,
          'pre-fail'
        );
        dependencyIntegrityResults.push(integrity);
        if (integrity.timedOut) failureReason = 'Dependency integrity hashing timed out after pre-fail';
        else if (!integrity.matched) failureReason = 'Dependency integrity gate failed after pre-fail';
      }
    }

    if (!failureReason && !prePassed) {
      const fingerprintFailure = fingerprintMatchResult && (fingerprintMatchResult.timedOut || fingerprintMatchResult.error)
        ? `, fingerprintError=${fingerprintMatchResult.error}`
        : '';
      failureReason = `Pre-fail gate failed (exit=${preResult.exitCode}, expected=${bundle.verification.expectedPreExit}, signatureMatched=${signatureMatched}${fingerprintFailure})`;
    } else if (!failureReason) {
      const postWorkspace = createFreshWorkspace('post-pass');
      applyPatchInWorkspace(postWorkspace, bundle.patch.targetFile, bundle.patch.unifiedDiff);
      const postOptions = nextScriptOptions();
      if (!postOptions) failureReason = 'Total verification time budget exceeded before post-pass';
      else postResult = await runScript(
        postWorkspace,
        bundle.verification.scriptLanguage,
        bundle.verification.testSuite,
        'post-pass',
        postOptions
      );
      if (postResult) {
        const postPassed = phasePassedWithoutHarnessFailure(postResult) &&
          postResult.exitCode === bundle.verification.expectedPostExit;
        const postIntegrityOptions = nextScriptOptions();
        if (!postIntegrityOptions) failureReason = 'Total verification time budget exceeded after post-pass';
        else {
          const postIntegrity = await probeDependencyIntegrity(
            bundle,
            environmentWorkspace,
            postIntegrityOptions,
            environmentResult.dependencyTreeSha256,
            'post-pass'
          );
          dependencyIntegrityResults.push(postIntegrity);
          if (postIntegrity.timedOut) failureReason = 'Dependency integrity hashing timed out after post-pass';
          else if (!postIntegrity.matched) failureReason = 'Dependency integrity gate failed after post-pass';
          else if (!postPassed) failureReason = `Post-pass gate failed (exit=${postResult.exitCode})`;
        }

        if (postPassed && !failureReason) {
          for (const [index, mutation] of bundle.verification.mutations.entries()) {
            const mutationWorkspace = createFreshWorkspace(`mutation-${String(index + 1).padStart(2, '0')}`);
            applyPatchInWorkspace(mutationWorkspace, bundle.patch.targetFile, mutation.unifiedDiff);
            const mutationOptions = nextScriptOptions();
            if (!mutationOptions) {
              failureReason = `Total verification time budget exceeded before mutation ${index + 1}`;
              break;
            }
            const mutationResult = await runScript(
              mutationWorkspace,
              bundle.verification.scriptLanguage,
              bundle.verification.testSuite,
              `mutation-${index + 1}`,
              mutationOptions
            );
            const mutationOutput = `${mutationResult.stderr}\n${mutationResult.stdout}`;
            let expectedErrorResult = null;
            if (mutation.expectedErrorRegex) {
              const mutationRegexOptions = nextScriptOptions();
              if (!mutationRegexOptions) {
                failureReason = `Total verification time budget exceeded before mutation ${index + 1} error matching`;
                expectedErrorResult = { matched: false, timedOut: true, error: 'total time budget exhausted' };
              } else {
                expectedErrorResult = await testRegexSafely(
                  mutation.expectedErrorRegex,
                  '',
                  mutationOutput,
                  Math.max(1, Math.min(REGEX_TIMEOUT_MS, mutationRegexOptions.timeoutMs))
                );
              }
            }
            const expectedErrorMatched = expectedErrorResult ? expectedErrorResult.matched : null;
            const killed = phasePassedWithoutHarnessFailure(mutationResult) &&
              mutationResult.exitCode !== 0 &&
              (expectedErrorMatched === null || (
                expectedErrorMatched && !expectedErrorResult.timedOut && expectedErrorResult.error === null
              ));
            mutationResults.push({
              id: mutation.id,
              description: mutation.description,
              killed,
              expectedErrorMatched,
              expectedErrorMatchTimedOut: expectedErrorResult ? expectedErrorResult.timedOut : null,
              expectedErrorMatchError: expectedErrorResult ? expectedErrorResult.error : null,
              ...summarizePhase(mutationResult, scriptOptions)
            });

            if (failureReason) break;

            const mutationIntegrityOptions = nextScriptOptions();
            if (!mutationIntegrityOptions) {
              failureReason = `Total verification time budget exceeded after mutation ${index + 1}`;
              break;
            }
            const mutationIntegrity = await probeDependencyIntegrity(
              bundle,
              environmentWorkspace,
              mutationIntegrityOptions,
              environmentResult.dependencyTreeSha256,
              `mutation-${index + 1}`
            );
            dependencyIntegrityResults.push(mutationIntegrity);
            if (mutationIntegrity.timedOut) {
              failureReason = `Dependency integrity hashing timed out after mutation ${index + 1}`;
              break;
            }
            if (!mutationIntegrity.matched) {
              failureReason = `Dependency integrity gate failed after mutation ${index + 1}`;
              break;
            }
          }
          const surviving = mutationResults.filter((mutation) => !mutation.killed);
          if (!failureReason && surviving.length > 0) {
            failureReason = `Mutation sanity gate failed; survivors: ${surviving.map((item) => item.id).join(', ')}`;
          }
        }
      }
    }

    const durationMs = Number(process.hrtime.bigint() - started) / 1_000_000;
    if (!failureReason && durationMs > totalTimeoutMs) {
      failureReason = 'Total verification time budget exceeded before successful result construction';
    }
    const result = {
      verified: failureReason === null,
      bundleId: bundle.bundleId,
      bundleStatus: bundle.status,
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
        dependencyIntegrity: dependencyIntegrityResults,
        preFail: preResult ? { ...summarizePhase(preResult, scriptOptions), fingerprint: fingerprintMatchResult } : null,
        postPass: postResult ? summarizePhase(postResult, scriptOptions) : null,
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
    const deadlineRemainingMs = options.deadlineMs === undefined
      ? null
      : Math.floor(options.deadlineMs - Date.now());
    if (deadlineRemainingMs !== null && deadlineRemainingMs <= 0) {
      reject(new BundleValidationError('Total source-loading time budget exceeded'));
      return;
    }
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') {
      reject(new BundleValidationError('Only HTTPS bundle URLs are permitted'));
      return;
    }
    if (parsed.username || parsed.password) {
      reject(new BundleValidationError('Bundle URLs must not contain credentials'));
      return;
    }
    const literalHostname = parsed.hostname.startsWith('[') && parsed.hostname.endsWith(']')
      ? parsed.hostname.slice(1, -1)
      : parsed.hostname;
    if (net.isIP(literalHostname) && !isPublicNetworkAddress(literalHostname)) {
      reject(new BundleValidationError('HTTPS bundle hostname resolves to a non-public network address'));
      return;
    }

    let deadlineTimer = null;
    const request = https.get(parsed, {
      headers: { Accept: 'application/json', 'User-Agent': `${VERIFIER_NAME}/${VERIFIER_VERSION}` },
      lookup: safeHttpsLookup,
      timeout: options.fetchTimeoutMs || 10_000
    }, (response) => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
        response.resume();
        if (redirectsRemaining <= 0 || !response.headers.location) {
          reject(new BundleValidationError('Too many or invalid HTTPS redirects while loading bundle'));
          return;
        }
        let destination;
        try { destination = new URL(response.headers.location, parsed); } catch {
          reject(new BundleValidationError('Invalid redirect URL'));
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
      response.on('error', (error) => {
        if (deadlineTimer) clearTimeout(deadlineTimer);
        reject(error);
      });
      response.on('end', () => {
        if (deadlineTimer) clearTimeout(deadlineTimer);
        resolve(Buffer.concat(chunks));
      });
    });
    if (deadlineRemainingMs !== null) {
      deadlineTimer = setTimeout(
        () => request.destroy(new BundleValidationError('Total source-loading time budget exceeded')),
        deadlineRemainingMs
      );
    }
    request.on('timeout', () => request.destroy(new BundleValidationError('HTTPS bundle request timed out')));
    request.on('error', (error) => {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      reject(error);
    });
    request.on('close', () => {
      if (deadlineTimer) clearTimeout(deadlineTimer);
    });
  });
}

async function loadJsonSource(source, options = {}) {
  let bytes;
  if (/^https:\/\//i.test(source)) {
    bytes = await readHttps(source, options);
  } else if (/^[a-z][a-z0-9+.-]*:\/\//i.test(source)) {
    throw new BundleValidationError('Only local paths and HTTPS URLs are supported');
  } else {
    try {
      const stat = fs.statSync(source);
      const maxBytes = options.maxBundleBytes || DEFAULT_MAX_BUNDLE_BYTES;
      if (!stat.isFile()) throw new BundleValidationError('Local JSON source is not a regular file');
      if (stat.size > maxBytes) throw new BundleValidationError(`Local JSON source exceeds ${maxBytes} bytes`);
      bytes = fs.readFileSync(source);
    } catch (error) {
      if (error instanceof BundleValidationError) throw error;
      throw new BundleValidationError(`Unable to read local JSON source (${error.code || error.name || 'I/O error'})`);
    }
  }

  let value;
  try {
    value = JSON.parse(bytes.toString('utf8'));
  } catch (error) {
    throw new BundleValidationError(`Invalid JSON bundle (${error.name || 'parse error'})`);
  }
  return { value, sha256: sha256(bytes), bytes };
}

function sanitizeEvidenceSource(source) {
  if (typeof source !== 'string' || source.length === 0) return null;
  return /^https:\/\//i.test(source) ? 'https-url' : 'local-file';
}

function evidencePhaseSummary(phase) {
  if (!isPlainObject(phase)) return null;
  const allowedKeys = [
    'exitCode', 'signal', 'durationMs', 'timedOut', 'outputLimitExceeded',
    'stdoutBytes', 'stderrBytes', 'stdoutSha256', 'stderrSha256', 'killed',
    'expectedErrorMatched', 'expectedErrorMatchTimedOut'
  ];
  const summary = {};
  for (const key of allowedKeys) {
    if (Object.prototype.hasOwnProperty.call(phase, key)) summary[key] = phase[key];
  }
  if (typeof phase.id === 'string') summary.idSha256 = sha256(Buffer.from(phase.id, 'utf8'));
  if (isPlainObject(phase.fingerprint)) {
    summary.fingerprint = {
      matched: Boolean(phase.fingerprint.matched),
      timedOut: Boolean(phase.fingerprint.timedOut),
      errorPresent: Boolean(phase.fingerprint.error)
    };
  }
  return summary;
}

function evidenceEnvironmentSummary(environment) {
  if (!isPlainObject(environment)) return null;
  const packages = isPlainObject(environment.packages)
    ? Object.fromEntries(Object.entries(environment.packages).map(([name, value]) => [
      name,
      isPlainObject(value) ? {
        expected: value.expected ?? null,
        actual: value.actual ?? null,
        matched: Boolean(value.matched)
      } : null
    ]))
    : null;
  const dependencyLock = isPlainObject(environment.dependencyLock)
    ? {
      expectedSha256: environment.dependencyLock.expectedSha256 ?? null,
      actualSha256: environment.dependencyLock.actualSha256 ?? null,
      matched: Boolean(environment.dependencyLock.matched)
    }
    : null;
  return {
    passed: Boolean(environment.passed),
    skipped: Boolean(environment.skipped),
    mismatchCount: Array.isArray(environment.mismatches) ? environment.mismatches.length : 0,
    dependencyLock,
    dependencyIntegrityKind: environment.dependencyIntegrityKind ?? null,
    dependencyIntegrityTimedOut: Boolean(environment.dependencyIntegrityTimedOut),
    dependencyTreeSha256: environment.dependencyTreeSha256 ?? null,
    platform: isPlainObject(environment.platform) ? environment.platform : null,
    runtime: isPlainObject(environment.runtime) ? environment.runtime : null,
    packages,
    probe: evidencePhaseSummary(environment.probe)
  };
}

function evidencePhasesSummary(phases) {
  if (!isPlainObject(phases)) return null;
  return {
    environment: evidenceEnvironmentSummary(phases.environment),
    dependencyIntegrity: Array.isArray(phases.dependencyIntegrity)
      ? phases.dependencyIntegrity.map((entry) => ({
        phase: typeof entry.phase === 'string' ? entry.phase : null,
        matched: Boolean(entry.matched),
        timedOut: Boolean(entry.timedOut),
        kind: typeof entry.kind === 'string' ? entry.kind : null,
        sha256: typeof entry.sha256 === 'string' ? entry.sha256 : null
      }))
      : [],
    preFail: evidencePhaseSummary(phases.preFail),
    postPass: evidencePhaseSummary(phases.postPass),
    mutations: Array.isArray(phases.mutations) ? phases.mutations.map(evidencePhaseSummary) : []
  };
}

function evidenceFailureReason(result) {
  if (!result || !result.failureReason) return null;
  const reason = String(result.failureReason);
  if (reason.startsWith('Environment preflight failed')) return 'ENVIRONMENT_PREFLIGHT_FAILED';
  if (reason.startsWith('Dependency integrity')) return 'DEPENDENCY_INTEGRITY_FAILED';
  if (reason.startsWith('Total verification time budget exceeded')) return 'TOTAL_TIME_BUDGET_EXCEEDED';
  if (reason.startsWith('Pre-fail gate failed')) return 'PRE_FAIL_GATE_FAILED';
  if (reason.startsWith('Post-pass gate failed')) return 'POST_PASS_GATE_FAILED';
  if (reason.startsWith('Mutation sanity gate failed')) return 'MUTATION_SANITY_GATE_FAILED';
  if (result.errorType === 'BundleValidationError') return 'BUNDLE_VALIDATION_FAILED';
  if (result.errorType === 'VerificationError') return 'VERIFICATION_ERROR';
  return 'VERIFICATION_FAILED';
}

function createAttestation(result, source) {
  const evidenceSource = sanitizeEvidenceSource(source);
  const evidenceBundleId = typeof result.bundleId === 'string' &&
    /^[a-z0-9](?:[a-z0-9._-]{1,126}[a-z0-9])?$/.test(result.bundleId)
    ? result.bundleId
    : null;
  const evidenceBundleStatus = ['DRAFT', 'CANDIDATE', 'VERIFIED', 'STALE', 'REVOKED'].includes(result.bundleStatus)
    ? result.bundleStatus
    : null;
  return {
    _type: 'https://in-toto.io/Statement/v1',
    subject: result.bundleSha256 ? [{
      name: evidenceBundleId || 'unknown-bundle',
      digest: { sha256: result.bundleSha256 }
    }] : [],
    predicateType: 'https://synapsemesh.dev/attestations/compatibility-verification/v1',
    predicate: {
      generatedAt: new Date().toISOString(),
      source: evidenceSource,
      verified: Boolean(result.verified),
      bundleStatus: evidenceBundleStatus,
      validationOnly: Boolean(result.validationOnly),
      validationPassed: result.validationPassed === undefined ? null : Boolean(result.validationPassed),
      failureReason: evidenceFailureReason(result),
      preExit: result.preExit ?? null,
      postExit: result.postExit ?? null,
      signatureMatched: Boolean(result.signatureMatched),
      mutantsKilled: result.mutantsKilled || null,
      durationMs: result.durationMs ?? null,
      phases: result.phases ? evidencePhasesSummary(result.phases) : null,
      executionEnvironment: {
        nodeVersion: process.version,
        platform: process.platform,
        architecture: process.arch,
        isolation: 'ephemeral-workspace-only'
      },
      verifier: { name: VERIFIER_NAME, version: VERIFIER_VERSION }
    }
  };
}

async function verifySource(source, options = {}) {
  const totalTimeoutMs = options.maxTotalDurationMs || DEFAULT_TOTAL_TIMEOUT_MS;
  const deadlineMs = options.deadlineMs || Date.now() + totalTimeoutMs;
  const sourceOptions = { ...options, deadlineMs };
  const bundleSource = await loadJsonSource(source, sourceOptions);
  if (options.expectedBundleSha256 && bundleSource.sha256 !== options.expectedBundleSha256) {
    throw new BundleValidationError('Bundle SHA-256 does not match the expected digest');
  }
  let schema = options.schema || null;
  if (!schema && options.schemaPath) schema = (await loadJsonSource(options.schemaPath, sourceOptions)).value;
  validateBundle(bundleSource.value, schema);
  const remainingMs = Math.floor(deadlineMs - Date.now());
  if (remainingMs <= 0) throw new VerificationError('Total verification time budget exceeded before execution');
  return verifyBundle(bundleSource.value, {
    ...options,
    schema,
    bundleSha256: bundleSource.sha256,
    maxTotalDurationMs: Math.min(totalTimeoutMs, remainingMs)
  });
}

if (!isMainThread && workerData && workerData.synapseVerifierTask === 'node-dependency-probe') {
  try {
    parentPort.postMessage(nodeDependencyProbeSync(workerData.packageNames, workerData.dependencyRoot));
  } catch (error) {
    parentPort.postMessage({
      packages: {},
      dependencyTreeSha256: null,
      error: error instanceof VerificationError ? error.message : 'Node dependency probe failed'
    });
  }
}

module.exports = {
  BundleValidationError,
  VerificationError,
  applyUnifiedDiff,
  assertSupportedNodeRuntime,
  createAttestation,
  inspectUnifiedDiff,
  isPublicNetworkAddress,
  loadJsonSource,
  normalizedHostPlatform,
  sanitizeEvidenceSource,
  sha256,
  stableStringify,
  testRegexSafely,
  validateBundle,
  validateInstanceAgainstSchema,
  verifyBundle,
  verifySource
};
