/**
 * core/context.js — Pipeline Context
 *
 * A typed, immutable-by-convention container that flows through every step
 * of a pipeline execution. Holds:
 *   - vars: arbitrary key/value bag (inputs, intermediate state)
 *   - results: per-step/node results keyed by id
 *   - log: ordered list of log entries
 *   - errors: collected errors
 *   - metrics: timing and counters
 *   - checkpoints: snapshots for rollback
 *   - meta: pipeline-level metadata (name, startedAt, ...)
 *
 * Context is passed by reference but exposes a snapshot() method for
 * safe serialization. Mutations are tracked so the executor can decide
 * whether to checkpoint.
 */

'use strict';

class PipelineContext {
  constructor(initial = {}) {
    this.vars = initial.vars || {};
    this.results = initial.results || {};
    this.log = initial.log || [];
    this.errors = initial.errors || [];
    this.metrics = initial.metrics || this._defaultMetrics();
    this.checkpoints = initial.checkpoints || [];
    this.meta = initial.meta || this._defaultMeta();
    this._frozen = false;
  }

  _defaultMetrics() {
    return {
      totalMs: 0,
      steps: 0,
      succeeded: 0,
      failed: 0,
      retried: 0,
      rolledBack: 0,
      perStep: {},
    };
  }

  _defaultMeta() {
    return {
      pipelineName: null,
      startedAt: Date.now(),
      finishedAt: null,
      status: 'pending', // pending | running | completed | failed | cancelled
      dryRun: false,
    };
  }

  /**
   * Set a variable.
   */
  set(key, value) {
    this._assertMutable();
    this.vars[key] = value;
    return this;
  }

  /**
   * Get a variable with optional default.
   */
  get(key, defaultValue) {
    return this.vars[key] !== undefined ? this.vars[key] : defaultValue;
  }

  /**
   * Check if a variable exists.
   */
  has(key) {
    return Object.prototype.hasOwnProperty.call(this.vars, key);
  }

  /**
   * Delete a variable.
   */
  unset(key) {
    this._assertMutable();
    delete this.vars[key];
    return this;
  }

  /**
   * Merge multiple variables at once.
   */
  mergeVars(obj) {
    this._assertMutable();
    Object.assign(this.vars, obj);
    return this;
  }

  /**
   * Record a step/node result.
   */
  setResult(id, result) {
    this._assertMutable();
    this.results[id] = result;
    return this;
  }

  /**
   * Get a step/node result.
   */
  getResult(id) {
    return this.results[id];
  }

  /**
   * Append a log entry.
   */
  log_(level, message, data) {
    this._assertMutable();
    this.log.push({
      level,
      message,
      data: data || null,
      at: Date.now(),
    });
    return this;
  }

  /**
   * Record an error.
   */
  addError(stepName, error) {
    this._assertMutable();
    this.errors.push({
      step: stepName,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : null,
      at: Date.now(),
    });
    this.metrics.failed += 1;
    return this;
  }

  /**
   * Record a successful step.
   */
  recordSuccess(stepName, elapsedMs) {
    this._assertMutable();
    this.metrics.succeeded += 1;
    this.metrics.perStep[stepName] = elapsedMs;
    return this;
  }

  /**
   * Record a retry.
   */
  recordRetry(stepName) {
    this._assertMutable();
    this.metrics.retried += 1;
    return this;
  }

  /**
   * Record a rollback.
   */
  recordRollback(checkpointId) {
    this._assertMutable();
    this.metrics.rolledBack += 1;
    return this;
  }

  /**
   * Save a checkpoint snapshot.
   */
  checkpoint(label) {
    const snap = this.snapshot();
    snap.label = label || `cp_${this.checkpoints.length + 1}`;
    snap.id = `cp_${Date.now()}_${this.checkpoints.length}`;
    this.checkpoints.push(snap);
    return snap.id;
  }

  /**
   * Restore from a checkpoint by id.
   */
  restore(checkpointId) {
    const cp = this.checkpoints.find(c => c.id === checkpointId);
    if (!cp) throw new Error(`Checkpoint not found: ${checkpointId}`);
    this.vars = JSON.parse(JSON.stringify(cp.vars));
    this.results = JSON.parse(JSON.stringify(cp.results));
    this.log = JSON.parse(JSON.stringify(cp.log));
    this.errors = JSON.parse(JSON.stringify(cp.errors));
    this.metrics = JSON.parse(JSON.stringify(cp.metrics));
    return this;
  }

  /**
   * Mark the context as finished.
   */
  finish(status) {
    this.meta.finishedAt = Date.now();
    this.meta.status = status || 'completed';
    this.metrics.totalMs = this.meta.finishedAt - this.meta.startedAt;
    return this;
  }

  /**
   * Freeze the context — no further mutations allowed.
   */
  freeze() {
    this._frozen = true;
    return this;
  }

  _assertMutable() {
    if (this._frozen) {
      throw new Error('PipelineContext is frozen');
    }
  }

  /**
   * Take a deep-cloned snapshot of the context.
   */
  snapshot() {
    return {
      vars: JSON.parse(JSON.stringify(this.vars)),
      results: JSON.parse(JSON.stringify(this.results)),
      log: JSON.parse(JSON.stringify(this.log)),
      errors: JSON.parse(JSON.stringify(this.errors)),
      metrics: JSON.parse(JSON.stringify(this.metrics)),
      checkpoints: this.checkpoints.map(c => ({ id: c.id, label: c.label, at: c.at })),
      meta: { ...this.meta },
    };
  }

  /**
   * Serialize to a plain JSON string.
   */
  toJSON() {
    return JSON.stringify(this.snapshot());
  }
}

module.exports = PipelineContext;
