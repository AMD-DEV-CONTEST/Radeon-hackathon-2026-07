import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveConfig } from './config';
import { MockStatusProvider } from './mockProvider';
import { LiveStatusProvider } from './liveProvider';
import { StatusFetchError } from './provider';
import healthExample from '../../contracts/examples/health.json';

describe('local-only provider configuration', () => {
  it('always uses same-origin for live browser requests', () => {
    const env = {
      VITE_DATA_SOURCE: 'live',
      VITE_API_BASE_URL: 'https://remote.example',
    } as unknown as ImportMetaEnv;

    expect(resolveConfig('?source=live&api=https://remote.example', env)).toMatchObject({
      source: 'live',
      apiBaseUrl: '',
    });
  });
});

describe('MockStatusProvider', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns a snapshot for a known scenario', async () => {
    const snap = await new MockStatusProvider({ scenario: 'stale' }).fetchStatus();
    expect(snap.source).toBe('mock');
    expect(snap.scenario).toBe('stale');
    expect(snap.asset).not.toBeNull();
  });

  it('throws a retryable error for the failure scenario', async () => {
    await expect(new MockStatusProvider({ scenario: 'failure' }).fetchStatus()).rejects.toBeInstanceOf(
      StatusFetchError,
    );
  });

  it('removes the abort listener after a delayed request completes', async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const addListener = vi.spyOn(controller.signal, 'addEventListener');
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener');
    const result = new MockStatusProvider({ scenario: 'healthy', delayMs: 25 }).fetchStatus(
      controller.signal,
    );

    await vi.advanceTimersByTimeAsync(25);
    await expect(result).resolves.toMatchObject({ source: 'mock' });
    const registered = addListener.mock.calls.find(([type]) => type === 'abort')?.[1];
    expect(registered).toBeDefined();
    expect(removeListener).toHaveBeenCalledWith('abort', registered);
  });

  it('cleans up and rejects when a delayed request is cancelled', async () => {
    const controller = new AbortController();
    const addListener = vi.spyOn(controller.signal, 'addEventListener');
    const removeListener = vi.spyOn(controller.signal, 'removeEventListener');
    const result = new MockStatusProvider({ scenario: 'healthy', delayMs: 25 }).fetchStatus(
      controller.signal,
    );

    controller.abort();
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    const registered = addListener.mock.calls.find(([type]) => type === 'abort')?.[1];
    expect(registered).toBeDefined();
    expect(removeListener).toHaveBeenCalledWith('abort', registered);
  });

  it('rejects an already-cancelled delayed request', async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(
      new MockStatusProvider({ scenario: 'healthy', delayMs: 25 }).fetchStatus(controller.signal),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('LiveStatusProvider', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it('reads live health and reports asset state as not_served (no fabrication)', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/health')) {
        return new Response(JSON.stringify(healthExample), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({ schema_version: '1.0.0', values: ['SUCCEEDED', 'PAUSED'] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }) as typeof fetch;

    const snap = await new LiveStatusProvider({ baseUrl: 'http://127.0.0.1:8080' }).fetchStatus();
    expect(snap.source).toBe('live');
    expect(snap.health?.status).toBe('ok');
    expect(snap.assetAvailability).toBe('not_served');
    expect(snap.asset).toBeNull();
    expect(snap.activeRun).toBeNull();
    expect(snap.terminalStates).toEqual(['SUCCEEDED', 'PAUSED']);
  });

  it('raises a retryable StatusFetchError when the backend is unreachable', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('fetch failed');
    }) as typeof fetch;
    await expect(
      new LiveStatusProvider({ baseUrl: 'http://127.0.0.1:8080' }).fetchStatus(),
    ).rejects.toMatchObject({
      name: 'StatusFetchError',
      retryable: true,
      message: expect.stringContaining('无法连接本地后端'),
    });
  });

  it('reports an HTTP failure separately from a network failure', async () => {
    globalThis.fetch = vi.fn(async () => new Response('', { status: 503 })) as typeof fetch;

    await expect(
      new LiveStatusProvider({ baseUrl: 'http://127.0.0.1:8080' }).fetchStatus(),
    ).rejects.toMatchObject({
      retryable: true,
      message: expect.stringContaining('HTTP 503'),
    });
  });

  it('fails closed with a distinct error for invalid JSON', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response('{invalid', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ) as typeof fetch;

    await expect(
      new LiveStatusProvider({ baseUrl: 'http://127.0.0.1:8080' }).fetchStatus(),
    ).rejects.toMatchObject({
      retryable: false,
      message: expect.stringContaining('无效 JSON'),
    });
  });

  it('fails closed when health JSON does not match the minimum contract', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ) as typeof fetch;

    await expect(
      new LiveStatusProvider({ baseUrl: 'http://127.0.0.1:8080' }).fetchStatus(),
    ).rejects.toMatchObject({
      retryable: false,
      message: expect.stringContaining('HealthStatusV1'),
    });
  });

  it('distinguishes timeout from caller cancellation', async () => {
    vi.useFakeTimers();
    globalThis.fetch = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        }),
    ) as typeof fetch;

    const timedOut = new LiveStatusProvider({
      baseUrl: 'http://127.0.0.1:8080',
      timeoutMs: 10,
    }).fetchStatus();
    const timedOutAssertion = expect(timedOut).rejects.toMatchObject({
      message: expect.stringContaining('请求超时'),
    });
    await vi.advanceTimersByTimeAsync(10);
    await timedOutAssertion;

    vi.useRealTimers();
    const controller = new AbortController();
    const cancelled = new LiveStatusProvider({
      baseUrl: 'http://127.0.0.1:8080',
    }).fetchStatus(controller.signal);
    const cancelledAssertion = expect(cancelled).rejects.toMatchObject({
      message: expect.stringContaining('请求已取消'),
    });
    controller.abort();
    await cancelledAssertion;
  });

  it('preserves timeout and cancellation classification while reading the JSON body', async () => {
    vi.useFakeTimers();
    let notifyBodyStarted: () => void = () => undefined;
    globalThis.fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const signal = init?.signal;
      return {
        ok: true,
        status: 200,
        json: () => {
          notifyBodyStarted();
          return new Promise<unknown>((_resolve, reject) => {
            if (signal?.aborted) {
              reject(new DOMException('Aborted', 'AbortError'));
              return;
            }
            signal?.addEventListener('abort', () => {
              reject(new DOMException('Aborted', 'AbortError'));
            });
          });
        },
      } as Response;
    }) as typeof fetch;

    const timeoutBodyStarted = new Promise<void>((resolve) => {
      notifyBodyStarted = resolve;
    });
    const timedOut = new LiveStatusProvider({
      baseUrl: 'http://127.0.0.1:8080',
      timeoutMs: 10,
    }).fetchStatus();
    const timedOutAssertion = expect(timedOut).rejects.toMatchObject({
      message: expect.stringContaining('请求超时'),
    });
    await timeoutBodyStarted;
    await vi.advanceTimersByTimeAsync(10);
    await timedOutAssertion;

    vi.useRealTimers();
    const controller = new AbortController();
    const cancelledBodyStarted = new Promise<void>((resolve) => {
      notifyBodyStarted = resolve;
    });
    const cancelled = new LiveStatusProvider({
      baseUrl: 'http://127.0.0.1:8080',
    }).fetchStatus(controller.signal);
    const cancelledAssertion = expect(cancelled).rejects.toMatchObject({
      message: expect.stringContaining('请求已取消'),
    });
    await cancelledBodyStarted;
    controller.abort();
    await cancelledAssertion;
  });
});
