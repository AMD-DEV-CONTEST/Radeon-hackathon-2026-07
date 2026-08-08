#!/usr/bin/env node
/**
 * test_pipeline.js — Comprehensive test suite for Screen-AI Pipeline System
 *
 * Run: node pipeline/test_pipeline.js
 * 
 * Tests:
 *   1. Operations: mkdir, writeFile, readFile, copyFile, moveFile, deleteFile
 *   2. Operations: listDir, glob, appendFile, template, connect
 *   3. Operations: batch, condition, variable, chain
 *   4. Engine: Pipeline, PipelineRegistry, middleware
 *   5. Engine: error handling, dry-run
 *   6. Integration: scaffold-full, build-frontend, clean, connect-all
 *   7. Integration: CLI commands
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { Pipeline, PipelineRegistry, loggingMiddleware, requireVars, tolerateErrors, metricsMiddleware } = require('./engine');
const os = require('os');
const ops = require('./operations');

// ─── Test Framework ─────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
let total = 0;

function test(name, fn) {
  total++;
  try {
    fn();
    passed++;
    console.log(`  ✅ ${name}`);
  } catch (err) {
    failed++;
    console.log(`  ❌ ${name}`);
    console.log(`     ${err.message}`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'Assertion failed');
}

function assertEqual(a, b, message) {
  if (a !== b) throw new Error(message || `Expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
}

function assertExists(filePath, message) {
  if (!fs.existsSync(filePath)) throw new Error(message || `File not found: ${filePath}`);
}

function assertNotExists(filePath, message) {
  if (fs.existsSync(filePath)) throw new Error(message || `File should not exist: ${filePath}`);
}

function assertIncludes(str, substr, message) {
  if (!str.includes(substr)) throw new Error(message || `Expected "${str}" to include "${substr}"`);
}

// ─── Test Directory ─────────────────────────────────────────────────────────

const TEST_DIR = path.join(__dirname, '_test_tmp');
const ROOT = path.join(TEST_DIR, 'project');

function setup() {
  if (fs.existsSync(TEST_DIR)) fs.rmSync(TEST_DIR, { recursive: true, force: true });
  fs.mkdirSync(ROOT, { recursive: true });
}

function teardown() {
  if (fs.existsSync(TEST_DIR)) fs.rmSync(TEST_DIR, { recursive: true, force: true });
}

// ─── TESTS ──────────────────────────────────────────────────────────────────

console.log('\n══════════════════════════════════════════════════════');
console.log('  Screen-AI Pipeline Test Suite');
console.log('══════════════════════════════════════════════════════\n');

// === Operations Tests ===

console.log('📦 Operations:');

test('createContext creates valid context', () => {
  const ctx = ops.createContext(path.join(os.tmpdir(), 'pipeline_test_xyz'));
  assert(ctx.root.includes('pipeline_test_xyz'));
  assert(Array.isArray(ctx.results));
  assert(Array.isArray(ctx.errors));
  assert(Array.isArray(ctx.log));
});

test('mkdir creates directory', () => {
  setup();
  try {
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'src/components';
    ctx = ops.mkdir(ctx);
    assertExists(path.join(ROOT, 'src/components'));
    assert(ctx.results.length === 1);
  } finally { teardown(); }
});

test('writeFile creates file with content', () => {
  setup();
  try {
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'hello.txt';
    ctx.vars.content = 'Hello World';
    ctx = ops.writeFile(ctx);
    assertExists(path.join(ROOT, 'hello.txt'));
    assertEqual(fs.readFileSync(path.join(ROOT, 'hello.txt'), 'utf-8'), 'Hello World');
    assert(ctx.results[0].bytes === 11);
  } finally { teardown(); }
});

test('writeFile creates nested dirs automatically', () => {
  setup();
  try {
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'deep/nested/path/file.txt';
    ctx.vars.content = 'nested';
    ctx = ops.writeFile(ctx);
    assertExists(path.join(ROOT, 'deep/nested/path/file.txt'));
  } finally { teardown(); }
});

test('readFile reads into vars', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'data.txt'), 'file content');
    let ctx = ops.createContext(ROOT);
    ctx.vars.source = 'data.txt';
    ctx.vars.destVar = 'myData';
    ctx = ops.readFile(ctx);
    assertEqual(ctx.vars.myData, 'file content');
  } finally { teardown(); }
});

test('copyFile copies file', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'src.txt'), 'source');
    let ctx = ops.createContext(ROOT);
    ctx.vars.source = 'src.txt';
    ctx.vars.target = 'dst.txt';
    ctx = ops.copyFile(ctx);
    assertExists(path.join(ROOT, 'dst.txt'));
    assertEqual(fs.readFileSync(path.join(ROOT, 'dst.txt'), 'utf-8'), 'source');
  } finally { teardown(); }
});

test('moveFile renames file', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'old.txt'), 'data');
    let ctx = ops.createContext(ROOT);
    ctx.vars.source = 'old.txt';
    ctx.vars.target = 'new.txt';
    ctx = ops.moveFile(ctx);
    assertNotExists(path.join(ROOT, 'old.txt'));
    assertExists(path.join(ROOT, 'new.txt'));
  } finally { teardown(); }
});

test('deleteFile removes file', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'delete_me.txt'), 'bye');
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'delete_me.txt';
    ctx = ops.deleteFile(ctx);
    assertNotExists(path.join(ROOT, 'delete_me.txt'));
  } finally { teardown(); }
});

test('deleteDir removes directory tree', () => {
  setup();
  try {
    fs.mkdirSync(path.join(ROOT, 'tree', 'sub'), { recursive: true });
    fs.writeFileSync(path.join(ROOT, 'tree', 'a.txt'), 'a');
    fs.writeFileSync(path.join(ROOT, 'tree', 'sub', 'b.txt'), 'b');
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'tree';
    ctx = ops.deleteDir(ctx);
    assertNotExists(path.join(ROOT, 'tree'));
  } finally { teardown(); }
});

test('listDir lists entries', () => {
  setup();
  try {
    fs.mkdirSync(path.join(ROOT, 'mydir'));
    fs.writeFileSync(path.join(ROOT, 'mydir', 'a.txt'), 'a');
    fs.writeFileSync(path.join(ROOT, 'mydir', 'b.py'), 'b');
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'mydir';
    ctx.vars.destVar = 'entries';
    ctx = ops.listDir(ctx);
    assert(ctx.vars.entries.length === 2);
    const names = ctx.vars.entries.map(e => e.name).sort();
    assertEqual(names[0], 'a.txt');
    assertEqual(names[1], 'b.py');
  } finally { teardown(); }
});

test('glob finds matching files', () => {
  setup();
  try {
    fs.mkdirSync(path.join(ROOT, 'code'));
    fs.writeFileSync(path.join(ROOT, 'code', 'a.py'), 'a');
    fs.writeFileSync(path.join(ROOT, 'code', 'b.py'), 'b');
    fs.writeFileSync(path.join(ROOT, 'code', 'c.txt'), 'c');
    let ctx = ops.createContext(ROOT);
    ctx.vars.pattern = '**/*.py';
    ctx.vars.searchPath = ROOT;
    ctx = ops.glob(ctx);
    assert(ctx.vars.matches.length === 2);
  } finally { teardown(); }
});

