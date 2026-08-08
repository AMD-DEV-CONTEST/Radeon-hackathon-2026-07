/**
 * core/scheduler.js — Scheduler
 *
 * Schedules pipeline executions with priorities, concurrency limits,
 * and optional delays. The Scheduler sits between the caller and the
 * Executor — callers submit jobs, the Scheduler queues them and runs
 * them according to policy.
 *
 * Features:
 *   - Priority queue (lower number = higher priority)
 *   - Concurrency limit (max parallel jobs)
 *   - FIFO within same priority
 *   - Optional delay before execution
 *   - Job status tracking (queued, running, completed, failed, cancelled)
 *   - Cancellation support
 *   - Event emission on state changes
 */

'use strict';

class Scheduler {
  constructor(opts = {}) {
    this.concurrency = opts.concurrency || 1;
    this.queue = []; // priority queue of jobs
    this.running = new Map(); // jobId -> job
    this.completed = []; // history
    this._nextId = 0;
    this._stopped = false;
    this.eventBus = opts.eventBus || null;
    this.logger = opts.logger || null;
    this.executor = opts.executor || null; // injected Executor
  }

  /**
   * Attach an executor (the Scheduler delegates actual execution to it).
   */
  setExecutor(executor) {
    this.executor = executor;
    return this;
  }

  /**
   * Submit a job to the scheduler.
   *
   * @param {Object} spec
   * @param {string} spec.pipelineName - name of pipeline to run
   * @param {Object} [spec.ctx] - initial context
   * @param {Object} [spec.opts] - executor options
   * @param {number} [spec.priority] - lower = sooner (default 0)
   * @param {number} [spec.delayMs] - delay before execution
   * @returns {string} job id
   */
  submit(spec) {
    if (this._stopped) throw new Error('Scheduler is stopped');
    if (!spec || !spec.pipelineName) {
      throw new TypeError('Job must have a pipelineName');
    }
    const id = `job_${Date.now()}_${++this._nextId}`;
    const job = {
      id,
      pipelineName: spec.pipelineName,
      ctx: spec.ctx || null,
      opts: spec.opts || {},
      priority: spec.priority || 0,
      delayMs: spec.delayMs || 0,
      status: 'queued',
      submittedAt: Date.now(),
      startedAt: null,
      finishedAt: null,
      result: null,
      error: null,
    };
    this._enqueue(job);
    this._emit('scheduler.submitted', { id, pipelineName: job.pipelineName, priority: job.priority });
    this._tick();
    return id;
  }

  /**
   * Insert a job into the priority queue (sorted by priority, then FIFO).
   */
  _enqueue(job) {
    let i = 0;
    while (i < this.queue.length && this.queue[i].priority <= job.priority) i++;
    this.queue.splice(i, 0, job);
  }

  /**
   * Try to start as many jobs as concurrency allows.
   */
  _tick() {
    while (this.running.size < this.concurrency && this.queue.length > 0) {
      const job = this.queue.shift();
      this._startJob(job);
    }
  }

  /**
   * Start a single job (after optional delay).
   */
  async _startJob(job) {
    job.status = 'running';
    job.startedAt = Date.now();
    this.running.set(job.id, job);
    this._emit('scheduler.started', { id: job.id, pipelineName: job.pipelineName });

    if (job.delayMs > 0) {
      await this._sleep(job.delayMs);
    }

    if (!this.executor) {
      this._finishJob(job, { error: new Error('No executor attached to scheduler') });
      return;
    }

    try {
      const result = await this.executor.execute(job.pipelineName, job.ctx, job.opts);
      this._finishJob(job, { result });
    } catch (e) {
      this._finishJob(job, { error: e });
    }
  }

  /**
   * Mark a job as finished and free a concurrency slot.
   */
  _finishJob(job, outcome) {
    job.finishedAt = Date.now();
    if (outcome.error) {
      job.status = 'failed';
      job.error = outcome.error.message || String(outcome.error);
      this._log('error', `Job ${job.id} (${job.pipelineName}) failed: ${job.error}`);
      this._emit('scheduler.failed', { id: job.id, error: job.error });
    } else {
      job.status = 'completed';
      job.result = outcome.result;
      this._log('info', `Job ${job.id} (${job.pipelineName}) completed`);
      this._emit('scheduler.completed', { id: job.id });
    }
    this.running.delete(job.id);
    this.completed.push(job);
    // Cap history
    if (this.completed.length > 100) this.completed.shift();
    this._tick();
  }

  /**
   * Cancel a queued or running job.
   */
  cancel(jobId) {
    // Try queue first
    const qi = this.queue.findIndex(j => j.id === jobId);
    if (qi >= 0) {
      const job = this.queue.splice(qi, 1)[0];
      job.status = 'cancelled';
      job.finishedAt = Date.now();
      this.completed.push(job);
      this._emit('scheduler.cancelled', { id: jobId });
      return true;
    }
    // Running jobs: mark for cancellation (executor must check)
    const running = this.running.get(jobId);
    if (running) {
      running.status = 'cancelling';
      this._emit('scheduler.cancelling', { id: jobId });
      return true;
    }
    return false;
  }

  /**
   * Stop accepting new jobs. Waits for running jobs to finish.
   */
  async stop() {
    this._stopped = true;
    while (this.running.size > 0) {
      await this._sleep(50);
    }
    this._emit('scheduler.stopped', {});
  }

  /**
   * Resume accepting jobs.
   */
  start() {
    this._stopped = false;
    this._tick();
    return this;
  }

  /**
   * Get current state.
   */
  status() {
    return {
      stopped: this._stopped,
      concurrency: this.concurrency,
      queued: this.queue.length,
      running: this.running.size,
      completed: this.completed.length,
      runningJobs: Array.from(this.running.values()).map(j => ({
        id: j.id, pipelineName: j.pipelineName, status: j.status,
      })),
      queuedJobs: this.queue.map(j => ({
        id: j.id, pipelineName: j.pipelineName, priority: j.priority,
      })),
    };
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

module.exports = Scheduler;
