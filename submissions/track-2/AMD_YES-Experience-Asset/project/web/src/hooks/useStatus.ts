import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createProvider, resolveConfig, type ResolvedConfig } from '../data/config';
import type { StatusProvider } from '../data/provider';
import { deriveStatusView, type StatusView } from '../viewmodel/statusView';

export type StatusPhase = 'loading' | 'ready' | 'error';

export interface UseStatusResult {
  phase: StatusPhase;
  view: StatusView | null;
  error: { message: string; retryable: boolean } | null;
  config: ResolvedConfig;
  /** Re-fetch the current source. Truthful refresh, never fabricated progress. */
  refresh: () => void;
  isRefreshing: boolean;
}

export function useStatus(
  search: string = window.location.search,
  env: ImportMetaEnv = import.meta.env,
  providerFactory: (c: ResolvedConfig) => StatusProvider = createProvider,
): UseStatusResult {
  const config = useMemo(() => resolveConfig(search, env), [search, env]);
  const provider = useMemo(() => providerFactory(config), [config, providerFactory]);

  const [phase, setPhase] = useState<StatusPhase>('loading');
  const phaseRef = useRef<StatusPhase>('loading');
  phaseRef.current = phase;
  const [view, setView] = useState<StatusView | null>(null);
  const [error, setError] = useState<UseStatusResult['error']>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async (mode: 'initial' | 'refresh') => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      if (mode === 'initial') setPhase('loading');
      else setIsRefreshing(true);
      try {
        const snapshot = await provider.fetchStatus(controller.signal);
        if (controller.signal.aborted) return;
        setView(deriveStatusView(snapshot));
        setError(null);
        setPhase('ready');
      } catch (err) {
        if (controller.signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
          return;
        }
        const retryable =
          typeof err === 'object' && err !== null && 'retryable' in err
            ? Boolean((err as { retryable: unknown }).retryable)
            : true;
        setError({ message: err instanceof Error ? err.message : String(err), retryable });
        setPhase('error');
      } finally {
        if (!controller.signal.aborted) setIsRefreshing(false);
      }
    },
    [provider],
  );

  useEffect(() => {
    void load('initial');
    return () => abortRef.current?.abort();
  }, [load]);

  const refresh = useCallback(() => {
    void load(phaseRef.current === 'error' ? 'initial' : 'refresh');
  }, [load]);

  return { phase, view, error, config, refresh, isRefreshing };
}
