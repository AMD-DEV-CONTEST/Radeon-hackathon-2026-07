/**
 * core/rollback_manager.js — Rollback Manager
 *
 * Coordinates undoing side effects when a pipeline fails.
 *
 * Strategy:
 *   - Each step/node may register a rollback action during execution.
 *   - Rollback actions are pushed onto a stack (LIFO).
 *   - On failure, the stack is unwound in reverse order.
 *   - Each rollback action receives the original input and the result/error.
 *   - Rollback failures are logged but do not stop the unwind.
 *
 * The RollbackManager does not own checkpoints — it delegates to
 * PipelineContext.checkpoint()/restore() for state snapshots.
 */

'use strict';

class RollbackManager {
  constructor(opts = {}) {
    this.eventBus = opts.eventBus || null;
    this.logger = opts.logger || null;
    this._stack = []; // LIFO of { id, name, action, input, result, error, at }
    this._idCounter = 0;
  }

  /**
   * Register a rollback action for a step.
   * Call this from inside a step's handler to make it undoable.
   *
   * @param {Object} spec
   * @param {string} spec.name - step name
   * @param {Function} spec.action - async (input, result, error) => void
   * @param {*} [spec.input] - input passed to the step (for undo)
   * @param {*} [spec.result] - result of the step (for undo)
   * @returns {string} rollback id
   */
  register(spec) {
    if (!spec || typeof spec.action !== 'function') {
      throw new TypeError('Rollback spec must include an action function');
    }
    const id = `rb_${Date.now()}_${++this._idCounter}`;
    this._stack.push({
      id,
      name: spec.name || 'anonymous',
      action: spec.action,
      input: spec.input,
      result: spec.result,
      error: spec.error || null,
      at: Date.now(),
    });
    this._log('debug', `Registered rollback ${id} for ${spec.name}`);
    this._emit('rollback.registered', { id, name: spec.name });
    return id;
  }

  /**
   * Manually push a rollback entry (alias for register).
   */
  push(spec) { return this.register(spec); }

  /**
   * Pop the most recent rollback entry without executing it.
   */
  pop() {
    return this._stack.pop();
  }

  /**
   * Peek at the rollback stack.
   */
  peek() {
    return this._stack[this._stack.length - 1];
  }

  /**
   * Get the current rollback stack (read-only copy).
   */
  stack() {
    return this._stack.slice();
  }

  /**
   * Number of pending rollbacks.
   */
  size() {
    return this._stack.length;
  }

  /**
   * Execute all pending rollbacks in reverse order (LIFO).
   * Stops on first failure unless opts.continueOnError is true.
   *
   * @param {Object} [opts]
   * @param {boolean} [opts.continueOnError] - keep unwinding even if a rollback fails
   * @param {Error} [opts.triggerError] - the error that triggered the rollback
   * @returns {Promise<{ rolledBack: number, failed: Array }>}
   */
  async rollbackAll(opts = {}) {
    const continueOnError = !!opts.continueOnError;
    const triggerError = opts.triggerError || null;
    const rolledBack = [];
    const failed = [];

    this._log('warn', `Rolling back ${this._stack.length} action(s)`);
    this._emit('rollback.start', { count: this._stack.length, triggerError });

    while (this._stack.length > 0) {
      const entry = this._stack.pop();
      try {
        await entry.action(entry.input, entry.result, entry.error || triggerError);
        rolledBack.push({ id: entry.id, name: entry.name });
        this._log('info', `Rolled back ${entry.name} (${entry.id})`);
        this._emit('rollback.completed', { id: entry.id, name: entry.name });
      } catch (e) {
        failed.push({ id: entry.id, name: entry.name, error: e.message });
        this._log('error', `Rollback failed for ${entry.name}: ${e.message}`);
        this._emit('rollback.failed', { id: entry.id, name: entry.name, error: e.message });
        if (!continueOnError) {
          this._log('error', 'Stopping rollback unwind due to failure');
          break;
        }
      }
    }

    this._emit('rollback.done', { rolledBack: rolledBack.length, failed: failed.length });
    return { rolledBack: rolledBack.length, failed };
  }

  /**
   * Roll back to a specific checkpoint by id.
   * Pops and executes rollbacks until the named checkpoint is reached.
   *
   * @param {string} checkpointId
   * @param {Object} ctx - PipelineContext (must support restore())
   */
  async rollbackToCheckpoint(checkpointId, ctx) {
    if (!ctx || typeof ctx.restore !== 'function') {
      throw new TypeError('rollbackToCheckpoint requires a PipelineContext with restore()');
    }
    this._log('warn', `Rolling back to checkpoint ${checkpointId}`);
    this._emit('rollback.toCheckpoint', { checkpointId });

    // Pop and execute all rollbacks above the checkpoint
    // (caller is responsible for tracking which rollbacks belong to which checkpoint)
    const result = await this.rollbackAll({ continueOnError: true });
    ctx.restore(checkpointId);
    return result;
  }

  /**
   * Clear the rollback stack without executing anything.
   */
  clear() {
    const count = this._stack.length;
    this._stack = [];
    this._log('debug', `Cleared ${count} rollback entries`);
    return count;
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

module.exports = RollbackManager;
