/**
 * operations.js — Screen-AI Pipeline Operations + Planning-Engine Execution Graph
 *
 * Two layers:
 *   1. Legacy file-system operations (mkdir, writeFile, readFile, ...) — preserved
 *      for backward compatibility with existing pipelines.
 *   2. Planning-engine execution graph (NODE_TYPES, buildNode, validateNode,
 *      OPERATIONS registry) — every operation carries verification, recovery,
 *      risk, and confidence metadata.
 *
 * Execution priority (per planning-engine spec):
 *   1. Native APIs
 *   2. Application APIs
 *   3. Accessibility APIs
 *   4. Browser DOM
 *   5. Filesystem
 *   6. OCR
 *   7. Vision Detection
 *   8. Mouse/Keyboard simulation (final fallback)
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// ════════════════════════════════════════════════════════════════════════════
// PLANNING-ENGINE LAYER
// ════════════════════════════════════════════════════════════════════════════

/**
 * Node types for the execution graph.
 * Every node in a plan must have one of these types.
 */
const NODE_TYPES = Object.freeze({
  OBSERVE: 'observe',
  DECIDE: 'decide',
  PARALLEL: 'parallel',
  ACT: 'act',
  VERIFY: 'verify',
  RETRY: 'retry',
  ROLLBACK: 'rollback',
  CHECKPOINT: 'checkpoint',
  APPROVAL: 'approval',
  WAIT: 'wait',
  REPLAN: 'replan',
  FINISH: 'finish',
});

/**
 * Risk levels (0-4) per planning-engine spec.
 *   0 = read-only
 *   1 = safe local
 *   2 = local destructive
 *   3 = external communication
 *   4 = financial / credentials / security / irreversible
 */
const RISK_LEVELS = Object.freeze({
  READ_ONLY: 0,
  SAFE_LOCAL: 1,
  LOCAL_DESTRUCTIVE: 2,
  EXTERNAL: 3,
  CRITICAL: 4,
});

/**
 * Build a planning-engine node with full metadata.
 * @param {Object} spec
 * @param {string} spec.id
 * @param {string} spec.type - one of NODE_TYPES
 * @param {string} spec.objective
 * @param {string} [spec.reason]
 * @param {string} [spec.preferred_skill]
 * @param {string[]} [spec.alternative_skills]
 * @param {string[]} [spec.dependencies]
 * @param {Object} [spec.parameters]
 * @param {string} [spec.expected_result]
 * @param {Object} spec.verification - { method, success }
 * @param {string[]} [spec.failure_conditions]
 * @param {string[]} spec.recovery
 * @param {number} [spec.risk]
 * @param {number} [spec.estimated_duration]
 * @param {number} [spec.confidence]
 */
function buildNode(spec) {
  if (!spec || typeof spec !== 'object') {
    throw new TypeError('buildNode requires a spec object');
  }
  if (!Object.values(NODE_TYPES).includes(spec.type)) {
    throw new TypeError(`Invalid node type: ${spec.type}`);
  }
  if (!spec.id) throw new TypeError('Node must have an id');
  if (!spec.objective) throw new TypeError(`Node ${spec.id} must have an objective`);
  if (!spec.verification || !spec.verification.method) {
    throw new TypeError(`Node ${spec.id} must have verification.method`);
  }
  if (!Array.isArray(spec.recovery) || spec.recovery.length === 0) {
    throw new TypeError(`Node ${spec.id} must have at least one recovery option`);
  }

  return {
    id: spec.id,
    type: spec.type,
    objective: spec.objective,
    reason: spec.reason || '',
    preferred_skill: spec.preferred_skill || null,
    alternative_skills: spec.alternative_skills || [],
    dependencies: spec.dependencies || [],
    parameters: spec.parameters || {},
    expected_result: spec.expected_result || '',
    verification: {
      method: spec.verification.method,
      success: spec.verification.success || '',
    },
    failure_conditions: spec.failure_conditions || [],
    recovery: spec.recovery,
    risk: typeof spec.risk === 'number' ? spec.risk : RISK_LEVELS.SAFE_LOCAL,
    estimated_duration: spec.estimated_duration || 5,
    confidence: typeof spec.confidence === 'number' ? spec.confidence : 0.8,
  };
}

