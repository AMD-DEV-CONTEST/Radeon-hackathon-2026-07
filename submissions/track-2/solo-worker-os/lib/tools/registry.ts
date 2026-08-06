import type { ToolSpec, ToolExecutionResult, SubagentId } from '@/lib/agent/types';
import type { ToolConfig, ToolContext } from './types';

// ─── Internal registry state ──────────────────────────────────────────────────

/** Map of tool name -> tool configuration. */
const registry = new Map<string, ToolConfig>();

/** Whether the full tool set has been registered (guards against re-registration). */
let registered = false;

// ─── Registration API ──────────────────────────────────────────────────────────

/**
 * Register a single tool. Idempotent: re-registering an existing name is a no-op.
 */
export function registerTool(config: ToolConfig): void {
  if (registry.has(config.name)) return;
  registry.set(config.name, config);
}

/**
 * Look up a tool configuration by name.
 */
export function getTool(name: string): ToolConfig | undefined {
  return registry.get(name);
}

/**
 * Return every registered tool configuration.
 */
export function getAllTools(): ToolConfig[] {
  return Array.from(registry.values());
}

/**
 * Return tools owned by a given subagent.
 * Tools without an explicit `subagent` default to 'general'.
 */
export function getToolsBySubagent(subagent: SubagentId): ToolConfig[] {
  return getAllTools().filter((t) => (t.subagent ?? 'general') === subagent);
}

/**
 * Return the ToolSpec list for a given competition mode.
 * Replaces the original `getToolSpecsForMode` for the base tool set.
 *
 * A tool is included when it has no `modes` filter (available everywhere) or
 * when its `modes` array contains the requested mode.
 */
export function getToolSpecsForMode(mode: string): ToolSpec[] {
  return getAllTools()
    .filter((t) => !t.modes || t.modes.includes(mode))
    .map((t) => ({
      name: t.name,
      description: t.description,
      input_schema: t.input_schema,
    }));
}

/**
 * Execute a registered tool by name for a given competition mode.
 * Replaces the original `executeTool` switch dispatch for the base tool set.
 *
 * Looks the tool up by name and invokes its handler. Mode-specific routing
 * (e.g. Casper blockchain tools) is handled by the caller.
 */
export async function executeToolForMode(
  mode: string,
  name: string,
  input: Record<string, unknown>,
  ctx: ToolContext,
): Promise<ToolExecutionResult> {
  const config = getTool(name);
  if (!config) throw new Error(`Unknown tool: ${name}`);
  return config.handler(input, ctx);
}

// ─── Registration-state helpers (used by registerAllTools) ─────────────────────

/** Whether `registerAllTools()` has already run. */
export function isRegistered(): boolean {
  return registered;
}

/** Mark the tool set as registered. */
export function setRegistered(value: boolean): void {
  registered = value;
}

// ─── Bulk registration ─────────────────────────────────────────────────────────

/**
 * Register a full set of tools at once.
 *
 * Defined here (in registry.ts) rather than index.ts so that consumers
 * outside the Next.js build pipeline (e.g. the MCP server) can import
 * it directly from the registry without hitting module-resolution issues
 * with index.ts re-export layout.
 */
export function registerAll(tools: ToolConfig[]): void {
  if (registered) return;
  for (const tool of tools) {
    registerTool(tool);
  }
  registered = true;
}
