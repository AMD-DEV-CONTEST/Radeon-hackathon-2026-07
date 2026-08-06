import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────

const AnalyzeDataSchema = z.object({
  metric: z.enum([
    'overview',
    'revenue',
    'overdue',
    'status_distribution',
    'client_list',
    'upcoming',
  ]).describe('The type of business data to analyze'),
});

// ─── Tool configuration ───────────────────────────────────────────────────────

export const analyzeBusinessDataTool: ToolConfig = {
  name: 'analyze_business_data',
  description:
    'Analyze business data for the freelancer. Returns revenue stats, project status distribution, overdue projects, client list, or a general overview. Use this when the user asks about their business metrics, income, or project statistics.',
  input_schema: {
    type: 'object',
    properties: {
      metric: {
        type: 'string',
        enum: ['overview', 'revenue', 'overdue', 'status_distribution', 'client_list', 'upcoming'],
        description: 'The type of analysis to perform: overview (general summary), revenue (total by status), overdue (past deadline), status_distribution (count by status), client_list (unique clients), upcoming (due within 2 weeks).',
      },
    },
    required: ['metric'],
  },
  subagent: 'data_analysis',
  tags: ['data', 'analytics', 'business'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    const parsed = AnalyzeDataSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);

    const { data: projects, error } = await supabase
      .from('projects')
      .select('*')
      .order('created_at', { ascending: false });

    if (error) throw new Error(error.message);

    const allProjects = (projects ?? []) as Array<{
      id: string;
      client_name: string;
      project_type: string;
      budget: number;
      currency: string;
      deadline: string;
      status: string;
      created_at: string;
    }>;

    const today = new Date().toISOString().slice(0, 10);
    const twoWeeksLater = new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10);

    switch (parsed.data.metric) {
      case 'overview': {
        const totalBudget = allProjects.reduce((s, p) => s + p.budget, 0);
        const active = allProjects.filter((p) => p.status === 'active').length;
        const paid = allProjects.filter((p) => p.status === 'paid').length;
        const overdue = allProjects.filter((p) => p.deadline < today && p.status === 'active').length;
        const currencies = [...new Set(allProjects.map((p) => p.currency))];

        return {
          toolResult: `Business Overview:\n- Total projects: ${allProjects.length}\n- Active: ${active}\n- Paid: ${paid}\n- Overdue: ${overdue}\n- Total contract value: ${totalBudget} (${currencies.join(', ')})\n- Unique clients: ${new Set(allProjects.map((p) => p.client_name)).size}`,
          clientSummary: `Overview: ${allProjects.length} projects, ${active} active, ${overdue} overdue, total value ${totalBudget} ${currencies.join('/')}.`,
        };
      }

      case 'revenue': {
        const byStatus: Record<string, { count: number; total: number; currency: string }> = {};
        for (const p of allProjects) {
          const key = `${p.status}_${p.currency}`;
          if (!byStatus[key]) byStatus[key] = { count: 0, total: 0, currency: p.currency };
          byStatus[key].count++;
          byStatus[key].total += p.budget;
        }
        const lines = Object.entries(byStatus).map(([key, v]) => `- ${key}: ${v.count} projects, ${v.total} ${v.currency}`);
        const totalEarned = allProjects.filter((p) => p.status === 'paid').reduce((s, p) => s + p.budget, 0);

        return {
          toolResult: `Revenue Analysis:\n${lines.join('\n')}\n- Total earned (paid): ${totalEarned}\n- Total pending (active+invoiced): ${allProjects.filter((p) => p.status !== 'paid' && p.status !== 'delivered').reduce((s, p) => s + p.budget, 0)}`,
          clientSummary: `Revenue: ${totalEarned} earned, ${allProjects.filter((p) => p.status === 'active').length} active projects pending.`,
        };
      }

      case 'overdue': {
        const overdueProjects = allProjects.filter((p) => p.deadline < today && p.status === 'active');
        if (overdueProjects.length === 0) {
          return {
            toolResult: 'No overdue projects. All active projects are within their deadlines.',
            clientSummary: 'No overdue projects.',
          };
        }
        const lines = overdueProjects.map((p) => `- ${p.client_name} | ${p.project_type} | deadline: ${p.deadline} | ${p.budget} ${p.currency}`);
        return {
          toolResult: `Overdue Projects (${overdueProjects.length}):\n${lines.join('\n')}`,
          clientSummary: `${overdueProjects.length} overdue projects found.`,
        };
      }

      case 'status_distribution': {
        const dist: Record<string, number> = {};
        for (const p of allProjects) {
          dist[p.status] = (dist[p.status] ?? 0) + 1;
        }
        const lines = Object.entries(dist).map(([status, count]) => `- ${status}: ${count}`);
        return {
          toolResult: `Project Status Distribution:\n${lines.join('\n')}\nTotal: ${allProjects.length}`,
          clientSummary: `Status: ${Object.entries(dist).map(([s, c]) => `${s}=${c}`).join(', ')}.`,
        };
      }

      case 'client_list': {
        const clients = new Map<string, { projects: number; totalValue: number; currency: string }>();
        for (const p of allProjects) {
          if (!clients.has(p.client_name)) {
            clients.set(p.client_name, { projects: 0, totalValue: 0, currency: p.currency });
          }
          const c = clients.get(p.client_name)!;
          c.projects++;
          c.totalValue += p.budget;
        }
        const lines = [...clients.entries()].map(([name, v]) => `- ${name}: ${v.projects} projects, ${v.totalValue} ${v.currency}`);
        return {
          toolResult: `Client List (${clients.size} unique clients):\n${lines.join('\n')}`,
          clientSummary: `${clients.size} unique clients.`,
        };
      }

      case 'upcoming': {
        const upcoming = allProjects.filter((p) => p.deadline >= today && p.deadline <= twoWeeksLater && p.status === 'active');
        if (upcoming.length === 0) {
          return {
            toolResult: 'No projects due in the next 2 weeks.',
            clientSummary: 'No upcoming deadlines.',
          };
        }
        const lines = upcoming.map((p) => `- ${p.client_name} | ${p.project_type} | deadline: ${p.deadline} | ${p.budget} ${p.currency}`);
        return {
          toolResult: `Upcoming Deadlines (next 2 weeks, ${upcoming.length}):\n${lines.join('\n')}`,
          clientSummary: `${upcoming.length} projects due within 2 weeks.`,
        };
      }

      default:
        return {
          toolResult: 'Unknown metric. Available: overview, revenue, overdue, status_distribution, client_list, upcoming.',
          clientSummary: 'Unknown analysis type.',
        };
    }
  },
};

export default analyzeBusinessDataTool;
