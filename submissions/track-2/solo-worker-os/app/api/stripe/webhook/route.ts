import { NextRequest, NextResponse } from 'next/server';
import type Stripe from 'stripe';
import { createServiceClient } from '@/lib/supabase-service';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Stripe webhook — the only writer of the `subscriptions` table.
 *
 * Keeping grants here (rather than on the checkout redirect) means a user who
 * closes the browser mid-redirect still gets what they paid for, and a user who
 * forges a success URL gets nothing.
 *
 * Configure the endpoint as https://<host>/api/stripe/webhook and subscribe to:
 *   checkout.session.completed
 *   customer.subscription.updated
 *   customer.subscription.deleted
 */

const PRICE_TO_PLAN: Record<string, 'pro' | 'team'> = {};

function planForPrice(priceId: string | undefined): 'pro' | 'team' {
  if (!priceId) return 'pro';
  if (Object.keys(PRICE_TO_PLAN).length === 0) {
    if (priceId === process.env.STRIPE_TEAM_PRICE_ID) return 'team';
    return 'pro';
  }
  return PRICE_TO_PLAN[priceId] ?? 'pro';
}

export async function POST(req: NextRequest) {
  const secretKey = process.env.STRIPE_SECRET_KEY;
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!secretKey || !webhookSecret) {
    return NextResponse.json({ error: 'Billing is not configured' }, { status: 503 });
  }

  const signature = req.headers.get('stripe-signature');
  if (!signature) {
    return NextResponse.json({ error: 'Missing stripe-signature header' }, { status: 400 });
  }

  const StripeCtor = (await import('stripe')).default;
  const stripe = new StripeCtor(secretKey);

  let event: Stripe.Event;
  try {
    // Signature verification needs the exact raw body, not a parsed object.
    const rawBody = await req.text();
    event = stripe.webhooks.constructEvent(rawBody, signature, webhookSecret);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: `Signature verification failed: ${message}` }, { status: 400 });
  }

  const supabase = createServiceClient();

  try {
    switch (event.type) {
      case 'checkout.session.completed': {
        const session = event.data.object as Stripe.Checkout.Session;
        const userId = session.client_reference_id;
        if (!userId) break;

        const subscriptionId =
          typeof session.subscription === 'string'
            ? session.subscription
            : session.subscription?.id;

        // The session does not carry the price, so read it off the subscription.
        let priceId: string | undefined;
        let status = 'active';
        let periodEnd: string | null = null;

        if (subscriptionId) {
          const sub = await stripe.subscriptions.retrieve(subscriptionId);
          priceId = sub.items.data[0]?.price?.id;
          status = sub.status;
          const end = (sub as unknown as { current_period_end?: number }).current_period_end;
          periodEnd = end ? new Date(end * 1000).toISOString() : null;
        }

        await supabase.from('subscriptions').upsert(
          {
            user_id: userId,
            plan: planForPrice(priceId),
            status,
            stripe_customer_id:
              typeof session.customer === 'string' ? session.customer : session.customer?.id ?? null,
            stripe_subscription_id: subscriptionId ?? null,
            current_period_end: periodEnd,
            updated_at: new Date().toISOString(),
          },
          { onConflict: 'user_id' },
        );
        break;
      }

      case 'customer.subscription.updated':
      case 'customer.subscription.deleted': {
        const sub = event.data.object as Stripe.Subscription;
        const customerId = typeof sub.customer === 'string' ? sub.customer : sub.customer?.id;
        if (!customerId) break;

        const canceled = event.type === 'customer.subscription.deleted';
        const status = canceled ? 'canceled' : sub.status;
        const active = !canceled && (status === 'active' || status === 'trialing');
        const end = (sub as unknown as { current_period_end?: number }).current_period_end;

        await supabase
          .from('subscriptions')
          .update({
            plan: active ? planForPrice(sub.items.data[0]?.price?.id) : 'free',
            status,
            current_period_end: end ? new Date(end * 1000).toISOString() : null,
            updated_at: new Date().toISOString(),
          })
          .eq('stripe_customer_id', customerId);
        break;
      }

      default:
        break;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    // Returning 500 makes Stripe retry, which is what we want for a transient
    // database failure — the grant must not be silently dropped.
    return NextResponse.json({ error: message }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}
