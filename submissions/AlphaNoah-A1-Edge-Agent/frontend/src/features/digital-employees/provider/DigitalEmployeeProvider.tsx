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
  DigitalEmployeeReadError,
  type DigitalEmployeeCollection,
  type DigitalEmployeeDataSource,
  type DigitalEmployeeResource,
  type DigitalEmployeeResourceStatus,
} from "../types";

const DigitalEmployeeContext =
  createContext<DigitalEmployeeResource | null>(null);

interface DigitalEmployeeProviderProps extends PropsWithChildren {
  dataSource: DigitalEmployeeDataSource;
}

interface ResourceState {
  readonly owner: DigitalEmployeeDataSource;
  readonly data: DigitalEmployeeCollection | null;
  readonly status: DigitalEmployeeResourceStatus;
  readonly error: DigitalEmployeeReadError | null;
}

interface InitialResource {
  readonly data: DigitalEmployeeCollection | null;
  readonly status: DigitalEmployeeResourceStatus;
  readonly error: DigitalEmployeeReadError | null;
}

export function DigitalEmployeeProvider({
  dataSource,
  children,
}: DigitalEmployeeProviderProps) {
  const initialResource = useMemo(
    () => readInitialResource(dataSource),
    [dataSource],
  );
  const [state, setState] = useState<ResourceState>(() => ({
    owner: dataSource,
    ...initialResource,
  }));
  const requestSequenceRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const readEmployees = useCallback(() => {
    const requestSequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestSequence;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((current) => {
      const data =
        current.owner === dataSource
          ? current.data
          : initialResource.data;
      return {
        owner: dataSource,
        data,
        status: data ? "refreshing" : "loading",
        error: null,
      };
    });

    void dataSource
      .getEmployees({ signal: controller.signal })
      .then((collection) => {
        if (
          controller.signal.aborted ||
          requestSequenceRef.current !== requestSequence
        ) {
          return;
        }

        assertCollectionSource(collection, dataSource);
        setState({
          owner: dataSource,
          data: collection,
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
          error: normalizeReadError(error, dataSource.source),
        }));
      });
  }, [dataSource, initialResource.data]);

  useEffect(() => {
    setState({
      owner: dataSource,
      ...initialResource,
    });
    readEmployees();

    return () => {
      requestSequenceRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [dataSource, initialResource, readEmployees]);

  const visibleState =
    state.owner === dataSource
      ? state
      : {
          owner: dataSource,
          ...initialResource,
        };

  const value = useMemo<DigitalEmployeeResource>(
    () => ({
      source: dataSource.source,
      data: visibleState.data,
      status: visibleState.status,
      error: visibleState.error,
      refresh: readEmployees,
    }),
    [
      dataSource.source,
      readEmployees,
      visibleState.data,
      visibleState.error,
      visibleState.status,
    ],
  );

  return (
    <DigitalEmployeeContext.Provider value={value}>
      {children}
    </DigitalEmployeeContext.Provider>
  );
}

export function useDigitalEmployeeContext(): DigitalEmployeeResource {
  const value = useContext(DigitalEmployeeContext);
  if (!value) {
    throw new Error(
      "Digital employee hooks must be used inside DigitalEmployeeProvider",
    );
  }

  return value;
}

export function useOptionalDigitalEmployeeContext(): DigitalEmployeeResource | null {
  return useContext(DigitalEmployeeContext);
}

function readInitialResource(
  dataSource: DigitalEmployeeDataSource,
): InitialResource {
  try {
    const data = dataSource.getInitialCollection();
    if (data) {
      assertCollectionSource(data, dataSource);
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
      error: normalizeReadError(error, dataSource.source),
    };
  }
}

function assertCollectionSource(
  collection: DigitalEmployeeCollection,
  dataSource: DigitalEmployeeDataSource,
): void {
  if (collection.source !== dataSource.source) {
    throw new DigitalEmployeeReadError(
      "contract",
      dataSource.source,
      `Digital employee source mismatch: expected ${dataSource.source}, received ${collection.source}.`,
    );
  }
}

function normalizeReadError(
  error: unknown,
  source: DigitalEmployeeDataSource["source"],
): DigitalEmployeeReadError {
  if (error instanceof DigitalEmployeeReadError) {
    return error;
  }

  return new DigitalEmployeeReadError(
    "unknown",
    source,
    "Digital employee data source failed.",
    { cause: error },
  );
}