/**
 * Validate a node or graph against the planning-engine schema.
 * @param {Object|Array} input - node or array of nodes
 * @returns {{ok: boolean, errors: string[]}}
 */
function validateNode(input) {
  const errors = [];
  const nodes = Array.isArray(input) ? input : [input];

  for (const node of nodes) {
    if (!node || typeof node !== 'object') {
      errors.push('node is not an object');
      continue;
    }
    if (!Object.values(NODE_TYPES).includes(node.type)) {
      errors.push(`node ${node.id || '?'}: invalid type ${node.type}`);
    }
    if (!node.id) errors.push('node missing id');
    if (!node.objective) errors.push(`node ${node.id || '?'}: missing objective`);
    if (!node.verification || !node.verification.method) {
      errors.push(`node ${node.id || '?'}: missing verification.method`);
    }
    if (!Array.isArray(node.recovery) || node.recovery.length === 0) {
      errors.push(`node ${node.id || '?'}: missing recovery[]`);
    }
    if (typeof node.risk === 'number' && (node.risk < 0 || node.risk > 4)) {
      errors.push(`node ${node.id || '?'}: risk must be 0-4`);
    }
  }

  // Graph-level checks
  if (Array.isArray(input) && input.length > 1) {
    const ids = new Set();
    for (const n of input) {
      if (ids.has(n.id)) errors.push(`duplicate node id: ${n.id}`);
      ids.add(n.id);
    }
    for (const n of input) {
      for (const dep of n.dependencies || []) {
        if (!ids.has(dep)) errors.push(`node ${n.id}: unknown dependency ${dep}`);
      }
    }
    // Auto-insert approval check: any node with risk >= 3 must have an approval node upstream
    const highRisk = input.filter(n => (n.risk || 0) >= RISK_LEVELS.EXTERNAL);
    for (const hr of highRisk) {
      const hasApproval = input.some(n =>
        n.type === NODE_TYPES.APPROVAL &&
        (n.dependencies || []).includes(hr.id) === false &&
        (hr.dependencies || []).includes(n.id)
      );
      const hasApprovalDep = (hr.dependencies || []).some(depId => {
        const dep = input.find(x => x.id === depId);
        return dep && dep.type === NODE_TYPES.APPROVAL;
      });
      if (!hasApproval && !hasApprovalDep) {
        errors.push(`node ${hr.id}: risk ${hr.risk} requires an upstream approval node`);
      }
    }
  }

  return { ok: errors.length === 0, errors };
}

/**
 * Auto-insert approval nodes before any high-risk action.
 * @param {Array} nodes
 * @returns {Array} new array with approval nodes inserted
 */
function insertApprovalNodes(nodes) {
  const out = [];
  let nextId = Math.max(...nodes.map(n => parseInt(String(n.id).replace(/\D/g, '')) || 0), 0) + 1;

  for (const node of nodes) {
    if ((node.risk || 0) >= RISK_LEVELS.EXTERNAL) {
      const approvalId = `auto_approval_${nextId++}`;
      out.push(buildNode({
        id: approvalId,
        type: NODE_TYPES.APPROVAL,
        objective: `Request mobile approval for ${node.objective}`,
        reason: `Auto-inserted because node ${node.id} has risk ${node.risk} >= 3`,
        preferred_skill: 'approvals.manager.create_approval',
        alternative_skills: ['approvals.manager.wait_for_approval'],
        dependencies: node.dependencies || [],
        parameters: { risk_level: node.risk, action_type: node.objective },
        expected_result: 'User approves or rejects the action',
        verification: { method: 'approval_resolved', success: 'approval status is approved' },
        recovery: [
          'If rejected, return rejected status to caller',
          'If timeout, abort the downstream action',
        ],
        risk: RISK_LEVELS.READ_ONLY,
        estimated_duration: 30,
        confidence: 0.95,
      }));
      // Make the high-risk node depend on the approval
      node.dependencies = [...(node.dependencies || []), approvalId];
    }
    out.push(node);
  }
  return out;
}

