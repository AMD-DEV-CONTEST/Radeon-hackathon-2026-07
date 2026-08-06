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
  ActivationError,
  type ActivationDataSource,
  type ActivationResource,
  type ActivationResourceStatus,
  type ActivationSnapshot,
} from "../models";

const DEFAULT_DESCRIPTION =
  "Synthetic demo incident: A08 air conditioner remained on outside schedule.";

const ActivationContext =
  createContext<ActivationResource | null>(null);

interface ActivationProviderProps extends PropsWithChildren {
  dataSource: ActivationDataSource;
  requestIdFactory?: () => string;
}

interface ActivationState {
  readonly owner: ActivationDataSource;
  readonly snapshot: ActivationSnapshot | null;
  readonly status: ActivationResourceStatus;
  readonly error: ActivationError | null;
}

interface LogicalAttempt {
  readonly description: string;
  readonly requestId: string;
  readonly eventId: string | null;
}

export function ActivationProvider({
  dataSource,
  requestIdFactory = createActivationRequestId,
  children,
}: ActivationProviderProps) {
  const [state, setState] = useState<ActivationState>({
    owner: dataSource,
    snapshot: null,
    status: "idle",
    error: null,
  });
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef<Promise<void> | null>(null);
  const attemptRef = useRef<LogicalAttempt | null>(null);
  const requestSequenceRef = useRef(0);

  useEffect(() => {
    requestSequenceRef.current += 1;
    controllerRef.current?.abort();
    inFlightRef.current = null;
    attemptRef.current = null;
    setState({
      owner: dataSource,
      snapshot: null,
      status: "idle",
      error: null,
    });
    return () => {
      requestSequenceRef.current += 1;
      controllerRef.current?.abort();
    };
  }, [dataSource]);

  const execute = useCallback(
    (attempt: LogicalAttempt, recover: boolean): Promise<void> => {
      if (inFlightRef.current) {
        return inFlightRef.current;
      }

      const sequence = requestSequenceRef.current + 1;
      requestSequenceRef.current = sequence;
      const controller = new AbortController();
      controllerRef.current = controller;
      setState((current) => ({
        owner: dataSource,
        snapshot:
          current.owner === dataSource ? current.snapshot : null,
        status: "activating",
        error: null,
      }));

      const operation =
        recover && attempt.eventId
          ? dataSource.getEvent(attempt.eventId, {
              signal: controller.signal,
            })
          : dataSource.activate({
              description: attempt.description,
              requestId: attempt.requestId,
              signal: controller.signal,
            });

      const pending = operation
        .then((snapshot) => {
          if (
            controller.signal.aborted ||
            requestSequenceRef.current !== sequence
          ) {
            return;
          }
          assertSnapshotSource(snapshot, dataSource);
          attemptRef.current = {
            ...attempt,
            eventId: snapshot.eventId,
          };
          setState({
            owner: dataSource,
            snapshot,
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
          const normalized = normalizeError(error, dataSource.source);
          attemptRef.current = {
            ...attempt,
            eventId: normalized.eventId ?? attempt.eventId,
          };
          setState((current) => ({
            owner: dataSource,
            snapshot:
              current.owner === dataSource
                ? current.snapshot
                : null,
            status: "error",
            error: normalized,
          }));
        })
        .finally(() => {
          if (inFlightRef.current === pending) {
            inFlightRef.current = null;
          }
        });
      inFlightRef.current = pending;
      return pending;
    },
    [dataSource],
  );

  const activate = useCallback(() => {
    const attempt: LogicalAttempt = {
      description: DEFAULT_DESCRIPTION,
      requestId: requestIdFactory(),
      eventId: null,
    };
    attemptRef.current = attempt;
    return execute(attempt, false);
  }, [execute, requestIdFactory]);

  const retry = useCallback(() => {
    const attempt = attemptRef.current;
    if (!attempt) {
      return activate();
    }
    return execute(attempt, Boolean(attempt.eventId));
  }, [activate, execute]);

  const visibleState =
    state.owner === dataSource
      ? state
      : {
          owner: dataSource,
          snapshot: null,
          status: "idle" as const,
          error: null,
        };
  const value = useMemo<ActivationResource>(
    () => ({
      source: dataSource.source,
      snapshot: visibleState.snapshot,
      status: visibleState.status,
      error: visibleState.error,
      activate,
      retry,
    }),
    [
      activate,
      dataSource.source,
      retry,
      visibleState.error,
      visibleState.snapshot,
      visibleState.status,
    ],
  );

  return (
    <ActivationContext.Provider value={value}>
      {children}
    </ActivationContext.Provider>
  );
}

export function useActivationContext(): ActivationResource {
  const value = useContext(ActivationContext);
  if (!value) {
    throw new Error(
      "Activation hooks must be used inside ActivationProvider.",
    );
  }
  return value;
}

export function useOptionalActivationContext(): ActivationResource | null {
  return useContext(ActivationContext);
}

let fallbackRequestSequence = 0;

export function createActivationRequestId(): string {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return `activation-${globalThis.crypto.randomUUID()}`;
  }
  fallbackRequestSequence += 1;
  return `activation-${Date.now().toString(36)}-${fallbackRequestSequence.toString(36)}`;
}

function assertSnapshotSource(
  snapshot: ActivationSnapshot,
  dataSource: ActivationDataSource,
): void {
  if (snapshot.source !== dataSource.source) {
    throw new ActivationError({
      code: "contract",
      source: dataSource.source,
      message: `Activation source mismatch: expected ${dataSource.source}, received ${snapshot.source}.`,
      retryable: false,
    });
  }
}

function normalizeError(
  error: unknown,
  source: ActivationDataSource["source"],
): ActivationError {
  if (error instanceof ActivationError) {
    return error;
  }
  return new ActivationError({
    code: "unknown",
    source,
    message: "Activation failed.",
    cause: error,
  });
}
