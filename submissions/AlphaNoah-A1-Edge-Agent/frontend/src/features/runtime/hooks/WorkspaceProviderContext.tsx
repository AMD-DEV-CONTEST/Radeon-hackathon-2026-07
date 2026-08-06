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
  WorkspaceReadError,
  type WorkspaceDataSource,
  type WorkspaceResource,
  type WorkspaceResourceStatus,
  type WorkspaceSnapshot,
} from "../models";

const WorkspaceContext = createContext<WorkspaceResource | null>(
  null,
);

interface WorkspaceProviderProps extends PropsWithChildren {
  dataSource: WorkspaceDataSource;
}

interface ResourceState {
  owner: WorkspaceDataSource;
  data: WorkspaceSnapshot | null;
  status: WorkspaceResourceStatus;
  error: WorkspaceReadError | null;
}

interface InitialResource {
  data: WorkspaceSnapshot | null;
  status: WorkspaceResourceStatus;
  error: WorkspaceReadError | null;
}

export function WorkspaceProvider({
  dataSource,
  children,
}: WorkspaceProviderProps) {
  const initialResource = useMemo(
    () => readInitialResource(dataSource),
    [dataSource],
  );
  const [state, setState] = useState<ResourceState>(() => ({
    owner: dataSource,
    ...initialResource,
  }));
  const dataRef = useRef(initialResource.data);
  const requestSequenceRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const readWorkspace = useCallback(() => {
    const requestSequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestSequence;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((current) => ({
      owner: dataSource,
      data:
        current.owner === dataSource
          ? current.data
          : initialResource.data,
      status: dataRef.current ? "refreshing" : "loading",
      error: null,
    }));

    void dataSource
      .getWorkspace({ signal: controller.signal })
      .then((snapshot) => {
        if (
          controller.signal.aborted ||
          requestSequenceRef.current !== requestSequence
        ) {
          return;
        }

        assertSnapshotSource(snapshot, dataSource);
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
          data:
            current.owner === dataSource
              ? current.data
              : initialResource.data,
          status: "error",
          error: normalizeWorkspaceError(error, dataSource.source),
        }));
      });
  }, [dataSource, initialResource.data]);

  useEffect(() => {
    dataRef.current = initialResource.data;
    setState({
      owner: dataSource,
      ...initialResource,
    });
    readWorkspace();

    return () => {
      requestSequenceRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [dataSource, initialResource, readWorkspace]);

  const visibleState =
    state.owner === dataSource
      ? state
      : {
          owner: dataSource,
          ...initialResource,
        };

  const value = useMemo<WorkspaceResource>(
    () => ({
      source: dataSource.source,
      data: visibleState.data,
      status: visibleState.status,
      error: visibleState.error,
      refresh: readWorkspace,
    }),
    [
      dataSource.source,
      readWorkspace,
      visibleState.data,
      visibleState.error,
      visibleState.status,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspaceContext(): WorkspaceResource {
  const value = useContext(WorkspaceContext);
  if (!value) {
    throw new Error(
      "Runtime hooks must be used inside WorkspaceProvider",
    );
  }

  return value;
}

export function useOptionalWorkspaceContext(): WorkspaceResource | null {
  return useContext(WorkspaceContext);
}

function readInitialResource(
  dataSource: WorkspaceDataSource,
): InitialResource {
  try {
    const data = dataSource.getInitialSnapshot();
    if (data) {
      assertSnapshotSource(data, dataSource);
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
      error: normalizeWorkspaceError(error, dataSource.source),
    };
  }
}

function assertSnapshotSource(
  snapshot: WorkspaceSnapshot,
  dataSource: WorkspaceDataSource,
): void {
  if (snapshot.source !== dataSource.source) {
    throw new WorkspaceReadError(
      "contract",
      dataSource.source,
      `Workspace source mismatch: expected ${dataSource.source}, received ${snapshot.source}.`,
    );
  }
}

function normalizeWorkspaceError(
  error: unknown,
  source: WorkspaceDataSource["source"],
): WorkspaceReadError {
  if (error instanceof WorkspaceReadError) {
    return error;
  }

  return new WorkspaceReadError(
    "unknown",
    source,
    "Workspace data source failed.",
    { cause: error },
  );
}
