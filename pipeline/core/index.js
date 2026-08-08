/**
 * core/index.js — Barrel export for the Pipeline Runtime core framework.
 *
 * Phase 1 components:
 *   - PipelineRegistry     : in-memory store of pipeline definitions
 *   - PipelineLoader       : load pipelines from disk or inline
 *   - PipelineExecutor     : orchestrate execution (the main entry point)
 *   - PipelineContext      : typed state container passed through execution
 *   - DependencyResolver   : topological sort + wave grouping + cycle detection
 *   - Scheduler            : priority queue with concurrency limits
 *   - EventBus             : typed pub/sub with wildcards and buffering
 *   - Logger               : structured logger with pluggable sinks
 *   - RetryManager         : exponential backoff retry orchestration
 *   - RollbackManager      : LIFO undo stack for failed pipelines
 */

'use strict';

const PipelineRegistry = require('./registry');
const PipelineLoader = require('./loader');
const PipelineExecutor = require('./executor');
const PipelineContext = require('./context');
const DependencyResolver = require('./dependency_resolver');
const Scheduler = require('./scheduler');
const EventBus = require('./event_bus');
const Logger = require('./logger');
const RetryManager = require('./retry_manager');
const RollbackManager = require('./rollback_manager');

module.exports = {
  // Core components
  PipelineRegistry,
  PipelineLoader,
  PipelineExecutor,
  PipelineContext,
  DependencyResolver,
  Scheduler,
  EventBus,
  Logger,
  RetryManager,
  RollbackManager,

  // Logger sinks (re-exported for convenience)
  ConsoleSink: Logger.ConsoleSink,
  FileSink: Logger.FileSink,
  MemorySink: Logger.MemorySink,
  LEVELS: Logger.LEVELS,
  LEVEL_NAMES: Logger.LEVEL_NAMES,
};
