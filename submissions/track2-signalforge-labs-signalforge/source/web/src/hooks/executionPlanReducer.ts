import type { ExecutionPlan, SafeEvent } from "../types";

export type ExecutionConnection = "idle" | "live" | "recovering" | "unavailable";

export type ExecutionPlanState = {
  plan: ExecutionPlan | null;
  runID: string | null;
  observedSequence: number;
  refreshNeeded: boolean;
  connection: ExecutionConnection;
};

export type ExecutionPlanAction =
  | { type: "reset"; runID: string | null; plan?: ExecutionPlan | null }
  | { type: "snapshot"; plan: ExecutionPlan }
  | { type: "event"; runID: string; event: SafeEvent }
  | { type: "unavailable"; runID: string };

export function executionPlanState(plan: ExecutionPlan | null = null): ExecutionPlanState {
  return {
    plan,
    runID: plan?.run_id ?? null,
    observedSequence: plan?.last_sequence ?? 0,
    refreshNeeded: false,
    connection: plan ? "live" : "idle"
  };
}

// SSE advances only the observation cursor. The signed Go projection remains
// the sole authority for plan transitions and is replaced only by snapshots.
export function executionPlanReducer(
  state: ExecutionPlanState,
  action: ExecutionPlanAction
): ExecutionPlanState {
  switch (action.type) {
    case "reset": {
      const plan = action.plan ?? null;
      return {
        plan,
        runID: action.runID ?? plan?.run_id ?? null,
        observedSequence: plan?.last_sequence ?? 0,
        refreshNeeded: false,
        connection: action.runID || plan ? "live" : "idle"
      };
    }
    case "snapshot": {
      if (state.runID && action.plan.run_id !== state.runID) return state;
      if (
        state.plan?.run_id === action.plan.run_id &&
        action.plan.last_sequence < state.plan.last_sequence
      ) {
        return state;
      }
      const observedSequence = Math.max(state.observedSequence, action.plan.last_sequence);
      const refreshNeeded = action.plan.last_sequence < observedSequence;
      return {
        plan: action.plan,
        runID: action.plan.run_id,
        observedSequence,
        refreshNeeded,
        connection: refreshNeeded ? "recovering" : "live"
      };
    }
    case "event": {
      if (state.runID && action.runID !== state.runID) return state;
      if (action.event.sequence <= state.observedSequence) return state;
      const gap = action.event.sequence !== state.observedSequence + 1;
      return {
        ...state,
        runID: action.runID,
        observedSequence: action.event.sequence,
        refreshNeeded: true,
        connection: gap ? "recovering" : "live"
      };
    }
    case "unavailable":
      if (state.runID && action.runID !== state.runID) return state;
      return {
        ...state,
        runID: action.runID,
        refreshNeeded: true,
        connection: "unavailable"
      };
  }
}
