import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import { searchKnowledge } from '@/lib/rag';
import type { ToolConfig } from '../types';

// ─── Zod schema ────────────────────────────────────────────────────────────────
const SearchKnowledgeSchema = z.object({
  query: z.string().min(1).max(500),
});

// ─── Tool configuration ───────────────────────────────────────────────────────
export const searchKnowledgeBaseTool: ToolConfig = {
  name: 'search_knowledge_base',
  description:
    "Search the user's private knowledge base (past contracts, email templates, pricing notes, client records). Use when the user asks about historical data, e.g. \"what did I charge Zhang Zong?\" or \"find my logo contract template\".",
  input_schema: {
    type: 'object',
    properties: {
      query: { type: 'string', description: 'Natural language search query.' },
    },
    required: ['query'],
  },
  subagent: 'knowledge_rag',
  tags: ['knowledge', 'search'],
  modes: ['default', 'qwen', 'casper'],
  async handler(input, ctx) {
    const supabase = ctx.supabase as SupabaseClient;

    const parsed = SearchKnowledgeSchema.safeParse(input);
    if (!parsed.success) throw new Error(`Invalid input: ${parsed.error.message}`);
    const docs = await searchKnowledge(parsed.data.query, 4, supabase);
    if (docs.length === 0) {
      return {
        toolResult: 'No matching documents found in the knowledge base.',
        clientSummary: `Searched knowledge base for: "${parsed.data.query}" — no results.`,
      };
    }
    const summary = docs.map((d) => `[${d.doc_type}] ${d.title}\n${d.content.slice(0, 500)}`).join('\n\n---\n\n');
    return {
      toolResult: `Found ${docs.length} relevant document(s):\n\n${summary}`,
      clientSummary: `Found ${docs.length} knowledge base entry(ies) for: "${parsed.data.query}".`,
    };
  },
};

export default searchKnowledgeBaseTool;