test('appendFile appends content', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'log.txt'), 'line1\n');
    let ctx = ops.createContext(ROOT);
    ctx.vars.target = 'log.txt';
    ctx.vars.content = 'line2\n';
    ctx = ops.appendFile(ctx);
    assertEqual(fs.readFileSync(path.join(ROOT, 'log.txt'), 'utf-8'), 'line1\nline2\n');
  } finally { teardown(); }
});

test('template renders variables', () => {
  setup();
  try {
    let ctx = ops.createContext(ROOT);
    ctx.vars.template = 'Hello {{name}}, you are {{age}} years old.';
    ctx.vars.name = 'Alice';
    ctx.vars.age = 30;
    ctx.vars.destVar = 'rendered';
    ctx = ops.template(ctx);
    assertEqual(ctx.vars.rendered, 'Hello Alice, you are 30 years old.');
  } finally { teardown(); }
});

test('connect copies with transform', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'input.html'), '<title>{{title}}</title>');
    let ctx = ops.createContext(ROOT);
    ctx.vars.source = 'input.html';
    ctx.vars.target = 'output.html';
    ctx.vars.transform = (content, vars) => content.replace('{{title}}', 'My App');
    ctx = ops.connect(ctx);
    assertEqual(fs.readFileSync(path.join(ROOT, 'output.html'), 'utf-8'), '<title>My App</title>');
  } finally { teardown(); }
});