// ─── Operation Registry (planning-engine aligned) ────────────────────────────

const OPERATIONS = {
  // ── File operations ──────────────────────────────────────────────────────
  'file.list': buildNode({
    id: 'file.list',
    type: NODE_TYPES.ACT,
    objective: 'List directory contents',
    preferred_skill: 'file.list',
    alternative_skills: ['fs.readdir'],
    parameters: { path: '.' },
    expected_result: 'Array of file/dir entries',
    verification: { method: 'returns_array', success: 'result is non-empty array' },
    recovery: ['Retry once', 'Return empty array on permission error'],
    risk: RISK_LEVELS.READ_ONLY,
    estimated_duration: 1,
    confidence: 0.98,
  }),
  'file.read': buildNode({
    id: 'file.read',
    type: NODE_TYPES.ACT,
    objective: 'Read file content',
    preferred_skill: 'file.read',
    alternative_skills: ['fs.readFileSync'],
    parameters: { path: '' },
    expected_result: 'File content as string',
    verification: { method: 'content_non_empty', success: 'content length > 0' },
    recovery: ['Retry once', 'Return empty string on missing file'],
    risk: RISK_LEVELS.READ_ONLY,
    estimated_duration: 1,
    confidence: 0.98,
  }),
  'file.write': buildNode({
    id: 'file.write',
    type: NODE_TYPES.ACT,
    objective: 'Write content to file',
    preferred_skill: 'file.write',
    alternative_skills: ['fs.writeFileSync'],
    parameters: { path: '', content: '' },
    expected_result: 'File written successfully',
    verification: { method: 'file_exists', success: 'file exists and size matches' },
    recovery: ['Retry once', 'Ensure parent directory exists, retry'],
    risk: RISK_LEVELS.LOCAL_DESTRUCTIVE,
    estimated_duration: 2,
    confidence: 0.95,
  }),
  'file.delete': buildNode({
    id: 'file.delete',
    type: NODE_TYPES.ACT,
    objective: 'Delete file (move to quarantine)',
    preferred_skill: 'file.quarantine',
    alternative_skills: ['fs.unlinkSync'],
    parameters: { path: '' },
    expected_result: 'File moved to quarantine',
    verification: { method: 'file_removed', success: 'original path no longer exists' },
    recovery: ['Restore from quarantine', 'Retry delete'],
    risk: RISK_LEVELS.LOCAL_DESTRUCTIVE,
    estimated_duration: 2,
    confidence: 0.9,
  }),
  'file.delete_permanent': buildNode({
    id: 'file.delete_permanent',
    type: NODE_TYPES.ACT,
    objective: 'Permanently delete file',
    preferred_skill: 'file.delete_permanent',
    alternative_skills: ['fs.unlinkSync'],
    parameters: { path: '' },
    expected_result: 'File permanently removed',
    verification: { method: 'file_removed', success: 'original path no longer exists' },
    recovery: ['Cannot recover — log warning'],
    risk: RISK_LEVELS.CRITICAL,
    estimated_duration: 2,
    confidence: 0.85,
  }),

  // ── Browser operations ───────────────────────────────────────────────────
  'browser.open': buildNode({
    id: 'browser.open',
    type: NODE_TYPES.ACT,
    objective: 'Open URL in browser',
    preferred_skill: 'browser.open',
    alternative_skills: ['playwright.page.goto', 'os.start'],
    parameters: { url: '' },
    expected_result: 'Browser tab opened with URL',
    verification: { method: 'dom_loaded', success: 'document.readyState === complete' },
    recovery: ['Retry with system browser fallback', 'Reuse existing tab if URL matches'],
    risk: RISK_LEVELS.EXTERNAL,
    estimated_duration: 5,
    confidence: 0.9,
  }),
  'browser.search': buildNode({
    id: 'browser.search',
    type: NODE_TYPES.ACT,
    objective: 'Search the web',
    preferred_skill: 'browser.search',
    alternative_skills: ['browser.open'],
    parameters: { query: '' },
    expected_result: 'Search results page loaded',
    verification: { method: 'results_visible', success: 'search result elements present' },
    recovery: ['Retry with different search engine', 'Open URL directly'],
    risk: RISK_LEVELS.EXTERNAL,
    estimated_duration: 5,
    confidence: 0.9,
  }),
  'browser.click': buildNode({
    id: 'browser.click',
    type: NODE_TYPES.ACT,
    objective: 'Click element in browser',
    preferred_skill: 'browser.click',
    alternative_skills: ['playwright.page.click', 'screen.click_text'],
    parameters: { selector: '', text: '' },
    expected_result: 'Element clicked, page state changed',
    verification: { method: 'dom_changed', success: 'expected element appeared or disappeared' },
    recovery: ['Retry with accessibility selector', 'Retry with OCR text match', 'Retry with mouse coordinates'],
    risk: RISK_LEVELS.EXTERNAL,
    estimated_duration: 3,
    confidence: 0.85,
  }),

  // ── System operations ────────────────────────────────────────────────────
  'system.status': buildNode({
    id: 'system.status',
    type: NODE_TYPES.ACT,
    objective: 'Get system status',
    preferred_skill: 'system.status',
    alternative_skills: ['os.cpus', 'os.freemem'],
    parameters: {},
    expected_result: 'CPU, RAM, disk usage',
    verification: { method: 'returns_object', success: 'result has cpu, ram, disk fields' },
    recovery: ['Retry once', 'Return partial data on error'],
    risk: RISK_LEVELS.READ_ONLY,
    estimated_duration: 1,
    confidence: 0.98,
  }),
  'system.open_app': buildNode({
    id: 'system.open_app',
    type: NODE_TYPES.ACT,
    objective: 'Open application',
    preferred_skill: 'system.open_app',
    alternative_skills: ['os.start'],
    parameters: { name: '' },
    expected_result: 'Application window visible',
    verification: { method: 'window_exists', success: 'process is running and window is visible' },
    recovery: ['Retry with full path', 'Search Start Menu'],
    risk: RISK_LEVELS.SAFE_LOCAL,
    estimated_duration: 3,
    confidence: 0.9,
  }),

  // ── Screen operations ────────────────────────────────────────────────────
  'screen.scan': buildNode({
    id: 'screen.scan',
    type: NODE_TYPES.ACT,
    objective: 'Scan screen for actionable controls',
    preferred_skill: 'screen.scan',
    alternative_skills: ['uia_scan', 'ocr_scan'],
    parameters: {},
    expected_result: 'List of UI elements with coordinates',
    verification: { method: 'returns_array', success: 'result has at least one element' },
    recovery: ['Retry with OCR fallback', 'Retry with vision detection'],
    risk: RISK_LEVELS.READ_ONLY,
    estimated_duration: 3,
    confidence: 0.9,
  }),
  'screen.click_text': buildNode({
    id: 'screen.click_text',
    type: NODE_TYPES.ACT,
    objective: 'Click on visible text',
    preferred_skill: 'screen.click_text',
    alternative_skills: ['uia_click', 'mouse_click'],
    parameters: { text: '' },
    expected_result: 'Element clicked',
    verification: { method: 'screen_changed', success: 'screen state changed after click' },
    recovery: ['Retry with fuzzy match', 'Retry with OCR', 'Retry with mouse coordinates'],
    risk: RISK_LEVELS.SAFE_LOCAL,
    estimated_duration: 3,
    confidence: 0.85,
  }),

  // ── Auth / Vault operations ──────────────────────────────────────────────
  'vault.unlock': buildNode({
    id: 'vault.unlock',
    type: NODE_TYPES.ACT,
    objective: 'Unlock password vault',
    preferred_skill: 'vault.unlock',
    alternative_skills: ['vault.derive_key'],
    parameters: { master_key: '' },
    expected_result: 'Vault unlocked, session token issued',
    verification: { method: 'vault_unlocked', success: 'vault.is_unlocked() returns true' },
    recovery: ['Retry with new master key', 'Request approval for biometric unlock'],
    risk: RISK_LEVELS.CRITICAL,
    estimated_duration: 5,
    confidence: 0.9,
  }),
  'auth.password_login': buildNode({
    id: 'auth.password_login',
    type: NODE_TYPES.ACT,
    objective: 'Login with saved password',
    preferred_skill: 'auth.password_login',
    alternative_skills: ['browser.fill_form'],
    parameters: { site: '', username: '' },
    expected_result: 'Login successful, dashboard visible',
    verification: { method: 'login_succeeded', success: 'expected post-login element visible' },
    recovery: ['Retry with different credentials', 'Request passkey approval'],
    risk: RISK_LEVELS.CRITICAL,
    estimated_duration: 10,
    confidence: 0.85,
  }),
};

