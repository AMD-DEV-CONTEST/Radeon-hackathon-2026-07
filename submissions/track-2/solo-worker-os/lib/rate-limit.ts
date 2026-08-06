import type { SupabaseClient } from '@supabase/supabase-js';
import { PLAN_LIMITS, getPlan } from './entitlements';

/**
 * Chat rate limiting.
 *
 * Two layers:
 *   1. A short burst limit per identity, held in process memory.
 *   2. A per-user daily cap, counted in Postgres.
 *
 * The daily cap is the one that bounds spend, and it deliberately does NOT live
 * in memory: a serverless deployment runs N instances each with their own Map,
 * so an in-memory "30/day" is really "30 per instance per day". Every chat turn
 * can fan out into several LLM calls, so an ineffective cap is a billing hole.
 *
 * The burst limit stays in memory on purpose — it only needs to stop a single
 * client hammering a single instance, and being approximate there is fine.
 */

const BURST_LIMIT = 10;
const BURST_WINDOW_MS = 60_000;

/** Demo mode has no accounts, so the daily cap is keyed by IP instead. */
const DEMO_DAILY_LIMIT = Number(process.env.DEMO_CHAT_PER_DAY ?? 20);

type Entry = { count: number; resetAt: number };
const burstMap = new Map<string, Entry>();
const demoDailyMap = new Map<string, Entry>();

// Bound the maps rather than letting them grow with unique IPs.
setInterval(() => {
  const now = Date.now();
  for (const map of [burstMap, demoDailyMap]) {
    for (const [key, entry] of map) {
      if (now >= entry.resetAt) map.delete(key);
    }
  }
}, 120_000).unref();

function hit(map: Map<string, Entry>, key: string, limit: number, windowMs: number) {
  const now = Date.now();
  const entry = map.get(key);
  if (!entry || now >= entry.resetAt) {
    map.set(key, { count: 1, resetAt: now + windowMs });
    return { allowed: true, retryAfterMs: 0 };
  }
  if (entry.count >= limit) {
    return { allowed: false, retryAfterMs: entry.resetAt - now };
  }
  entry.count += 1;
  return { allowed: true, retryAfterMs: 0 };
}

export interface RateLimitResult {
  ok: boolean;
  reason?: 'burst' | 'daily_quota' | 'store_unavailable';
  message?: string;
  retryAfterMs?: number;
  remaining?: number;
}

export function checkBurst(identity: string): RateLimitResult {
  const { allowed, retryAfterMs } = hit(burstMap, identity, BURST_LIMIT, BURST_WINDOW_MS);
  if (allowed) return { ok: true };
  return {
    ok: false,
    reason: 'burst',
    message: 'Too many messages in a short time. Please wait a moment.',
    retryAfterMs,
  };
}

/**
 * Consume one unit of the daily chat quota.
 *
 * Authenticated: atomic increment in Postgres, limit derived from the plan.
 * Demo mode: per-IP memory counter (see the production guard below).
 */
export async function consumeChatQuota(
  supabase: SupabaseClient,
  identity: string,
): Promise<RateLimitResult> {
  const isDemo = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

  if (isDemo) {
    // A publicly reachable demo has no login, so anyone can spend our tokens.
    // The memory counter cannot bound that across instances, so refuse to run
    // an unmetered public demo instead of discovering it on the invoice.
    if (
      process.env.NODE_ENV === 'production' &&
      process.env.ALLOW_UNMETERED_DEMO !== 'true'
    ) {
      console.error(
        '[rate-limit] Demo mode is deployed to production without a shared quota store. ' +
        'Each instance counts separately, so DEMO_CHAT_PER_DAY cannot bound LLM spend. ' +
        'Set NEXT_PUBLIC_DEMO_MODE=false and configure Supabase, or set ' +
        'ALLOW_UNMETERED_DEMO=true to accept the risk (single-instance hosts only).',
      );
      return {
        ok: false,
        reason: 'store_unavailable',
        message: 'This demo is not configured for public use. Please contact the operator.',
      };
    }

    const { allowed, retryAfterMs } = hit(
      demoDailyMap, `demo:${identity}`, DEMO_DAILY_LIMIT, 86_400_000,
    );
    return allowed
      ? { ok: true }
      : {
          ok: false,
          reason: 'daily_quota',
          message: `Demo limit of ${DEMO_DAILY_LIMIT} messages per day reached. Try again tomorrow.`,
          retryAfterMs,
        };
  }

  const plan = await getPlan(supabase);
  const limit = PLAN_LIMITS[plan].chatPerDay;

  const { data, error } = await supabase
    .rpc('increment_usage', { p_kind: 'chat', p_limit: limit })
    .maybeSingle<{ allowed: boolean; current_count: number }>();

  // Fail open on infrastructure errors: a database hiccup should not lock every
  // user out of the product. The burst limit still applies.
  if (error || !data) {
    if (error) console.warn('[rate-limit] increment_usage failed, allowing request:', error.message);
    return { ok: true };
  }

  if (!data.allowed) {
    return {
      ok: false,
      reason: 'daily_quota',
      message:
        `You have used all ${limit} messages for today on the ${plan} plan. ` +
        (plan === 'free' ? 'Upgrade at /pricing for more.' : 'Resets at 00:00 UTC.'),
      remaining: 0,
    };
  }

  return { ok: true, remaining: Math.max(0, limit - data.current_count) };
}
