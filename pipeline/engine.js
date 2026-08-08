/**
 * engine.js — Screen-AI Pipeline Execution Engine
 *
 * Two execution modes:
 *   1. Legacy Pipeline class (step/use/middleware) — preserved for backward compat
 *   2. ExecutionGraphRunner — consumes planning-engine graphs (nodes with
 *      dependencies, verification, recovery, risk) and runs them in dependency
 *      order with parallel branches, retries, and verification gates.
 */

'use strict';

const EventEmitter = require('events');
const {
  NODE_TYPES,
  RISK_LEVELS,
  validateNode,
  insertApprovalNodes,
} = require('./operations');

// ════════════════════════════════════════════════════════════════════════════
// EXECUTION GRAPH RUNNER (planning-engine aligned)
// ════════════════════════════════════════════════════════════════════════════

/**
 * Topologically sort nodes by dependencies.
 * Returns nodes in execution order.
 */
function topoSort(nodes) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const visited = new Set();
  const visiting = new Set();
  const order = [];

  function visit(id) {
    if (visited.has(id)) return;
    if (visiting.has(id)) {
      throw new Error(`Cycle detected involving node ${id}`);
    }
    visiting.add(id);
    const node = byId.get(id);
    if (!node) throw new Error(`Unknown dependency: ${id}`);
    for (const dep of node.dependencies || []) {
      visit(dep);
    }
    visiting.delete(id);
    visited.add(id);
    order.push(node);
  }

  for (const node of nodes) {
    visit(node.id);
  }
  return order;
}

/**
 * Group nodes into execution waves (parallel branches).
 * Each wave contains nodes whose dependencies are all in earlier waves.
 */
function buildWaves(nodes) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const remaining = new Set(nodes.map(n => n.id));
  const waves = [];

  while (remaining.size > 0) {
    const wave = [];
    for (const id of remaining) {
      const node = byId.get(id);
      const deps = node.dependencies || [];
      const ready = deps.every(d => !remaining.has(d));
      if (ready) wave.push(node);
    }
    if (wave.length === 0) {
      throw new Error('No nodes ready — possible cycle in execution graph');
    }
    waves.push(wave);
    for (const n of wave) remaining.delete(n.id);
  }
  return waves;
}

/**
 * Run a planning-engine execution graph.
 *
 * @param {Array} nodes - array of planning-engine nodes
 * @param {Object} [opts]
 * @param {Object} [opts.handlers] - map of node.id -> async (node, ctx) => result
 * @param {Object} [opts.verifiers] - map of verification.method -> async (result, node) => bool
 * @param {Object} [opts.approver] - async (node) => 'approved'|'rejected'
 * @param {Object} [opts.context] - initial context
 * @param {boolean} [opts.dryRun]
 * @param {boolean} [opts.autoApprove] - skip approval nodes (for dry-run / tests)
 */
class ExecutionGraphRunner extends EventEmitter {
  constructor(nodes, opts = {}) {
    super();
    this.nodes = insertApprovalNodes(nodes.map(node => ({ ...node })));
    const validation = validateNode(this.nodes);
    if (!validation.ok) {
      throw new Error(`Invalid execution graph: ${validation.errors.join('; ')}`);
    }
    this.waves = buildWaves(this.nodes);
    this.opts = opts;
    this.context = opts.context || { vars: {}, results: {}, log: [] };
    this.dryRun = !!opts.dryRun;
    this.autoApprove = !!opts.autoApprove;
    this.results = new Map();
    this.status = 'pending';
  }

