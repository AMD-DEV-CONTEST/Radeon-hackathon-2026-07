// ============================================================================
// Unified API Response format + idempotency helper
// ============================================================================

import { NextResponse } from "next/server";
import { createCorrelationId } from "./correlation";

export interface ApiSuccess<T = unknown> {
  success: true;
  data: T;
  trace_id: string;
}

export interface ApiError {
  success: false;
  error: string;
  code: string;
  trace_id: string;
}

export function apiOk<T extends Record<string, unknown>>(data: T, status = 200): NextResponse<T & { trace_id: string }> {
  const traceId = createCorrelationId();
  return NextResponse.json({ ...data, trace_id: traceId } as T & { trace_id: string }, { status });
}

export function apiErr(error: string, code: string, status = 500): NextResponse<ApiError> {
  const traceId = createCorrelationId("err");
  return NextResponse.json({ success: false, error, code, trace_id: traceId }, { status });
}

// Idempotency: in-memory store for POST/PUT idempotency keys
const idempotencyStore = new Map<string, { response: unknown; ts: number }>();
const IDEMPOTENCY_TTL = 1000 * 60 * 60; // 1 hour

export function getIdempotencyResult(key: string): unknown | null {
  const entry = idempotencyStore.get(key);
  if (!entry) return null;
  if (Date.now() - entry.ts > IDEMPOTENCY_TTL) {
    idempotencyStore.delete(key);
    return null;
  }
  return entry.response;
}

export function setIdempotencyResult(key: string, response: unknown) {
  // Keep store bounded
  if (idempotencyStore.size > 2000) {
    const firstKey = idempotencyStore.keys().next().value;
    if (firstKey) idempotencyStore.delete(firstKey);
  }
  idempotencyStore.set(key, { response, ts: Date.now() });
}

export function extractIdempotencyKey(request: Request): string | null {
  return request.headers.get("x-idempotency-key") || null;
}
