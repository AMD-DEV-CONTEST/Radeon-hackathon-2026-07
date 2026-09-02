import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  HumanReviewError,
  type HumanReviewResource,
  type HumanReviewResourceStatus,
  type HumanReviewSnapshot,
} from "../models/humanReview";
import { useHumanReviewDataSource } from "../provider/HumanReviewDataSourceContext";

interface ResourceState {
  readonly eventId: string | null;
  readonly data: HumanReviewSnapshot | null;
  readonly status: HumanReviewResourceStatus;
  readonly error: HumanReviewError | null;
}

export function useHumanReview(
  eventId: string | null,
  enabled: boolean,
): HumanReviewResource {
  const dataSource = useHumanReviewDataSource();
  const [state, setState] = useState<ResourceState>({
    eventId: null,
    data: null,
    status: "idle",
    error: null,
  });
  const sequenceRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);

  const execute = useCallback(
    async (
      status: "loading" | "submitting",
      operation: (
        activeEventId: string,
        signal: AbortSignal,
      ) => Promise<HumanReviewSnapshot>,
    ): Promise<boolean> => {
      if (!enabled || eventId === null || inFlightRef.current) {
        return false;
      }

      inFlightRef.current = true;
      const sequence = sequenceRef.current + 1;
      sequenceRef.current = sequence;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      setState((current) => ({
        eventId,
        data: current.eventId === eventId ? current.data : null,
        status,
        error: null,
      }));

      try {
        const snapshot = await operation(eventId, controller.signal);
        if (
          controller.signal.aborted ||
          sequenceRef.current !== sequence
        ) {
          return false;
        }
        if (snapshot.eventId !== eventId) {
          throw new HumanReviewError(
            "contract",
            "Human review response referenced another Event.",
          );
        }
        setState({
          eventId,
          data: snapshot,
          status: "ready",
          error: null,
        });
        return true;
      } catch (error: unknown) {
        if (
          controller.signal.aborted ||
          sequenceRef.current !== sequence
        ) {
          return false;
        }
        setState((current) => ({
          eventId,
          data: current.eventId === eventId ? current.data : null,
          status: "error",
          error: normalizeError(error),
        }));
        return false;
      } finally {
        if (sequenceRef.current === sequence) {
          inFlightRef.current = false;
        }
      }
    },
    [enabled, eventId],
  );

  const refresh = useCallback(() => {
    void execute("loading", (activeEventId, signal) =>
      dataSource.getReview(activeEventId, { signal }),
    );
  }, [dataSource, execute]);

  useEffect(() => {
    if (!enabled || eventId === null) {
      sequenceRef.current += 1;
      controllerRef.current?.abort();
      inFlightRef.current = false;
      setState({
        eventId: null,
        data: null,
        status: "idle",
        error: null,
      });
      return;
    }

    refresh();
    return () => {
      sequenceRef.current += 1;
      controllerRef.current?.abort();
      inFlightRef.current = false;
    };
  }, [enabled, eventId, refresh]);

  const approve = useCallback(
    () =>
      execute("submitting", (activeEventId, signal) =>
        dataSource.approve(activeEventId, { signal }),
      ),
    [dataSource, execute],
  );
  const reject = useCallback(
    () =>
      execute("submitting", (activeEventId, signal) =>
        dataSource.reject(activeEventId, { signal }),
      ),
    [dataSource, execute],
  );
  const createTask = useCallback(
    () =>
      execute("submitting", (activeEventId, signal) =>
        dataSource.createTask(activeEventId, { signal }),
      ),
    [dataSource, execute],
  );

  return {
    data: state.eventId === eventId ? state.data : null,
    status: state.eventId === eventId ? state.status : "idle",
    error: state.eventId === eventId ? state.error : null,
    refresh,
    approve,
    reject,
    createTask,
  };
}

function normalizeError(error: unknown): HumanReviewError {
  if (error instanceof HumanReviewError) {
    return error;
  }
  return new HumanReviewError(
    "unknown",
    "Human review data source failed.",
    { cause: error },
  );
}