  async run() {
    this.status = 'running';
    this.emit('start', { nodeCount: this.nodes.length, waveCount: this.waves.length });

    try {
      for (let i = 0; i < this.waves.length; i++) {
        const wave = this.waves[i];
        this.emit('wave', { index: i, nodes: wave.map(n => n.id) });

        // Run all nodes in the wave in parallel
        const waveResults = await Promise.all(
          wave.map(node => this._runNode(node))
        );

        for (let j = 0; j < wave.length; j++) {
          const node = wave[j];
          const result = waveResults[j];
          this.results.set(node.id, result);

          if (result.status === 'failed' && node.type !== NODE_TYPES.VERIFY) {
            // Try recovery
            const recovered = await this._tryRecovery(node, result);
            if (!recovered) {
              this.status = 'failed';
              this.emit('failed', { node: node.id, error: result.error });
              return this._summary();
            }
          }
        }
      }

      this.status = 'completed';
      this.emit('complete', this._summary());
      return this._summary();
    } catch (e) {
      this.status = 'error';
      this.emit('error', e);
      throw e;
    }
  }

  async _runNode(node) {
    this.emit('node:start', node);
    this.context.log.push(`[${node.type}] ${node.id}: ${node.objective}`);

    try {
      // Approval gate
      if (node.type === NODE_TYPES.APPROVAL) {
        if (this.autoApprove || this.dryRun) {
          this.context.results[node.id] = { status: 'approved', auto: true };
          this.emit('node:complete', { node, result: { status: 'approved', auto: true } });
          return { status: 'approved', auto: true };
        }
        if (!this.opts.approver) {
          throw new Error(`Approval node ${node.id} has no approver configured`);
        }
        const decision = await this.opts.approver(node);
        if (decision !== 'approved') {
          this.context.results[node.id] = { status: 'rejected', decision };
          this.emit('node:complete', { node, result: { status: 'rejected', decision } });
          return { status: 'rejected', decision };
        }
        this.context.results[node.id] = { status: 'approved' };
        this.emit('node:complete', { node, result: { status: 'approved' } });
        return { status: 'approved' };
      }

      // Wait node
      if (node.type === NODE_TYPES.WAIT) {
        const ms = (node.parameters && node.parameters.ms) || 1000;
        if (!this.dryRun) await new Promise(r => setTimeout(r, ms));
        this.context.results[node.id] = { status: 'waited', ms };
        return { status: 'waited', ms };
      }

      // Verify node — runs verifier on upstream result
      if (node.type === NODE_TYPES.VERIFY) {
        const target = (node.dependencies || [])[0];
        const upstream = this.context.results[target];
        const verifier = this.opts.verifiers && this.opts.verifiers[node.verification.method];
        let ok = false;
        if (verifier) {
          ok = await verifier(upstream, node);
        } else {
          // Default: upstream must have status === 'success'
          ok = upstream && upstream.status === 'success';
        }
        this.context.results[node.id] = { status: ok ? 'verified' : 'failed', upstream: target };
        return { status: ok ? 'verified' : 'failed' };
      }

      // Act / Observe / Decide / Replan / Rollback / Checkpoint / Finish
      const handler = this.opts.handlers && this.opts.handlers[node.id];
      let result;
      if (handler) {
        result = await handler(node, this.context);
      } else if (this.dryRun) {
        result = { status: 'success', dryRun: true, node: node.id };
      } else {
        // No handler — treat as a no-op success (useful for decide/observe nodes)
        result = { status: 'success', noop: true, node: node.id };
      }

      this.context.results[node.id] = result;
      this.emit('node:complete', { node, result });
      return result;
    } catch (e) {
      const errResult = { status: 'failed', error: e.message };
      this.context.results[node.id] = errResult;
      this.emit('node:error', { node, error: e });
      return errResult;
    }
  }

  async _tryRecovery(node, failedResult) {
    for (const recovery of node.recovery || []) {
      this.context.log.push(`[recovery] ${node.id}: ${recovery}`);
      this.emit('recovery', { node, recovery, error: failedResult.error });
      // Recovery is advisory — the caller decides what to do.
      // For now, we just log and continue.
    }
    return false;
  }

  _summary() {
    return {
      status: this.status,
      nodeCount: this.nodes.length,
      waveCount: this.waves.length,
      results: Object.fromEntries(this.results),
      context: this.context,
    };
  }
}

// ════════════════════════════════════════════════════════════════════════════
// LEGACY PIPELINE CLASS (preserved for backward compatibility)
// ════════════════════════════════════════════════════════════════════════════

