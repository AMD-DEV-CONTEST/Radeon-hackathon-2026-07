/**
 * core/executor.js — Pipeline Executor
 *
 * The Executor is the orchestrator that ties together:
 *   - PipelineRegistry (lookup)
 *   - PipelineContext (state)
 *   - DependencyResolver (ordering)
 *   - RetryManager (failure recovery)
 *   - RollbackManager (undo)
 *   - EventBus (notifications)
 *   - Logger (observability)
 *
 * It runs a pipeline by:
 *   1. Looking up the pipeline definition in the registry
 *   2. Creating a fresh PipelineContext
 *   3. Resolving dependencies and building execution waves
 *   4. Running each wave (parallel within wave, sequential across waves)
 *   5. For each node: optionally retry, verify, checkpoint, rollback on failure
 *   6. Emitting events at every state transition
 *
 * The Executor is the single entry point for "run this pipeline".
 */

'use strict';

const PipelineContext = require('./context');
const DependencyResolver = require('./dependency_resolver');

class PipelineExecutor {
  constructor(opts = {}) {
    this.registry = opts.registry || null;
    this.resolver = opts.resolver || new DependencyResolver();
    this.retryManager = opts.retryManager || null;
    this.rollbackManager = opts.rollbackManager || null;
    this.eventBus = opts.eventBus || null;
    this.logger = opts.logger || null;
    this.handlers = opts.handlers || {}; // node.id -> async (node, ctx) => result
    this.verifiers = opts.verifiers || {}; // method -> async (result, node) => bool
    this.approver = opts.approver || null;
  }

  /**
   * Attach a handler map (node.id -> async fn).
   */
  setHandlers(handlers) {
    this.handlers = { ...this.handlers, ...handlers };
    return this;
  }

  /**
   * Attach a verifier map (method -> async fn).
   */
  setVerifiers(verifiers) {
    this.verifiers = { ...this.verifiers, ...verifiers };
    return this;
  }

  /**
   * Attach an approver (async (node) => 'approved'|'rejected').
   */
  setApprover(fn) {
    this.approver = fn;
    return this;
  }

  /**
   * Execute a pipeline by name.
   *
   * @param {string} name - pipeline name (or alias)
   * @param {Object} [initialVars] - initial context variables
   * @param {Object} [opts]
   * @param {boolean} [opts.dryRun]
   * @param {boolean} [opts.autoApprove]
   * @param {boolean} [opts.checkpoint] - save checkpoint before each act node
   * @param {boolean} [opts.rollbackOnFailure] - auto-rollback on failure
   * @returns {Promise<PipelineContext>}
   */
  async execute(name, initialVars = {}, opts = {}) {
    if (!this.registry) throw new Error('Executor requires a PipelineRegistry');
    const entry = this.registry.get(name);
    if (!entry) throw new Error(`Pipeline not found: ${name}`);

    const pipeline = entry.pipeline;
    const ctx = new PipelineContext({
      vars: initialVars,
      meta: {
        pipelineName: name,
        startedAt: Date.now(),
        status: 'running',
        dryRun: !!opts.dryRun,
      },
    });

    this._log('info', `Executing pipeline "${name}"`);
    this._emit('pipeline.start', { name, meta: ctx.meta });

    try {
      // Normalize pipeline shape: { nodes: [...] } or { steps: [...] }
      const nodes = this._normalize(pipeline);

      // Validate
      const validation = this.resolver.validate(nodes);
      if (!validation.ok) {
        throw new Error(`Invalid pipeline: ${validation.errors.join('; ')}`);
      }

      // Build waves
      const waves = this.resolver.buildWaves(nodes);
      ctx.meta.waveCount = waves.length;
      ctx.meta.nodeCount = nodes.length;
      this._log('debug', `Pipeline has ${nodes.length} nodes in ${waves.length} waves`);

      // Execute waves sequentially, nodes within wave in parallel
      for (let i = 0; i < waves.length; i++) {
        const wave = waves[i];
        this._emit('pipeline.wave', { index: i, nodeIds: wave.map(n => n.id) });

        const results = await Promise.all(
          wave.map(node => this._runNode(node, ctx, opts))
        );

        // Check for failures
        for (let j = 0; j < wave.length; j++) {
          const node = wave[j];
          const result = results[j];
          ctx.setResult(node.id, result);

          if (result && result.status === 'failed') {
            this._log('error', `Node ${node.id} failed: ${result.error}`);
            ctx.addError(node.id, new Error(result.error));

            if (opts.rollbackOnFailure && this.rollbackManager) {
              this._log('warn', 'Rolling back due to failure');
              await this.rollbackManager.rollbackAll({ continueOnError: true });
              ctx.recordRollback('auto');
            }

            ctx.finish('failed');
            this._emit('pipeline.failed', { name, nodeId: node.id, error: result.error });
            return ctx;
          }
        }
      }

      ctx.finish('completed');
      this._log('info', `Pipeline "${name}" completed in ${ctx.metrics.totalMs}ms`);
      this._emit('pipeline.complete', { name, metrics: ctx.metrics });
      return ctx;
    } catch (e) {
      ctx.addError('_executor', e);
      ctx.finish('failed');
      this._log('error', `Pipeline "${name}" errored: ${e.message}`);
      this._emit('pipeline.error', { name, error: e.message });
      throw e;
    }
  }