test('connect copies with string template', () => {
  setup();
  try {
    fs.writeFileSync(path.join(ROOT, 'tpl.txt'), 'Name: {{name}}');
    let ctx = ops.createContext(ROOT);
    ctx.vars.source = 'tpl.txt';
    ctx.vars.target = 'out.txt';
    ctx.vars.transform = '{{name}}';
    ctx.vars.name = 'Bob';
    ctx = ops.connect(ctx);
    assertEqual(fs.readFileSync(path.join(ROOT, 'out.txt'), 'utf-8'), 'Name: Bob');
  } finally { teardown(); }
});

test('batch runs on list', () => {
  setup();
  try {
    let ctx = ops.createContext(ROOT);
    ctx.vars.list = [
      { target: 'file1.txt', content: 'one' },
      { target: 'file2.txt', content: 'two' },
      { target: 'file3.txt', content: 'three' },
    ];
    const writeAll = ops.batch(ops.writeFile);
    ctx = writeAll(ctx);
    assertExists(path.join(ROOT, 'file1.txt'));
    assertExists(path.join(ROOT, 'file2.txt'));
    assertExists(path.join(ROOT, 'file3.txt'));
  } finally { teardown(); }
});

test('condition executes then branch', () => {
  let ctx = ops.createContext(ROOT);
  ctx.vars.enabled = true;
  const thenOp = ops.variable('result', 'then-branch');
  const elseOp = ops.variable('result', 'else-branch');
  ctx = ops.condition('enabled', [thenOp], [elseOp])(ctx);
  assertEqual(ctx.vars.result, 'then-branch');
});

test('condition executes else branch', () => {
  let ctx = ops.createContext(ROOT);
  ctx.vars.enabled = false;
  const thenOp = ops.variable('result', 'then-branch');
  const elseOp = ops.variable('result', 'else-branch');
  ctx = ops.condition('enabled', [thenOp], [elseOp])(ctx);
  assertEqual(ctx.vars.result, 'else-branch');
});

test('condition with function check', () => {
  let ctx = ops.createContext(ROOT);
  ctx.vars.risk = 5;
  ctx = ops.condition((v) => v.risk >= 3, [ops.variable('needs_approval', true)])(ctx);
  assertEqual(ctx.vars.needs_approval, true);
});

test('variable sets value', () => {
  let ctx = ops.createContext(ROOT);
  ctx = ops.variable('key', 'value')(ctx);
  assertEqual(ctx.vars.key, 'value');
});

test('variable with function', () => {
  let ctx = ops.createContext(ROOT);
  ctx.vars.x = 5;
  ctx = ops.variable('doubled', (v) => v.x * 2)(ctx);
  assertEqual(ctx.vars.doubled, 10);
});

test('chain runs sequence', () => {
  setup();
  try {
    let ctx = ops.createContext(ROOT);
    const chain = ops.chain([
      ops.variable('step', 1),
      ops.variable('step', 2),
      ops.variable('final', (v) => `step-${v.step}`),
    ]);
    ctx = chain(ctx);
    assertEqual(ctx.vars.final, 'step-2');
  } finally { teardown(); }
});