// ════════════════════════════════════════════════════════════════════════════
// LEGACY FILE-SYSTEM OPERATIONS (preserved for backward compatibility)
// ════════════════════════════════════════════════════════════════════════════

function resolveProject(root, ...segments) {
  return path.resolve(root, ...segments);
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function simpleGlob(pattern, rootDir) {
  const regex = pattern
    .replace(/\*\*/g, '<<GLOBSTAR>>')
    .replace(/\*/g, '[^/]*')
    .replace(/\?/g, '[^/]')
    .replace(/\{([^}]+)\}/g, (_, alternates) => {
      return `(${alternates.split(',').join('|')})`;
    })
    .replace(/<<GLOBSTAR>>/g, '.*');

  const re = new RegExp(`^${regex}$`);
  const results = [];

  function walk(dir) {
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const full = path.join(dir, entry.name);
        const rel = path.relative(rootDir, full).replace(/\\/g, '/');
        if (entry.isDirectory()) {
          walk(full);
        } else if (re.test(rel)) {
          results.push(full);
        }
      }
    } catch (e) {
      // Skip inaccessible dirs
    }
  }

  walk(rootDir);
  return results;
}

function createContext(root, vars = {}) {
  return {
    root: path.resolve(root),
    vars: { ...vars },
    results: [],
    errors: [],
    log: [],
    startTime: Date.now(),
    dryRun: vars.dryRun || false,
  };
}