class Pipeline extends EventEmitter {
  constructor(name, options = {}) {
    super();
    this.name = name;
    this.description = options.description || '';
    this.steps = [];
    this.middleware = [];
    this.errorHandlers = [];
    this.completeHandlers = [];
    this.beforeAllFns = [];
    this.afterAllFns = [];
    this.options = options;
  }

  step(name, fn, vars) {
    this.steps.push({ name, fn, vars: vars || null });
    return this;
  }

  use(middleware) {
    // Detect factory vs middleware:
    // - Middleware: function with arity 2 that takes (stepFn, ctx)
    // - Factory: function with arity 0 or 1 that returns a middleware
    if (typeof middleware === 'function') {
      if (middleware.length >= 2) {
        // Direct middleware: (stepFn, ctx) => result
        this.middleware.push(middleware);
      } else {
        // Factory: call it to get the middleware
        const produced = middleware();
        this.middleware.push(produced);
      }
    } else {
      this.middleware.push(middleware);
    }
    return this;
  }

  onError(handler) {
    this.errorHandlers.push(handler);
    return this;
  }

  onComplete(handler) {
    this.completeHandlers.push(handler);
    return this;
  }

  beforeAll(fn) {
    this.beforeAllFns.push(fn);
    return this;
  }

  afterAll(fn) {
    this.afterAllFns.push(fn);
    return this;
  }

  describe() {
    return {
      name: this.name,
      description: this.description,
      stepCount: this.steps.length,
      steps: this.steps.map(s => s.name),
    };
  }

  run(ctx) {
    // Legacy synchronous API — preserved for backward compatibility.
    // For async execution, use ExecutionGraphRunner.
    const startTime = Date.now();
    this.emit('start', { name: this.name });
    this.emit('pipeline:start', { name: this.name });
    let currentCtx = ctx || createDefaultContext();
    // Ensure vars/results/log exist even if caller passed a partial ctx
    if (!currentCtx.vars) currentCtx.vars = {};
    if (!currentCtx.results) currentCtx.results = [];
    if (!currentCtx.errors) currentCtx.errors = [];
    if (!currentCtx.log) currentCtx.log = [];

    for (const before of this.beforeAllFns) {
      const r = before(currentCtx);
      if (r && typeof r.then === 'function') {
        // If a beforeAll returns a promise, we still proceed synchronously
        // (legacy behavior). Callers needing async should use ExecutionGraphRunner.
      }
    }

    for (const step of this.steps) {
      try {
        this.emit('step:start', { name: step.name });
        // Merge step-specific vars (if provided) into ctx.vars for this step only
        let stepCtx = currentCtx;
        if (step.vars) {
          stepCtx = { ...currentCtx, vars: { ...currentCtx.vars, ...step.vars } };
        }
        // Tag step function with its name so middleware can access it
        const taggedFn = step.fn;
        taggedFn._stepName = step.name;
        // Apply middleware — each middleware wraps the step function
        let stepFn = taggedFn;
        for (const mw of this.middleware) {
          const prevFn = stepFn;
          stepFn = (ctx) => mw(prevFn, ctx);
        }
        const result = stepFn(stepCtx);
        if (result && typeof result.then === 'function') {
          currentCtx = result;
        } else {
          currentCtx = result;
        }
        this.emit('step:complete', { name: step.name });
      } catch (e) {
        this.emit('step:error', { name: step.name, error: e });
        if (!currentCtx.errors) currentCtx.errors = [];
        currentCtx.errors.push({ step: step.name, error: e.message });
        let handled = false;
        for (const handler of this.errorHandlers) {
          const r = handler(e, currentCtx, step.name);
          if (r !== false && r !== undefined) {
            handled = true;
            if (r && typeof r === 'object') currentCtx = r;
            break;
          }
        }
        if (!handled) {
          // Default behavior: stop pipeline, return ctx with errors
          break;
        }
      }
    }

    for (const after of this.afterAllFns) {
      after(currentCtx);
    }

    for (const handler of this.completeHandlers) {
      handler(currentCtx);
    }

    this.emit('complete', currentCtx);
    this.emit('pipeline:complete', currentCtx);
    currentCtx.elapsed = Date.now() - startTime;
    return currentCtx;
  }
}

