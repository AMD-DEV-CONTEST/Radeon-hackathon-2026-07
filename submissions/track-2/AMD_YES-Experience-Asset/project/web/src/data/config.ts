/**
 * Resolves which status provider to use, from build-time env plus URL query
 * params. URL params only select a checked-in fixture or the live same-origin
 * provider; they never select an arbitrary backend or fabricate data.
 *
 *   ?source=mock|live        override the data source
 *   ?scenario=<id>           mock scenario id (healthy, empty, safe-stop, stale,
 *                            terminal-failure, failure, loading)
 *   ?delay=<ms>              artificial mock latency (loading captures)
 */
import { DEFAULT_MOCK_SCENARIO } from './fixtures';
import { LiveStatusProvider } from './liveProvider';
import { MockStatusProvider } from './mockProvider';
import type { StatusProvider } from './provider';

export interface ResolvedConfig {
  source: 'mock' | 'live';
  scenario: string;
  delayMs: number;
  apiBaseUrl: string;
}

// Empty base = same-origin. The Vite dev/preview `/api` proxy forwards to the
// backend, so the browser stays same-origin and no CORS config is required.
const DEFAULT_API_BASE_URL = '';

export function resolveConfig(search: string, env: ImportMetaEnv): ResolvedConfig {
  const params = new URLSearchParams(search);
  const source =
    (params.get('source') as 'mock' | 'live' | null) ??
    env.VITE_DATA_SOURCE ??
    'mock';
  const scenario =
    params.get('scenario') ?? env.VITE_MOCK_SCENARIO ?? DEFAULT_MOCK_SCENARIO;
  const delayRaw = params.get('delay');
  const delayMs = delayRaw !== null ? Math.max(0, Number.parseInt(delayRaw, 10) || 0) : 0;
  return {
    source: source === 'live' ? 'live' : 'mock',
    scenario,
    delayMs,
    apiBaseUrl: DEFAULT_API_BASE_URL,
  };
}

export function createProvider(config: ResolvedConfig): StatusProvider {
  if (config.source === 'live') {
    return new LiveStatusProvider({ baseUrl: config.apiBaseUrl });
  }
  return new MockStatusProvider({ scenario: config.scenario, delayMs: config.delayMs });
}
