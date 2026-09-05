/**
 * Live status provider: reads the localhost FastAPI backend.
 *
 * The aggregate status contract currently exposes:
 *   GET /api/v1/health                     -> HealthStatusV1
 *   GET /api/v1/contracts/terminal-states  -> frozen terminal-state list
 *
 * M1–M5 use their own typed product endpoints, but this aggregate provider does
 * not compose canonical asset or run state. Rather than infer that state from
 * unrelated responses, it reports `assetAvailability: 'not_served'` and a null
 * `activeRun`. The shell renders no aggregate milestone badge in live mode;
 * each workspace shows its own backend-owned state.
 */
import type { HealthStatusV1 } from '../contracts/types';
import { StatusFetchError, type StatusProvider, type StatusSnapshot } from './provider';

export interface LiveProviderOptions {
  baseUrl: string;
  /** Per-request timeout in ms. */
  timeoutMs?: number;
}

function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, '')}${path}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isHealthStatusV1(value: unknown): value is HealthStatusV1 {
  if (!isRecord(value)) return false;
  return (
    (value.status === 'ok' || value.status === 'degraded') &&
    typeof value.app_version === 'string' &&
    value.app_version.length > 0 &&
    (value.database === 'ok' ||
      value.database === 'unavailable' ||
      value.database === 'not_configured') &&
    typeof value.model_endpoint === 'string' &&
    value.model_endpoint.length > 0 &&
    typeof value.model_profile === 'string' &&
    value.model_profile.length > 0 &&
    (value.gpu_viability === 'VERIFIED' ||
      value.gpu_viability === 'NOT_VERIFIED' ||
      value.gpu_viability === 'BLOCKED') &&
    typeof value.checked_at === 'string'
  );
}

async function getJson(url: string, signal: AbortSignal, timeoutMs: number): Promise<unknown> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  signal.addEventListener('abort', onAbort, { once: true });
  if (signal.aborted) controller.abort();
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new StatusFetchError(`后端返回 HTTP ${response.status}（${url}）。`, {
        retryable: response.status >= 500 || response.status === 429,
      });
    }
    return (await response.json()) as unknown;
  } catch (err) {
    if (err instanceof StatusFetchError) throw err;
    if (timedOut) {
      throw new StatusFetchError(`请求超时（${url}）。`, { retryable: true, cause: err });
    }
    if (signal.aborted) {
      throw new StatusFetchError(`请求已取消（${url}）。`, { retryable: true, cause: err });
    }
    if (err instanceof SyntaxError) {
      throw new StatusFetchError(`后端返回无效 JSON（${url}）。`, {
        retryable: false,
        cause: err,
      });
    }
    throw new StatusFetchError(`无法连接本地后端（${url}）。请确认 FastAPI 正在运行。`, {
      retryable: true,
      cause: err,
    });
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', onAbort);
  }
}

export class LiveStatusProvider implements StatusProvider {
  readonly source = 'live' as const;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(options: LiveProviderOptions) {
    this.baseUrl = options.baseUrl;
    this.timeoutMs = options.timeoutMs ?? 5000;
  }

  async fetchStatus(signal?: AbortSignal): Promise<StatusSnapshot> {
    const activeSignal = signal ?? new AbortController().signal;

    const rawHealth = await getJson(
      joinUrl(this.baseUrl, '/api/v1/health'),
      activeSignal,
      this.timeoutMs,
    );
    if (!isHealthStatusV1(rawHealth)) {
      throw new StatusFetchError('本地后端响应不符合 HealthStatusV1 合同。', {
        retryable: false,
      });
    }
    const health = rawHealth;

    // The frozen terminal-state contract is a bonus proof of the live surface.
    // A failure here must not fail the whole snapshot — it is not run state.
    let terminalStates: readonly string[] | null = null;
    try {
      const raw = await getJson(
        joinUrl(this.baseUrl, '/api/v1/contracts/terminal-states'),
        activeSignal,
        this.timeoutMs,
      );
      if (
        isRecord(raw) &&
        Array.isArray(raw.values) &&
        raw.values.every((v) => typeof v === 'string')
      ) {
        terminalStates = raw.values as string[];
      }
    } catch {
      terminalStates = null;
    }

    return {
      source: this.source,
      scenario: null,
      fetchedAt: new Date().toISOString(),
      health,
      healthError: null,
      assetAvailability: 'not_served',
      asset: null,
      activeRun: null,
      terminalStates,
      retrievalTrace: null,
      relationWorkspace: null,
    };
  }
}
