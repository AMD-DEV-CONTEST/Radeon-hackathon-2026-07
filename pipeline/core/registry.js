/**
 * core/registry.js — Pipeline Registry
 *
 * Central in-memory store for pipeline definitions.
 * Supports registration, lookup, listing, namespacing, and metadata.
 *
 * Design:
 *   - Pipelines are stored by name (string) in a Map.
 *   - Each entry holds { pipeline, meta } where meta is arbitrary metadata.
 *   - Namespaces are supported via "namespace:name" keys.
 *   - Lookup is O(1) via Map.
 *   - Iteration order is insertion order (Map semantics).
 */

'use strict';

class PipelineRegistry {
  constructor(opts = {}) {
    this._pipelines = new Map();
    this._aliases = new Map();
    this._tags = new Map(); // tag -> Set<name>
    this._listeners = new Set();
    this._frozen = !!opts.frozen;
  }

  /**
   * Register a pipeline.
   * @param {string} name - pipeline name (may include "namespace:name")
   * @param {Object} pipeline - pipeline definition (must have .name or be a function)
   * @param {Object} [meta] - optional metadata { description, tags, version, ... }
   * @returns {PipelineRegistry} this
   */
  register(name, pipeline, meta = {}) {
    if (this._frozen) {
      throw new Error('PipelineRegistry is frozen');
    }
    if (typeof name !== 'string' || !name) {
      throw new TypeError('Pipeline name must be a non-empty string');
    }
    if (pipeline === null || pipeline === undefined) {
      throw new TypeError(`Pipeline "${name}" cannot be null/undefined`);
    }

    const entry = {
      pipeline,
      meta: {
        name,
        description: meta.description || '',
        tags: Array.isArray(meta.tags) ? [...meta.tags] : [],
        version: meta.version || '1.0.0',
        registeredAt: Date.now(),
        ...meta,
      },
    };

    this._pipelines.set(name, entry);

    // Index tags
    for (const tag of entry.meta.tags) {
      if (!this._tags.has(tag)) this._tags.set(tag, new Set());
      this._tags.get(tag).add(name);
    }

    this._emit({ type: 'register', name, meta: entry.meta });
    return this;
  }

  /**
   * Register an alias that points to another pipeline name.
   */
  alias(aliasName, targetName) {
    if (!this._pipelines.has(targetName)) {
      throw new Error(`Cannot alias unknown pipeline: ${targetName}`);
    }
    this._aliases.set(aliasName, targetName);
    this._emit({ type: 'alias', alias: aliasName, target: targetName });
    return this;
  }

  /**
   * Check if a pipeline (or alias) exists.
   */
  has(name) {
    return this._pipelines.has(name) || this._aliases.has(name);
  }

  /**
   * Get a pipeline by name. Follows aliases.
   * @returns {{ pipeline: *, meta: Object } | null}
   */
  get(name) {
    if (this._pipelines.has(name)) {
      return this._pipelines.get(name);
    }
    if (this._aliases.has(name)) {
      const target = this._aliases.get(name);
      return this._pipelines.get(target) || null;
    }
    return null;
  }

  /**
   * List all registered pipeline names.
   */
  list() {
    return Array.from(this._pipelines.keys());
  }

  /**
   * List pipelines filtered by tag.
   */
  listByTag(tag) {
    const set = this._tags.get(tag);
    return set ? Array.from(set) : [];
  }

  /**
   * List all aliases.
   */
  listAliases() {
    return Array.from(this._aliases.entries()).map(([alias, target]) => ({ alias, target }));
  }

  /**
   * Remove a pipeline.
   */
  unregister(name) {
    const entry = this._pipelines.get(name);
    if (!entry) return false;
    for (const tag of entry.meta.tags || []) {
      const set = this._tags.get(tag);
      if (set) {
        set.delete(name);
        if (set.size === 0) this._tags.delete(tag);
      }
    }
    this._pipelines.delete(name);
    this._emit({ type: 'unregister', name });
    return true;
  }

  /**
   * Clear all pipelines.
   */
  clear() {
    this._pipelines.clear();
    this._aliases.clear();
    this._tags.clear();
    this._emit({ type: 'clear' });
  }

  /**
   * Freeze the registry — no further registrations allowed.
   */
  freeze() {
    this._frozen = true;
    return this;
  }

  /**
   * Subscribe to registry events.
   */
  on(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  _emit(event) {
    for (const fn of this._listeners) {
      try { fn(event); } catch (_) { /* swallow listener errors */ }
    }
  }

  /**
   * Get a snapshot of the registry state.
   */
  snapshot() {
    return {
      count: this._pipelines.size,
      pipelines: Array.from(this._pipelines.entries()).map(([name, entry]) => ({
        name,
        meta: { ...entry.meta },
      })),
      aliases: this.listAliases(),
      tags: Array.from(this._tags.entries()).map(([tag, set]) => ({ tag, count: set.size })),
      frozen: this._frozen,
    };
  }
}

module.exports = PipelineRegistry;
