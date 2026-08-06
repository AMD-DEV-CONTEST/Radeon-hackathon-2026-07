import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import {
  PulseReadError,
  type PulseDataSource,
  type PulseResource,
  type PulseResourceStatus,
} from "./pulseDataSource";
import type { PulseNotice } from "../models";

const PulseContext = createContext<PulseResource | null>(null);

interface PulseProviderProps extends PropsWithChildren {
  dataSource: PulseDataSource;
}

interface PulseState {
  readonly owner: PulseDataSource;
  readonly notice: PulseNotice | null;
  readonly status: PulseResourceStatus;
  readonly error: PulseReadError | null;
}

interface InitialPulseState {
  readonly notice: PulseNotice | null;
  readonly status: PulseResourceStatus;
  readonly error: PulseReadError | null;
}

export function PulseProvider({
  dataSource,
  children,
}: PulseProviderProps) {
  const initial = useMemo(
    () => readInitialPulse(dataSource),
    [dataSource],
  );
  const [state, setState] = useState<PulseState>(() => ({
    owner: dataSource,
    ...initial,
  }));
  const hasProjectionRef = useRef(initial.status === "ready");
  const requestSequenceRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const readPulse = useCallback(() => {
    const sequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = sequence;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((current) => ({
      owner: dataSource,
      notice:
        current.owner === dataSource
          ? current.notice
          : initial.notice,
      status: hasProjectionRef.current
        ? "refreshing"
        : "loading",
      error: null,
    }));

    void dataSource
      .getPulse({ signal: controller.signal })
      .then((notice) => {
        if (
          controller.signal.aborted ||
          requestSequenceRef.current !== sequence
        ) {
          return;
        }
        hasProjectionRef.current = true;
        setState({
          owner: dataSource,
          notice,
          status: "ready",
          error: null,
        });
      })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          requestSequenceRef.current !== sequence
        ) {
          return;
        }
        setState((current) => ({
          owner: dataSource,
          notice:
            current.owner === dataSource
              ? current.notice
              : initial.notice,
          status: "error",
          error: normalizePulseError(error, dataSource.source),
        }));
      });
  }, [dataSource, initial.notice, initial.status]);

  useEffect(() => {
    hasProjectionRef.current = initial.status === "ready";
    setState({
      owner: dataSource,
      ...initial,
    });
    readPulse();

    return () => {
      requestSequenceRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [dataSource, initial, readPulse]);

  const visibleState =
    state.owner === dataSource
      ? state
      : { owner: dataSource, ...initial };
  const value = useMemo<PulseResource>(
    () => ({
      source: dataSource.source,
      notice: visibleState.notice,
      status: visibleState.status,
      error: visibleState.error,
      refresh: readPulse,
    }),
    [
      dataSource.source,
      readPulse,
      visibleState.error,
      visibleState.notice,
      visibleState.status,
    ],
  );

  return (
    <PulseContext.Provider value={value}>
      {children}
    </PulseContext.Provider>
  );
}

export function useOptionalPulseContext(): PulseResource | null {
  return useContext(PulseContext);
}

function readInitialPulse(
  dataSource: PulseDataSource,
): InitialPulseState {
  try {
    const pulse = dataSource.getInitialPulse();
    return {
      notice: pulse ?? null,
      status: pulse === undefined ? "idle" : "ready",
      error: null,
    };
  } catch (error: unknown) {
    return {
      notice: null,
      status: "error",
      error: normalizePulseError(error, dataSource.source),
    };
  }
}

function normalizePulseError(
  error: unknown,
  source: PulseDataSource["source"],
): PulseReadError {
  if (error instanceof PulseReadError) {
    return error;
  }
  return new PulseReadError(
    "unknown",
    source,
    "Pulse data source failed.",
    { cause: error },
  );
}
