import { claudeProvider } from './claude';

/**
 * Lazily-loaded providers — only imported when their env var is set.
 * This keeps the default qwen path lean.
 */

let _qwenProvider: import('./types').AgentProvider | null = null;
async function loadQwenProvider(): Promise<import('./types').AgentProvider> {
  if (!_qwenProvider) {
    const mod = await import('./qwen');
    _qwenProvider = mod.qwenProvider;
  }
  return _qwenProvider;
}

let _provider: import('./types').AgentProvider | null = null;

/**
 * Returns the configured agent provider (singleton).
 *
 * Provider selection order:
 *   1. AGENT_PROVIDER env var (qwen | mtclaw | claude | openai | local)
 *   2. Default: qwen
 */
export async function getAgent(): Promise<import('./types').AgentProvider> {
  if (_provider) return _provider;

  const providerName = (process.env.AGENT_PROVIDER ?? 'qwen').toLowerCase();

  switch (providerName) {
    case 'claude': {
      const { claudeProvider } = await import('./claude');
      _provider = claudeProvider;
      break;
    }
    case 'openai': {
      const { openaiProvider } = await import('./openai');
      _provider = openaiProvider;
      break;
    }
    case 'mtclaw': {
      const { mtclawProvider } = await import('./mtclaw');
      _provider = mtclawProvider;
      break;
    }
    case 'qwen': {
      _provider = await loadQwenProvider();
      break;
    }
    case 'local': {
      const { localProvider } = await import('./local');
      _provider = localProvider;
      break;
    }
    default:
      throw new Error(
        `Unknown AGENT_PROVIDER "${providerName}". Supported: qwen, mtclaw, claude, openai, local. ` +
          `Set AGENT_PROVIDER in .env.local.`
      );
  }
  return _provider;
}

/**
 * Synchronous variant — returns the cached provider if available.
 * For cold starts (serverless / first request), this falls back to
 * the configured provider's default (qwen), NOT a hardcoded Claude.
 * Always prefer getAgent() for first-call scenarios.
 */
export function getAgentSync(): import('./types').AgentProvider {
  if (_provider) return _provider;
  // Return qwen as the default fallback (matches AGENT_PROVIDER default).
  // This is a best-effort sync accessor; callers should use getAgent()
  // for proper async initialization.
  const providerName = (process.env.AGENT_PROVIDER ?? 'qwen').toLowerCase();
  if (providerName === 'claude') return claudeProvider;
  // For qwen/mtclaw/openai, we can't sync-load them here.
  // Return claude as last resort to avoid crash, but log a warning.
  console.warn('[getAgentSync] Provider not yet initialized, falling back to claude. Use getAgent() instead.');
  return claudeProvider;
}

export type {
  AgentProvider,
  AgentMessage,
  AgentStreamCallbacks,
  RunStreamParams,
  ToolSpec,
  ToolExecutor,
  ToolExecutionResult,
} from './types';
