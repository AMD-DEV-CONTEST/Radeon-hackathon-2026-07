import { describe, expect, it } from "vitest";
import type { ExecutionPlan, SafeEvent } from "../types";
import { executionPlanReducer, executionPlanState } from "./executionPlanReducer";

describe("executionPlanReducer", () => {
  it("deduplicates events without mutating the canonical plan", () => {
    const plan = samplePlan(2);
    const initial = executionPlanState(plan);
    const event = safeEvent(3);
    const advanced = executionPlanReducer(initial, { type: "event", runID: plan.run_id, event });
    const duplicate = executionPlanReducer(advanced, { type: "event", runID: plan.run_id, event });

    expect(advanced.plan).toBe(plan);
    expect(advanced.observedSequence).toBe(3);
    expect(advanced.refreshNeeded).toBe(true);
    expect(duplicate).toBe(advanced);
  });

  it("detects a sequence gap and recovers only when a canonical snapshot catches up", () => {
    const plan = samplePlan(2);
    const gap = executionPlanReducer(executionPlanState(plan), {
      type: "event",
      runID: plan.run_id,
      event: safeEvent(5)
    });
    expect(gap.connection).toBe("recovering");

    const lagging = executionPlanReducer(gap, { type: "snapshot", plan: samplePlan(4) });
    expect(lagging.connection).toBe("recovering");
    expect(lagging.refreshNeeded).toBe(true);

    const recovered = executionPlanReducer(lagging, { type: "snapshot", plan: samplePlan(5) });
    expect(recovered.connection).toBe("live");
    expect(recovered.refreshNeeded).toBe(false);
  });

  it("recovers when the stream arrives before the first plan snapshot", () => {
    const streamed = executionPlanReducer(executionPlanState(), {
      type: "event",
      runID: "run-1",
      event: safeEvent(1)
    });
    expect(streamed.plan).toBeNull();
    expect(streamed.observedSequence).toBe(1);
    expect(streamed.refreshNeeded).toBe(true);

    const hydrated = executionPlanReducer(streamed, {
      type: "snapshot",
      plan: samplePlan(1)
    });
    expect(hydrated.plan?.run_id).toBe("run-1");
    expect(hydrated.refreshNeeded).toBe(false);
    expect(hydrated.connection).toBe("live");
  });

  it("ignores stale snapshots and events from another run", () => {
    const current = executionPlanState(samplePlan(4));
    const stale = executionPlanReducer(current, { type: "snapshot", plan: samplePlan(3) });
    const other = executionPlanReducer(current, {
      type: "event",
      runID: "run-other",
      event: { ...safeEvent(5), run_id: "run-other" }
    });
    expect(stale).toBe(current);
    expect(other).toBe(current);
  });

  it("keeps the last signed plan visible while the stream reconnects", () => {
    const plan = samplePlan(4);
    const unavailable = executionPlanReducer(executionPlanState(plan), {
      type: "unavailable",
      runID: plan.run_id
    });
    expect(unavailable.plan).toBe(plan);
    expect(unavailable.connection).toBe("unavailable");
    expect(unavailable.refreshNeeded).toBe(true);
  });
});

function safeEvent(sequence: number): SafeEvent {
  return {
    sequence,
    run_id: "run-1",
    step_id: "context-01",
    type: "context",
    status: "completed",
    at: "2026-07-25T12:00:00Z"
  };
}

function samplePlan(lastSequence: number): ExecutionPlan {
  return {
    schema_version: "signalforge/execution-plan/v1",
    run_id: "run-1",
    request_id: "request-1",
    status: "running",
    created_at: "2026-07-25T12:00:00Z",
    total_steps: 2,
    terminal_steps: 1,
    progress_ratio: 0.5,
    max_parallel_specialists: 4,
    phases: [
      {
        phase_id: "interpretation", order: 1, safe_label: "Interpretation",
        safe_objective: "Resolve the request.", mandatory: true, status: "passed",
        step_ids: ["interpret-request"], safe_summary: "Validated."
      },
      {
        phase_id: "planning", order: 2, safe_label: "Planning",
        safe_objective: "Freeze the plan.", mandatory: true, status: "passed",
        step_ids: [], safe_summary: "Validated."
      },
      {
        phase_id: "context", order: 3, safe_label: "Context",
        safe_objective: "Compile context.", mandatory: true, status: "running",
        step_ids: ["context-01"], safe_summary: "Running."
      },
      {
        phase_id: "tools", order: 4, safe_label: "Tools",
        safe_objective: "Run deterministic tools.", mandatory: false, status: "pending",
        step_ids: [], safe_summary: "Waiting."
      },
      {
        phase_id: "review", order: 5, safe_label: "Review",
        safe_objective: "Review evidence.", mandatory: true, status: "pending",
        step_ids: [], safe_summary: "Waiting."
      },
      {
        phase_id: "synthesis", order: 6, safe_label: "Synthesis",
        safe_objective: "Compose the answer.", mandatory: true, status: "pending",
        step_ids: [], safe_summary: "Waiting."
      },
      {
        phase_id: "memory", order: 7, safe_label: "Memory",
        safe_objective: "Apply retention.", mandatory: false, status: "pending",
        step_ids: [], safe_summary: "Waiting."
      },
      {
        phase_id: "release", order: 8, safe_label: "Release",
        safe_objective: "Apply release gates.", mandatory: true, status: "pending",
        step_ids: [], safe_summary: "Waiting."
      }
    ],
    steps: [
      {
        step_id: "interpret-request",
        parent_phase_id: "interpretation",
        phase: "interpretation",
        kind: "control",
        safe_label: "Interpret request",
        safe_objective: "Validate request.",
        mandatory: true,
        status: "passed",
        checklist: [],
        attempt: 1,
        max_attempts: 1,
        safe_summary: "Validated."
      },
      {
        step_id: "context-01",
        parent_phase_id: "context",
        phase: "context",
        kind: "context",
        safe_label: "Accounting",
        safe_objective: "Compile context.",
        mandatory: true,
        status: "running",
        checklist: [],
        attempt: 1,
        max_attempts: 2,
        safe_summary: "Running."
      }
    ],
    last_sequence: lastSequence,
    projection_sha256: "a".repeat(64)
  };
}
