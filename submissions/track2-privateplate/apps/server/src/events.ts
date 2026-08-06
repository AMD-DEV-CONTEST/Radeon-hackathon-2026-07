import type { CaregiverTaskCard } from "@privateplate/contracts";

export type ConfirmationRequiredEvent = {
  type: "confirmation_required";
  pendingActionId: string;
  confirmationToken: string;
  payloadHash: string;
  expiresAt: string;
  actionType?: string;
  confirmLabel?: string;
  taskCard?: CaregiverTaskCard;
  preview?: Record<string, unknown>;
};

export type AgentEvent =
  | { type: "run_started"; runId: string }
  | { type: "action_started"; label: string; tool: string }
  | {
      type: "action_completed";
      label: string;
      durationMs: number;
      ok: boolean;
    }
  | { type: "plan_ready"; planId: string; version: number; menu: string[] }
  | { type: "plan_infeasible" }
  | { type: "answer_delta"; text: string }
  | { type: "run_failed"; code: string; message: string }
  | { type: "run_completed"; auditRef: string }
  | ConfirmationRequiredEvent;

export type ReplayableAgentEvent = Exclude<
  AgentEvent,
  ConfirmationRequiredEvent
>;

export const UI_ONLY_EVENT_TYPES = new Set(["confirmation_required"] as const);
