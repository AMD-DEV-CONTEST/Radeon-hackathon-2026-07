/**
 * Mock status provider driven by checked-in fixtures.
 *
 * Special scenarios:
 *  - `failure` throws a retryable `StatusFetchError` (recoverable-failure state).
 *  - `loading` never resolves within `delayMs`, so a capture can show the loading
 *    state. Any other unknown id falls back to the default scenario.
 */
import { MOCK_SCENARIOS, DEFAULT_MOCK_SCENARIO } from './fixtures';
import { StatusFetchError, type StatusProvider, type StatusSnapshot } from './provider';

export interface MockProviderOptions {
  scenario?: string;
  /** Artificial latency in ms (used to expose the loading state). */
  delayMs?: number;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export class MockStatusProvider implements StatusProvider {
  readonly source = 'mock' as const;
  private readonly scenario: string;
  private readonly delayMs: number;

  constructor(options: MockProviderOptions = {}) {
    this.scenario = options.scenario ?? DEFAULT_MOCK_SCENARIO;
    this.delayMs = options.delayMs ?? 0;
  }

  async fetchStatus(signal?: AbortSignal): Promise<StatusSnapshot> {
    await delay(this.delayMs, signal);

    if (this.scenario === 'failure') {
      throw new StatusFetchError('无法读取本地状态（模拟的可恢复故障）。', {
        retryable: true,
      });
    }

    if (this.scenario === 'loading') {
      // Resolve as healthy after the delay; callers that want a persistent
      // loading capture pass a long delayMs and screenshot before it resolves.
      const base = MOCK_SCENARIOS[DEFAULT_MOCK_SCENARIO];
      return { ...base, source: this.source, fetchedAt: new Date().toISOString() };
    }

    const base = MOCK_SCENARIOS[this.scenario] ?? MOCK_SCENARIOS[DEFAULT_MOCK_SCENARIO];
    return { ...base, source: this.source, fetchedAt: new Date().toISOString() };
  }
}
