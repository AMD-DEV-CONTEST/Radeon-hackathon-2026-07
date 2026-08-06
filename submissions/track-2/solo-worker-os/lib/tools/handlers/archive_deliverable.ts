import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ToolConfig } from '../types';
import { resolveProject } from '@/lib/tools/resolve-project';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const DeliverableSchema = z.object({
  project_id: z.string().uuid().optional(),
  client_name: z.string().optional(),
  project_type: z.string().optional(),
  title: z.string().min(1, 'Deliverable title is required'),
  url: z.string().url().optional(),
  content: z.string().max(2000).optional(),
  type: z.enum(['final_delivery', 'draft', 'source_file', 'documentation', 'other']).default('final_delivery'),
  notes: z.string().max(500).optional(),
}).refine(
  (data) => data.project_id || data.client_name,
  { message: 'Either project_id or client_name must be provided' }
);

// ─── Tool configuration ───────────────────────────────────────────────────────
export const archiveDeliverableTool: ToolConfig = {
  name: 'archive_deliverable',
  description: 'Archive a project deliverable (final delivery, draft, source file, or documentation) to the deliverables registry. Pass project_id (UUID) OR client_name to look up the project. When the user says "归档交付物" or "存档刘洋的视频成片", pass client_name and title. This creates a permanent deliverable record linked to the project.',
  input_schema: {
    type: 'object',
    properties: {
      project_id: { type: 'string', description: 'UUID of the project. Optional if client_name is given.' },
      client_name: { type: 'string', description: 'Client name to look up the project.' },
      project_type: { type: 'string', description: 'Optional: project type to disambiguate when a client has multiple projects.' },
      title: { type: 'string', description: 'Deliverable title (e.g. "产品宣传视频成片")' },
      url: { type: 'string', description: 'Optional URL to the deliverable file (e.g. Google Drive link)' },
      content: { type: 'string', description: 'Optional inline content for text-based deliverables' },
      type: { type: 'string', enum: ['final_delivery', 'draft', 'source_file', 'documentation', 'other'], description: 'Deliverable type. Default: final_delivery' },
      notes: { type: 'string', description: 'Optional notes about this deliverable' },
    },
    required: ['title'],
  },
  subagent: 'general',
  tags: ['deliverable', 'archive', 'delivery'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;
    const { data: authData } = await supabase.auth.getUser().catch(() => ({ data: { user: null } }));
    const userId = authData?.user?.id;

    const parsed = DeliverableSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const p = await resolveProject(supabase, parsed.data);

    const { data, error } = await supabase.from('deliverables').insert({
      project_id: p.id,
      title: parsed.data.title,
      url: parsed.data.url ?? null,
      content: parsed.data.content ?? null,
      type: parsed.data.type,
      notes: parsed.data.notes ?? null,
      status: 'filed',
      version: 1,
      ...(userId && { user_id: userId }),
    }).select().single();
    if (error) throw new Error(error.message);

    // Write to agent_actions for timeline visibility
    await supabase.from('agent_actions').insert({
      project_id: p.id,
      action_type: 'deliverable_filed',
      payload: {
        deliverable_id: data.id,
        title: parsed.data.title,
        type: parsed.data.type,
        url: parsed.data.url ?? null,
        source: 'AI',
      },
      ...(userId && { user_id: userId }),
    });

    const typeLabels: Record<string, string> = {
      final_delivery: '最终交付物',
      draft: '草稿',
      source_file: '源文件',
      documentation: '文档',
      other: '其他',
    };

    return {
      toolResult: `Deliverable "${parsed.data.title}" archived for ${p.client_name} (${typeLabels[parsed.data.type] ?? parsed.data.type}). Deliverable ID: ${data.id}. View it in the Dashboard deliverables section.`,
      clientSummary: `归档交付物「${parsed.data.title}」→ ${p.client_name}`,
      displayText: `# 交付物归档\n\n**项目：** ${p.project_type} · ${p.client_name}\n**交付物：** ${parsed.data.title}\n**类型：** ${typeLabels[parsed.data.type] ?? parsed.data.type}\n${parsed.data.url ? `**链接：** ${parsed.data.url}\n` : ''}${parsed.data.notes ? `**备注：** ${parsed.data.notes}\n` : ''}\n---\n*归档时间：${new Date().toLocaleString('zh-CN')}*\n*Solo Worker OS 交付物管理系统*`,
    };
  },
};

export default archiveDeliverableTool;