  /**
   * Run a single node within a wave.
   */
  async _runNode(node, ctx, opts) {
    this._emit('node.start', { node: node.id, type: node.type });
    const startedAt = Date.now();

    try {
      // Approval gate
      if (node.type === 'approval') {
        if (opts.autoApprove || opts.dryRun) {
          ctx.setResult(node.id, { status: 'approved', auto: true });
          return { status: 'approved', auto: true };
        }
        if (!this.approver) {
          throw new Error(`Approval node ${node.id} has no approver`);
        }
        const decision = await this.approver(node);
        ctx.setResult(node.id, { status: decision });
        return { status: decision };
      }

      // Wait node
      if (node.type === 'wait') {
        const ms = (node.parameters && node.parameters.ms) || 1000;
        if (!opts.dryRun) await new Promise(r => setTimeout(r, ms));
        ctx.setResult(node.id, { status: 'waited', ms });
        return { status: 'waited', ms };
      }

      // Verify node
      if (node.type === 'verify') {
        const target = (node.dependencies || [])[0];
        const upstream = ctx.getResult(target);
        const verifier = this.verifiers[node.verification && node.verification.method];
        let ok = false;
        if (verifier) {
          ok = await verifier(upstream, node);
        } else {
          ok = upstream && upstream.status === 'success';
        }
        ctx.setResult(node.id, { status: ok ? 'verified' : 'failed' });
        return { status: ok ? 'verified' : 'failed' };
      }

      // Checkpoint before act nodes
      if (node.type === 'act' && opts.checkpoint) {
        ctx.checkpoint(`before_${node.id}`);
      }

      // Act / Observe / Decide / etc.
      const handler = this.handlers[node.id];
      let result;
      if (handler) {
        if (this.retryManager && (node.retry !== false)) {
          const retried = await this.retryManager.runWithRetry(
            (c) => handler(node, c),
            {
              name: node.id,
              maxAttempts: node.maxAttempts || 3,
              backoffMs: node.backoffMs || 100,
              ctx,
            }
          );
          result = retried.result || { status: 'failed', error: 'retries exhausted' };
        } else {
          result = await handler(node, ctx);
        }
      } else if (opts.dryRun) {
        result = { status: 'success', dryRun: true, node: node.id };
      } else {
        result = { status: 'success', noop: true, node: node.id };
      }

      const elapsed = Date.now() - startedAt;
      ctx.recordSuccess(node.id, elapsed);
      ctx.setResult(node.id, result);
      this._emit('node.complete', { node: node.id, result, elapsed });
      return result;
    } catch (e) {
      const elapsed = Date.now() - startedAt;
      const errResult = { status: 'failed', error: e.message, elapsed };
      ctx.setResult(node.id, errResult);
      this._emit('node.error', { node: node.id, error: e.message });
      return errResult;
    }
  }

  /**
   * Normalize a pipeline definition into a list of nodes.
   * Supports { nodes: [...] }, { steps: [...] }, or a function.
   */
  _normalize(pipeline) {
    if (Array.isArray(pipeline)) return pipeline;
    if (pipeline && Array.isArray(pipeline.nodes)) return pipeline.nodes;
    if (pipeline && Array.isArray(pipeline.steps)) {
      // Convert legacy steps to nodes
      return pipeline.steps.map((s, i) => ({
        id: s.name || `step_${i}`,
        type: 'act',
        objective: s.name || `step_${i}`,
        dependencies: i === 0 ? [] : [`step_${i - 1}`],
        verification: { method: 'noop' },
        recovery: ['log'],
      }));
    }
    if (typeof pipeline === 'function') {
      return [{
        id: pipeline.name || 'fn',
        type: 'act',
        objective: 'function pipeline',
        dependencies: [],
        verification: { method: 'noop' },
        recovery: ['log'],
      }];
    }
    throw new Error('Pipeline must have nodes, steps, or be a function');
  }

  _log(level, msg) {
    if (this.logger && typeof this.logger[level] === 'function') {
      this.logger[level](msg);
    }
  }

  _emit(type, payload) {
    if (this.eventBus && typeof this.eventBus.emitSync === 'function') {
      this.eventBus.emitSync(type, payload);
    }
  }
}

module.exports = PipelineExecutor;
