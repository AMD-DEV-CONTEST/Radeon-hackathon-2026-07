import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';
import type { Project } from '@/lib/types';
import { resolveProject } from '@/lib/tools/resolve-project';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const FollowupSchema = z.object({
  project_id: z.string().uuid().optional(),
  client_name: z.string().optional(),
  project_type: z.string().optional(),
  tone: z.enum(['polite', 'firm', 'final_notice']).default('polite'),
}).refine(
  (data) => data.project_id || data.client_name,
  { message: 'Either project_id or client_name must be provided' }
);

// ─── Helper (moved verbatim from lib/tools.ts) ─────────────────────────────────
function buildFollowup(
  p: Project,
  tone: 'polite' | 'firm' | 'final_notice'
): string {
  const opener =
    tone === 'polite'
      ? `Hi ${p.client_name},`
      : tone === 'firm'
        ? `Hello ${p.client_name},`
        : `Dear ${p.client_name},`;

  const body =
    tone === 'polite'
      ? `I hope you're doing well. Just a gentle reminder regarding our project "${p.project_type}" (agreed fee ${p.currency} ${Number(p.budget).toFixed(2)}, due ${p.deadline}). When you have a moment, could you confirm the payment status? Happy to answer any questions. Thanks so much!`
      : tone === 'firm'
        ? `Following up on the project "${p.project_type}" (fee ${p.currency} ${Number(p.budget).toFixed(2)}, due ${p.deadline}). Payment is now overdue. Please arrange payment at your earliest convenience and let me know if there is an issue I should be aware of. I would like to resolve this promptly.`
        : `This is a final notice regarding the outstanding payment of ${p.currency} ${Number(p.budget).toFixed(2)} for "${p.project_type}" (due ${p.deadline}). Despite previous reminders, payment has not been received. Please settle this within 7 days to avoid further action. Contact me immediately if you wish to discuss.`;

  const closer =
    tone === 'polite'
      ? `Warm regards,\nYour Freelancer`
      : `Regards,\nYour Freelancer`;

  return `${opener}\n\n${body}\n\n${closer}`;
}

// ─── Tool configuration ───────────────────────────────────────────────────────
export const generateFollowupMessageTool: ToolConfig = {
  name: 'generate_followup_message',
  description:
    'Generate a follow-up message to send to a client about an unpaid or overdue project. You can pass project_id (UUID) OR client_name to look up the project. When the user says "给 张明 写催款邮件", pass client_name="张明".',
  input_schema: {
    type: 'object',
    properties: {
      project_id: { type: 'string', description: 'UUID of the project. Optional if client_name is given.' },
      client_name: { type: 'string', description: 'Client name to look up the project.' },
      project_type: { type: 'string', description: 'Optional: project type to disambiguate.' },
      tone: { type: 'string', enum: ['polite', 'firm', 'final_notice'], description: 'Tone of the message. Default: polite.' },
    },
    required: [],
  },
  subagent: 'writing_assistant',
  tags: ['followup', 'generate'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = FollowupSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const { tone } = parsed.data;
    const p = await resolveProject(supabase, parsed.data);
    const message = buildFollowup(p, tone);
    await supabase.from('agent_actions').insert({
      project_id: p.id,
      action_type: 'followup_generated',
      payload: { tone, message },
      ...(userId && { user_id: userId }),
    });
    return {
      toolResult: 'Follow-up message generated and already displayed to the user verbatim. Do NOT repeat it; just confirm in one short sentence.',
      clientSummary: `Generated a ${tone} follow-up for ${p.client_name}.`,
      displayText: message,
    };
  },
};

export default generateFollowupMessageTool;
