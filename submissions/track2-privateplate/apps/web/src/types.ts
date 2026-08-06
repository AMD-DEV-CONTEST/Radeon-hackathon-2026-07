import type { fetchInbox } from "./api";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  tools?: string[];
  /** True only for the assistant turn that produced / revised a meal plan. */
  attachPlanPreview?: boolean;
};

/**
 * Product pipeline status for the current meal:
 * idle → plan → pending (preview) → sent (task saved) → ready_to_eat → eaten
 */
export type ActionStatus =
  | "idle"
  | "plan"
  | "pending"
  | "sent"
  | "ready_to_eat"
  | "eaten";

export type InboxSnapshot = Awaited<ReturnType<typeof fetchInbox>>;
