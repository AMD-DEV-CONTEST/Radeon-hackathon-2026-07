export type ToolOutcomeLike = {
  tool: string;
  ok: boolean;
  code?: string;
  data?: Record<string, unknown> | null;
};

export type ToolOutcomeClassification =
  | { kind: "succeeded"; code: null }
  | { kind: "invocation_failed"; code: string }
  | { kind: "business_rejected"; code: string };

/**
 * One meaning of success for runtime control flow.
 *
 * ToolResult.ok only says the gateway invocation returned normally. Planning
 * also has a valid Domain response whose business status is `failed`; that is
 * recoverable feedback for the model, not a completed plan.
 */
export function classifyToolOutcome(
  outcome: ToolOutcomeLike
): ToolOutcomeClassification {
  if (
    outcome.tool === "finalize_meal_plan" &&
    outcome.data?.status !== undefined &&
    outcome.data?.status !== "ok" &&
    outcome.data?.status !== "valid"
  ) {
    return {
      kind: "business_rejected",
      code:
        typeof outcome.data?.code === "string"
          ? outcome.data.code
          : "FINALIZE_FAILED"
    };
  }

  if (!outcome.ok) {
    return {
      kind: "invocation_failed",
      code: outcome.code ?? "TOOL_INVOCATION_FAILED"
    };
  }

  return { kind: "succeeded", code: null };
}

export function isSuccessfulToolOutcome(outcome: ToolOutcomeLike): boolean {
  return classifyToolOutcome(outcome).kind === "succeeded";
}