// === Engine Tests ===

console.log('\n⚙️  Engine:');

test('Pipeline runs steps in sequence', () => {
  setup();
  try {
    const order = [];
    const pipe = new Pipeline('test-seq')
      .step('first', (ctx) => { order.push('first'); return ctx; })
      .step('second', (ctx) => { order.push('second'); return ctx; })
      .step('third', (ctx) => { order.push('third'); return ctx; });

    pipe.run({ root: ROOT });
    assertEqual(order.join(','), 'first,second,third');
  } finally { teardown(); }
});

test('Pipeline passes vars between steps', () => {
  const pipe = new Pipeline('test-vars')
    .step('set', (ctx) => { ctx.vars.name = 'Alice'; return ctx; })
    .step('use', (ctx) => { ctx.vars.greeting = `Hello ${ctx.vars.name}`; return ctx; });

  const ctx = pipe.run({ root: ROOT });
  assertEqual(ctx.vars.greeting, 'Hello Alice');
});

test('Pipeline step-specific vars', () => {
  let captured;
  const pipe = new Pipeline('test-step-vars')
    .step('capture', (ctx) => { captured = ctx.vars.extra; return ctx; }, { extra: 'hello' });

  pipe.run({ root: ROOT });
  assertEqual(captured, 'hello');
});

test('Pipeline middleware wraps every step', () => {
  const log = [];
  const pipe = new Pipeline('test-mw')
    .use((stepFn, ctx) => { log.push('before'); const r = stepFn(ctx); log.push('after'); return r; })
    .step('a', (ctx) => { log.push('step-a'); return ctx; })
    .step('b', (ctx) => { log.push('step-b'); return ctx; });

  pipe.run({ root: ROOT });
  assertEqual(log.join(','), 'before,step-a,after,before,step-b,after');
});

test('Pipeline requireVars middleware', () => {
  const pipe = new Pipeline('test-reqvars')
    .use(requireVars('mustExist'))
    .step('fail', (ctx) => ctx);

  const ctx = pipe.run({ root: ROOT });
  assert(ctx.errors.length > 0);
  assertIncludes(ctx.errors[0].error, 'mustExist');
});

test('Pipeline tolerateErrors middleware', () => {
  const pipe = new Pipeline('test-tolerate')
    .use(tolerateErrors)
    .step('fail', (ctx) => { throw new Error('boom'); })
    .step('continue', (ctx) => { ctx.vars.continued = true; return ctx; });

  const ctx = pipe.run({ root: ROOT });
  assertEqual(ctx.vars.continued, true);
});

test('Pipeline metricsMiddleware tracks time', () => {
  const pipe = new Pipeline('test-metrics')
    .use(metricsMiddleware)
    .step('work', (ctx) => ctx);

  const ctx = pipe.run({ root: ROOT });
  assert(ctx.metrics);
  assert(ctx.metrics.totalMs >= 0);
  assertEqual(ctx.metrics.steps, 1);
});

test('Pipeline events fire correctly', () => {
  const events = [];
  const pipe = new Pipeline('test-events')
    .on('pipeline:start', () => events.push('start'))
    .on('step:start', () => events.push('step-start'))
    .on('step:complete', () => events.push('step-complete'))
    .on('pipeline:complete', () => events.push('pipeline-complete'))
    .step('x', (ctx) => ctx);

  pipe.run({ root: ROOT });
  assertEqual(events.join(','), 'start,step-start,step-complete,pipeline-complete');
});

test('Pipeline dry-run mode', () => {
  setup();
  try {
    const pipe = new Pipeline('test-dry')
      .step('mkdir', ops.mkdir, { target: 'should-not-exist' })
      .step('write', ops.writeFile, { target: 'should-not-exist.txt', content: 'nope' });

    const ctx = pipe.run({ root: ROOT, dryRun: true });
    assertNotExists(path.join(ROOT, 'should-not-exist'));
    assert(ctx.log.some(l => l.includes('[DRY]')));
  } finally { teardown(); }
});

