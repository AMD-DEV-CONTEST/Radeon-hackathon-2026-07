/**
 * MCP Bridge — adapts Solo's ToolConfig registry to MCP tool definitions.
 *
 * This is a thin adapter: it calls registerAllTools() once, then maps
 * the resulting ToolSpec[] to MCP's { name, description, inputSchema } format.
 * Tool execution delegates to executeToolForMode(), which runs the same
 * handler code used by the web UI — zero business logic duplication.
 *
 * Per the spec (docs/MCP_BRIDGE_SPEC.md section 4), the first batch only
 * exposes read-only and generation tools. Write tools (create_project,
 * record_payment, update_project_status) are excluded until we've observed
 * how host agents invoke them.
 */

import { ALL_TOOLS } from '../lib/tools/list';
import { registerAll, getToolSpecsForMode, executeToolForMode, getTool } from '../lib/tools/registry';
import type { ToolContext } from '../lib/tools/types';
import type { ToolSpec } from '../lib/agent/types';

// ─── Read-only tool whitelist (spec section 4) ────────────────────────────────
const READONLY_TOOLS = new Set([
  'get_upcoming_deadlines',
  'analyze_business_data',
  'generate_contract',
  'generate_invoice',
  'generate_followup_message',
  'search_knowledge_base',
  'get_pricing_benchmark',
  'get_exchange_rates',
  'archive_deliverable',
  'browser_automate',
]);

/** MCP tool definition shape (matches ListToolsResult.tools[]). */
export interface McpToolDef {
  name: string;
  description: string;
  inputSchema: {
    type: 'object';
    properties?: Record<string, unknown>;
    required?: string[];
  };
}

/** Ensure tools are registered, then return the MCP-filtered tool list. */
export function getMcpToolDefs(): McpToolDef[] {
  registerAll(ALL_TOOLS);
  const specs = getToolSpecsForMode('default');

  return specs
    .filter((s) => READONLY_TOOLS.has(s.name))
    .map((s: ToolSpec) => ({
      name: s.name,
      description: s.description,
      inputSchema: normalizeSchema(s.input_schema),
    }));
}

/**
 * Normalize our JSON Schema to MCP's expected format.
 * MCP requires inputSchema.type === 'object'.
 */
function normalizeSchema(schema: Record<string, unknown>): McpToolDef['inputSchema'] {
  return {
    type: 'object',
    properties: (schema.properties as Record<string, unknown>) ?? undefined,
    required: (schema.required as string[]) ?? undefined,
  };
}

/**
 * Create the ToolContext for MCP tool execution.
 *
 * Demo mode (NEXT_PUBLIC_DEMO_MODE=true): uses the in-memory mock client,
 * pre-seeded with demo data. Zero configuration needed.
 *
 * Real mode: uses the service-role client. The SOLO_USER_ID env var scopes
 * data access — without it, the server refuses to start to avoid leaking
 * all users' data.
 */
export function createMcpContext(): ToolContext {
  // createServerClient (alias for createServiceClient) handles demo detection
  // internally and returns a mock client when DEMO_MODE is set.
  // We import dynamically to avoid pulling Next.js server code at module
  // load time in environments where it's not available.
  const isDemo = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

  if (isDemo) {
    // Lazy import — only needed in demo mode
    const { createMockClient } = require('@/lib/mock-supabase');
    return { supabase: createMockClient() };
  }

  // Real mode — require SOLO_USER_ID for safety
  const userId = process.env.SOLO_USER_ID;
  if (!userId) {
    throw new Error(
      'SOLO_USER_ID is required when not in demo mode. ' +
      'Set it in .env.local or export it before starting the MCP server.',
    );
  }

  // Use the service client (service role bypasses RLS)
  const { createServerClient } = require('@/lib/supabase-server');
  return { supabase: createServerClient() };
}

/**
 * Execute an MCP tool call by delegating to Solo's tool registry.
 * Returns the text content to send back to the MCP client.
 */
export async function executeMcpTool(
  name: string,
  args: Record<string, unknown>,
  ctx: ToolContext,
): Promise<{ text: string; isError: boolean }> {
  const config = getTool(name);
  if (!config) {
    return { text: `Unknown tool: ${name}`, isError: true };
  }

  if (!READONLY_TOOLS.has(name)) {
    return {
      text: `Tool "${name}" is not exposed via MCP. Only read-only tools are available.`,
      isError: true,
    };
  }

  try {
    const result = await executeToolForMode('default', name, args, ctx);
    // Prefer displayText (full output), fall back to toolResult (model feedback)
    return {
      text: result.displayText ?? result.toolResult,
      isError: false,
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { text: `Tool execution failed: ${msg}`, isError: true };
  }
}
