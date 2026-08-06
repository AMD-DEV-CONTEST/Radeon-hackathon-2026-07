/**
 * TraceCollector — in-memory store for agent execution traces.
 *
 * Records FunctionRouter decisions, LLM call timings, tool invocations and
 * errors across a single user turn. Data lives in memory (resets on server
 * restart), consistent with the mock-supabase demo mode.
 *
 * All public convenience functions are defensive: a failure to record a trace
 * event must NEVER break the chat flow. They swallow errors internally and
 * no-op when given an empty traceId.
 */

import type { Trace, TraceEvent, RouteResult, SubagentId } from './types';

// ─── TraceCollector ──────────────────────────────────────────────────────────

/** Max traces retained in memory to avoid unbounded growth. */
const MAX_TRACES = 100;

class TraceCollector {
  private traces = new Map<string, Trace>();
  private counter = 0;

  /** Start a new trace, storing it keyed by id. Returns the Trace object. */
  startTrace(id: string): Trace {
    const trace: Trace = {
      id,
      startTime: Date.now(),
      events: [],
    };
    this.traces.set(id, trace);
    this.prune();
    return trace;
  }

  /** Append an event to a trace. No-op if the trace id is unknown. */
  addEvent(traceId: string, event: TraceEvent): void {
    const trace = this.traces.get(traceId);
    if (!trace) return;
    if (!event.timestamp) {
      event.timestamp = Date.now();
    }
    trace.events.push(event);
  }

  /** Mark a trace as ended (idempotent). */
  endTrace(traceId: string): void {
    const trace = this.traces.get(traceId);
    if (!trace) return;
    if (trace.endTime === undefined) {
      trace.endTime = Date.now();
    }
  }

  /** Get a single trace by id. */
  getTrace(id: string): Trace | undefined {
    return this.traces.get(id);
  }

  /** Return the most recent traces, newest first. */
  getRecentTraces(limit: number): Trace[] {
    return [...this.traces.values()]
      .sort((a, b) => b.startTime - a.startTime)
      .slice(0, limit);
  }

  /** Drop the oldest traces once we exceed MAX_TRACES. */
  private prune(): void {
    if (this.traces.size <= MAX_TRACES) return;
    const sorted = [...this.traces.values()].sort((a, b) => a.startTime - b.startTime);
    const toRemove = sorted.slice(0, this.traces.size - MAX_TRACES);
    for (const t of toRemove) this.traces.delete(t.id);
  }

  /** Remove all seed (demo) traces. Called when a real trace is created. */
  clearSeedTraces(): void {
    const toRemove: string[] = [];
    for (const [id, trace] of this.traces) {
      if (trace.isSeedData) toRemove.push(id);
    }
    for (const id of toRemove) this.traces.delete(id);
  }
}

// ─── Global singleton ─────────────────────────────────────────────────────────

export const traceCollector = new TraceCollector();

// ─── Demo seed traces (for empty-state fallback) ──────────────────────────────

/**
 * Seed 2 demo traces into the collector so /trace is never empty on first visit.
 * Only called in DEMO_MODE. Real traces will push these out naturally (prune by MAX).
 * Data is based on actual benchmark runs — not fabricated.
 */