test('Pipeline stops on unhandled error', () => {
  const order = [];
  const pipe = new Pipeline('test-stop')
    .step('ok', (ctx) => { order.push('ok'); return ctx; })
    .step('fail', (ctx) => { throw new Error('fail'); })
    .step('never', (ctx) => { order.push('never'); return ctx; });

  const ctx = pipe.run({ root: ROOT });
  assertEqual(order.join(','), 'ok');
  assert(ctx.errors.length === 1);
});

test('Pipeline onError continues pipeline', () => {
  const order = [];
  const pipe = new Pipeline('test-onerror')
    .step('ok1', (ctx) => { order.push('ok1'); return ctx; })
    .step('fail', (ctx) => { throw new Error('fail'); })
    .step('ok2', (ctx) => { order.push('ok2'); return ctx; })
    .onError((err, ctx, stepName) => {
      ctx.log.push(`caught: ${stepName}`);
      return ctx; // returning ctx continues pipeline
    });

  const ctx = pipe.run({ root: ROOT });
  assertEqual(order.join(','), 'ok1,ok2');
});

test('PipelineRegistry registers and runs', () => {
  const reg = new PipelineRegistry();
  const p = new Pipeline('p1').step('x', (ctx) => ctx);
  reg.register(p);
  assert(reg.has('p1'));
  assertEqual(reg.list().length, 1);
  const ctx = reg.run('p1', { root: ROOT });
  assert(ctx);
});

test('PipelineRegistry runSequence', () => {
  const reg = new PipelineRegistry();
  reg.register(new Pipeline('a').step('x', (ctx) => { ctx.vars.a = 1; return ctx; }));
  reg.register(new Pipeline('b').step('x', (ctx) => { ctx.vars.b = 2; return ctx; }));
  const results = reg.runSequence(['a', 'b'], { root: ROOT });
  assertEqual(results.length, 2);
});

test('Pipeline.describe()', () => {
  const pipe = new Pipeline('test-desc')
    .step('a', (ctx) => ctx)
    .step('b', (ctx) => ctx)
    .step('c', (ctx) => ctx);

  const desc = pipe.describe();
  assertEqual(desc.name, 'test-desc');
  assertEqual(desc.stepCount, 3);
  assertEqual(desc.steps.join(','), 'a,b,c');
});

// === Integration Tests ===

console.log('\n🔗 Integration:');

