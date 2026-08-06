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
  ProviderRuntimeReadError,
  type ProviderRuntimeDataSource,
  type ProviderRuntimeResource,
  type ProviderRuntimeResourceStatus,
  type ProviderRuntimeSnapshot,
} from "../models/providerRuntime";

const ProviderRuntimeStatusContext =
  createContext<ProviderRuntimeResource | null>(null);

interface ProviderRuntimeStatusProviderProps extends PropsWithChildren {
  dataSource: ProviderRuntimeDataSource;
}

interface ResourceState {
  owner: ProviderRuntimeDataSource;
  data: ProviderRuntimeSnapshot | null;
  status: ProviderRuntimeResourceStatus;
  error: ProviderRuntimeReadError | null;
}

export function ProviderRuntimeStatusProvider({
  dataSource,
  children,
}: ProviderRuntimeStatusProviderProps) {
  const initial = useMemo(() => readInitial(dataSource), [dataSource]);
  const [state, setState] = useState<ResourceState>(() => ({
    owner: dataSource,
    ...initial,
  }));
  const dataRef = useRef(initial.data);
  const requestSequenceRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    const requestSequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestSequence;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((current) => ({
      owner: dataSource,
      data: current.owner === dataSource ? current.data : initial.data,
      status: dataRef.current ? "refreshing" : "loading",
      error: null,
    }));

    void dataSource
      .getRuntimeStatus({ signal: controller.signal })
      .then((snapshot) => {
        if (
          controller.signal.aborted ||
          requestSequenceRef.current !== requestSequence
        ) {
          return;
        }
        assertSource(snapshot, dataSource);
        dataRef.current = snapshot;
        setState({
          owner: dataSource,
          data: snapshot,
          status: "ready",
          error: null,
        });
      })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          requestSequenceRef.current !== requestSequence
        ) {
          return;
        }
        setState((current) => ({
          owner: dataSource,
          data: current.owner === dataSource ? current.data : initial.data,
          status: "error",
          error: normalizeError(error, dataSource.source),
        }));
      });
  }, [dataSource, initial.data]);

  useEffect(() => {
    dataRef.current = initial.data;
    setState({ owner: dataSource, ...initial });
    refresh();
    return () => {
      requestSequenceRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [dataSource, initial, refresh]);

  const visibleState =
    state.owner === dataSource
      ? state
      : { owner: dataSource, ...initial };
  const value = useMemo<ProviderRuntimeResource>(
    () => ({
      source: dataSource.source,
      data: visibleState.data,
      status: visibleState.status,
      error: visibleState.error,
      refresh,
    }),
    [
      dataSource.source,
      refresh,
      visibleState.data,
      visibleState.error,
      visibleState.status,
    ],
  );

  return (
    <ProviderRuntimeStatusContext.Provider value={value}>
      {children}
    </ProviderRuntimeStatusContext.Provider>
  );
}

export function useProviderRuntimeStatus(): ProviderRuntimeResource {
  const value = useContext(ProviderRuntimeStatusContext);
  if (!value) {
    throw new Error(
      "useProviderRuntimeStatus must be used inside ProviderRuntimeStatusProvider",
    );
  }
  return value;
}

function readInitial(dataSource: ProviderRuntimeDataSource): {
  data: ProviderRuntimeSnapshot | null;
  status: ProviderRuntimeResourceStatus;
  error: ProviderRuntimeReadError | null;
} {
  try {
    const data = dataSource.getInitialSnapshot();
    if (data) {
      assertSource(data, dataSource);
    }
    return {
      data,
      status: data ? "ready" : "idle",
      error: null,
    };
  } catch (error: unknown) {
    return {
      data: null,
      status: "error",
      error: normalizeError(error, dataSource.source),
    };
  }
}

function assertSource(
  snapshot: ProviderRuntimeSnapshot,
  dataSource: ProviderRuntimeDataSource,
): void {
  if (snapshot.source !== dataSource.source) {
    throw new ProviderRuntimeReadError(
      "contract",
      dataSource.source,
      `Runtime source mismatch: expected ${dataSource.source}, received ${snapshot.source}.`,
    );
  }
}

function normalizeError(
  error: unknown,
  source: ProviderRuntimeDataSource["source"],
): ProviderRuntimeReadError {
  if (error instanceof ProviderRuntimeReadError) {
    return error;
  }
  return new ProviderRuntimeReadError(
    "unknown",
    source,
    "AI Runtime status data source failed.",
    { cause: error },
  );
}