export function seedDemoTraces(): void {
  try {
    const now = Date.now();

    // Trace 1: Business overview (data_analysis → analyze_business_data)
    const t1 = traceCollector.startTrace('demo_seed_1');
    t1.startTime = now - 120000; // 2 min ago
    t1.isSeedData = true;
    t1.routeResult = {
      subagent: 'data_analysis',
      confidence: 1.0,
      routedBy: 'keyword',
      reason: 'Matched keywords: 业务, 概况, overview',
    };
    traceCollector.addEvent('demo_seed_1', {
      timestamp: now - 120000,
      type: 'route',
      subagent: 'data_analysis',
      data: { subagent: 'data_analysis', confidence: 1.0, routedBy: 'keyword', reason: 'Matched keywords: 业务, 概况, overview' },
    });
    traceCollector.addEvent('demo_seed_1', {
      timestamp: now - 118000,
      type: 'tool_call',
      data: { name: 'analyze_business_data', input: { metric: 'overview' } },
    });
    traceCollector.addEvent('demo_seed_1', {
      timestamp: now - 118000,
      type: 'tool_result',
      data: { name: 'analyze_business_data', result: 'Revenue: $6,200 earned, 3 active projects pending, 0 overdue.', durationMs: 3 },
    });
    traceCollector.addEvent('demo_seed_1', {
      timestamp: now - 118000,
      type: 'llm_call',
      subagent: 'data_analysis',
      data: { durationMs: 8980 },
    });
    traceCollector.endTrace('demo_seed_1');
    t1.endTime = now - 110000;

    // Trace 2: Knowledge search (knowledge_rag → search_knowledge_base)
    const t2 = traceCollector.startTrace('demo_seed_2');
    t2.startTime = now - 300000; // 5 min ago
    t2.isSeedData = true;
    t2.routeResult = {
      subagent: 'knowledge_rag',
      confidence: 1.0,
      routedBy: 'keyword',
      reason: 'Matched keywords: 付款, 条款, payment',
    };
    traceCollector.addEvent('demo_seed_2', {
      timestamp: now - 300000,
      type: 'route',
      subagent: 'knowledge_rag',
      data: { subagent: 'knowledge_rag', confidence: 1.0, routedBy: 'keyword', reason: 'Matched keywords: 付款, 条款, payment' },
    });
    traceCollector.addEvent('demo_seed_2', {
      timestamp: now - 298000,
      type: 'tool_call',
      data: { name: 'search_knowledge_base', input: { query: '我的标准付款条款是什么？' } },
    });
    traceCollector.addEvent('demo_seed_2', {
      timestamp: now - 298000,
      type: 'tool_result',
      data: { name: 'search_knowledge_base', result: 'Found: 付款条款 — 50%预付，50%验收后付清，逾期14天加收5%', durationMs: 5 },
    });
    traceCollector.addEvent('demo_seed_2', {
      timestamp: now - 298000,
      type: 'llm_call',
      subagent: 'knowledge_rag',
      data: { durationMs: 7230 },
    });
    traceCollector.endTrace('demo_seed_2');
    t2.endTime = now - 290000;
  } catch {
    /* non-blocking */
  }
}

// ─── ID generation ────────────────────────────────────────────────────────────

let globalCounter = 0;

function genTraceId(): string {
  return `trace_${Date.now()}_${globalCounter++}`;
}

// ─── Convenience functions (defensive / non-blocking) ────────────────────────

/**
 * Start a new trace. Returns the trace id (empty string on failure).
 */
export function startTrace(): string {
  try {
    // Clear seed traces when a real user interaction occurs
    traceCollector.clearSeedTraces();
    const trace = traceCollector.startTrace(genTraceId());
    return trace.id;
  } catch {
    return '';
  }
}

/**
 * Record a FunctionRouter routing decision. Also stamps `routeResult` on the
 * trace envelope for quick access by the list API.
 */
export function addRouteEvent(traceId: string, route: RouteResult): void {
  if (!traceId) return;
  try {
    traceCollector.addEvent(traceId, {
      timestamp: Date.now(),
      type: 'route',
      subagent: route.subagent,
      data: {
        subagent: route.subagent,
        confidence: route.confidence,
        routedBy: route.routedBy,
        reason: route.reason,
      },
    });
    const trace = traceCollector.getTrace(traceId);
    if (trace) trace.routeResult = route;
  } catch {
    /* non-blocking */
  }
}

/**
 * Record the start of a tool invocation (with its input).
 */
export function addToolCallEvent(
  traceId: string,
  name: string,
  input: Record<string, unknown>,
): void {
  if (!traceId) return;
  try {
    traceCollector.addEvent(traceId, {
      timestamp: Date.now(),
      type: 'tool_call',
      data: { name, input },
    });
  } catch {
    /* non-blocking */
  }
}

/**
 * Record the result of a tool invocation, including how long it took.
 */
export function addToolResultEvent(
  traceId: string,
  name: string,
  result: string,
  durationMs: number,
): void {
  if (!traceId) return;
  try {
    traceCollector.addEvent(traceId, {
      timestamp: Date.now(),
      type: 'tool_result',
      data: { name, result, durationMs },
    });
  } catch {
    /* non-blocking */
  }
}

/**
 * Record an LLM call and its total duration (coarse-grained: wraps the whole
 * agentic stream). Optional subagent stamp for cross-referencing.
 */
export function addLlmCallEvent(
  traceId: string,
  durationMs: number,
  subagent?: SubagentId,
): void {
  if (!traceId) return;
  try {
    traceCollector.addEvent(traceId, {
      timestamp: Date.now(),
      type: 'llm_call',
      subagent,
      data: { durationMs },
    });
  } catch {
    /* non-blocking */
  }
}

/**
 * Record an error that occurred during the agent turn.
 */
export function addErrorEvent(traceId: string, error: string): void {
  if (!traceId) return;
  try {
    traceCollector.addEvent(traceId, {
      timestamp: Date.now(),
      type: 'error',
      data: { error },
    });
  } catch {
    /* non-blocking */
  }
}

/**
 * Mark a trace as ended. Safe to call multiple times.
 */
export function endTrace(traceId: string): void {
  if (!traceId) return;
  try {
    traceCollector.endTrace(traceId);
  } catch {
    /* non-blocking */
  }
}
