import { NextRequest, NextResponse } from 'next/server';
import { createSupabaseServerClient } from '@/lib/supabase-server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Stripe customer portal — where a subscriber cancels or updates payment details.
 * This is what makes the "cancel anytime" promise on /pricing真实存在.
 */
export async function GET(req: NextRequest) {
  const secretKey = process.env.STRIPE_SECRET_KEY;
  if (!secretKey) {
    return NextResponse.json({ error: 'Billing is not configured' }, { status: 503 });
  }

  const supabase = createSupabaseServerClient();
  const { data: { user } } = await supabase.auth.getUser().catch(() => ({
    data: { user: null },
  }));

  if (!user) {
    const url = new URL('/login', req.url);
    url.searchParams.set('next', '/api/stripe/portal');
    return NextResponse.redirect(url);
  }

  const { data: sub } = await supabase
    .from('subscriptions')
    .select('stripe_customer_id')
    .eq('user_id', user.id)
    .maybeSingle();

  const customerId = sub?.stripe_customer_id;
  if (!customerId) {
    const url = new URL('/pricing', req.url);
    url.searchParams.set('status', 'no_subscription');
    return NextResponse.redirect(url);
  }

  try {
    const Stripe = (await import('stripe')).default;
    const stripe = new Stripe(secretKey);
    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: `${req.nextUrl.origin}/dashboard`,
    });
    return NextResponse.redirect(session.url);
  } catch {
    const url = new URL('/dashboard', req.url);
    url.searchParams.set('status', 'portal_error');
    return NextResponse.redirect(url);
  }
}
