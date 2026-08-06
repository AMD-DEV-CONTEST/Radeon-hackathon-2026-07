import { NextRequest, NextResponse } from 'next/server';
import { traceCollector, seedDemoTraces } from '@/lib/agent/trace';
import type { Trace } from '@/lib/agent/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// Seed demo traces on first API access in demo mode (once per process)
let demoSeeded = false;
function ensureDemoSeeded() {
  if (!demoSeeded && process.env.NEXT_PUBLIC_DEMO_MODE === 'true') {
    demoSeeded = true;
    seedDemoTraces();
  }
}

// ─── Response shapes ─────────────────────────────────────────────────────────

/**
 * Summary row for the list endpoint. Deliberately excludes tool inputs and
 * raw results so the list view never leaks potentially sensitive payload data.
 */
interface TraceSummary {
  id: string;
  startTime: number;
  endTime?: number;
  durationMs?: number;
  subagent?: string;
  routedBy?: string;
  confidence?: number;
  reason?: string;
  toolCallCount: number;
  eventCount: number;
  hasError: boolean;
  isSeedData?: boolean;
}

const MAX_RESULT_PREVIEW = 1000;

function summarize(trace: Trace): TraceSummary {
  const toolCallCount = trace.events.filter((e) => e.type === 'tool_call').length;
  const hasError = trace.events.some((e) => e.type === 'error');
  const durationMs = trace.endTime ? trace.endTime - trace.startTime : undefined;
  return {
    id: trace.id,
    startTime: trace.startTime,
    endTime: trace.endTime,
    durationMs,
    subagent: trace.routeResult?.subagent,
    routedBy: trace.routeResult?.routedBy,
    confidence: trace.routeResult?.confidence,
    reason: trace.routeResult?.reason,
    toolCallCount,
    eventCount: trace.events.length,
    hasError,
    isSeedData: trace.isSeedData,
  };
}

/**
 * Build a sanitised deep-copy of a trace for the detail endpoint.
 * Long tool-result strings are truncated to keep payloads small and to avoid
 * dumping large generated documents (contracts, etc.) into the trace viewer.
 * The stored trace object itself is never mutated.
 */
function sanitizeTrace(trace: Trace) {
  return {
    id: trace.id,
    startTime: trace.startTime,
    endTime: trace.endTime,
    tokenCount: trace.tokenCount,
    routeResult: trace.routeResult,
    events: trace.events.map((e) => {
      const data: Record<string, unknown> = { ...e.data };
      if (typeof data.result === 'string' && data.result.length > MAX_RESULT_PREVIEW) {
        data.result = data.result.slice(0, MAX_RESULT_PREVIEW) + '… [truncated]';
      }
      return {
        timestamp: e.timestamp,
        type: e.type,
        subagent: e.subagent,
        data,
      };
    }),
  };
}

// ─── Route handler ───────────────────────────────────────────────────────────

export async function GET(req: NextRequest) {
  ensureDemoSeeded();
  const { searchParams } = new URL(req.url);
  const id = searchParams.get('id');

  // Single-trace detail
  if (id) {
    const trace = traceCollector.getTrace(id);
    if (!trace) {
      return NextResponse.json(
        { error: 'Trace not found', id },
        { status: 404 },
      );
    }
    return NextResponse.json({ trace: sanitizeTrace(trace) });
  }

  // Recent traces list (no sensitive data)
  const recent = traceCollector.getRecentTraces(20);
  return NextResponse.json({
    traces: recent.map(summarize),
    count: recent.length,
  });
}
