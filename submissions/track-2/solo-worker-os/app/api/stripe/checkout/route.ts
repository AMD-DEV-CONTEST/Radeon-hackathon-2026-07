import { NextRequest, NextResponse } from 'next/server';
import { createSupabaseServerClient } from '@/lib/supabase-server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const PLANS = ['pro', 'team'] as const;
type PlanId = (typeof PLANS)[number];

function priceIdFor(plan: PlanId): string | undefined {
  return plan === 'team' ? process.env.STRIPE_TEAM_PRICE_ID : process.env.STRIPE_PRO_PRICE_ID;
}

export async function GET(req: NextRequest) {
  const planId = (new URL(req.url).searchParams.get('plan') ?? 'pro') as PlanId;
  if (!PLANS.includes(planId)) {
    return NextResponse.json({ error: 'Invalid plan' }, { status: 400 });
  }

  const secretKey = process.env.STRIPE_SECRET_KEY;
  const priceId = priceIdFor(planId);
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

  // Without a webhook secret nothing can grant the plan after payment, so taking
  // money here would be charging for something the app cannot deliver.
  if (!secretKey || !priceId || !webhookSecret) {
    const url = new URL('/pricing', req.url);
    url.searchParams.set('status', 'billing_unavailable');
    return NextResponse.redirect(url);
  }

  // The subscription has to be attached to a user, otherwise the webhook has no
  // one to grant it to.
  const supabase = createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser().catch(() => ({
    data: { user: null },
  }));

  if (!user) {
    const url = new URL('/login', req.url);
    url.searchParams.set('next', `/api/stripe/checkout?plan=${planId}`);
    return NextResponse.redirect(url);
  }

  try {
    const Stripe = (await import('stripe')).default;
    const stripe = new Stripe(secretKey);

    const session = await stripe.checkout.sessions.create({
      mode: 'subscription',
      line_items: [{ price: priceId, quantity: 1 }],
      client_reference_id: user.id,
      customer_email: user.email ?? undefined,
      success_url: `${req.nextUrl.origin}/dashboard?upgrade=${planId}&status=success`,
      cancel_url: `${req.nextUrl.origin}/pricing?status=cancelled`,
      metadata: { plan: planId, user_id: user.id },
    });

    if (!session.url) {
      return NextResponse.json({ error: 'Failed to create checkout session' }, { status: 500 });
    }
    return NextResponse.redirect(session.url);
  } catch {
    const url = new URL('/pricing', req.url);
    url.searchParams.set('status', 'error');
    return NextResponse.redirect(url);
  }
}
