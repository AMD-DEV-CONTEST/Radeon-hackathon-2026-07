import { startTransition, useEffect, useRef, useState } from "react";
import { createFollowUp, createRun, getRun, subscribeToRun } from "../api";
import type { Projection, RunView, SafeEvent, ScenarioControl } from "../types";

export function useResearchRun(initial: Projection | null) {
  const [projection, setProjection] = useState(initial);
  const [run, setRun] = useState<RunView | null>(null);
  const [events, setEvents] = useState<SafeEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);

  useEffect(() => {
    if (initial && !projection) setProjection(initial);
  }, [initial, projection]);

  useEffect(() => () => eventSource.current?.close(), []);

  async function follow(runID: string) {
    eventSource.current?.close();
    eventSource.current = subscribeToRun(runID, (message) => {
      const event = JSON.parse(message.data) as SafeEvent;
      setEvents((current) => current.some((item) => item.sequence === event.sequence) ? current : [...current, event]);
      if (event.type === "workspace" && ["completed", "failed", "cancelled"].includes(event.status)) void refresh(runID);
    }, () => void refresh(runID));
  }

  async function refresh(runID: string) {
    try {
      const next = await getRun(runID);
      setRun(next);
      if (next.result) startTransition(() => setProjection(next.result!));
      if (next.status !== "running") eventSource.current?.close();
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
      await follow(next.run_id);
    } catch (cause) {
      setError(messageFor(cause));
    }
  }

  function loadProjection(next: Projection) {
    eventSource.current?.close();
    setRun(null);
    setEvents([]);
    setError(null);
    startTransition(() => setProjection(next));
  }

  return { projection, run, events, error, start, askFollowUp, loadProjection, running: run?.status === "running" };
}

function messageFor(cause: unknown): string {
  const code = cause instanceof Error ? cause.message : "unknown_error";
  const messages: Record<string, string> = {
    follow_up_requires_completed_live_case: "Follow-up analysis requires live Radeon mode. The public fixture remains fully inspectable.",
    local_run_failed: "The local model run stopped safely. Your previous research case is still available.",
    invalid_scenario: "Choose one option in each scenario control.",
    invalid_json: "The workspace could not send a valid request."
  };
  return messages[code] ?? "The research run stopped safely. Please retry or inspect the existing case.";
}
