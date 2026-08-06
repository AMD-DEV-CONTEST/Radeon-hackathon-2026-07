import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';
import { assertProjectQuota } from '@/lib/entitlements';
import { initWorkflowForProject } from '@/lib/workflow-sync';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const CreateProjectSchema = z.object({
  client_name:     z.string().min(1).max(100),
  project_type:    z.string().min(1).max(200),
  budget:          z.number().positive().max(10_000_000),
  currency:        z.string().min(2).max(5),
  deadline:        z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'deadline must be YYYY-MM-DD'),
  casper_address:  z.string().optional(),
});

// ─── Tool configuration ───────────────────────────────────────────────────────
export const createProjectTool: ToolConfig = {
  name: 'create_project',
  description:
    'Create a new project record for a client. Call this tool IMMEDIATELY when the user provides complete project info (client name + project type + budget + deadline) in one sentence. Do NOT ask for confirmation.',
  input_schema: {
    type: 'object',
    properties: {
      client_name: { type: 'string', description: "Client's full name." },
      project_type: { type: 'string', description: 'e.g. Logo Design, Website, Consulting.' },
      budget: { type: 'number', description: 'Project budget as a number.' },
      currency: { type: 'string', description: 'ISO 4217 code, e.g. SGD, USD, EUR.' },
      deadline: { type: 'string', description: 'Absolute ISO date YYYY-MM-DD.' },
    },
    required: ['client_name', 'project_type', 'budget', 'currency', 'deadline'],
  },
  subagent: 'general',
  tags: ['project', 'create'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    // Resolve user ID for attribution; undefined when using service client
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = CreateProjectSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);

    await assertProjectQuota(supabase);

    const row = { ...parsed.data, status: 'active' as const, ...(userId && { user_id: userId }) };
    const { data, error } = await supabase.from('projects').insert(row).select().single();
    if (error) throw new Error(error.message);
    await supabase.from('agent_actions').insert({
      project_id: data.id,
      action_type: 'project_created',
      payload: { ...row, project_id: data.id },
      ...(userId && { user_id: userId }),
    });

    // Auto-create a workflow_steps row so the tracker starts at "kickoff"
    await initWorkflowForProject(supabase, data.id);

    return {
      toolResult: `Project created. project_id=${data.id}. client=${data.client_name}, type=${data.project_type}, budget=${data.budget} ${data.currency}, deadline=${data.deadline}, status=active.`,
      clientSummary: `Created project "${data.project_type}" for ${data.client_name} (${data.budget} ${data.currency}, due ${data.deadline}).`,
    };
  },
};

export default createProjectTool;
