/**
 * Versioned agent checkpoint envelope.
 * V1 = bare AgentState (legacy). V2 = AgentState + TaskState.
 * Never stores confirmation tokens or health tags.
 */
import { z } from "zod";
import { AgentStateSchema, type AgentState } from "./state.js";
import {
  createEmptyTaskState,
  TASK_STATE_SCHEMA_VERSION,
  type TaskKnownSlots,
  type TaskState,
  type TaskStateStatus
} from "./task-state.js";
import type { AgentGoal, MissingField } from "./contracts.js";
import { MISSING_FIELDS } from "./model/tool-field-contract.js";

export const AGENT_CHECKPOINT_SCHEMA_VERSION = 2 as const;

export type AgentCheckpointV2 = {
  schemaVersion: typeof AGENT_CHECKPOINT_SCHEMA_VERSION;
  agentState: AgentState;
  taskState: TaskState;
};

const TaskKnownSlotsSchema = z
  .object({
    dinerIds: z.array(z.string().min(1)).max(3).optional(),
    mealType: z.enum(["lunch", "dinner"]).optional(),
    recipientLabel: z.string().min(1).max(64).optional(),
    serveAt: z.string().min(1).max(64).optional()
  })
  .strict();

const TaskStateSchema = z
  .object({
    schemaVersion: z.literal(TASK_STATE_SCHEMA_VERSION),
    objective: z
      .enum([
        "inspect_context",
        "inspect_inventory",
        "compose_meal",
        "revise_meal",
        "retrieve_guidance",
        "preview_handoff",
        "send_handoff",
        "preview_inventory",
        "update_inventory",
        "preview_member_memory",
        "update_member_memory",
        "preview_meal_completion",
        "complete_meal",
        "no_action",
        "unsupported"
      ])
      .nullable(),
    status: z.enum([
      "active",
      "waiting_user",
      "waiting_confirmation",
      "completed",
      "blocked"
    ]),
    workflowStage: z.enum([
      "idle",
      "day_context",
      "candidates",
      "plan_ready",
      "preview_write",
      "awaiting_confirm",
      "completed"
    ]),
    unresolvedSlots: z.array(z.enum(MISSING_FIELDS)),
    knownSlots: TaskKnownSlotsSchema,
    focusedTemplateId: z.string().min(1).nullable(),
    lastDomainFailureCode: z.string().nullable(),
    pendingActionId: z.string().min(1).nullable(),
    pendingActionType: z.string().min(1).nullable(),
    candidateSetId: z.string().min(1).nullable(),
    candidateSetVersion: z.string().nullable(),
    serviceDate: z.string().nullable()
  })
  .strict();

const CheckpointV2Schema = z
  .object({
    schemaVersion: z.literal(AGENT_CHECKPOINT_SCHEMA_VERSION),
    agentState: AgentStateSchema,
    taskState: TaskStateSchema
  })
  .strict();

export function buildCheckpointV2(
  agentState: AgentState,
  taskState: TaskState
): AgentCheckpointV2 {
  return {
    schemaVersion: AGENT_CHECKPOINT_SCHEMA_VERSION,
    agentState: { ...agentState },
    taskState: {
      ...taskState,
      knownSlots: { ...taskState.knownSlots },
      unresolvedSlots: [...taskState.unresolvedSlots]
    }
  };
}

/**
 * Accept V2 envelopes or legacy bare AgentState snapshots.
 */
export function parseCheckpointPayload(raw: unknown): {
  agentState: AgentState;
  taskState: TaskState;
  fromVersion: 1 | 2;
} {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const record = raw as Record<string, unknown>;
    if (record.schemaVersion === AGENT_CHECKPOINT_SCHEMA_VERSION) {
      const parsed = CheckpointV2Schema.parse(record);
      return {
        agentState: parsed.agentState,
        taskState: parsed.taskState as TaskState,
        fromVersion: 2
      };
    }
  }
  const agentState = AgentStateSchema.parse(raw);
  return {
    agentState,
    taskState: createEmptyTaskState(),
    fromVersion: 1
  };
}

export type { TaskState, TaskKnownSlots, TaskStateStatus, AgentGoal, MissingField };
