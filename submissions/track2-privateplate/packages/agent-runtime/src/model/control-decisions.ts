/**
 * Provider-layer control decisions as native OpenAI-style functions.
 * They never enter ToolGateway / Domain allowlists.
 */
import { z } from "zod";
import {
  MISSING_FIELDS,
  REASON_CODES,
  normalizeMissingFields,
  normalizeReasonCode,
  type MissingField,
  type ReasonCode
} from "./tool-field-contract.js";
import type { AgentGoal } from "../contracts.js";

export const CONTROL_DECISION_NAMES = [
  "ask_user",
  "finish_turn",
  "refuse_request"
] as const;
export type ControlDecisionName = (typeof CONTROL_DECISION_NAMES)[number];

export function isControlDecisionName(
  name: string
): name is ControlDecisionName {
  return (CONTROL_DECISION_NAMES as readonly string[]).includes(name);
}

export const FINISH_TURN_GOALS = [
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
  "no_action"
] as const;
export type FinishTurnGoal = (typeof FINISH_TURN_GOALS)[number];

const goalEnum = [...FINISH_TURN_GOALS, "unsupported"] as const;
export const CONTROL_MESSAGE_MAX_LENGTH = 1200;

type JsonSchema = {
  type: "object";
  additionalProperties: false;
  properties: Record<string, unknown>;
  required: string[];
};

export type ControlToolDefinition = {
  type: "function";
  function: {
    name: ControlDecisionName;
    description: string;
    strict: true;
    parameters: JsonSchema;
  };
};

export const PRIVATEPLATE_CONTROL_TOOLS: ControlToolDefinition[] = [
  {
    type: "function",
    function: {
      name: "ask_user",
      description:
        "Ask the user for missing in-scope information. Use only real user-required slots such as dinerIds, mealType, recipientLabel, activePlanId, focusedTemplateId, currentPreview, softPreferenceToRelax or availableFoodIds. Never list empty arrays, preferLowEffort, planTags or topK as missing fields.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: [...goalEnum],
            description: "Unchanged user goal for this task."
          },
          message: {
            type: "string",
            minLength: 1,
            maxLength: CONTROL_MESSAGE_MAX_LENGTH
          },
          missingFields: {
            type: "array",
            maxItems: 8,
            items: {
              type: "string",
              enum: [...MISSING_FIELDS]
            }
          }
        },
        required: ["goal", "message", "missingFields"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "finish_turn",
      description:
        "End the turn with a grounded user-visible message when the goal is complete, blocked without further tools, or only needs a factual summary from successful tool results. Do not claim sending or external writes.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: [...FINISH_TURN_GOALS]
          },
          message: {
            type: "string",
            minLength: 1,
            maxLength: CONTROL_MESSAGE_MAX_LENGTH
          }
        },
        required: ["goal", "message"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "refuse_request",
      description:
        "Refuse out-of-scope, unsafe or unsupported requests without calling Domain tools. goal must be unsupported.",
      strict: true,
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          goal: {
            type: "string",
            enum: ["unsupported"]
          },
          message: {
            type: "string",
            minLength: 1,
            maxLength: CONTROL_MESSAGE_MAX_LENGTH
          },
          reasonCode: {
            type: "string",
            enum: [...REASON_CODES]
          }
        },
        required: ["goal", "message", "reasonCode"]
      }
    }
  }
];

/** Strict: only allowlisted slots, at least one. Illegal names fail schema (no silent drop). */
const AskUserArgsSchema = z
  .object({
    goal: z.enum(goalEnum),
    message: z.string().min(1).max(CONTROL_MESSAGE_MAX_LENGTH),
    missingFields: z
      .array(z.enum(MISSING_FIELDS))
      .min(1, "missingFields must include at least one real user-required slot")
      .max(8)
  })
  .strict();

const FinishTurnArgsSchema = z
  .object({
    goal: z.enum(FINISH_TURN_GOALS),
    message: z.string().min(1).max(CONTROL_MESSAGE_MAX_LENGTH)
  })
  .strict();

const RefuseArgsSchema = z
  .object({
    goal: z.literal("unsupported"),
    message: z.string().min(1).max(CONTROL_MESSAGE_MAX_LENGTH),
    reasonCode: z.string().min(1).max(64)
  })
  .strict();

export type ParsedControlDecision =
  | {
      kind: "ask_user";
      goal: AgentGoal;
      message: string;
      missingFields: MissingField[];
    }
  | {
      kind: "final";
      goal: FinishTurnGoal;
      message: string;
    }
  | {
      kind: "refuse";
      goal: "unsupported";
      message: string;
      reasonCode: ReasonCode;
    };

/** Unwrap one layer of JSON-encoded string (e.g. goal: "\"compose_meal\""). */
function unwrapJsonStringLayer(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (trimmed.length < 2) return value;
  const quote = trimmed[0];
  if (quote !== '"' && quote !== "'") return value;
  if (trimmed[trimmed.length - 1] !== quote) return value;
  try {
    const parsed = JSON.parse(trimmed);
    return typeof parsed === "string" ? parsed : value;
  } catch {
    return value;
  }
}

export function parseControlDecisionArguments(
  name: ControlDecisionName,
  input: unknown
): ParsedControlDecision {
  const rawArgs: Record<string, unknown> =
    input !== null && typeof input === "object" && !Array.isArray(input)
      ? (input as Record<string, unknown>)
      : {};
  const args: Record<string, unknown> = {
    ...rawArgs,
    goal: unwrapJsonStringLayer(rawArgs.goal)
  };
  if (name === "ask_user") {
    // Compat aliases before strict enum validation (not silent drops of junk).
    const rawFields = Array.isArray(args.missingFields)
      ? args.missingFields.map((item) => {
          if (item === "activePlan") return "activePlanId";
          if (item === "focusedTemplate") return "focusedTemplateId";
          return item;
        })
      : args.missingFields;
    const parsed = AskUserArgsSchema.parse({
      ...args,
      missingFields: rawFields
    });
    return {
      kind: "ask_user",
      goal: parsed.goal,
      message: parsed.message,
      // Schema already enforced allowlist + min(1); keep normalize for typing only.
      missingFields: normalizeMissingFields(parsed.missingFields)
    };
  }
  if (name === "finish_turn") {
    const parsed = FinishTurnArgsSchema.parse(args);
    return {
      kind: "final",
      goal: parsed.goal,
      message: parsed.message
    };
  }
  const parsed = RefuseArgsSchema.parse(args);
  return {
    kind: "refuse",
    goal: "unsupported",
    message: parsed.message,
    reasonCode:
      normalizeReasonCode(parsed.reasonCode) ?? "UNSUPPORTED_OR_UNCLEAR"
  };
}

/** Detect pseudo tool JSON in plain content — never execute it. */
export function contentLooksLikeProtocolObject(
  content: string | null | undefined
): boolean {
  if (!content) return false;
  const trimmed = content.trim();
  if (!trimmed.startsWith("{")) return false;
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object") return false;
    if (typeof parsed.decision === "string") return true;
    if (typeof parsed.name === "string" || typeof parsed.tool === "string") {
      return true;
    }
    return false;
  } catch {
    return false;
  }
}
