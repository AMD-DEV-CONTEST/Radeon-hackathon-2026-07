import { NextResponse } from 'next/server';
import { createServerClient } from '@/lib/supabase-server';
import { generateBenchmarkReport } from '@/lib/analytics/aggregator';
import { validateApiKey, toFreeTierSummary } from '@/lib/api-auth';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * GET /api/analytics
 * Returns anonymous aggregated business benchmark data.
 *
 * All data is anonymized — no client names, user IDs, or project-specific details.
 * Useful for industry benchmark reports and ROI analysis.
 *
 * Authentication: Requires a valid API key via Authorization: Bearer sk_live_...
 * or X-API-Key header.
 *
 * Query params:
 * - months: lookback period in months (default: 3, max: 12)
 */
export async function GET(req: Request) {
  // Authenticate the request
  const auth = await validateApiKey(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  try {
    const { searchParams } = new URL(req.url);
    const months = Math.min(Math.max(parseInt(searchParams.get('months') ?? '3', 10) || 3, 1), 12);

    const supabase = createServerClient();
    const report = await generateBenchmarkReport(supabase, months);

    // Free tier gets summary-only response
    if (auth.key?.tier === 'free') {
      return NextResponse.json(toFreeTierSummary(report));
    }

    return NextResponse.json({ ...report, tier: auth.key?.tier ?? 'pro' });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Unknown error';
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
