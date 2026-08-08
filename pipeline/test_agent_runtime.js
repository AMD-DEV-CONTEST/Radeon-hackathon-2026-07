const assert = require('assert');
const pipelines = require('./screenai_pipelines.js');

function check(name, fn) {
  try {
    fn();
    console.log(`  OK ${name}`);
  } catch (error) {
    console.error(`  FAIL ${name}`);
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
  }
}

console.log('\nScreen-AI Agent Runtime Regression\n');

check('exports runtime classes and global instance', () => {
  assert.strictEqual(typeof pipelines.IntentEngine, 'function');
  assert.strictEqual(typeof pipelines.AgentRuntime, 'function');
  assert.strictEqual(typeof pipelines.globalAgentRuntime, 'object');
});

check('IntentEngine accepts both string and request object input', () => {
  const engine = new pipelines.IntentEngine();
  assert.strictEqual(engine.classify('open chrome').name, 'browser_open');
  assert.strictEqual(engine.classify({ text: 'open chrome' }).name, 'browser_open');
});

check('safe browser request completes without approval node', () => {
  const runtime = new pipelines.AgentRuntime();
  const result = runtime.processRequest({ text: 'open chrome' });
  assert.strictEqual(result.status, 'completed');
  assert.strictEqual(result.intent.name, 'browser_open');
  assert.strictEqual(result.intent.risk, 1);
  assert.strictEqual(
    result.graph.nodes.some((node) => String(node.type).toLowerCase() === 'approval'),
    false
  );
});

check('high risk file delete request inserts approval node', () => {
  const runtime = new pipelines.AgentRuntime();
  const result = runtime.processRequest({ text: 'delete file C:/tmp/demo.txt' });
  assert.strictEqual(result.status, 'completed');
  assert.strictEqual(result.intent.name, 'file_delete');
  assert.ok(result.intent.risk >= 3);
  assert.strictEqual(
    result.graph.nodes.some((node) => String(node.type).toLowerCase() === 'approval'),
    true
  );
});

check('critical command request inserts approval node', () => {
  const runtime = new pipelines.AgentRuntime();
  const result = runtime.processRequest({ text: 'run command whoami' });
  assert.strictEqual(result.status, 'completed');
  assert.strictEqual(result.intent.name, 'system_run');
  assert.strictEqual(result.intent.risk, 4);
  assert.strictEqual(
    result.graph.nodes.some((node) => String(node.type).toLowerCase() === 'approval'),
    true
  );
});

check('runtime records memory and execution history', () => {
  const runtime = new pipelines.AgentRuntime();
  const result = runtime.processRequest({ text: 'check system status' });
  assert.strictEqual(result.status, 'completed');
  assert.ok(Array.isArray(runtime.executionRuntime.history()));
  assert.ok(runtime.executionRuntime.history().length > 0);
  assert.ok(result.memory);
});

if (process.exitCode) {
  console.error('\nAgent Runtime regression failed.');
  process.exit(process.exitCode);
}

console.log('\nAgent Runtime regression passed.\n');
