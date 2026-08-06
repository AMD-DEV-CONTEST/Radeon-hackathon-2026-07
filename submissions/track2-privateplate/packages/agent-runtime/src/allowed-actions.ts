/**
 * Compatibility surface: re-export task-state action helpers.
 * Provider and Gateway should call computeAvailableActions().
 */
export {
  applyTaskTransition,
  computeAvailableActions,
  createEmptyTaskState,
  isDomainToolInAvailableActions,
  phaseAfterToolFailure,
  TASK_STATE_SCHEMA_VERSION,
  type AvailableActions,
  type TaskKnownSlots,
  type TaskState,
  type TaskStateStatus,
  type TaskTransition
} from "./task-state.js";

import {
  computeAvailableActions,
  createEmptyTaskState,
  type TaskState
} from "./task-state.js";
import type { AgentState, AgentToolName } from "./state.js";
import { AGENT_TOOL_ALLOWLIST } from "./state.js";

/** @deprecated Prefer computeAvailableActions(state, task, mode).domainTools */
export function allowedDomainTools(state: AgentState): AgentToolName[] {
  const emptyTask = createEmptyTaskState();
  return computeAvailableActions(state, emptyTask, "ACTION_ALLOWED").domainTools;
}

export function isDomainToolAllowed(
  state: AgentState,
  tool: string
): tool is AgentToolName {
  if (!(AGENT_TOOL_ALLOWLIST as readonly string[]).includes(tool)) {
    return false;
  }
  return allowedDomainTools(state).includes(tool as AgentToolName);
}