function mkdir(ctx) {
  const target = resolveProject(ctx.root, ctx.vars.target || ctx.vars.path);
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] mkdir: ${target}`);
    return ctx;
  }
  ensureDir(target);
  ctx.results.push({ op: 'mkdir', path: target, created: true });
  ctx.log.push(`mkdir: ${target}`);
  return ctx;
}

function writeFile(ctx) {
  const target = resolveProject(ctx.root, ctx.vars.target || ctx.vars.path);
  const content = ctx.vars.contentVar ? (ctx.vars[ctx.vars.contentVar] || '') : (ctx.vars.content || '');
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] writeFile: ${target} (${content.length} chars)`);
    return ctx;
  }
  ensureDir(path.dirname(target));
  fs.writeFileSync(target, content, 'utf-8');
  ctx.results.push({ op: 'writeFile', path: target, bytes: Buffer.byteLength(content) });
  ctx.log.push(`writeFile: ${target} (${Buffer.byteLength(content)} bytes)`);
  return ctx;
}

function readFile(ctx) {
  const source = resolveProject(ctx.root, ctx.vars.source);
  const destVar = ctx.vars.destVar || 'content';
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] readFile: ${source} -> vars.${destVar}`);
    return ctx;
  }
  const content = fs.readFileSync(source, 'utf-8');
  ctx.vars[destVar] = content;
  ctx.results.push({ op: 'readFile', path: source, bytes: Buffer.byteLength(content) });
  ctx.log.push(`readFile: ${source} -> vars.${destVar} (${Buffer.byteLength(content)} bytes)`);
  return ctx;
}

function copyFile(ctx) {
  const source = resolveProject(ctx.root, ctx.vars.source);
  const target = resolveProject(ctx.root, ctx.vars.target);
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] copy: ${source} -> ${target}`);
    return ctx;
  }
  ensureDir(path.dirname(target));
  fs.copyFileSync(source, target);
  ctx.results.push({ op: 'copyFile', source, target });
  ctx.log.push(`copy: ${source} -> ${target}`);
  return ctx;
}

