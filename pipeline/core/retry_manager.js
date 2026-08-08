/**
 * core/retry_manager.js — Retry Manager
 *
 * Wraps a step/node handler with retry logic.
 *
 * Features:
 *   - Configurable max attempts
 *   - Exponential backoff with jitter
 *   - Custom retry predicate (decide which errors are retryable)
 *   - Per-attempt timeout
 *   - Records each attempt in the context
 *   - Emits retry events on the event bus
 *
 * Pure orchestration — does not execute steps itself; the Executor
 * calls into RetryManager.runWithRetry().
 */

'use strict';

class RetryManager {
  constructor(opts = {}) {
    this.defaultMaxAttempts = opts.maxAttempts || 3;
    this.defaultBackoffMs = opts.backoffMs || 100;
    this.defaultBackoffMultiplier = opts.backoffMultiplier || 2;
    this.defaultMaxBackoffMs = opts.maxBackoffMs || 30000;
    this.defaultJitter = opts.jitter !== false;
    this.defaultTimeoutMs = opts.timeoutMs || 0; // 0 = no timeout
    this.eventBus = opts.eventBus || null;
    this.logger = opts.logger || null;
  }

  /**
   * Run a handler with retry logic.
   *
   * @param {Function} handler - async (ctx) => result
   * @param {Object} opts
   * @param {string} opts.name - step/node name (for logging)
   * @param {number} [opts.maxAttempts]
   * @param {number} [opts.backoffMs]
   * @param {number} [opts.backoffMultiplier]
   * @param {number} [opts.maxBackoffMs]
   * @param {boolean} [opts.jitter]
   * @param {number} [opts.timeoutMs]
   * @param {Function} [opts.shouldRetry] - (error, attempt) => bool
   * @param {Object} opts.ctx - PipelineContext
   * @returns {Promise<{ result: *, attempts: number, errors: Array }>}
   */
  async runWithRetry(handler, opts) {
    if (typeof handler !== 'function') {
      throw new TypeError('handler must be a function');
    }
    const name = opts.name || 'anonymous';
    const maxAttempts = opts.maxAttempts || this.defaultMaxAttempts;
    const backoffMs = opts.backoffMs || this.defaultBackoffMs;
    const multiplier = opts.backoffMultiplier || this.defaultBackoffMultiplier;
    const maxBackoff = opts.maxBackoffMs || this.defaultMaxBackoffMs;
    const jitter = opts.jitter !== undefined ? opts.jitter : this.defaultJitter;
    const timeoutMs = opts.timeoutMs || this.defaultTimeoutMs;
    const shouldRetry = opts.shouldRetry || ((err) => true);
    const ctx = opts.ctx;

    const errors = [];
    let attempt = 0;
    let lastResult = null;

    while (attempt < maxAttempts) {
      attempt += 1;
      const startedAt = Date.now();

      try {
        const result = timeoutMs > 0
          ? await this._withTimeout(handler(ctx), timeoutMs, name, attempt)
          : await handler(ctx);

        const elapsed = Date.now() - startedAt;
        if (ctx) ctx.recordSuccess(name, elapsed);

        if (attempt > 1) {
          this._log('info', `${name} succeeded on attempt ${attempt}/${maxAttempts}`);
          this._emit('retry.success', { name, attempt, elapsed });
        }
        return { result, attempts: attempt, errors };
      } catch (err) {
        const elapsed = Date.now() - startedAt;
        const errorInfo = {
          attempt,
          message: err && err.message ? err.message : String(err),
          stack: err && err.stack ? err.stack : null,
          elapsed,
          at: Date.now(),
        };
        errors.push(errorInfo);

        this._log('warn', `${name} failed on attempt ${attempt}/${maxAttempts}: ${errorInfo.message}`);
        this._emit('retry.attempt', { name, attempt, error: errorInfo });

        if (ctx) ctx.recordRetry(name);

        const retryable = shouldRetry(err, attempt);
        if (!retryable || attempt >= maxAttempts) {
          this._log('error', `${name} giving up after ${attempt} attempts`);
          this._emit('retry.exhausted', { name, attempts: attempt, errors });
          return { result: null, attempts: attempt, errors };
        }

        // Compute backoff
        const delay = this._computeBackoff(attempt, backoffMs, multiplier, maxBackoff, jitter);
        this._log('debug', `${name} backing off ${delay}ms before retry`);
        await this._sleep(delay);
      }
    }

    return { result: lastResult, attempts: attempt, errors };
  }

  /**
   * Compute backoff delay with optional jitter.
   */
  _computeBackoff(attempt, base, multiplier, max, jitter) {
    const exp = base * Math.pow(multiplier, attempt - 1);
    const capped = Math.min(exp, max);
    if (!jitter) return capped;
    // Full jitter: random between 0 and capped
    return Math.floor(Math.random() * capped);
  }

  /**
   * Wrap a promise with a timeout.
   */
  _withTimeout(promise, ms, name, attempt) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`${name} timed out after ${ms}ms (attempt ${attempt})`));
      }, ms);
      promise.then(
        (v) => { clearTimeout(timer); resolve(v); },
        (e) => { clearTimeout(timer); reject(e); }
      );
    });
  }

  _sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
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

module.exports = RetryManager;
