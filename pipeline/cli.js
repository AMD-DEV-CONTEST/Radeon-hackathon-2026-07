#!/usr/bin/env node
/**
 * cli.js — Screen-AI Pipeline CLI
 *
 * Commands:
 *   list                       List all available pipelines
 *   describe <name>            Show pipeline steps
 *   run <name>                 Run a named pipeline
 *   run-all                    Run every pipeline
 *   graph <file.json>          Run a planning-engine execution graph from JSON
 *   validate <file.json>       Validate a planning-engine graph without running
 *   agent <text...>            Plan text through AgentRuntime and run the graph
 *
 * Flags:
 *   --dry-run                  Don't actually execute side effects
 *   --name <name>              Override pipeline name
 *   --source <path>            Source path
 *   --target <path>            Target path
 *   --ext <ext>                File extension filter
 *   --auto-approve             Skip approval nodes (for tests)
 *   --vars <json>              JSON string of extra vars
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { ExecutionGraphRunner, PipelineRegistry } = require('./engine');
const { validateNode, insertApprovalNodes, NODE_TYPES } = require('./operations');
const pipelines = require('./screenai_pipelines');

const registry = new PipelineRegistry();

// Pre-build all legacy pipelines from factory functions
const FACTORY_MAP = {
  'scaffold-full': pipelines.scaffoldFullPipeline,
  'build-frontend': pipelines.buildFrontendPipeline,
  'build-native': pipelines.buildNativePipeline,
  'clean': pipelines.cleanPipeline,
  'init-new-module': pipelines.initNewModulePipeline,
  'generate-docs': pipelines.generateDocsPipeline,
  'backup-database': pipelines.backupDatabasePipeline,
  'connect-all': pipelines.connectAllPipeline,
  'deploy-package': pipelines.deployPackagePipeline,
  'batch-convert': pipelines.batchConvertPipeline,
};

for (const [name, factory] of Object.entries(FACTORY_MAP)) {
  if (typeof factory === 'function') {
    try {
      registry.register(name, factory());
    } catch (e) {
      // Skip pipelines that fail to construct (e.g., missing args)
    }
  }
}

// Register graph pipelines (they expose .nodes instead of .run)
const GRAPH_MAP = {
  'scaffold-full-graph': pipelines.scaffoldFullGraph,
  'backup-database-graph': pipelines.backupDatabaseGraph,
  'clean-graph': pipelines.cleanGraph,
  'research-collect-graph': pipelines.researchCollectGraph,
};

for (const [name, factory] of Object.entries(GRAPH_MAP)) {
  if (typeof factory === 'function') {
    try {
      const graph = factory();
      // Wrap graph as a pseudo-pipeline for CLI listing
      registry.register(name, {
        name: graph.name || name,
        run: async (ctx) => {
          const runner = new ExecutionGraphRunner(graph.nodes, {
            dryRun: !!ctx.dryRun,
            autoApprove: true,
            context: ctx,
          });
          return runner.run();
        },
        describe: () => ({
          name: graph.name || name,
          stepCount: graph.nodes.length,
          steps: graph.nodes.map(n => `[${n.type}] ${n.id}`),
        }),
      });
    } catch (e) {
      // Skip
    }
  }
}

function parseArgs(argv) {
  const args = { _: [], flags: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith('--')) {
        args.flags[key] = next;
        i++;
      } else {
        args.flags[key] = true;
      }
    } else {
      args._.push(a);
    }
  }
  return args;
}

function listPipelines() {
  const names = registry.list();
  console.log(`\nAvailable pipelines (${names.length}):\n`);
  for (const name of names) {
    const p = registry.get(name);
    const stepCount = p.steps ? p.steps.length : 'graph';
    console.log(`  - ${name}  (${stepCount} steps)`);
  }
  console.log('');
}

function describePipeline(name) {
  if (!name) {
    // Describe all pipelines
    console.log(`\nAll pipelines:\n`);
    for (const n of registry.list()) {
      const p = registry.get(n);
      console.log(`\nPipeline: ${n}`);
      if (p && typeof p.describe === 'function') {
        const desc = p.describe();
        if (desc.description) console.log(`  ${desc.description}`);
        console.log(`  Steps: ${desc.stepCount}`);
        for (const s of desc.steps) console.log(`    - ${s}`);
      } else if (p && p.steps) {
        for (let i = 0; i < p.steps.length; i++) {
          console.log(`  ${i + 1}. ${p.steps[i].name}`);
        }
      }
    }
    console.log('');
    return;
  }
  const p = registry.get(name);
  if (!p) {
    console.error(`Pipeline not found: ${name}`);
    process.exit(1);
  }
  console.log(`\nPipeline: ${name}\n`);
  if (p && typeof p.describe === 'function') {
    const desc = p.describe();
    if (desc.description) console.log(`  ${desc.description}`);
    console.log(`  Steps: ${desc.stepCount}`);
    for (const s of desc.steps) console.log(`    - ${s}`);
  } else if (p.steps) {
    for (let i = 0; i < p.steps.length; i++) {
      console.log(`  ${i + 1}. ${p.steps[i].name}`);
    }
  } else if (p.nodes) {
    for (const node of p.nodes) {
      console.log(`  - [${node.type}] ${node.id}: ${node.objective}`);
    }
  }
  console.log('');
}

async function runPipeline(name, opts) {
  const p = registry.get(name);
  if (!p) {
    console.error(`Pipeline not found: ${name}`);
    process.exit(1);
  }
  console.log(`Running pipeline: ${name} (dryRun=${!!opts.dryRun})`);
  const ctx = {
    root: opts.root || process.cwd(),
    vars: { ...opts.vars, dryRun: !!opts.dryRun },
    results: [],
    errors: [],
    log: [],
    startTime: Date.now(),
    dryRun: !!opts.dryRun,
  };
  const result = await p.run(ctx);
  console.log(`\nPipeline ${name} completed.`);
  console.log(`  Steps: ${result.results ? result.results.length : 'n/a'}`);
  console.log(`  Errors: ${result.errors ? result.errors.length : 0}`);
  console.log(`  Duration: ${Date.now() - ctx.startTime}ms`);
  return result;
}

async function runAllPipelines(opts) {
  for (const name of registry.list()) {
    try {
      await runPipeline(name, opts);
    } catch (e) {
      console.error(`Pipeline ${name} failed: ${e.message}`);
    }
  }
}

async function runGraphFile(filePath, opts) {
  const abs = path.resolve(filePath);
  if (!fs.existsSync(abs)) {
    console.error(`Graph file not found: ${abs}`);
    process.exit(1);
  }
  const raw = fs.readFileSync(abs, 'utf-8');
  let nodes;
  try {
    nodes = JSON.parse(raw);
  } catch (e) {
    console.error(`Invalid JSON in ${abs}: ${e.message}`);
    process.exit(1);
  }
  if (!Array.isArray(nodes)) {
    console.error(`Graph file must contain an array of nodes`);
    process.exit(1);
  }

  const executableNodes = insertApprovalNodes(nodes.map(node => ({ ...node })));
  const validation = validateNode(executableNodes);
  if (!validation.ok) {
    console.error(`Graph validation failed:`);
    for (const err of validation.errors) console.error(`  - ${err}`);
    process.exit(1);
  }

  console.log(`Running execution graph: ${abs} (${nodes.length} nodes, ${executableNodes.length} executable nodes)`);
  const runner = new ExecutionGraphRunner(nodes, {
    dryRun: !!opts.dryRun,
    autoApprove: !!opts.autoApprove,
    context: {
      vars: { ...opts.vars, dryRun: !!opts.dryRun },
      results: {},
      log: [],
    },
  });
  const summary = await runner.run();
  console.log(`\nExecution graph completed.`);
  console.log(`  Status: ${summary.status}`);
  console.log(`  Nodes: ${summary.nodeCount}`);
  console.log(`  Waves: ${summary.waveCount}`);
  return summary;
}

async function runAgentText(text, opts) {
  if (!text || !text.trim()) {
    console.error('Agent command text is required');
    process.exit(1);
  }
  const runtime = new pipelines.AgentRuntime();
  const result = runtime.processRequest({ text });
  console.log(`Agent runtime completed.`);
  console.log(`  Intent: ${result.intent ? result.intent.name : 'unknown'}`);
  console.log(`  Risk: ${result.intent ? result.intent.risk : 'n/a'}`);
  console.log(`  Status: ${result.status}`);
  console.log(`  Runtime graph nodes: ${result.graph && result.graph.nodes ? result.graph.nodes.length : 0}`);

  const nodes = ((result.graph && result.graph.nodes) || []).map((node, index) => ({
    id: node.id || `agent_${index}`,
    type: node.type || NODE_TYPES.ACT,
    objective: node.tool ? `Execute ${node.tool}` : `${node.type || 'agent'} stage`,
    preferred_skill: node.tool || null,
    dependencies: index === 0 ? [] : [result.graph.nodes[index - 1].id],
    parameters: node.args || {},
    expected_result: 'Agent stage completed',
    verification: { method: 'status_success', success: 'status is success/completed/approved' },
    recovery: ['Retry stage once', 'Replan from current observation', 'Report failure'],
    risk: typeof node.risk === 'number' ? node.risk : 0,
    confidence: 0.85,
  }));

  if (nodes.length === 0) {
    console.log('No execution graph nodes were produced.');
    return result;
  }

  const runner = new ExecutionGraphRunner(nodes, {
    dryRun: opts.dryRun !== false,
    autoApprove: !!opts.autoApprove || !!opts.dryRun,
    context: {
      vars: { ...opts.vars, agentText: text, dryRun: opts.dryRun !== false },
      results: {},
      log: [],
    },
    verifiers: {
      status_success: async (upstream) => {
        return !!upstream && ['success', 'completed', 'approved', 'verified'].includes(upstream.status);
      },
    },
  });
  const summary = await runner.run();
  console.log(`  Execution graph status: ${summary.status}`);
  console.log(`  Execution graph waves: ${summary.waveCount}`);
  return { result, summary };
}

function validateGraphFile(filePath) {
  const abs = path.resolve(filePath);
  if (!fs.existsSync(abs)) {
    console.error(`Graph file not found: ${abs}`);
    process.exit(1);
  }
  const raw = fs.readFileSync(abs, 'utf-8');
  let nodes;
  try {
    nodes = JSON.parse(raw);
  } catch (e) {
    console.error(`Invalid JSON in ${abs}: ${e.message}`);
    process.exit(1);
  }
  const withApproval = insertApprovalNodes(nodes.map(node => ({ ...node })));
  const validation = validateNode(withApproval);
  if (validation.ok) {
    console.log(`✓ Graph ${abs} is valid (${nodes.length} nodes)`);
    console.log(`  After auto-approval insertion: ${withApproval.length} nodes`);
    process.exit(0);
  } else {
    console.error(`✗ Graph ${abs} has ${validation.errors.length} error(s):`);
    for (const err of validation.errors) console.error(`  - ${err}`);
    process.exit(1);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  const opts = {
    dryRun: !!args.flags['dry-run'],
    autoApprove: !!args.flags['auto-approve'],
    root: args.flags.root || process.cwd(),
    vars: {},
  };
  if (args.flags.vars) {
    try {
      opts.vars = JSON.parse(args.flags.vars);
    } catch (e) {
      console.error(`Invalid --vars JSON: ${e.message}`);
      process.exit(1);
    }
  }

  switch (cmd) {
    case 'list':
      listPipelines();
      break;
    case 'describe':
      describePipeline(args._[1]);
      break;
    case 'run':
      await runPipeline(args._[1], opts);
      break;
    case 'run-all':
      await runAllPipelines(opts);
      break;
    case 'graph':
      await runGraphFile(args._[1], opts);
      break;
    case 'agent':
      await runAgentText(args._.slice(1).join(' '), opts);
      break;
    case 'validate':
      validateGraphFile(args._[1]);
      break;
    default:
      console.log(`Screen-AI Pipeline CLI

Usage:
  pipeline list
  pipeline describe <name>
  pipeline run <name> [--dry-run] [--vars <json>]
  pipeline run-all [--dry-run]
  pipeline graph <file.json> [--dry-run] [--auto-approve]
  pipeline agent <text...> [--dry-run] [--auto-approve]
  pipeline validate <file.json>

Flags:
  --dry-run        Don't execute side effects
  --auto-approve   Skip approval nodes (for tests)
  --vars <json>    Extra variables as JSON
`);
  }
}

if (require.main === module) {
  main().catch(e => {
    console.error(e);
    process.exit(1);
  });
}

module.exports = {
  listPipelines,
  describePipeline,
  runPipeline,
  runAllPipelines,
  runGraphFile,
  runAgentText,
  validateGraphFile,
  main,
};
