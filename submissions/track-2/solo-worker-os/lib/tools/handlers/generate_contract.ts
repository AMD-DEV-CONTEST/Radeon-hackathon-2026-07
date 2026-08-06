import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';
import type { Project } from '@/lib/types';
import { resolveProject } from '@/lib/tools/resolve-project';

// ─── Zod schema ────────────────────────────────────────────────────────────────
// 支持 project_id (UUID) 或 client_name + project_type 模糊查找
const ContractSchema = z.object({
  project_id: z.string().uuid().optional(),
  client_name: z.string().optional(),
  project_type: z.string().optional(),
}).refine(
  (data) => data.project_id || data.client_name,
  { message: 'Either project_id or client_name must be provided' }
);

// ─── Helper (moved verbatim from lib/tools.ts) ─────────────────────────────────
function buildContract(p: Project): string {
  const today = new Date().toISOString().slice(0, 10);
  return `# Services Agreement

**Between** the Service Provider (Freelancer) and **${p.client_name}** (Client).

## Project
${p.project_type}

## Compensation
Total fee: **${p.currency} ${Number(p.budget).toFixed(2)}**.

## Timeline
Final delivery / deadline: **${p.deadline}**.

## Terms
1. Scope of work covers the deliverables described as "${p.project_type}".
2. A 50% deposit may be required before work begins; the balance is due upon delivery.
3. Revisions beyond two rounds are billable at an agreed hourly rate.
4. Either party may terminate with 7 days written notice; work completed up to that point remains billable.
5. Final deliverables transfer to the Client upon receipt of full payment.

## Agreement
This agreement is effective as of ${today}.

— Signed electronically via Solo Worker OS.
`;
}

// ─── Tool configuration ───────────────────────────────────────────────────────
export const generateContractTool: ToolConfig = {
  name: 'generate_contract',
  description: 'Generate a markdown services contract for a project. You can pass project_id (UUID from the project list in the system prompt) OR client_name to look up the project. When the user says "为 刘洋 生成合同", pass client_name="刘洋".',
  input_schema: {
    type: 'object',
    properties: {
      project_id: { type: 'string', description: 'UUID of the project (from the project list in system prompt). Optional if client_name is given.' },
      client_name: { type: 'string', description: 'Client name to look up the project. Use this when the user mentions a client by name.' },
      project_type: { type: 'string', description: 'Optional: project type to disambiguate when a client has multiple projects.' },
    },
    required: [],
  },
  subagent: 'writing_assistant',
  tags: ['contract', 'generate'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    // Resolve user ID for attribution; undefined when using service client
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = ContractSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const p = await resolveProject(supabase, parsed.data);
    const contract = buildContract(p);
    await supabase.from('agent_actions').insert({
      project_id: p.id,
      action_type: 'contract_generated',
      payload: { contract },
      ...(userId && { user_id: userId }),
    });
    return {
      toolResult: 'Contract generated and already displayed to the user verbatim. Do NOT repeat the contract; just confirm in one short sentence.',
      clientSummary: `Drafted a contract for "${p.project_type}" for ${p.client_name}.`,
      displayText: contract,
    };
  },
};

export default generateContractTool;