function moveFile(ctx) {
  const source = resolveProject(ctx.root, ctx.vars.source);
  const target = resolveProject(ctx.root, ctx.vars.target);
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] move: ${source} -> ${target}`);
    return ctx;
  }
  ensureDir(path.dirname(target));
  fs.renameSync(source, target);
  ctx.results.push({ op: 'moveFile', source, target });
  ctx.log.push(`move: ${source} -> ${target}`);
  return ctx;
}

function deleteFile(ctx) {
  const target = resolveProject(ctx.root, ctx.vars.target || ctx.vars.path);
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] delete: ${target}`);
    return ctx;
  }
  try {
    fs.unlinkSync(target);
    ctx.results.push({ op: 'deleteFile', path: target, deleted: true });
    ctx.log.push(`delete: ${target}`);
  } catch (e) {
    ctx.errors.push({ op: 'deleteFile', path: target, error: e.message });
    ctx.log.push(`delete FAILED: ${target} - ${e.message}`);
  }
  return ctx;
}

function deleteDir(ctx) {
  const target = resolveProject(ctx.root, ctx.vars.target || ctx.vars.path);
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] deleteDir: ${target}`);
    return ctx;
  }
  try {
    fs.rmSync(target, { recursive: true, force: true });
    ctx.results.push({ op: 'deleteDir', path: target, deleted: true });
    ctx.log.push(`deleteDir: ${target}`);
  } catch (e) {
    ctx.errors.push({ op: 'deleteDir', path: target, error: e.message });
    ctx.log.push(`deleteDir FAILED: ${target} - ${e.message}`);
  }
  return ctx;
}

function listDir(ctx) {
  const target = resolveProject(ctx.root, ctx.vars.target || ctx.vars.path);
  const destVar = ctx.vars.destVar || 'files';
  try {
    const entries = fs.readdirSync(target, { withFileTypes: true });
    ctx.vars[destVar] = entries.map(e => ({
      name: e.name,
      isDir: e.isDirectory(),
      path: path.join(target, e.name),
    }));
    ctx.results.push({ op: 'listDir', path: target, count: entries.length });
    ctx.log.push(`listDir: ${target} (${entries.length} entries)`);
  } catch (e) {
    ctx.vars[destVar] = [];
    ctx.errors.push({ op: 'listDir', path: target, error: e.message });
    ctx.log.push(`listDir FAILED: ${target} - ${e.message}`);
  }
  return ctx;
}

function glob(ctx) {
  const rootDir = resolveProject(ctx.root, ctx.vars.searchPath || '.');
  const pattern = ctx.vars.pattern;
  const destVar = ctx.vars.destVar || 'matches';
  const files = simpleGlob(pattern, rootDir);
  ctx.vars[destVar] = files;
  ctx.results.push({ op: 'glob', pattern, rootDir, count: files.length });
  ctx.log.push(`glob: ${pattern} (${files.length} matches)`);
  return ctx;
}

function appendFile(ctx) {
  const target = resolveProject(ctx.root, ctx.vars.target);
  const content = ctx.vars.contentVar ? (ctx.vars[ctx.vars.contentVar] || '') : (ctx.vars.content || '');
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] append: ${target}`);
    return ctx;
  }
  ensureDir(path.dirname(target));
  fs.appendFileSync(target, content, 'utf-8');
  ctx.results.push({ op: 'appendFile', path: target, bytes: Buffer.byteLength(content) });
  ctx.log.push(`append: ${target} (${Buffer.byteLength(content)} bytes)`);
  return ctx;
}

function template(ctx) {
  const tpl = ctx.vars.template || '';
  const destVar = ctx.vars.destVar || 'content';
  const rendered = tpl.replace(/\{\{(\w+)\}\}/g, (_, key) => {
    return ctx.vars[key] !== undefined ? String(ctx.vars[key]) : `{{${key}}}`;
  });
  ctx.vars[destVar] = rendered;
  ctx.results.push({ op: 'template', destVar });
  ctx.log.push(`template -> vars.${destVar}`);
  return ctx;
}

