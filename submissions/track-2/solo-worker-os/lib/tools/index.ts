import { registerAll } from './registry';
import type { ToolConfig } from './types';
import { ALL_TOOLS } from './list';

export { ALL_TOOLS };

/**
 * Register every tool into the registry.
 * Idempotent: safe to call multiple times — the internal `registered` flag
 * and `registerTool`'s duplicate guard prevent double registration.
 */
export function registerAllTools(): void {
  registerAll(ALL_TOOLS);
}

// ─── Re-exports ───────────────────────────────────────────────────────────────
export type { ToolConfig, ToolContext } from './types';
export {
  registerTool,
  registerAll,
  getTool,
  getAllTools,
  getToolsBySubagent,
  getToolSpecsForMode,
  executeToolForMode,
  isRegistered,
  setRegistered,
} from './registry';
