/**
 * core/event_bus.js — Event Bus
 *
 * A typed pub/sub bus for pipeline events. Unlike Node's EventEmitter,
 * this bus:
 *   - Supports namespaced event names ("pipeline.start", "step.complete")
 *   - Supports wildcard subscriptions ("pipeline.*", "*")
 *   - Supports async listeners (awaits each one)
 *   - Buffers events when no listeners are attached (optional)
 *   - Records a history of recent events for debugging
 *
 * The bus is intentionally decoupled from any specific pipeline so that
 * the Logger, Retry Manager, Rollback Manager, and Executor can all
 * publish/subscribe without coupling.
 */

'use strict';

class EventBus {
  constructor(opts = {}) {
    this._listeners = new Map(); // event -> Set<fn>
    this._wildcardListeners = new Set();
    this._history = [];
    this._maxHistory = opts.maxHistory || 500;
    this._buffer = opts.buffer === true;
    this._buffered = [];
    this._maxBuffer = opts.maxBuffer || 100;
    this._async = opts.async !== false; // await listeners by default
  }

  /**
   * Subscribe to an event or pattern.
   * Pattern may end with ".*" for namespace match, or be "*" for all events.
   * Returns an unsubscribe function.
   */
  on(pattern, listener) {
    if (typeof pattern !== 'string') throw new TypeError('pattern must be a string');
    if (typeof listener !== 'function') throw new TypeError('listener must be a function');

    if (pattern === '*') {
      this._wildcardListeners.add(listener);
      return () => this._wildcardListeners.delete(listener);
    }

    if (pattern.endsWith('.*')) {
      const ns = pattern.slice(0, -2);
      const wrapped = (event) => {
        if (event.type && event.type.startsWith(ns + '.') || event.type === ns) {
          return listener(event);
        }
      };
      this._wildcardListeners.add(wrapped);
      return () => this._wildcardListeners.delete(wrapped);
    }

    if (!this._listeners.has(pattern)) this._listeners.set(pattern, new Set());
    this._listeners.get(pattern).add(listener);
    return () => {
      const set = this._listeners.get(pattern);
      if (set) set.delete(listener);
    };
  }

  /**
   * Subscribe to a single occurrence, then auto-unsubscribe.
   */
  once(pattern, listener) {
    const off = this.on(pattern, (event) => {
      off();
      return listener(event);
    });
    return off;
  }

  /**
   * Publish an event.
   * @param {string} type - event type (e.g. "pipeline.start")
   * @param {Object} [payload] - event data
   */
  async emit(type, payload = {}) {
    const event = {
      type,
      payload,
      at: Date.now(),
      id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    };

    // Record in history
    this._history.push(event);
    if (this._history.length > this._maxHistory) {
      this._history.shift();
    }

    // Buffer if no listeners and buffering is enabled
    const hasExact = this._listeners.has(type) && this._listeners.get(type).size > 0;
    const hasWild = this._wildcardListeners.size > 0;
    if (!hasExact && !hasWild && this._buffer) {
      this._buffered.push(event);
      if (this._buffered.length > this._maxBuffer) this._buffered.shift();
      return;
    }

    // Notify exact listeners
    const exact = this._listeners.get(type);
    if (exact) {
      for (const fn of exact) {
        try {
          const r = fn(event);
          if (this._async && r && typeof r.then === 'function') await r;
        } catch (e) {
          // Listener errors must not break the bus
          // eslint-disable-next-line no-console
          console.error(`[EventBus] listener error for ${type}:`, e.message);
        }
      }
    }

    // Notify wildcard listeners
    for (const fn of this._wildcardListeners) {
      try {
        const r = fn(event);
        if (this._async && r && typeof r.then === 'function') await r;
      } catch (e) {
        // eslint-disable-next-line no-console
        console.error(`[EventBus] wildcard listener error:`, e.message);
      }
    }
  }

  /**
   * Synchronous emit (does not await listeners).
   */
  emitSync(type, payload = {}) {
    const event = { type, payload, at: Date.now() };
    this._history.push(event);
    if (this._history.length > this._maxHistory) this._history.shift();

    const exact = this._listeners.get(type);
    if (exact) {
      for (const fn of exact) {
        try { fn(event); } catch (_) { /* swallow */ }
      }
    }
    for (const fn of this._wildcardListeners) {
      try { fn(event); } catch (_) { /* swallow */ }
    }
  }

  /**
   * Drain buffered events (replay them to current listeners).
   */
  async drainBuffer() {
    const buffered = this._buffered.slice();
    this._buffered = [];
    for (const event of buffered) {
      await this.emit(event.type, event.payload);
    }
    return buffered.length;
  }

  /**
   * Get recent event history.
   */
  history(limit) {
    if (limit && limit > 0) return this._history.slice(-limit);
    return [...this._history];
  }

  /**
   * Clear all listeners and history.
   */
  clear() {
    this._listeners.clear();
    this._wildcardListeners.clear();
    this._history = [];
    this._buffered = [];
  }

  /**
   * Count listeners for a pattern.
   */
  listenerCount(pattern) {
    if (pattern === '*') return this._wildcardListeners.size;
    return (this._listeners.get(pattern) || new Set()).size;
  }
}

module.exports = EventBus;
