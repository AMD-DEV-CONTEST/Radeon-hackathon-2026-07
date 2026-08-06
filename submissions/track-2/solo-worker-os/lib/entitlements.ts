import type { SupabaseClient } from '@supabase/supabase-js';

export type Plan = 'free' | 'pro' | 'team';

/** Quotas advertised on /pricing. Kept here so the page and the enforcement
 *  cannot drift apart. */
export const PLAN_LIMITS: Record<Plan, { projects: number; chatPerDay: number }> = {
  free: { projects: 10, chatPerDay: 30 },
  pro:  { projects: Number.POSITIVE_INFINITY, chatPerDay: 500 },
  team: { projects: Number.POSITIVE_INFINITY, chatPerDay: 2000 },
};

/** Statuses Stripe considers a live, paid subscription. */
const ACTIVE_STATUSES = ['active', 'trialing'];

export class QuotaExceededError extends Error {
  constructor(public readonly plan: Plan, message: string) {
    super(message);
    this.name = 'QuotaExceededError';
  }
}

/**
 * Resolve the current user's plan.
 *
 * A missing subscription row means Free — the only writer of this table is the
 * Stripe webhook, so a plan can never be self-assigned by the client.
 */
export async function getPlan(supabase: SupabaseClient): Promise<Plan> {
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') return 'free';

  const { data: authData } = await supabase.auth.getUser().catch(() => ({
    data: { user: null },
  }));
  const userId = authData?.user?.id;
  if (!userId) return 'free';

  const { data } = await supabase
    .from('subscriptions')
    .select('plan, status')
    .eq('user_id', userId)
    .in('status', ACTIVE_STATUSES)
    .maybeSingle();

  const plan = data?.plan;
  return plan === 'pro' || plan === 'team' ? plan : 'free';
}

/**
 * Throw when the caller has no project quota left.
 *
 * Called before inserting a project so an over-quota user is told to upgrade
 * rather than silently getting more than they paid for.
 */
export async function assertProjectQuota(supabase: SupabaseClient): Promise<void> {
  // Demo mode has no accounts and no billing, so capping projects would only
  // cripple the walkthrough. Left explicit rather than relying on the mock
  // client silently returning no count.
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') return;

  const plan = await getPlan(supabase);
  const limit = PLAN_LIMITS[plan].projects;
  if (!Number.isFinite(limit)) return;

  // Resolve user ID to count only the current user's projects
  const { data: authData } = await supabase.auth.getUser().catch(() => ({
    data: { user: null },
  }));
  const userId = authData?.user?.id;
  if (!userId) return; // Cannot enforce quota without a user context

  const { count, error } = await supabase
    .from('projects')
    .select('id', { count: 'exact', head: true })
    .eq('user_id', userId);

  // Fail open on a broken count: blocking real work over an infrastructure
  // hiccup is worse than briefly allowing one project past the line.
  if (error) return;

  if ((count ?? 0) >= limit) {
    throw new QuotaExceededError(
      plan,
      `The ${plan} plan is limited to ${limit} projects and you already have ${count}. ` +
      `Upgrade at /pricing to add more.`,
    );
  }
}
