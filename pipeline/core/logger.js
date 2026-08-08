/**
 * core/logger.js — Logger
 *
 * Structured logger for pipeline execution. Supports:
 *   - Levels: trace, debug, info, warn, error, fatal
 *   - Multiple sinks: console, file, memory ring buffer, custom
 *   - Per-pipeline child loggers with inherited config
 *   - Structured fields (timestamp, level, pipeline, step, ...)
 *   - Level filtering
 *
 * The Logger is decoupled from console so tests can capture output
 * without polluting stdout.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const LEVELS = Object.freeze({
  TRACE: 10,
  DEBUG: 20,
  INFO: 30,
  WARN: 40,
  ERROR: 50,
  FATAL: 60,
});

const LEVEL_NAMES = Object.freeze({
  10: 'trace', 20: 'debug', 30: 'info', 40: 'warn', 50: 'error', 60: 'fatal',
});

class Logger {
  constructor(opts = {}) {
    this.level = LEVELS[opts.level?.toUpperCase()] || LEVELS.INFO;
    this.sinks = [];
    this.fields = opts.fields || {};
    this._children = new Map();

    // Default sinks
    if (opts.console !== false) {
      this.addSink(new ConsoleSink(opts.consoleOpts || {}));
    }
    if (opts.file) {
      this.addSink(new FileSink(opts.file));
    }
    if (opts.memory !== false) {
      this.addSink(new MemorySink(opts.memorySize || 500));
    }
  }

  /**
   * Add a sink.
   */
  addSink(sink) {
    if (!sink || typeof sink.write !== 'function') {
      throw new TypeError('Sink must implement write(entry)');
    }
    this.sinks.push(sink);
    return this;
  }

  /**
   * Remove a sink.
   */
  removeSink(sink) {
    const i = this.sinks.indexOf(sink);
    if (i >= 0) {
      this.sinks.splice(i, 1);
      return true;
    }
    return false;
  }

  /**
   * Create a child logger with additional fields.
   */
  child(fields) {
    const child = new Logger({
      console: false,
      memory: false,
      level: LEVEL_NAMES[this.level],
    });
    child.fields = { ...this.fields, ...fields };
    child.sinks = this.sinks.slice(); // share sinks
    child._parent = this;
    return child;
  }

  /**
   * Set log level.
   */
  setLevel(level) {
    this.level = typeof level === 'string' ? LEVELS[level.toUpperCase()] : level;
    return this;
  }

  /**
   * Log at a specific level.
   */
  log(level, message, data = {}) {
    const lvl = typeof level === 'string' ? LEVELS[level.toUpperCase()] : level;
    if (lvl < this.level) return;

    const entry = {
      timestamp: new Date().toISOString(),
      level: LEVEL_NAMES[lvl] || String(lvl),
      levelValue: lvl,
      message,
      ...this.fields,
      ...data,
    };

    for (const sink of this.sinks) {
      try {
        sink.write(entry);
      } catch (e) {
        // Sink errors must not break logging
        // eslint-disable-next-line no-console
        console.error('[Logger] sink error:', e.message);
      }
    }
    return entry;
  }

  trace(msg, data) { return this.log('trace', msg, data); }
  debug(msg, data) { return this.log('debug', msg, data); }
  info(msg, data)  { return this.log('info',  msg, data); }
  warn(msg, data)  { return this.log('warn',  msg, data); }
  error(msg, data) { return this.log('error', msg, data); }
  fatal(msg, data) { return this.log('fatal', msg, data); }
}

// ─── Sinks ───────────────────────────────────────────────────────────────────

class ConsoleSink {
  constructor(opts = {}) {
    this.colors = opts.colors !== false;
    this.stderrLevels = new Set(['warn', 'error', 'fatal']);
  }
  write(entry) {
    const line = this._format(entry);
    if (this.stderrLevels.has(entry.level)) {
      process.stderr.write(line + '\n');
    } else {
      process.stdout.write(line + '\n');
    }
  }
  _format(entry) {
    if (!this.colors) {
      return `${entry.timestamp} ${entry.level.toUpperCase().padEnd(5)} ${entry.message}`;
    }
    const colors = {
      trace: '\x1b[90m', debug: '\x1b[36m', info: '\x1b[32m',
      warn: '\x1b[33m', error: '\x1b[31m', fatal: '\x1b[35m',
    };
    const reset = '\x1b[0m';
    const c = colors[entry.level] || '';
    return `${entry.timestamp} ${c}${entry.level.toUpperCase().padEnd(5)}${reset} ${entry.message}`;
  }
}

class FileSink {
  constructor(filePath) {
    this.path = filePath;
    this._dir = path.dirname(filePath);
    if (!fs.existsSync(this._dir)) fs.mkdirSync(this._dir, { recursive: true });
    this._stream = fs.createWriteStream(filePath, { flags: 'a' });
  }
  write(entry) {
    this._stream.write(JSON.stringify(entry) + '\n');
  }
  close() {
    return new Promise(resolve => this._stream.end(resolve));
  }
}

class MemorySink {
  constructor(maxSize = 500) {
    this.maxSize = maxSize;
    this.entries = [];
  }
  write(entry) {
    this.entries.push(entry);
    if (this.entries.length > this.maxSize) this.entries.shift();
  }
  /** Get recent entries, optionally filtered by level. */
  recent(limit, level) {
    let filtered = this.entries;
    if (level) {
      const minLevel = LEVELS[level.toUpperCase()] || 0;
      filtered = filtered.filter(e => e.levelValue >= minLevel);
    }
    if (limit && limit > 0) return filtered.slice(-limit);
    return filtered.slice();
  }
  clear() {
    this.entries = [];
  }
}

module.exports = Logger;
module.exports.LEVELS = LEVELS;
module.exports.LEVEL_NAMES = LEVEL_NAMES;
module.exports.ConsoleSink = ConsoleSink;
module.exports.FileSink = FileSink;
module.exports.MemorySink = MemorySink;
