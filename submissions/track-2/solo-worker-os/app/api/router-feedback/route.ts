import { NextRequest, NextResponse } from 'next/server';
import type { SubagentId } from '@/lib/agent/types';
import {
  submitFeedback,
  getRouterLearningStats,
  loadPersistedWeights,
} from '@/lib/agent/router-learning';
import { createSupabaseServerClient } from '@/lib/supabase-server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// ─── Validation ──────────────────────────────────────────────────────────────

/** Every SubagentId the type system allows (includes 'blockchain'). */
const VALID_SUBAGENTS: SubagentId[] = [
  'general',
  'knowledge_rag',
  'data_analysis',
  'writing_assistant',
  'blockchain',
  'quick_chat',
];

function isSubagentId(value: unknown): value is SubagentId {
  return typeof value === 'string' && VALID_SUBAGENTS.includes(value as SubagentId);
}

/**
 * Get the authenticated user's ID (or null in demo mode / anonymous).
 * This is used to scope persisted router weights to the current user.
 */
async function getUserId(): Promise<string | null> {
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') return null;
  try {
    const supabase = createSupabaseServerClient();
    const { data: { user } } = await supabase.auth.getUser();
    return user?.id ?? null;
  } catch {
    return null;
  }
}

// ─── POST: submit a routing correction ───────────────────────────────────────

interface FeedbackRequestBody {
  message?: string;
  correctSubagent?: string;
  originalSubagent?: string;
}

/**
 * Record a user correction for a routing decision.
 *
 * Body:
 *   - message          : the original user message that was routed
 *   - correctSubagent  : the subagent that *should* have handled it
 *   - originalSubagent : the subagent the router actually picked
 *
 * On success the weight map is refreshed synchronously, so the very next
 * `routeMessageWithLearning()` call benefits from the correction. The
 * adjusted weights are also asynchronously persisted to the `router_weights`
 * table so they survive server restarts.
 */
export async function POST(req: NextRequest) {
  let body: FeedbackRequestBody;
  try {
    body = (await req.json()) as FeedbackRequestBody;
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON body' },
      { status: 400 },
    );
  }

  const { message, correctSubagent, originalSubagent } = body;

  if (!message || typeof message !== 'string' || !message.trim()) {
    return NextResponse.json(
      { error: '`message` is required and must be a non-empty string' },
      { status: 400 },
    );
  }
  if (!isSubagentId(correctSubagent)) {
    return NextResponse.json(
      {
        error: `\`correctSubagent\` is invalid; expected one of: ${VALID_SUBAGENTS.join(', ')}`,
      },
      { status: 400 },
    );
  }
  if (!isSubagentId(originalSubagent)) {
    return NextResponse.json(
      {
        error: `\`originalSubagent\` is invalid; expected one of: ${VALID_SUBAGENTS.join(', ')}`,
      },
      { status: 400 },
    );
  }

  try {
    // Ensure persisted weights are loaded before applying new feedback
    await loadPersistedWeights();

    const userId = await getUserId();
    const record = submitFeedback(
      message.trim(),
      correctSubagent,
      originalSubagent,
      userId,
    );
    const stats = getRouterLearningStats(0);
    return NextResponse.json(
      {
        feedback: record,
        correctionRate: stats.correctionRate,
        adjustmentCount: stats.adjustmentCount,
      },
      { status: 201 },
    );
  } catch {
    return NextResponse.json(
      { error: 'Failed to record feedback' },
      { status: 500 },
    );
  }
}

// ─── GET: weight-adjustment statistics ───────────────────────────────────────

/**
 * Return the current self-learning snapshot:
 *   - feedbackCount       : total corrections stored
 *   - correctionRate      : { total, corrected, rate }
 *   - adjustmentCount     : number of learned (subagent, keyword) pairs
 *   - adjustments         : full list of WeightAdjustment entries
 *   - recentFeedback      : most recent feedback records (default 50)
 *
 * Optional query param `?limit=N` caps the recentFeedback payload.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const rawLimit = searchParams.get('limit');
  let limit = 50;
  if (rawLimit) {
    const parsed = Number.parseInt(rawLimit, 10);
    if (Number.isFinite(parsed) && parsed >= 0) {
      limit = Math.min(parsed, 1000);
    }
  }

  // Ensure persisted weights are loaded before reporting stats
  await loadPersistedWeights();

  const stats = getRouterLearningStats(limit);
  return NextResponse.json(stats);
}
