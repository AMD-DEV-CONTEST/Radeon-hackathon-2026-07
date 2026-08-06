/**
 * External API authentication — API key validation for the benchmark data API.
 *
 * Keys use the format: sk_live_<32 hex chars>
 * We store only the SHA-256 hash; the plaintext is shown once at creation time.
 *
 * Tiers:
 *   free       — summary metrics only (totals, averages)
 *   pro        — full benchmark report (distributions, monthly revenue, etc.)
 *   enterprise — full report + custom lookback periods (up to 12 months)
 */

import { createHash, randomBytes } from 'crypto';
import { createServerClient } from '@/lib/supabase-server';

export type ApiTier = 'free' | 'pro' | 'enterprise';

export interface ApiKeyRecord {
  id: string;
  tier: ApiTier;
  label: string;
  dailyLimit: number;
}

export interface AuthResult {
  ok: boolean;
  status: number;
  error?: string;
  key?: ApiKeyRecord;
}

const KEY_PREFIX = 'sk_live_';
const KEY_LENGTH = 32; // hex chars after prefix

/** Generate a new API key (plaintext shown once to the user). */
export function generateApiKey(): { plaintext: string; hash: string; prefix: string } {
  const hex = randomBytes(KEY_LENGTH).toString('hex');
  const plaintext = `${KEY_PREFIX}${hex}`;
  const hash = hashKey(plaintext);
  const prefix = plaintext.slice(0, 12);
  return { plaintext, hash, prefix };
}

/** Hash a key for storage. Uses SHA-256. */
export function hashKey(plaintext: string): string {
  return createHash('sha256').update(plaintext).digest('hex');
}

/** Extract and validate the API key from request headers. */
export function extractApiKey(req: Request): string | null {
  // Support both Bearer token and X-API-Key header
  const authHeader = req.headers.get('authorization');
  if (authHeader?.startsWith('Bearer ')) {
    const key = authHeader.slice(7).trim();
    if (key.startsWith(KEY_PREFIX)) return key;
  }
  const xKey = req.headers.get('x-api-key');
  if (xKey?.startsWith(KEY_PREFIX)) return xKey.trim();
  return null;
}

/**
 * Validate an API key against the database and record usage.
 * Returns the key record if valid.
 */
export async function validateApiKey(req: Request): Promise<AuthResult> {
  const rawKey = extractApiKey(req);
  if (!rawKey) {
    return { ok: false, status: 401, error: 'Missing or invalid API key. Use Authorization: Bearer sk_live_...' };
  }

  const hash = hashKey(rawKey);
  const supabase = createServerClient();

  // Look up the key
  const { data: keyRow, error } = await supabase
    .from('api_keys')
    .select('id, tier, label, daily_limit, requests_today, last_used_at, revoked_at')
    .eq('key_hash', hash)
    .maybeSingle();

  if (error || !keyRow) {
    return { ok: false, status: 401, error: 'Invalid API key.' };
  }

  if (keyRow.revoked_at) {
    return { ok: false, status: 403, error: 'This API key has been revoked.' };
  }

  // Check daily rate limit
  const today = new Date().toISOString().slice(0, 10);
  const lastUsedDate = keyRow.last_used_at ? new Date(keyRow.last_used_at).toISOString().slice(0, 10) : null;
  const isSameDay = lastUsedDate === today;

  if (isSameDay && keyRow.requests_today >= keyRow.daily_limit) {
    return {
      ok: false,
      status: 429,
      error: `Daily limit (${keyRow.daily_limit}) exceeded. Resets at 00:00 UTC.`,
    };
  }

  // Increment usage (or reset for new day)
  const newCount = isSameDay ? keyRow.requests_today + 1 : 1;
  await supabase
    .from('api_keys')
    .update({ requests_today: newCount, last_used_at: new Date().toISOString() })
    .eq('id', keyRow.id);

  return {
    ok: true,
    status: 200,
    key: {
      id: keyRow.id,
      tier: keyRow.tier as ApiTier,
      label: keyRow.label,
      dailyLimit: keyRow.daily_limit,
    },
  };
}

/**
 * Reduce a full benchmark report to a free-tier summary.
 * Free tier sees only aggregate metrics — no distributions, no monthly breakdowns.
 */
export function toFreeTierSummary(report: {
  generatedAt: string;
  period: string;
  metrics: {
    totalProjects: number;
    activeProjects: number;
    completedProjects: number;
    paidProjects: number;
    averageBudget: number;
    medianBudget: number;
    averageProjectDuration: number;
    contractSigningRate: number;
    invoicePaymentRate: number;
    averagePaymentCycle: number;
  };
}) {
  return {
    generatedAt: report.generatedAt,
    period: report.period,
    tier: 'free',
    metrics: report.metrics,
    upgradeUrl: '/pricing',
    message: 'Upgrade to Pro for full distribution data, monthly revenue trends, and tool usage rankings.',
  };
}