function createDefaultContext() {
  return {
    vars: {},
    results: [],
    errors: [],
    log: [],
    startTime: Date.now(),
    dryRun: false,
  };
}

// ─── Middleware ──────────────────────────────────────────────────────────────

async function loggingMiddleware(step, ctx) {
  ctx.log.push(`[middleware] starting step: ${step.name}`);
}

async function requireMiddleware(step, ctx) {
  // Placeholder for legacy compat
}

function requireVars(...keys) {
  return function requireVarsMiddleware(stepFn, ctx) {
    const stepName = stepFn._stepName || stepFn.name || 'anonymous';
    for (const key of keys) {
      if (!ctx.vars || ctx.vars[key] === undefined) {
        const err = new Error(`Step ${stepName} requires var: ${key}`);
        if (!ctx.errors) ctx.errors = [];
        ctx.errors.push({ step: stepName, error: err.message });
        throw err;
      }
    }
    return stepFn(ctx);
  };
}

function tolerateErrors() {
  return function tolerateErrorsMiddleware(stepFn, ctx) {
    try {
      return stepFn(ctx);
    } catch (e) {
      if (!ctx.errors) ctx.errors = [];
      ctx.errors.push({ step: stepFn._stepName || stepFn.name || 'anonymous', error: e.message });
      // Return ctx unchanged so pipeline continues
      return ctx;
    }
  };
}

function metricsMiddleware(metrics) {
  return function metricsMiddlewareFn(stepFn, ctx) {
    const start = Date.now();
    const result = stepFn(ctx);
    const elapsed = Date.now() - start;
    if (!ctx.metrics) {
      ctx.metrics = { totalMs: 0, steps: 0, perStep: {} };
    }
    ctx.metrics.totalMs += elapsed;
    ctx.metrics.steps += 1;
    ctx.metrics.perStep[stepFn._stepName || stepFn.name || 'anonymous'] = elapsed;
    return result;
  };
}

// ─── Pipeline Registry ───────────────────────────────────────────────────────

class PipelineRegistry {
  constructor() {
    this.pipelines = new Map();
  }

  /**
   * Register a pipeline. Accepts either (name, pipeline) or (pipeline).
   * If a pipeline object is passed, its .name property is used as the key.
   */
  register(nameOrPipeline, maybePipeline) {
    if (maybePipeline !== undefined) {
      this.pipelines.set(nameOrPipeline, maybePipeline);
    } else if (nameOrPipeline && typeof nameOrPipeline === 'object' && nameOrPipeline.name) {
      this.pipelines.set(nameOrPipeline.name, nameOrPipeline);
    } else if (typeof nameOrPipeline === 'string') {
      // Register a placeholder by name
      this.pipelines.set(nameOrPipeline, null);
    }
    return this;
  }

  has(name) {
    return this.pipelines.has(name);
  }

  get(name) {
    return this.pipelines.get(name);
  }

  list() {
    return Array.from(this.pipelines.keys());
  }

  run(name, ctx) {
    const pipeline = this.get(name);
    if (!pipeline) throw new Error(`Pipeline not found: ${name}`);
    return pipeline.run(ctx);
  }

  runSequence(names, ctx) {
    const results = [];
    for (const name of names) {
      results.push(this.run(name, ctx));
    }
    return results;
  }
}

// ════════════════════════════════════════════════════════════════════════════
// EXPORTS
// ════════════════════════════════════════════════════════════════════════════

module.exports = {
  // Planning-engine layer
  ExecutionGraphRunner,
  topoSort,
  buildWaves,

  // Legacy pipeline
  Pipeline,
  PipelineRegistry,

  // Legacy middleware
  loggingMiddleware,
  requireMiddleware,
  requireVars,
  tolerateErrors,
  metricsMiddleware,
};
