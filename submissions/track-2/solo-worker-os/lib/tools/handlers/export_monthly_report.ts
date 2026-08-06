import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { Project, AgentAction } from '@/lib/types';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const ReportSchema = z.object({
  year: z.number().int().min(2020).max(2100).optional(),
  month: z.number().int().min(1).max(12).optional(),
}).optional();

// ─── Tool configuration ───────────────────────────────────────────────────────
export const exportMonthlyReportTool: ToolConfig = {
  name: 'export_monthly_report',
  description: "Generate a monthly business report summarizing projects, revenue, and activity. Pass year and month (1-12) to specify the period; defaults to the current month. When the user says '这个月月报' or '导出上月报告' or 'give me a monthly report', call this tool.",
  input_schema: {
    type: 'object',
    properties: {
      year: { type: 'number', description: 'Year (e.g. 2026). Defaults to current year.' },
      month: { type: 'number', description: 'Month 1-12. Defaults to current month.' },
    },
    required: [],
  },
  subagent: 'general',
  tags: ['report', 'finance', 'export'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = ReportSchema.safeParse(input) ?? { success: true, data: {} };
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);

    const now = new Date();
    const year = parsed.data?.year ?? now.getFullYear();
    const month = parsed.data?.month ?? (now.getMonth() + 1);

    // Calculate date range for the month
    const startDate = `${year}-${String(month).padStart(2, '0')}-01`;
    const endOfMonth = new Date(year, month, 0); // day 0 = last day of previous month
    const endDate = `${year}-${String(month).padStart(2, '0')}-${String(endOfMonth.getDate()).padStart(2, '0')}`;

    // Fetch all projects and actions
    const [{ data: allProjects }, { data: allActions }, { data: payments }] = await Promise.all([
      supabase.from('projects').select('*').order('created_at', { ascending: false }),
      supabase.from('agent_actions').select('*').order('created_at', { ascending: false }),
      supabase.from('payments').select('*').order('received_date', { ascending: false }),
    ]);

    const projectList = (allProjects as Project[]) ?? [];
    const actionList = (allActions as AgentAction[]) ?? [];
    const paymentList = (payments as Array<{ amount: number; currency: string; received_date: string; project_id: string }>) ?? [];

    // Filter projects created this month
    const newProjects = projectList.filter((p) => {
      const created = p.created_at.slice(0, 10);
      return created >= startDate && created <= endDate;
    });

    // Filter payments received this month
    const monthPayments = paymentList.filter((p) => {
      return p.received_date >= startDate && p.received_date <= endDate;
    });

    // Revenue by currency this month
    const revenueByCurrency = new Map<string, number>();
    for (const p of monthPayments) {
      revenueByCurrency.set(p.currency, (revenueByCurrency.get(p.currency) ?? 0) + Number(p.amount));
    }

    // Total revenue (all time)
    const totalRevenueByCurrency = new Map<string, number>();
    for (const p of paymentList) {
      totalRevenueByCurrency.set(p.currency, (totalRevenueByCurrency.get(p.currency) ?? 0) + Number(p.amount));
    }

    // Active projects
    const activeProjects = projectList.filter((p) => p.status === 'active');
    const paidProjects = projectList.filter((p) => p.status === 'paid');

    // Actions this month
    const monthActions = actionList.filter((a) => {
      const created = a.created_at.slice(0, 10);
      return created >= startDate && created <= endDate;
    });

    // Build the report
    const monthName = new Date(year, month - 1).toLocaleDateString('en-US', { year: 'numeric', month: 'long' });

    const revenueStr = revenueByCurrency.size === 0
      ? '—'
      : [...revenueByCurrency.entries()].map(([cur, amt]) => `${cur} ${amt.toFixed(2)}`).join(' · ');

    const totalRevenueStr = totalRevenueByCurrency.size === 0
      ? '—'
      : [...totalRevenueByCurrency.entries()].map(([cur, amt]) => `${cur} ${amt.toFixed(2)}`).join(' · ');

    const report = `# Monthly Business Report — ${monthName}

## Revenue (This Month)
**${revenueStr}**

## Revenue (All Time)
**${totalRevenueStr}**

## Projects Overview
| Metric | Count |
|--------|-------|
| New projects this month | ${newProjects.length} |
| Active projects | ${activeProjects.length} |
| Completed (paid) projects | ${paidProjects.length} |
| Total projects | ${projectList.length} |

## New Projects This Month
${newProjects.length === 0
  ? '_No new projects this month._'
  : newProjects.map((p, i) => `${i + 1}. **${p.client_name}** — ${p.project_type} (${p.currency} ${Number(p.budget).toFixed(2)}, due ${p.deadline})`).join('\n')
}

## Payments Received This Month
${monthPayments.length === 0
  ? '_No payments recorded this month._'
  : monthPayments.map((p, i) => {
      const proj = projectList.find((pr) => pr.id === p.project_id);
      return `${i + 1}. ${p.currency} ${Number(p.amount).toFixed(2)} from ${proj?.client_name ?? 'Unknown'} on ${p.received_date}`;
    }).join('\n')
}

## Agent Activity
| Action | Count |
|--------|-------|
| Total actions this month | ${monthActions.length} |
| Projects created | ${monthActions.filter((a) => a.action_type === 'project_created').length} |
| Status updates | ${monthActions.filter((a) => a.action_type === 'status_updated').length} |
| Contracts generated | ${monthActions.filter((a) => a.action_type === 'contract_generated').length} |
| Invoices generated | ${monthActions.filter((a) => a.action_type === 'invoice_generated').length} |
| Payments recorded | ${monthActions.filter((a) => a.action_type === 'payment_recorded').length} |

---
*Generated by Solo Worker OS on ${now.toISOString().slice(0, 10)}*
`;

    return {
      toolResult: `Monthly report for ${monthName} generated. Revenue: ${revenueStr}. New projects: ${newProjects.length}. Payments: ${monthPayments.length}. The report is already displayed to the user verbatim. Do NOT repeat it; just summarize the key highlights in 2-3 sentences.`,
      clientSummary: `Generated monthly report for ${monthName}.`,
      displayText: report,
    };
  },
};

export default exportMonthlyReportTool;
