import { startTransition, useEffect, useReducer, useRef, useState } from "react";
import { createFollowUp, createRun, getExecutionPlan, getRun, subscribeToRun } from "../api";
import type { ExecutionPlan, Projection, RunView, SafeEvent, ScenarioControl } from "../types";
import { executionPlanReducer, executionPlanState } from "./executionPlanReducer";

export function useResearchRun(initial: Projection | null) {
  const [projection, setProjection] = useState(initial);
  const [run, setRun] = useState<RunView | null>(null);
  const [events, setEvents] = useState<SafeEvent[]>([]);
  const [execution, dispatchExecution] = useReducer(
    executionPlanReducer,
    initial?.execution_plan ?? null,
    executionPlanState
  );
  const executionPlan = execution.plan;
  const [error, setError] = useState<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);
  const executionRefreshTimer = useRef<number | null>(null);

  useEffect(() => {
    if (initial && !projection) setProjection(initial);
    if (initial?.execution_plan) dispatchExecution({ type: "snapshot", plan: initial.execution_plan });
  }, [initial, projection]);

  useEffect(() => {
    if (!execution.refreshNeeded || !execution.runID) return;
    if (executionRefreshTimer.current !== null) window.clearTimeout(executionRefreshTimer.current);
    const runID = execution.runID;
    executionRefreshTimer.current = window.setTimeout(() => {
      executionRefreshTimer.current = null;
      void getExecutionPlan(runID)
        .then((plan) => dispatchExecution({ type: "snapshot", plan }))
        .catch(() => dispatchExecution({ type: "unavailable", runID }));
    }, 45);
    return () => {
      if (executionRefreshTimer.current !== null) {
        window.clearTimeout(executionRefreshTimer.current);
        executionRefreshTimer.current = null;
      }
    };
  }, [execution.refreshNeeded, execution.runID, execution.observedSequence, execution.plan?.last_sequence]);

  useEffect(() => () => {
    eventSource.current?.close();
    if (executionRefreshTimer.current !== null) window.clearTimeout(executionRefreshTimer.current);
  }, []);

  function acceptExecutionPlan(next: ExecutionPlan | undefined) {
    if (!next) return;
    startTransition(() => dispatchExecution({ type: "snapshot", plan: next }));
  }

  async function follow(runID: string) {
    eventSource.current?.close();
    eventSource.current = subscribeToRun(runID, (message) => {
      const event = JSON.parse(message.data) as SafeEvent;
      setEvents((current) => current.some((item) => item.sequence === event.sequence) ? current : [...current, event]);
      dispatchExecution({ type: "event", runID, event });
      if (event.type === "workspace" && ["completed", "failed", "cancelled"].includes(event.status)) void refresh(runID);
    }, () => {
      dispatchExecution({ type: "unavailable", runID });
      void refresh(runID);
    });
  }

  async function refresh(runID: string) {
    try {
      const next = await getRun(runID);
      setRun(next);
      acceptExecutionPlan(next.execution_plan);
      if (next.result) startTransition(() => setProjection(next.result!));
      if (next.status !== "running") {
        eventSource.current?.close();
        if (next.status === "failed") {
          setError(messageFor(next.failure?.code ?? "local_run_failed"));
        } else if (next.status === "cancelled") {
          setError(messageFor("cancelled"));
        }
      }
    } catch (cause) {
      setError(messageFor(cause));
    }
  }

  async function start(question: string, scenario: ScenarioControl, retain: boolean) {
    setError(null);
    setEvents([]);
    try {
      const next = await createRun(question, scenario, retain);
      setRun(next);
      dispatchExecution({ type: "reset", runID: next.run_id, plan: next.execution_plan });
      await follow(next.run_id);
    } catch (cause) {
      setError(messageFor(cause));
    }
  }

  async function askFollowUp(question: string, retain: boolean) {
    if (!projection) return;
    setError(null);
    setEvents([]);
    try {
      const next = await createFollowUp(projection.run_id, question, retain);
      setRun(next);
      dispatchExecution({ type: "reset", runID: next.run_id, plan: next.execution_plan });
      await follow(next.run_id);
    } catch (cause) {
      setError(messageFor(cause));
    }
  }

  function loadProjection(next: Projection) {
    eventSource.current?.close();
    setRun(null);
    setEvents([]);
    dispatchExecution({ type: "reset", runID: next.run_id, plan: next.execution_plan });
    setError(null);
    startTransition(() => setProjection(next));
  }

  return {
    projection,
    run,
    events,
    executionPlan,
    executionConnection: execution.connection,
    error,
    start,
    askFollowUp,
    loadProjection,
    running: run?.status === "running"
  };
}

function messageFor(cause: unknown): string {
  const code = cause instanceof Error ? cause.message : typeof cause === "string" ? cause : "unknown_error";
  const messages: Record<string, string> = {
    follow_up_requires_completed_live_case: "Follow-up analysis requires live Radeon mode. The public fixture remains fully inspectable.",
    local_run_failed: "The local model run stopped safely. Your previous research case is still available.",
    deadline_exceeded: "The local research deadline was reached. The previous case remains available and no partial answer was released.",
    model_unavailable: "The local model is unavailable. SignalForge preserved the previous case and released no unsupported answer.",
    api_unavailable: "The optional specialist API is unavailable. SignalForge preserved the local evidence boundary.",
    retrieval_unavailable: "Narrative retrieval is unavailable. SignalForge retained deterministic evidence and withheld unsupported prose.",
    tool_failure: "A deterministic tool failed. SignalForge released no value without a valid calculation receipt.",
    cancelled: "The research run was cancelled safely. Your previous case remains available.",
    invalid_scenario: "Choose one option in each scenario control.",
    invalid_json: "The workspace could not send a valid request."
  };
  return messages[code] ?? "The research run stopped safely. Please retry or inspect the existing case.";
}
