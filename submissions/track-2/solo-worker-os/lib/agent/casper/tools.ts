import type { ToolSpec, ToolExecutionResult } from '../types';
import {
  queryAccount,
  getDeploy,
  healthCheck,
  type CasperDeployInfo,
} from './client';

/**
 * Casper Network tool specs (read-only — no trading/transfer features).
 */

export const CASPER_TOOL_SPECS: ToolSpec[] = [
  // ── Read tools ──────────────────────────────────────────────

  {
    name: 'casper_query_account',
    description:
      'Query a Casper Network account by its public key. Returns balance in CSPR, account hash, and main purse URef. Use this when the user asks about an account balance, wallet status, or on-chain holdings.',
    input_schema: {
      type: 'object',
      properties: {
        public_key_hash: {
          type: 'string',
          description:
            'The Casper account public key in hex. Ed25519 keys start with "01" followed by 64 hex chars. Secp256k1 keys start with "02" followed by 66 hex chars.',
        },
      },
      required: ['public_key_hash'],
    },
  },
  {
    name: 'casper_get_deploy',
    description:
      'Look up a deploy (transaction) on Casper Network by its deploy hash. Returns the deploy status, timestamp, and execution result. Use this when the user asks about a transaction status or deploy confirmation.',
    input_schema: {
      type: 'object',
      properties: {
        deploy_hash: {
          type: 'string',
          description: 'The deploy hash. Accepts formats: "deploy-<hex>" or raw hex.',
        },
      },
      required: ['deploy_hash'],
    },
  },
];

/**
 * Execute a Casper-specific tool by name.
 */
export async function executeCasperTool(
  name: string,
  input: Record<string, unknown>
): Promise<ToolExecutionResult> {
  switch (name) {
    // ── Read: Query Account ────────────────────────────────────
    case 'casper_query_account': {
      const publicKeyHash = String(input.public_key_hash).trim();
      try {
        const info = await queryAccount(publicKeyHash);
        const result = JSON.stringify(info, null, 2);
        return {
          toolResult: result,
          clientSummary: `Casper account ${publicKeyHash.slice(0, 16)}...: ${info.balance_cspr} CSPR`,
          displayText: `Account ${publicKeyHash.slice(0, 16)}... has ${info.balance_cspr} CSPR on testnet.`,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return {
          toolResult: `Error querying account: ${message}`,
          clientSummary: `Failed to query Casper account`,
          displayText: `Unable to query account: ${message}`,
        };
      }
    }

    // ── Read: Get Deploy ───────────────────────────────────────
    case 'casper_get_deploy': {
      const deployHash = String(input.deploy_hash).trim();
      try {
        const info = await getDeploy(deployHash);
        const result = JSON.stringify(info, null, 2);
        return {
          toolResult: result,
          clientSummary: `Deploy ${deployHash.slice(0, 16)}...: ${info.state}`,
          displayText: `Deploy ${deployHash.slice(0, 16)}... is ${info.state}.`,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return {
          toolResult: `Error looking up deploy: ${message}`,
          clientSummary: `Failed to look up deploy`,
          displayText: `Unable to look up deploy: ${message}`,
        };
      }
    }

    default:
      return {
        toolResult: `Unknown Casper tool: ${name}`,
        clientSummary: `Unknown tool: ${name}`,
      };
  }
}
