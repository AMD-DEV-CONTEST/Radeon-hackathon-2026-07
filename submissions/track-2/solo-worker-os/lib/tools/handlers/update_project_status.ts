import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';
import { resolveProject } from '@/lib/tools/resolve-project';
import { syncWorkflowForProject } from '@/lib/workflow-sync';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const UpdateStatusSchema = z.object({
  project_id: z.string().uuid().optional(),
  client_name: z.string().optional(),
  status: z.enum(['active', 'delivered', 'invoiced', 'paid']),
}).refine(
  (data) => data.project_id || data.client_name,
  { message: 'Either project_id or client_name must be provided' }
);

// ─── Tool configuration ───────────────────────────────────────────────────────
export const updateProjectStatusTool: ToolConfig = {
  name: 'update_project_status',
  description: "Update a project's status. Pass project_id (UUID) OR client_name to look up the project. When the user says '把张明的项目更新为delivered', pass client_name='张明'.",
  input_schema: {
    type: 'object',
    properties: {
      project_id: { type: 'string', description: 'UUID of the project. Optional if client_name is given.' },
      client_name: { type: 'string', description: 'Client name to look up the project.' },
      status: { type: 'string', enum: ['active', 'delivered', 'invoiced', 'paid'] },
    },
    required: ['status'],
  },
  subagent: 'general',
  tags: ['project', 'update'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = UpdateStatusSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const { status } = parsed.data;
    const project = await resolveProject(supabase, parsed.data);
    const { data, error } = await supabase.from('projects').update({ status }).eq('id', project.id).select().single();
    if (error) throw new Error(error.message);
    await supabase.from('agent_actions').insert({
      project_id: data.id,
      action_type: 'status_updated',
      payload: { status },
      ...(userId && { user_id: userId }),
    });

    // Sync workflow stage to match the new project status
    await syncWorkflowForProject(supabase, data.id, status);

    return {
      toolResult: `Project ${data.id} status updated to ${status}.`,
      clientSummary: `Marked "${data.project_type}" for ${data.client_name} as ${status}.`,
    };
  },
};

export default updateProjectStatusTool;
