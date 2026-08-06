import type { SubagentId, ToolExecutionResult } from '@/lib/agent/types';

/** Context passed to tool handlers */
export interface ToolContext {
  supabase: unknown; // Supabase client or mock
}

/** Declarative tool configuration */
export interface ToolConfig {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  /** Which subagent owns this tool (default: 'general') */
  subagent?: SubagentId;
  /** Tags for filtering (e.g. ['project', 'create']) */
  tags?: string[];
  /** Competition modes where this tool is available (e.g. ['qwen', 'casper', 'default']) */
  modes?: string[];
  /** The actual handler function */
  handler: (input: Record<string, unknown>, ctx: ToolContext) => Promise<ToolExecutionResult>;
}
