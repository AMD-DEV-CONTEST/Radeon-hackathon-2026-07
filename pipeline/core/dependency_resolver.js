/**
 * core/dependency_resolver.js — Dependency Resolver
 *
 * Resolves execution order for nodes/steps based on declared dependencies.
 * Produces a topological ordering and groups nodes into execution waves
 * (parallel branches).
 *
 * Features:
 *   - Topological sort with cycle detection
 *   - Wave grouping (nodes whose deps are all in earlier waves run together)
 *   - Optional priority ordering within a wave
 *   - Optional critical-path highlighting
 *   - Validation of dependency references
 *
 * Pure functions — no side effects, no I/O.
 */

'use strict';

class DependencyResolver {
  constructor(opts = {}) {
    this.strict = opts.strict !== false; // throw on unknown deps
  }

  /**
   * Topologically sort nodes by dependencies.
   * @param {Array} nodes - each must have { id, dependencies? }
   * @returns {Array} nodes in execution order
   */
  topoSort(nodes) {
    if (!Array.isArray(nodes)) throw new TypeError('nodes must be an array');
    const byId = new Map();
    for (const n of nodes) {
      if (!n || !n.id) throw new Error('Each node must have an id');
      byId.set(n.id, n);
    }

    const visited = new Set();
    const visiting = new Set();
    const order = [];

    const visit = (id, path) => {
      if (visited.has(id)) return;
      if (visiting.has(id)) {
        throw new Error(`Cycle detected: ${path.join(' -> ')} -> ${id}`);
      }
      const node = byId.get(id);
      if (!node) {
        if (this.strict) throw new Error(`Unknown node id: ${id}`);
        return;
      }
      visiting.add(id);
      for (const dep of node.dependencies || []) {
        visit(dep, [...path, id]);
      }
      visiting.delete(id);
      visited.add(id);
      order.push(node);
    };

    for (const node of nodes) {
      visit(node.id, []);
    }
    return order;
  }

  /**
   * Group nodes into execution waves.
   * Each wave contains nodes whose dependencies are all in earlier waves.
   * @returns {Array<Array>} waves
   */
  buildWaves(nodes) {
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

      // Sort within wave by priority (lower number = higher priority)
      wave.sort((a, b) => (a.priority || 0) - (b.priority || 0));
      waves.push(wave);
      for (const n of wave) remaining.delete(n.id);
    }
    return waves;
  }

  /**
   * Validate that all dependency references exist.
   */
  validate(nodes) {
    const errors = [];
    const ids = new Set(nodes.map(n => n.id));
    for (const n of nodes) {
      for (const dep of n.dependencies || []) {
        if (!ids.has(dep)) {
          errors.push(`Node "${n.id}" depends on unknown node "${dep}"`);
        }
      }
    }
    return { ok: errors.length === 0, errors };
  }

  /**
   * Detect cycles and return the cycle path if found.
   */
  detectCycles(nodes) {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const WHITE = 0, GRAY = 1, BLACK = 2;
    const color = new Map();
    const parent = new Map();

    for (const n of nodes) color.set(n.id, WHITE);

    const dfs = (id, path) => {
      color.set(id, GRAY);
      const node = byId.get(id);
      if (!node) return null;
      for (const dep of node.dependencies || []) {
        if (!byId.has(dep)) continue;
        if (color.get(dep) === GRAY) {
          // Found cycle — reconstruct path
          const cyclePath = [dep, id];
          let cur = id;
          while (parent.has(cur) && parent.get(cur) !== dep) {
            cur = parent.get(cur);
            cyclePath.push(cur);
          }
          cyclePath.reverse();
          return cyclePath;
        }
        if (color.get(dep) === WHITE) {
          parent.set(dep, id);
          const found = dfs(dep, [...path, id]);
          if (found) return found;
        }
      }
      color.set(id, BLACK);
      return null;
    };

    for (const n of nodes) {
      if (color.get(n.id) === WHITE) {
        const cycle = dfs(n.id, []);
        if (cycle) return cycle;
      }
    }
    return null;
  }

  /**
   * Compute the critical path (longest dependency chain).
   */
  criticalPath(nodes) {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const dist = new Map();
    const order = this.topoSort(nodes);

    for (const n of order) {
      const deps = n.dependencies || [];
      const maxDepDist = deps.length === 0
        ? 0
        : Math.max(...deps.map(d => dist.get(d) || 0));
      dist.set(n.id, maxDepDist + (n.estimated_duration || 1));
    }

    // Find the node with max distance
    let endNode = null;
    let maxDist = -1;
    for (const [id, d] of dist) {
      if (d > maxDist) {
        maxDist = d;
        endNode = id;
      }
    }

    // Reconstruct path
    const path = [];
    let cur = endNode;
    while (cur) {
      path.unshift(cur);
      const node = byId.get(cur);
      const deps = (node && node.dependencies) || [];
      if (deps.length === 0) break;
      cur = deps.reduce((a, b) => (dist.get(a) || 0) >= (dist.get(b) || 0) ? a : b);
    }
    return { path, totalDuration: maxDist };
  }
}

module.exports = DependencyResolver;
