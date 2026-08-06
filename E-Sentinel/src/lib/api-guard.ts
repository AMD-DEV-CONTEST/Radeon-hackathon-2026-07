// ============================================================================
// API security guard (adapted from rag-ai-agent for qa-system)
// Input validation, rate limiting, spam detection, CORS for public endpoints.
// All fail-soft when threshold not met. Integrates with existing correlation, audit, api-response.
// Server-only.
// ============================================================================

import { NextResponse } from "next/server";
import { createCorrelationId } from "@/lib/correlation";
import { supabaseAdmin } from "@/lib/supabase";

// ── Constants ──

const MAX_CONVERSATION_LENGTH = 50000; // for evaluate, etc.
const MAX_MESSAGE_LENGTH = 4000;
const RATE_WINDOW_MS = 60_000;
const RATE_MAX_REQUESTS = 120;
const SPAM_REPEAT_THRESHOLD = 0.85;
const SPAM_URL_THRESHOLD = 5;

// ── In-memory rate store (dev only; replace with Redis in production) ──
// Periodic cleanup: evict entries older than RATE_WINDOW_MS every 64 checks.

const rateStore = new Map<string, { count: number; windowStart: number }>();
let cleanupCounter = 0;

function evictStaleRateEntries(): void {
  const cutoff = Date.now() - RATE_WINDOW_MS;
  for (const [ip, entry] of rateStore) {
    if (entry.windowStart < cutoff) rateStore.delete(ip);
  }
}

function getClientIp(request: Request): string {
  const xff = request.headers.get("x-forwarded-for");
  if (xff) {
    // Take last segment (closest to server, added by trusted proxy)
    const segments = xff.split(",").map((s) => s.trim()).filter(Boolean);
    if (segments.length > 0) return segments[segments.length - 1];
  }
  return request.headers.get("x-real-ip")?.trim() || "127.0.0.1";
}

// ── CORS ──

export function corsHeaders(request: Request): Record<string, string> {
  const origin = request.headers.get("origin") || "";
  const allowedOrigins = [
    process.env.NEXT_PUBLIC_APP_URL || "https://qa-system.example.com",
    "http://localhost:3000",
    "http://localhost:3001",
  ];

  const allowOrigin = allowedOrigins.includes(origin) ? origin : allowedOrigins[0];

  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key",
    "Access-Control-Max-Age": "86400",
  };
}

export function handleCors(request: Request): NextResponse | null {
  if (request.method === "OPTIONS") {
    return NextResponse.json(null, {
      status: 204,
      headers: corsHeaders(request),
    });
  }
  return null;
}

// ── Rate limiting ──

export function checkRateLimit(request: Request): { ok: true } | { ok: false; error: NextResponse } {
  const ip = getClientIp(request);
  const now = Date.now();

  cleanupCounter = (cleanupCounter + 1) % 64;
  if (cleanupCounter === 0) evictStaleRateEntries();

  const entry = rateStore.get(ip);

  if (!entry || (now - entry.windowStart) > RATE_WINDOW_MS) {
    rateStore.set(ip, { count: 1, windowStart: now });
    return { ok: true };
  }

  entry.count += 1;

  if (entry.count > RATE_MAX_REQUESTS) {
    return {
      ok: false,
      error: NextResponse.json(
        { error: "请求过于频繁，请稍后再试。", correlation_id: createCorrelationId() },
        { status: 429, headers: { "Retry-After": "60" } },
      ),
    };
  }

  return { ok: true };
}

// ── Input validation ──

export type ValidationResult =
  | { ok: true }
  | { ok: false; error: NextResponse };

export function checkConversationLength(conversation: unknown): ValidationResult {
  if (typeof conversation !== "string") {
    return { ok: false, error: NextResponse.json({ error: "conversation 必须是文本。" }, { status: 400 }) };
  }
  if (conversation.length > MAX_CONVERSATION_LENGTH) {
    return { ok: false, error: NextResponse.json({ error: `conversation 不能超过 ${MAX_CONVERSATION_LENGTH} 字符。` }, { status: 400 }) };
  }
  return { ok: true };
}

export function checkMessageLength(message: unknown): ValidationResult {
  if (typeof message !== "string") {
    return { ok: false, error: NextResponse.json({ error: "消息必须是文本。" }, { status: 400 }) };
  }
  if (message.length > MAX_MESSAGE_LENGTH) {
    return { ok: false, error: NextResponse.json({ error: `消息不能超过 ${MAX_MESSAGE_LENGTH} 字。` }, { status: 400 }) };
  }
  return { ok: true };
}

// ── Spam detection ──

export function checkSpam(message: string): ValidationResult {
  if (typeof message !== "string") {
    return { ok: true };
  }

  const repeats = message.match(/(.)\1{5,}/g);
  if (repeats && repeats.some((r) => r.length / message.length > SPAM_REPEAT_THRESHOLD)) {
    return { ok: false, error: NextResponse.json({ error: "消息包含重复内容，请重试。" }, { status: 400 }) };
  }

  const urlCount = (message.match(/https?:\/\/[^\s]+/g) || []).length;
  if (urlCount > SPAM_URL_THRESHOLD) {
    return { ok: false, error: NextResponse.json({ error: "消息包含过多链接。" }, { status: 400 }) };
  }

  return { ok: true };
}

// ── Full guard for public endpoints ──

export function guardPublicEndpoint(request: Request, body: { message?: unknown; conversation?: unknown }): null | NextResponse {
  const cors = handleCors(request);
  if (cors) return cors;

  const rate = checkRateLimit(request);
  if (!rate.ok) return rate.error;

  if (body.message !== undefined) {
    const len = checkMessageLength(body.message);
    if (!len.ok) return len.error;

    const spam = checkSpam(body.message as string);
    if (!spam.ok) return spam.error;
  }

  if (body.conversation !== undefined) {
    const len = checkConversationLength(body.conversation);
    if (!len.ok) return len.error;

    const spam = checkSpam(body.conversation as string);
    if (!spam.ok) return spam.error;
  }

  return null;
}
