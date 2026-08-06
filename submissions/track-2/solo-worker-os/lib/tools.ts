import type { SupabaseClient } from '@supabase/supabase-js';
import { createServiceClient } from './supabase-service';
import type { ToolSpec, ToolExecutionResult } from './agent/types';
import { executeCasperTool, CASPER_TOOL_SPECS } from './agent/casper/tools';
import { registerAllTools } from './tools/index';
import {
  getToolSpecsForMode as registryGetToolSpecsForMode,
  executeToolForMode as registryExecuteToolForMode,
} from './tools/registry';
import type { ToolContext } from './tools/types';

// ──────────────────────────────────────────────────────────────────────────────
// Register all declarative tools on first import.
// `registerAllTools()` is idempotent (guarded by an internal `registered` flag),
// so importing this module multiple times is safe.
// ──────────────────────────────────────────────────────────────────────────────
registerAllTools();

export { ToolExecutionResult };

// ──────────────────────────────────────────────────────────────────────────────
// Competition mode extensions
// ──────────────────────────────────────────────────────────────────────────────

export type CompetitionMode = 'default' | 'qwen' | 'casper';

/**
 * Return the tool specs available for a given competition mode.
 *
 * Base tools come from the declarative registry (filtered by each tool's
 * `modes` field). Casper mode additionally appends the blockchain tool specs.
 */
export function getToolSpecsForMode(mode: CompetitionMode): ToolSpec[] {
  const base = registryGetToolSpecsForMode(mode);
  switch (mode) {
    case 'qwen':   return [...base];
    case 'casper': return [...base, ...CASPER_TOOL_SPECS];
    default:       return base;
  }
}

/**
 * Execute a tool by name for a given competition mode.
 *
 * Casper-specific tools are routed to `executeCasperTool`. All base tools are
 * dispatched through the declarative registry, which looks up the tool config
 * and invokes its handler.
 */
export async function executeToolForMode(
  mode: CompetitionMode,
  name: string,
  input: Record<string, unknown>,
  supabaseClient?: SupabaseClient,
): Promise<ToolExecutionResult> {
  if (mode === 'casper' && CASPER_TOOL_SPECS.some((t) => t.name === name)) {
    const result = await executeCasperTool(name, input);
    return result;
  }
  const supabase = supabaseClient ?? createServiceClient();
  const ctx: ToolContext = { supabase };
  return registryExecuteToolForMode(mode, name, input, ctx);
}
