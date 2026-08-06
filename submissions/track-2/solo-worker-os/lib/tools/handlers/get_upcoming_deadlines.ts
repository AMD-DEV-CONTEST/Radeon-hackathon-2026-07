import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────

const GetUpcomingDeadlinesSchema = z.object({
  days: z
    .number()
    .int()
    .min(1)
    .max(90)
    .default(7)
    .describe('Look-ahead window in days (e.g. 3 = next 3 days, 7 = this week)'),
  include_overdue: z
    .boolean()
    .default(true)
    .describe('Whether to include overdue active projects in the results'),
});

// ─── Tool configuration ───────────────────────────────────────────────────────

export const getUpcomingDeadlinesTool: ToolConfig = {
  name: 'get_upcoming_deadlines',
  description:
    'Get upcoming project deadlines sorted by due date. Returns projects with their remaining days until deadline. Use when the user asks about upcoming deadlines, schedules, tasks, or what is due soon.',
  input_schema: {
    type: 'object',
    properties: {
      days: {
        type: 'number',
        description: 'Look-ahead window in days (e.g. 3 = next 3 days, 7 = this week). Default: 7.',
      },
      include_overdue: {
        type: 'boolean',
        description: 'Whether to include overdue active projects. Default: true.',
      },
    },
    required: [],
  },
  subagent: 'general',
  tags: ['project', 'deadline', 'schedule', 'task'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;

    const parsed = GetUpcomingDeadlinesSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const { days, include_overdue } = parsed.data;

    const { data: projects, error } = await supabase
      .from('projects')
      .select('*')
      .order('deadline', { ascending: true });

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

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayStr = today.toISOString().slice(0, 10);
    const futureStr = new Date(today.getTime() + days * 86400000)
      .toISOString()
      .slice(0, 10);

    // Filter: active projects with deadline within the window (or overdue if included)
    const filtered = allProjects.filter((p) => {
      if (p.status !== 'active') return false;
      const isOverdue = p.deadline < todayStr;
      const isUpcoming = p.deadline >= todayStr && p.deadline <= futureStr;
      if (isOverdue) return include_overdue;
      return isUpcoming;
    });

    if (filtered.length === 0) {
      return {
        toolResult: `No projects due in the next ${days} day(s).${
          include_overdue ? ' No overdue active projects either.' : ''
        }`,
        clientSummary: `No upcoming deadlines in the next ${days} days.`,
      };
    }

    // Sort: overdue first (most overdue = highest priority), then by deadline ascending
    filtered.sort((a, b) => {
      const aOverdue = a.deadline < todayStr;
      const bOverdue = b.deadline < todayStr;
      if (aOverdue && !bOverdue) return -1;
      if (!aOverdue && bOverdue) return 1;
      return a.deadline.localeCompare(b.deadline);
    });

    const lines = filtered.map((p) => {
      const deadlineDate = new Date(p.deadline + 'T00:00:00');
      const diffMs = deadlineDate.getTime() - today.getTime();
      const diffDays = Math.round(diffMs / 86400000);
      const dayLabel =
        diffDays < 0
          ? `${Math.abs(diffDays)} day(s) overdue`
          : diffDays === 0
            ? 'due today'
            : `${diffDays} day(s) left`;
      const priority = diffDays < 0 ? '⚠️ OVERDUE' : diffDays <= 3 ? '🔴 URGENT' : '🟡';
      return `- ${priority} ${p.client_name} | ${p.project_type} | deadline: ${p.deadline} (${dayLabel}) | ${p.budget} ${p.currency}`;
    });

    const overdueCount = filtered.filter((p) => p.deadline < todayStr).length;
    const urgentCount = filtered.filter(
      (p) => p.deadline >= todayStr && p.deadline <= new Date(today.getTime() + 3 * 86400000).toISOString().slice(0, 10)
    ).length;

    return {
      toolResult: `Upcoming Deadlines (next ${days} days, ${filtered.length} project(s), ${overdueCount} overdue, ${urgentCount} urgent):\n${lines.join('\n')}`,
      clientSummary: `${filtered.length} deadline(s) in the next ${days} days (${overdueCount} overdue, ${urgentCount} urgent).`,
    };
  },
};

export default getUpcomingDeadlinesTool;