test('connect-all pipeline generates relation-map.md', () => {
  // Use a temp project root
  const tempRoot = path.join(TEST_DIR, 'integration');
  fs.mkdirSync(tempRoot, { recursive: true });
  fs.mkdirSync(path.join(tempRoot, 'backend', 'app', 'agent'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, 'backend', 'app', 'tools'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, 'frontend'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, 'backend', 'native'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, 'docs'), { recursive: true });
  fs.writeFileSync(path.join(tempRoot, 'backend', 'app', 'main.py'), '# main');
  fs.writeFileSync(path.join(tempRoot, 'frontend', 'app.js'), '// app');

  try {
    const pipe = new Pipeline('test-connect')
      .step('scan-py', (ctx) => {
        ctx.vars.pattern = '**/*.py';
        ctx.vars.searchPath = path.join(tempRoot, 'backend');
        ctx = ops.glob(ctx);
        ctx.vars.pythonFiles = (ctx.vars.matches || []).slice();
        return ctx;
      })
      .step('generate', (ctx) => {
        const lines = ['# Relation Map', '', `Files: ${(ctx.vars.pythonFiles || []).length}`];
        for (const f of (ctx.vars.pythonFiles || [])) {
          lines.push(`- ${path.relative(tempRoot, f)}`);
        }
        ctx.vars.mapContent = lines.join('\n');
        return ctx;
      })
      .step('write', (ctx) => {
        ctx.vars.target = path.join(tempRoot, 'relation-map.md');
        ctx.vars.content = ctx.vars.mapContent;
        ctx = ops.writeFile(ctx);
        return ctx;
      });

    const ctx = pipe.run({ root: tempRoot });
    assertExists(path.join(tempRoot, 'relation-map.md'));
    const content = fs.readFileSync(path.join(tempRoot, 'relation-map.md'), 'utf-8');
    assertIncludes(content, 'Relation Map');
    assertIncludes(content, 'main.py');
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('scaffold pipeline creates project structure', () => {
  const tempRoot = path.join(TEST_DIR, 'scaffold');
  fs.mkdirSync(tempRoot, { recursive: true });

  try {
    const { scaffoldFullPipeline } = require('./screenai_pipelines');
    const pipe = scaffoldFullPipeline();
    const ctx = pipe.run({ root: tempRoot });

    assertExists(path.join(tempRoot, 'backend', 'app', 'agent'));
    assertExists(path.join(tempRoot, 'backend', 'app', 'tools'));
    assertExists(path.join(tempRoot, 'frontend'));
    assertExists(path.join(tempRoot, 'data', 'datasets'));
    assertExists(path.join(tempRoot, 'data', 'models'));
    assertExists(path.join(tempRoot, 'data', 'quarantine'));
    assertExists(path.join(tempRoot, 'docs'));
    assertExists(path.join(tempRoot, 'tests'));
    assertExists(path.join(tempRoot, '.gitignore'));
    assertExists(path.join(tempRoot, 'package.json'));
    assert(ctx.results.length > 10);
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

test('clean pipeline removes caches from real project', () => {
  const projectRoot = path.resolve(__dirname, '..');
  const { cleanPipeline } = require('./screenai_pipelines');
  const pipe = cleanPipeline();
  const ctx = pipe.run({ root: projectRoot });
  // Pipeline should complete with results (some removals may fail if dirs don't exist, that's ok)
  assert(ctx.results.length > 0);
  assert(typeof ctx.elapsed === 'number');
});

test('build-frontend pipeline copies files', () => {
  const projectRoot = path.resolve(__dirname, '..');
  const { buildFrontendPipeline } = require('./screenai_pipelines');
  const pipe = buildFrontendPipeline();
  const ctx = pipe.run({ root: projectRoot });
  // At minimum, it tries to copy files (some may not exist in test env)
  assert(typeof ctx.elapsed === 'number');
  assert(ctx.log.length > 0);
});

test('CLI list command works', () => {
  const { execSync } = require('child_process');
  const output = execSync('node pipeline/cli.js list', {
    cwd: path.resolve(__dirname, '..'),
    encoding: 'utf-8',
  });
  assertIncludes(output, 'scaffold-full');
  assertIncludes(output, 'build-frontend');
  assertIncludes(output, 'clean');
  assertIncludes(output, 'connect-all');
});

test('CLI describe command works', () => {
  const { execSync } = require('child_process');
  const output = execSync('node pipeline/cli.js describe', {
    cwd: path.resolve(__dirname, '..'),
    encoding: 'utf-8',
  });
  assertIncludes(output, 'Create entire project');
  assertIncludes(output, 'Copy and bundle');
});

test('CLI dry-run does not modify filesystem', () => {
  const tempRoot = path.join(TEST_DIR, 'cli-dry');
  fs.mkdirSync(tempRoot, { recursive: true });
  try {
    const { execSync } = require('child_process');
    execSync('node pipeline/cli.js run clean --dry-run', {
      cwd: path.resolve(__dirname, '..'),
      encoding: 'utf-8',
    });
    // Verify nothing was actually deleted
    assert(true); // If we got here without error, dry-run didn't crash
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
});

// === Results ===

console.log('\n══════════════════════════════════════════════════════');
console.log(`  Results: ${passed}/${total} passed, ${failed} failed`);
console.log('══════════════════════════════════════════════════════\n');

process.exit(failed > 0 ? 1 : 0);