function connect(ctx) {
  const source = resolveProject(ctx.root, ctx.vars.source);
  const target = resolveProject(ctx.root, ctx.vars.target);
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] connect: ${source} -> ${target}`);
    return ctx;
  }
  let content = fs.readFileSync(source, 'utf-8');
  if (typeof ctx.vars.transform === 'function') {
    content = ctx.vars.transform(content, ctx.vars);
  } else if (typeof ctx.vars.transform === 'string') {
    content = content.replace(/\{\{(\w+)\}\}/g, (_, key) => {
      return ctx.vars[key] !== undefined ? String(ctx.vars[key]) : `{{${key}}}`;
    });
  }
  ensureDir(path.dirname(target));
  fs.writeFileSync(target, content, 'utf-8');
  ctx.results.push({ op: 'connect', source, target, bytes: Buffer.byteLength(content) });
  ctx.log.push(`connect: ${source} -> ${target} (${Buffer.byteLength(content)} bytes)`);
  return ctx;
}

function exec_cmd(ctx) {
  const command = ctx.vars.command;
  if (ctx.dryRun) {
    ctx.log.push(`[DRY] exec: ${command}`);
    return ctx;
  }
  try {
    const output = execSync(command, {
      cwd: ctx.root,
      encoding: 'utf-8',
      timeout: ctx.vars.timeout || 30000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    ctx.vars.lastOutput = output.trim();
    ctx.results.push({ op: 'exec', command, output: output.trim() });
    ctx.log.push(`exec: ${command} (${output.length} chars)`);
  } catch (e) {
    ctx.errors.push({ op: 'exec', command, error: e.message });
    ctx.log.push(`exec FAILED: ${command} - ${e.message}`);
    ctx.vars.lastOutput = e.stdout ? e.stdout.toString() : '';
  }
  return ctx;
}

function batch(operation) {
  return function batchOp(ctx) {
    const list = ctx.vars.list || [];
    for (let i = 0; i < list.length; i++) {
      const item = list[i];
      const oldVars = { ...ctx.vars };
      Object.assign(ctx.vars, item);
      ctx = operation(ctx);
      ctx.vars = { ...oldVars, ...ctx.vars };
    }
    return ctx;
  };
}

function condition(checkFn, thenOps, elseOps = []) {
  return function condOp(ctx) {
    const result = typeof checkFn === 'function' ? checkFn(ctx.vars) : !!ctx.vars[checkFn];
    const ops = result ? thenOps : elseOps;
    for (const op of ops) {
      ctx = op(ctx);
    }
    return ctx;
  };
}

function variable(key, valueOrFn) {
  return function varOp(ctx) {
    if (typeof valueOrFn === 'function') {
      ctx.vars[key] = valueOrFn(ctx.vars);
    } else {
      ctx.vars[key] = valueOrFn;
    }
    ctx.log.push(`var: ${key} = ${JSON.stringify(ctx.vars[key]).slice(0, 80)}`);
    return ctx;
  };
}

function sleep(ms) {
  return function sleepOp(ctx) {
    if (ctx.dryRun) {
      ctx.log.push(`[DRY] sleep: ${ms}ms`);
      return ctx;
    }
    const end = Date.now() + ms;
    while (Date.now() < end) { /* busy wait */ }
    ctx.log.push(`sleep: ${ms}ms`);
    return ctx;
  };
}

function chain(operations) {
  return function chainOp(ctx) {
    for (const op of operations) {
      if (typeof op === 'function') {
        ctx = op(ctx);
      }
    }
    return ctx;
  };
}

// ════════════════════════════════════════════════════════════════════════════
// EXPORTS
// ════════════════════════════════════════════════════════════════════════════

module.exports = {
  // Planning-engine layer
  NODE_TYPES,
  RISK_LEVELS,
  buildNode,
  validateNode,
  insertApprovalNodes,
  OPERATIONS,

  // Legacy helpers
  createContext,
  resolveProject,
  ensureDir,
  simpleGlob,

  // Legacy file operations
  mkdir,
  writeFile,
  readFile,
  copyFile,
  moveFile,
  deleteFile,
  deleteDir,
  listDir,
  glob,
  appendFile,

  // Legacy content operations
  template,
  connect,
  exec: exec_cmd,

  // Legacy control flow
  batch,
  condition,
  variable,
  sleep,
  chain,
};
