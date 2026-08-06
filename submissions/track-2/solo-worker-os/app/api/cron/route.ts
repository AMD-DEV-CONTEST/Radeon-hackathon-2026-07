import { NextRequest, NextResponse } from 'next/server';
import { createServiceClient } from '@/lib/supabase-service';
import { getAgent } from '@/lib/agent';
import { Resend } from 'resend';
import type { Project } from '@/lib/types';

export const dynamic = 'force-dynamic';

function isAuthorized(req: NextRequest): boolean {
  const secret = process.env.CRON_SECRET;
  if (secret) {
    // Vercel Cron sends Authorization: Bearer <CRON_SECRET>.
    return (
      req.headers.get('x-cron-secret') === secret ||
      req.headers.get('authorization') === `Bearer ${secret}`
    );
  }
  // Open only outside production. This endpoint spends LLM tokens and sends
  // email, so an unsecured public route is a billable denial-of-wallet.
  return process.env.NODE_ENV !== 'production';
}

function getResend(): Resend | null {
  if (!process.env.RESEND_API_KEY) return null;
  return new Resend(process.env.RESEND_API_KEY);
}

async function sendEmail(to: string, subject: string, html: string): Promise<void> {
  const resend = getResend();
  if (!resend) return; // skip if not configured
  await resend.emails.send({
    from: process.env.NOTIFICATION_FROM_EMAIL ?? 'Solo Worker OS <onboarding@resend.dev>',
    to,
    subject,
    html,
  });
}

