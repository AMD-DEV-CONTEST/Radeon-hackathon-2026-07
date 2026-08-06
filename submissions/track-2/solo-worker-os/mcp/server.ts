#!/usr/bin/env node
/**
 * Solo MCP Server — stdio transport.
 *
 * Exposes Solo Worker OS's read-only tools as MCP tools, so they can be
 * called from any MCP-compatible client (Claude Desktop, WorkBuddy, Cursor,
 * TRAE, etc.).
 *
 * Usage:
 *   npx tsx mcp/server.ts               # demo mode (mock data)
 *   SOLO_USER_ID=xxx npx tsx mcp/server.ts  # real data
 *
 * Or add to package.json:
 *   "mcp": "tsx mcp/server.ts"
 *
 * See mcp/README.md for client configuration.
 */

import { Server } from '@modelcontextprotocol/sdk/server';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio';
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types';
import { getMcpToolDefs, createMcpContext, executeMcpTool } from './bridge';

async function main() {
  const toolDefs = getMcpToolDefs();

  // Create context (demo mock or real service client)
  const ctx = createMcpContext();

  const server = new Server(
    { name: 'solo-worker-os', version: '1.0.0' },
    {
      capabilities: {
        tools: {},
      },
      instructions:
        'Solo Worker OS — business management tools for freelancers. ' +
        'Available tools include deadline tracking, business analysis, ' +
        'contract/invoice generation, knowledge search, and pricing benchmarks. ' +
        'All tools operate on real business data. Read-only in this version.',
    },
  );

  // ─── tools/list ────────────────────────────────────────────────────────────
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: toolDefs };
  });

  // ─── tools/call ─────────────────────────────────────────────────────────────
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const input = (args ?? {}) as Record<string, unknown>;

    const { text, isError } = await executeMcpTool(name, input, ctx);

    return {
      content: [{ type: 'text' as const, text }],
      isError,
    };
  });

  // ─── Start ──────────────────────────────────────────────────────────────────
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Log to stderr (stdout is reserved for MCP protocol)
  console.error(
    `[solo-mcp] Server started — ${toolDefs.length} tools available ` +
    `(${process.env.NEXT_PUBLIC_DEMO_MODE === 'true' ? 'demo mode' : 'live mode'})`,
  );
}

main().catch((error) => {
  console.error('[solo-mcp] Fatal error:', error);
  process.exit(1);
});
