/**
 * Casper Network — JSON-RPC client (Testnet)
 *
 * Correct endpoint (confirmed from Buildathon official docs):
 *   Primary:  https://node.testnet.casper.network/rpc
 *   Backup:   https://node.testnet.cspr.cloud/rpc
 *   Events:   https://node.testnet.casper.network/events
 *   Explorer: https://testnet.cspr.live
 *
 * ALL read/write operations go through JSON-RPC POST at /rpc.
 * There is NO REST API for account/deploy queries in Casper 2.x —
 * everything is JSON-RPC.
 *
 * Key RPC methods used:
 *   info_get_status             → health check
 *   chain_get_state_root_hash   → prerequisite for state queries
 *   state_get_account_info      → account info (public key → account hash + purse)
 *   state_get_balance           → balance (purse URef + state root hash)
 *   info_get_deploy             → deploy status by hash
 */

const PRIMARY_RPC =
  process.env.NEXT_PUBLIC_CASPER_RPC_URL ?? 'https://node.testnet.casper.network/rpc';
const BACKUP_RPC = 'https://node.testnet.cspr.cloud/rpc';

export const CASPER_EXPLORER = 'https://testnet.cspr.live';

// ──────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────

export interface CasperAccountInfo {
  public_key: string;
  account_hash: string;
  balance_motes: string;
  balance_cspr: string;
  main_purse: string;
}

export interface CasperDeployInfo {
  deploy_hash: string;
  state: string;
  timestamp: string;
  error_message?: string;
}

export class CasperAPIError extends Error {
  constructor(message: string, public code?: number) {
    super(message);
    this.name = 'CasperAPIError';
  }
}

// ──────────────────────────────────────────────────────────────
// JSON-RPC core
// ──────────────────────────────────────────────────────────────

let _rpcUrl = PRIMARY_RPC;

async function jsonRpc<T>(
  method: string,
  params: Record<string, unknown> = {},
  retryOnFailure = true
): Promise<T> {
  const body = JSON.stringify({ id: 1, jsonrpc: '2.0', method, params });

  const attempt = async (url: string): Promise<T> => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    });

    if (!res.ok) {
      throw new CasperAPIError(`HTTP ${res.status} from ${url}`, res.status);
    }

    const json = (await res.json()) as {
      result?: T;
      error?: { code: number; message: string };
    };

    if (json.error) {
      throw new CasperAPIError(
        `RPC error ${json.error.code}: ${json.error.message}`,
        json.error.code
      );
    }

    if (json.result === undefined) {
      throw new CasperAPIError('RPC returned empty result');
    }

    return json.result;
  };

  try {
    return await attempt(_rpcUrl);
  } catch (err) {
    // If primary fails, try backup once
    if (retryOnFailure && _rpcUrl === PRIMARY_RPC) {
      try {
        const result = await attempt(BACKUP_RPC);
        _rpcUrl = BACKUP_RPC; // Stick to backup for this session
        return result;
      } catch {
        throw err; // Re-throw original error
      }
    }
    throw err;
  }
}

// ──────────────────────────────────────────────────────────────
// Encoding helpers
// ──────────────────────────────────────────────────────────────

/** 1 CSPR = 1,000,000,000 motes */
export const MOTES_PER_CSPR = 1_000_000_000n;

export function csprToMotes(cspr: string): bigint {
  const [int, dec = '0'] = cspr.split('.');
  const decPadded = dec.padEnd(9, '0').slice(0, 9);
  return BigInt(int) * MOTES_PER_CSPR + BigInt(decPadded);
}

export function motesToCspr(motes: string): string {
  const m = BigInt(motes);
  const whole = m / MOTES_PER_CSPR;
  const frac  = m % MOTES_PER_CSPR;
  return `${whole}.${frac.toString().padStart(9, '0').slice(0, 4)}`;
}

// ──────────────────────────────────────────────────────────────
// Step 0 helper — get current state root hash
// Required before any state_get_* call
// ──────────────────────────────────────────────────────────────

async function getStateRootHash(): Promise<string> {
  const result = await jsonRpc<{ state_root_hash: string }>(
    'chain_get_state_root_hash',
    { block_identifier: null }
  );
  return result.state_root_hash;
}

// ──────────────────────────────────────────────────────────────
// Public API — Read operations
// ──────────────────────────────────────────────────────────────

/**
 * Health check — returns true if the RPC node responds to info_get_status.
 */
export async function healthCheck(): Promise<boolean> {
  try {
    await jsonRpc<{ api_version: string }>('info_get_status', {});
    return true;
  } catch {
    return false;
  }
}

/**
 * Query account balance and purse info by public key hex.
 *
 * Flow (required by Casper JSON-RPC spec):
 *   1. chain_get_state_root_hash   → current state root
 *   2. state_get_account_info      → account hash + main_purse URef
 *   3. state_get_balance           → balance in motes
 *
 * @param publicKeyHex  Ed25519 key: "01<64 hex chars>"
 *                      Secp256k1:   "02<66 hex chars>"
 */
export async function queryAccount(publicKeyHex: string): Promise<CasperAccountInfo> {
  const key = publicKeyHex.replace(/^(account-hash-|hash-)/, '');

  // Step 1: state root hash
  const stateRootHash = await getStateRootHash();

  // Step 2: account info (requires public key, not account hash)
  const accountResult = await jsonRpc<{
    account: {
      account_hash: string;
      main_purse:   string;
    };
  }>('state_get_account_info', {
    public_key:       key,
    state_root_hash: stateRootHash,
  });

  const { account_hash, main_purse } = accountResult.account;

  // Step 3: balance
  const balanceResult = await jsonRpc<{ balance_value: string }>(
    'state_get_balance',
    { state_root_hash: stateRootHash, purse_uref: main_purse }
  );

  const balanceMotes = balanceResult.balance_value ?? '0';

  return {
    public_key:    key,
    account_hash,
    balance_motes: balanceMotes,
    balance_cspr:  motesToCspr(balanceMotes),
    main_purse,
  };
}

/**
 * Look up a deploy by its hash.
 * Uses info_get_deploy JSON-RPC method.
 *
 * @param deployHash  Raw 64-char hex (with or without "deploy-" prefix)
 */
export async function getDeploy(deployHash: string): Promise<CasperDeployInfo> {
  const hash = deployHash.replace(/^deploy-/, '');

  const result = await jsonRpc<{
    deploy: {
      hash:   string;
      header: { timestamp: string };
    };
    execution_results: Array<{
      result: {
        Success?: Record<string, unknown>;
        Failure?: { error_message: string };
      };
    }>;
  }>('info_get_deploy', { deploy_hash: hash });

  const execResult = result.execution_results?.[0]?.result;
  let state = 'pending';
  let errorMessage: string | undefined;

  if (execResult) {
    if (execResult.Success) state = 'success';
    if (execResult.Failure) {
      state = 'failed';
      errorMessage = execResult.Failure.error_message;
    }
  }

  return {
    deploy_hash:  result.deploy.hash,
    state,
    timestamp:    result.deploy.header.timestamp,
    ...(errorMessage ? { error_message: errorMessage } : {}),
  };
}