export async function GET(req: NextRequest) {
  if (!isAuthorized(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const type = new URL(req.url).searchParams.get('type') ?? 'all';
  const results: Record<string, unknown> = {};

  const supabase = createServiceClient();
  const today = new Date().toISOString().slice(0, 10);
  const notifyEmail = process.env.NOTIFICATION_EMAIL;

  // ── 1. Deadline reminders ─────────────────────────────────
  if (type === 'all' || type === 'deadlines') {
    const threeDaysOut = new Date();
    threeDaysOut.setDate(threeDaysOut.getDate() + 3);
    const cutoff = threeDaysOut.toISOString().slice(0, 10);

    const { data: urgentProjects } = await supabase
      .from('projects')
      .select('id, user_id, client_name, project_type, deadline, status, budget, currency')
      .lte('deadline', cutoff)
      .neq('status', 'paid')
      .order('deadline', { ascending: true });

    const projects = (urgentProjects as Project[]) ?? [];
    const created: string[] = [];

    for (const p of projects) {
      const { count } = await supabase
        .from('notifications')
        .select('id', { count: 'exact', head: true })
        .eq('project_id', p.id)
        .eq('type', 'deadline_reminder')
        .gte('created_at', today + 'T00:00:00Z');

      if ((count ?? 0) > 0) continue;

      const daysLeft = Math.ceil(
        (new Date(p.deadline).getTime() - Date.now()) / 86400000
      );
      const isOverdue = daysLeft < 0;

      const title = isOverdue
        ? `OVERDUE: ${p.project_type} for ${p.client_name}`
        : `Due in ${daysLeft}d: ${p.project_type} for ${p.client_name}`;

      const body = isOverdue
        ? `The project "${p.project_type}" for ${p.client_name} was due on ${p.deadline} and is now ${Math.abs(daysLeft)} day(s) overdue. Status: ${p.status}. Budget: ${p.currency} ${p.budget}.`
        : `Deadline approaching: "${p.project_type}" for ${p.client_name} is due on ${p.deadline} (${daysLeft} day(s) left). Status: ${p.status}. Budget: ${p.currency} ${p.budget}.`;

      // user_id must be carried from the project: the RLS policy treats a null
      // user_id as visible to everyone, so an unscoped row leaks one user's
      // client names into every other user's notification feed.
      await supabase.from('notifications').insert({
        type: 'deadline_reminder',
        title,
        body,
        project_id: p.id,
        user_id: p.user_id ?? null,
      });

      if (notifyEmail) {
        await sendEmail(
          notifyEmail,
          `[Solo Worker OS] ${title}`,
          `<p>${body}</p><p><a href="${process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000'}/projects/${p.id}">查看项目</a></p>`
        ).catch(() => {}); // don't fail cron if email fails
      }

      created.push(p.id);
    }

    results.deadlines = { checked: projects.length, created: created.length };
  }

  // ── 2. Weekly report (Mondays or ?type=weekly) ────────────
  if (type === 'weekly' || (type === 'all' && new Date().getDay() === 1)) {
    try {
      const { data: projects } = await supabase
        .from('projects')
        .select('*')
        .order('created_at', { ascending: false });

      const projectList = (projects as Project[]) ?? [];

      // One report per user. Aggregating every user's projects into a single
      // summary would both leak counts across tenants and be meaningless.
      const byUser = new Map<string | null, Project[]>();
      for (const p of projectList) {
        const key = p.user_id ?? null;
        const bucket = byUser.get(key);
        if (bucket) bucket.push(p);
        else byUser.set(key, [p]);
      }

      const agent = await getAgent();
      let generated = 0;

      for (const [userId, userProjects] of byUser) {
        const active   = userProjects.filter((p) => p.status === 'active').length;
        const invoiced = userProjects.filter((p) => p.status === 'invoiced').length;
        const paid     = userProjects.filter((p) => p.status === 'paid').length;
        const overdue  = userProjects.filter(
          (p) => p.status !== 'paid' && p.deadline < today
        ).length;

        const prompt = `You are a business analyst assistant. Write a concise weekly business summary for a solo freelancer.

Current data:
- Active projects: ${active}
- Awaiting payment (invoiced): ${invoiced}
- Completed & paid this period: ${paid}
- Overdue projects: ${overdue}
- Total projects: ${userProjects.length}

Write a 3-4 sentence summary covering: overall health, immediate priorities, and one concrete recommendation. Be direct and actionable. No markdown headers, just plain paragraphs.`;

        const reportText = await agent.runStream({
          system: 'You are a concise business analyst. Respond in plain text, no markdown.',
          messages: [{ role: 'user', content: prompt }],
          tools: [],
          executeTool: async (_name: string, _input: Record<string, unknown>) => ({ toolResult: '', clientSummary: '' }),
          callbacks: { onText: () => {}, onTool: () => {} },
        });

        await supabase.from('notifications').insert({
          type: 'weekly_report',
          title: `Weekly Business Summary — ${today}`,
          body: reportText,
          project_id: null,
          user_id: userId,
        });

        if (notifyEmail) {
          await sendEmail(
            notifyEmail,
            `[Solo Worker OS] Weekly Report — ${today}`,
            `<p>${reportText.replace(/\n/g, '<br>')}</p>`
          ).catch(() => {});
        }

        generated += 1;
      }

      results.weekly_report = { generated };
    } catch (e) {
      results.weekly_report = { error: String(e) };
    }
  }

  // ── 3. Invoice overdue follow-ups ─────────────────────────
  if (type === 'all' || type === 'invoices') {
    const { data: overdueInvoices } = await supabase
      .from('invoices')
      .select('id, invoice_number, project_id, amount, currency, due_date, status, user_id')
      .eq('status', 'sent')
      .lt('due_date', today)
      .order('due_date', { ascending: true });

    const invoices = (overdueInvoices as Array<{
      id: string; invoice_number: string; project_id: string;
      amount: number; currency: string; due_date: string;
      status: string; user_id: string | null;
    }>) ?? [];

    const invoiceCreated: string[] = [];
    for (const inv of invoices) {
      // Dedupe: skip if already notified today
      const { count } = await supabase
        .from('notifications')
        .select('id', { count: 'exact', head: true })
        .eq('project_id', inv.project_id)
        .eq('type', 'warning')
        .gte('created_at', today + 'T00:00:00Z');

      if ((count ?? 0) > 0) continue;

      const overdueDays = Math.ceil(
        (Date.now() - new Date(inv.due_date).getTime()) / 86400000
      );

      const title = `Invoice overdue ${overdueDays}d: ${inv.invoice_number}`;
      const body = `Invoice ${inv.invoice_number} (${inv.currency} ${inv.amount}) was due on ${inv.due_date} and is now ${overdueDays} day(s) overdue. Consider sending a follow-up message.`;

      await supabase.from('notifications').insert({
        type: 'warning',
        title,
        body,
        project_id: inv.project_id,
        user_id: inv.user_id ?? null,
      });

      invoiceCreated.push(inv.id);
    }

    results.invoices = { checked: invoices.length, created: invoiceCreated.length };
  }

  // ── 4. Weekly API usage summary (benchmark API business tracking) ──────────
  if (type === 'weekly' || (type === 'all' && new Date().getDay() === 1)) {
    try {
      const { data: apiKeys } = await supabase
        .from('api_keys')
        .select('id, key_prefix, label, tier, daily_limit, requests_today, last_used_at, created_at, revoked_at')
        .is('revoked_at', null)
        .order('created_at', { ascending: false });

      const keys = (apiKeys as Array<{
        id: string; key_prefix: string; label: string;
        tier: string; daily_limit: number; requests_today: number;
        last_used_at: string | null;
      }>) ?? [];

      const activeKeys = keys.filter((k) => k.last_used_at);
      const totalRequests = activeKeys.reduce((s, k) => s + k.requests_today, 0);
      const tierCounts = new Map<string, number>();
      for (const k of keys) {
        tierCounts.set(k.tier, (tierCounts.get(k.tier) ?? 0) + 1);
      }

      if (keys.length > 0 && notifyEmail) {
        const tierLines = [...tierCounts.entries()].map(([t, c]) => `${t}: ${c}`).join(', ');
        await sendEmail(
          notifyEmail,
          `[Solo Worker OS] API Usage — ${today}`,
          `<h3>Benchmark API Weekly Summary</h3>
           <p>Active keys: ${activeKeys.length} / ${keys.length} total</p>
           <p>Requests this week: ${totalRequests}</p>
           <p>Tiers: ${tierLines}</p>
           <table border="1" cellpadding="4" style="border-collapse:collapse;">
             <tr><th>Label</th><th>Prefix</th><th>Tier</th><th>Requests</th><th>Last Used</th></tr>
             ${activeKeys.map((k) =>
               `<tr><td>${k.label}</td><td>${k.key_prefix}…</td><td>${k.tier}</td><td>${k.requests_today}</td><td>${k.last_used_at ?? '—'}</td></tr>`
             ).join('')}
           </table>`,
        ).catch(() => {});
      }

      results.api_usage = {
        totalKeys: keys.length,
        activeKeys: activeKeys.length,
        totalRequests,
        tiers: Object.fromEntries(tierCounts),
      };
    } catch (e) {
      results.api_usage = { error: String(e) };
    }
  }

  return NextResponse.json({ ok: true, date: today, results });
}
