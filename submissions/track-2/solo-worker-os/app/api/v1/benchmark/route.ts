import { NextResponse } from 'next/server';
import { createServerClient } from '@/lib/supabase-server';
import { generateBenchmarkReport } from '@/lib/analytics/aggregator';
import { validateApiKey, toFreeTierSummary } from '@/lib/api-auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/benchmark
 *
 * External API endpoint for anonymous business benchmark data.
 * Requires API key via Authorization: Bearer sk_live_... or X-API-Key header.
 *
 * Tiers:
 *   free       — summary metrics only
 *   pro        — full report (distributions, monthly revenue, tool usage)
 *   enterprise — full report + custom lookback up to 12 months
 *
 * Query params:
 *   months  — lookback period (default 3, max 12 for enterprise / 6 for pro)
 *   summary — if true, returns only free-tier summary regardless of key tier
 */
export async function GET(req: Request) {
  // 1. Authenticate
  const auth = await validateApiKey(req);
  if (!auth.ok || !auth.key) {
    return NextResponse.json(
      { error: auth.error ?? 'Unauthorized' },
      { status: auth.status },
    );
  }

  try {
    const { searchParams } = new URL(req.url);
    const requestedMonths = Math.min(
      Math.max(parseInt(searchParams.get('months') ?? '3', 10) || 3, 1),
      12,
    );

    // Tier-based month caps
    const maxMonths = auth.key.tier === 'enterprise' ? 12
      : auth.key.tier === 'pro' ? 6
      : 3;
    const months = Math.min(requestedMonths, maxMonths);

    const summaryOnly = searchParams.get('summary') === 'true'
      || auth.key.tier === 'free';

    // 2. Generate report
    const supabase = createServerClient();
    const report = await generateBenchmarkReport(supabase, months);

    // 3. Tiered response
    if (summaryOnly) {
      return NextResponse.json(toFreeTierSummary(report));
    }

    return NextResponse.json({
      ...report,
      tier: auth.key.tier,
      apiKey: {
        label: auth.key.label,
        dailyLimit: auth.key.dailyLimit,
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Unknown error';
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
