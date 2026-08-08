/**
 * core/loader.js — Pipeline Loader
 *
 * Loads pipeline definitions from disk (JSON files, JS modules) and registers
 * them into a PipelineRegistry.
 *
 * Supported sources:
 *   - Single JSON file: { name, steps, ... }
 *   - Single JS module: exports a pipeline object or factory function
 *   - Directory: scans for *.pipeline.json / *.pipeline.js files
 *   - Inline definition: passed directly to load()
 *
 * Loader is intentionally simple — it does not execute pipelines, only
 * parses and registers them. Execution is the Executor's job.
 */

'use strict';

const fs = require('fs');
const path = require('path');

class PipelineLoader {
  constructor(registry, opts = {}) {
    if (!registry) throw new TypeError('PipelineLoader requires a PipelineRegistry');
    this.registry = registry;
    this.opts = {
      extensions: opts.extensions || ['.pipeline.json', '.pipeline.js', '.json', '.js'],
      recursive: opts.recursive !== false,
      validate: opts.validate !== false,
      logger: opts.logger || null,
    };
    this._loaded = []; // history of loaded sources
  }

  /**
   * Load a single file or inline definition.
   * @param {string|Object} source - file path or inline definition
   * @returns {Array<string>} names of registered pipelines
   */
  load(source) {
    if (source === null || source === undefined) {
      throw new TypeError('load() requires a source');
    }

    if (typeof source === 'object') {
      return this._loadInline(source);
    }

    if (typeof source !== 'string') {
      throw new TypeError('load() source must be a string path or object');
    }

    const stat = fs.existsSync(source) ? fs.statSync(source) : null;
    if (!stat) {
      throw new Error(`Pipeline source not found: ${source}`);
    }

    if (stat.isDirectory()) {
      return this.loadDirectory(source);
    }

    return this._loadFile(source);
  }

  /**
   * Load all pipeline files from a directory.
   */
  loadDirectory(dir) {
    if (!fs.existsSync(dir)) {
      throw new Error(`Directory not found: ${dir}`);
    }
    const names = [];
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory() && this.opts.recursive) {
        names.push(...this.loadDirectory(full));
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name);
        if (this.opts.extensions.includes(ext)) {
          try {
            names.push(...this._loadFile(full));
          } catch (e) {
            this._log('error', `Failed to load ${full}: ${e.message}`);
          }
        }
      }
    }
    return names;
  }

  /**
   * Load a single file by path.
   */
  _loadFile(filePath) {
    const ext = path.extname(filePath);
    let defs;
    if (ext === '.json') {
      const raw = fs.readFileSync(filePath, 'utf8');
      defs = JSON.parse(raw);
    } else if (ext === '.js') {
      // Clear require cache so re-loading picks up edits
      delete require.cache[require.resolve(filePath)];
      const mod = require(filePath);
      defs = mod.default || mod.pipeline || mod;
    } else {
      throw new Error(`Unsupported pipeline file extension: ${ext}`);
    }

    const names = this._registerDefinitions(defs, filePath);
    this._loaded.push({ source: filePath, names, at: Date.now() });
    return names;
  }

  /**
   * Load an inline definition (object or array of objects).
   */
  _loadInline(def) {
    const names = this._registerDefinitions(def, '<inline>');
    this._loaded.push({ source: '<inline>', names, at: Date.now() });
    return names;
  }

  /**
   * Normalize and register one or more definitions.
   * Accepts: single object, array of objects, or { pipelines: [...] } wrapper.
   */
  _registerDefinitions(def, source) {
    let list;
    if (Array.isArray(def)) {
      list = def;
    } else if (def && Array.isArray(def.pipelines)) {
      list = def.pipelines;
    } else if (def && (def.name || def.steps || def.nodes)) {
      list = [def];
    } else {
      throw new Error(`Invalid pipeline definition in ${source}`);
    }

    const names = [];
    for (const p of list) {
      if (this.opts.validate) this._validate(p, source);
      const name = p.name || `pipeline_${names.length + 1}`;
      this.registry.register(name, p, {
        description: p.description || '',
        tags: p.tags || [],
        version: p.version || '1.0.0',
        source,
      });
      names.push(name);
    }
    return names;
  }

  /**
   * Lightweight structural validation.
   */
  _validate(p, source) {
    if (!p || typeof p !== 'object') {
      throw new Error(`Pipeline in ${source} is not an object`);
    }
    if (!p.name && !p.steps && !p.nodes) {
      throw new Error(`Pipeline in ${source} must have name, steps, or nodes`);
    }
    if (p.steps && !Array.isArray(p.steps)) {
      throw new Error(`Pipeline "${p.name}" steps must be an array`);
    }
    if (p.nodes && !Array.isArray(p.nodes)) {
      throw new Error(`Pipeline "${p.name}" nodes must be an array`);
    }
  }

  /**
   * Get the load history.
   */
  history() {
    return [...this._loaded];
  }

  /**
   * Clear load history.
   */
  clearHistory() {
    this._loaded = [];
  }

  _log(level, msg) {
    if (this.opts.logger && typeof this.opts.logger[level] === 'function') {
      this.opts.logger[level](msg);
    }
  }
}

module.exports = PipelineLoader;
