import { NextResponse } from 'next/server';
import { createServerClient } from '@/lib/supabase-server';
import { generateApiKey } from '@/lib/api-auth';
import { z } from 'zod';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// ─── Schemas ──────────────────────────────────────────────────────────────────
const CreateKeySchema = z.object({
  label: z.string().min(1).max(60).default('Default'),
  tier: z.enum(['free', 'pro', 'enterprise']).default('free'),
  daily_limit: z.number().int().min(10).max(10000).optional(),
});

const TIER_DEFAULTS: Record<string, number> = {
  free: 100,
  pro: 1000,
  enterprise: 10000,
};

/**
 * GET /api/api-keys
 * List the current user's API keys (without plaintext — shown once at creation).
 */
export async function GET() {
  const supabase = createServerClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { data, error } = await supabase
    .from('api_keys')
    .select('id, key_prefix, label, tier, daily_limit, requests_today, last_used_at, created_at, revoked_at')
    .eq('user_id', userData.user.id)
    .order('created_at', { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ keys: data ?? [] });
}

/**
 * POST /api/api-keys
 * Create a new API key. The plaintext key is returned ONLY in this response —
 * it cannot be retrieved again.
 */
export async function POST(req: Request) {
  const supabase = createServerClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  let body: z.infer<typeof CreateKeySchema>;
  try {
    const json = await req.json();
    body = CreateKeySchema.parse(json);
  } catch {
    // Allow empty body → defaults
    body = CreateKeySchema.parse({});
  }

  const { plaintext, hash, prefix } = generateApiKey();
  const dailyLimit = body.daily_limit ?? TIER_DEFAULTS[body.tier];

  const { data, error } = await supabase
    .from('api_keys')
    .insert({
      user_id: userData.user.id,
      key_hash: hash,
      key_prefix: prefix,
      label: body.label,
      tier: body.tier,
      daily_limit: dailyLimit,
      requests_today: 0,
    })
    .select('id, key_prefix, label, tier, daily_limit, created_at')
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    ...data,
    // Plaintext key — shown ONCE. The UI must warn the user to save it.
    api_key: plaintext,
    warning: 'Save this key securely. It will not be shown again.',
  }, { status: 201 });
}

/**
 * DELETE /api/api-keys?id=<key_id>
 * Revoke an API key (soft delete — sets revoked_at, does not hard-delete).
 */
export async function DELETE(req: Request) {
  const supabase = createServerClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const keyId = searchParams.get('id');
  if (!keyId) {
    return NextResponse.json({ error: 'Missing id parameter' }, { status: 400 });
  }

  // RLS ensures user can only revoke their own keys
  const { error } = await supabase
    .from('api_keys')
    .update({ revoked_at: new Date().toISOString() })
    .eq('id', keyId)
    .eq('user_id', userData.user.id)
    .is('revoked_at', null);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, message: 'API key revoked.' });
}
