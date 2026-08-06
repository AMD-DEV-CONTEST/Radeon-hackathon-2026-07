import { z } from "zod";
import {
  goalForTool,
  missingFieldsFromPolicyReasons,
  normalizeMissingFields,
  normalizeReasonCode,
  type AgentGoal,
  type MissingField,
  type ReasonCode,
  type ModelDecisionTransport
} from "../contracts.js";
import {
  PRIVATEPLATE_MODEL_TOOLS,
  parseModelToolArguments,
  parseModelToolGoal
} from "./tool-definitions.js";
import {
  CONTROL_DECISION_NAMES,
  PRIVATEPLATE_CONTROL_TOOLS,
  contentLooksLikeProtocolObject,
  isControlDecisionName,
  parseControlDecisionArguments,
  type ControlDecisionName
} from "./control-decisions.js";
import type { AgentLoopMode } from "../loop-mode.js";
import { AGENT_TOOL_ALLOWLIST, type AgentState, type AgentToolName } from "../state.js";
import {
  resolveHandoffRecipient,
  resolveMealTypeSlot
} from "../product-semantics.js";
import {
  applyTrustedArgumentPolicy,
  type PolicyDictionary,
  type PolicyResult
} from "./argument-policy.js";
import {
  buildPrivacyMinimizedMemberDirectory,
  detectPrivacyLeakInMemberPayload,
  detectPrivacyLeakInToolArgumentText,
  detectPrivacyLeakInToolArguments,
  type PrivacyMember
} from "./privacy-context.js";
import { ModelProviderError } from "./errors.js";
import { isSuccessfulToolOutcome } from "../tool-outcome.js";
import {
  buildToolEnvelopeSchema,
  envelopeInstructionForTools,
  parseToolEnvelopeContent,
  shouldUseStructuredToolEnvelope,
  synthesizeOpenAiToolCallResponse
} from "./structured-tool-envelope.js";

export type ModelRouteDecision =
  | {
      kind: "tool";
      goal: AgentGoal;
      tool: AgentToolName;
      /** @deprecated Prefer effective_arguments for execution; kept for compatibility. */
      arguments: Record<string, unknown>;
      raw_model_arguments: Record<string, unknown>;
      normalized_model_arguments: Record<string, unknown>;
      effective_arguments: Record<string, unknown>;
      policy: PolicyResult;
      privacy_violation: boolean;
      model: string;
      format_retry_count: number;
      format_retry_reasons: string[];
    }
  | {
      kind: "ask_user";
      goal: AgentGoal;
      tool: AgentToolName | null;
      message: string;
      missingFields: MissingField[];
      raw_model_arguments: Record<string, unknown> | null;
      normalized_model_arguments: Record<string, unknown> | null;
      effective_arguments: null;
      policy: PolicyResult;
      privacy_violation: boolean;
      model: string;
      reasons: string[];
      format_retry_count: number;
      format_retry_reasons: string[];
    }
  | {
      kind: "final";
      goal: Exclude<AgentGoal, "unsupported">;
      message: string;
      reasonCode: null;
      transport?: ModelDecisionTransport;
      model: string;
      privacy_violation: boolean;
      format_retry_count: number;
      format_retry_reasons: string[];
    }
  | {
      kind: "refuse";
      goal: "unsupported";
      message: string;
      reasonCode: ReasonCode;
      model: string;
      privacy_violation: boolean;
      format_retry_count: number;
      format_retry_reasons: string[];
    };

export type ModelConversationTurn = {
  user: string;
  assistant: string;
  tools: Array<{ name: string; ok: boolean }>;
};

export type ModelActivePlan = {
  id: string;
  version: number;
  mealType: "lunch" | "dinner";
  dinerIds: string[];
  menu: Array<{
    templateId: string;
    name: string;
    role?: string;
    coversRoles?: string[];
  }>;
  rejectedFoodIds: string[];
  rejectedTemplateIds: string[];
  pinnedTemplateIds: string[];
  requestedPriorityFoodIds: string[];
  preferLowEffort: boolean;
};

export type ModelPendingClarification = {
  tool: AgentToolName | null;
  goal: Exclude<AgentGoal, "no_action" | "unsupported">;
  missing: string[];
  known: Record<string, unknown> & {
    serveAt?: string;
  };
};

export type ModelVisibleToolResult = {
  step: number;
  goal: Exclude<AgentGoal, "no_action" | "unsupported">;
  tool: AgentToolName;
  ok: boolean;
  code?: string;
  retryable?: boolean;
  data: Record<string, unknown> | null;
};

export type ModelTurnContext = {
  goal: Exclude<AgentGoal, "no_action" | "unsupported"> | null;
  mode: AgentLoopMode;
  modeReason: string;
  decisionIndex: number;
  modelRequestCount: number;
  maxModelRequests: number;
  toolResults: ModelVisibleToolResult[];
  answerValidationFailure: {
    reasons: string[];
    regenerationAttempt: number;
  } | null;
  priorOutcome?: {
    phase: AgentState["phase"];
    lastToolStatus: AgentState["lastToolStatus"];
    errorCode: string | null;
  } | null;
};

export type ModelRouteInput = {
  userText: string;
  conversationHistory: ModelConversationTurn[];
  currentTurn: ModelTurnContext;
  activePlan: ModelActivePlan | null;
  focusedTemplateId?: string | null;
  pendingClarification: ModelPendingClarification | null;
  /** Single-source action set from computeAvailableActions() — required for real runs. */
  availableActions?: {
    domainTools: string[];
    controlDecisions: string[];
  };
  /**
   * Privacy-safe TaskState projection (no tokens, no health tags).
   * Model uses this to continue multi-turn goals after restart.
   */
  taskState?: {
    objective: string | null;
    status: string;
    workflowStage: string;
    unresolvedSlots: string[];
    knownSlots: Record<string, unknown>;
    focusedTemplateId: string | null;
    lastDomainFailureCode: string | null;
    hasPendingAction: boolean;
    pendingActionType: string | null;
    candidateSetId: string | null;
    serviceDate: string | null;
    hasActivePlan: boolean;
  };
  state: Pick<
    AgentState,
    | "phase"
    | "dinerIds"
    | "activePlanId"
    | "activePlanVersion"
    | "rejectedFoodIds"
    | "rejectedTemplateIds"
  > & {
    hasPendingAction?: boolean;
  };
  requestContext?: {
    handoffRecipient: ReturnType<typeof resolveHandoffRecipient>;
  };
  dinerIdsLocked: boolean;
  /**
   * Full member directory for trusted policy (may include healthTags).
   * The model payload is privacy-filtered separately.
   */
  memberDirectory: PrivacyMember[];
  fixtureDirectory: {
    foods: Array<{ id: string; name: string; aliases: string[] }>;
    templates: Array<{
      id: string;
      name: string;
      aliases?: string[];
      ingredientFoodIds?: string[];
    }>;
    planTags?: Array<{ id: string; label: string }>;
    caregiverRecipientLabels?: string[];
  };
};

export interface AgentModelProvider {
  /** local_vllm = real loopback model; scripted_mock = local product E2E double */
  readonly mode: "local_vllm" | "scripted_mock";
  readonly model: string;
  route(input: ModelRouteInput): Promise<ModelRouteDecision>;
}

export type OpenAiCompatibleToolProviderOptions = {
  baseUrl: string;
  model: string;
  apiKey?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
};

const ToolCallResponseSchema = z.object({
  choices: z
    .array(
      z.object({
        message: z.object({
          tool_calls: z
            .array(
              z.object({
                function: z.object({
                  name: z.string(),
                  arguments: z.string()
                })
              })
            )
            .max(1)
            .optional(),
          content: z.string().nullable().optional()
        })
      })
    )
    .min(1)
});

/** Exported for prompt-hygiene lint; keep free of fixture ids and sealed user utterances. */
export const PRIVATEPLATE_SYSTEM_PROMPT = [
  "You are the language and tool-decision layer for a Chinese household meal coordination agent.",
  "Your scope is the closed loop: read day context (remaining nutrition budget, inventory, memory), list hard-filtered dish candidates, finalize your own full dish selection, retrieve local knowledge via embedding RAG, preview caregiver shopping/task handoff, and preview meal completion. Domain never ranks dishes or picks a winner; Domain owns grams, nutrition math, shopping gaps and vector retrieval.",
  "Use conversationHistory, currentTurn, activePlan, focusedTemplateId, pendingClarification, requestContext and state. You own language understanding; code owns contracts, grams, nutrition math and safety.",
  "Every model decision must be exactly one native function call. Business tools: get_day_context, get_inventory, find_dish_candidates, finalize_meal_plan, retrieve_local_knowledge, preview_caregiver_task, preview_meal_completion, preview_inventory_change, preview_member_memory_change. Control decisions: ask_user, finish_turn, refuse_request. Never put decisions in plain message content. When a business tool exposes a goal field, use it to state the semantic target: inspect_inventory for inventory-only reads, preview_inventory or update_inventory, preview_member_memory or update_member_memory, preview_meal_completion or complete_meal, and preview_handoff or send_handoff. Use get_inventory (not get_day_context) when the user only asks to view stock. Planning order when composing a meal: get_day_context → find_dish_candidates → finalize_meal_plan → finish_turn. If finalize fails, call find_dish_candidates or finalize again with a new selection; do not stop.",
  "Take at most one function call per decision. Do not repeat a successful Domain tool unless its result proves a recovery call is necessary.",
  "currentTurn.mode is authoritative. ACTION_ALLOWED permits one Domain tool or a control decision. FINAL_ONLY permits only finish_turn (or ask_user when clarification is still required). BLOCKED permits only finish_turn, ask_user or refuse_request and never Domain tools.",
  "Planning order: get_day_context → find_dish_candidates → finalize_meal_plan with your complete selectedDishes, mealPortionScale and selectionReason. Priority: cover the three standard roles (shared_main, shared_side, staple). Each role is not limited to one dish — you may select multiple dishes in the same role for a richer table, and split that role's shared budget with relativePortion. selectedDishes may contain 1–12 different dishes; choose the count from diner count, user intent, nutrition budget, cooking effort and candidate facts. Prefer a satisfying, varied combination when candidates and remaining budget allow; do not stop at one dish per role just because roles are covered, and do not add dishes only to inflate count. Use mealStructure mode simple or one_pot with a clear reason only when the user explicitly asks for that exception. mealPortionScale is the direct base-serving scale; remaining budget is only an upper cap, not another multiplier. Keep plannedIntake as the actual planned intake and preparedBatch as the procurement quantity with its small prep buffer; never describe the buffer as consumed. Write selectionReason as brief, user-facing Chinese, preferably no more than 120 Chinese characters; explain only this actual model selection and do not invent facts that Domain did not return. Revisions submit a new full selectedDishes list; Domain does not auto-substitute dishes.",
  "When planningRecovery is present, treat it as mandatory reselection guidance. Call finalize_meal_plan again with a DIFFERENT selectedDishes and/or mealPortionScale; never repeat the failed selection. Follow recommendedActions exactly.",
  "If recovery contains feasibleSuggestion, it is a Domain-verified feasible selection under the current hard constraints. Adopt it via finalize_meal_plan unless the user's explicit soft preferences conflict, and briefly explain the tradeoff.",
  "Successful currentTurn.toolResults are the only authoritative facts. Describe only their actual menu, inventory, shopping gap and budget facts; never fabricate execution or sending.",
  "Use only member ids, food ids and template ids supplied in the request context. Never invent ids.",
  "The policy layer validates ids, permissions, state and privacy; it does not reinterpret the user's language. If required information is missing, call ask_user with exact missing fields or refuse_request.",
  "taskState is the trusted task lifecycle. Prefer taskState over guessing. If taskState.status is waiting_user and the user supplies an unresolved slot, continue that objective.",
  "retrieve_local_knowledge is real local RAG (embed query, cosine search over approved corpus chunks with source paths). If hits are empty, say the corpus has no relevant evidence — never invent citations.",
  "preview_caregiver_task builds a min-disclosure task card with shopping list from Domain; it never sends. preview_meal_completion only previews intake/inventory ledger changes. Real write/send happens only through the UI confirm channel; chat confirmation never commits.",
  "When currentTurn.answerValidationFailure is present, call finish_turn using only successful currentTurn.toolResults; do not call a Domain tool again.",
  "Never put health tags into tool arguments, never expose member health privacy, and never provide diagnosis, prescriptions, medication changes or real external writes."
].join(" ");

export class OpenAiCompatibleToolProvider implements AgentModelProvider {
  readonly mode = "local_vllm" as const;
  readonly model: string;
  private readonly endpoint: URL;
  private readonly apiKey: string | undefined;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: OpenAiCompatibleToolProviderOptions) {
    const baseUrl = new URL(options.baseUrl.endsWith("/") ? options.baseUrl : `${options.baseUrl}/`);
    if (!isLoopbackHost(baseUrl.hostname)) {
      throw new Error("PrivatePlate core provider must use a loopback URL.");
    }
    if (!options.model.trim()) {
      throw new Error("PrivatePlate model name is required.");
    }

    this.endpoint = new URL("chat/completions", baseUrl);
    this.model = options.model;
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? 180_000;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    const modelMembers = buildPrivacyMinimizedMemberDirectory(
      input.memberDirectory,
      input.userText
    );
    const requestPrivacyViolation = detectPrivacyLeakInMemberPayload(
      modelMembers,
      input.memberDirectory,
      input.userText
    );

    const planningRecovery = buildPlanningRecoveryHint(input.currentTurn);
    const baseMessages = [
      { role: "system", content: PRIVATEPLATE_SYSTEM_PROMPT },
      {
        role: "user",
        content: JSON.stringify({
          request: input.userText,
          conversationHistory: input.conversationHistory,
          currentTurn: input.currentTurn,
          ...(planningRecovery ? { planningRecovery } : {}),
          activePlan: input.activePlan,
          focusedTemplateId: input.focusedTemplateId ?? null,
          pendingClarification: input.pendingClarification,
          taskState: input.taskState ?? null,
          availableActions: input.availableActions ?? null,
          state: input.state,
          requestContext: input.requestContext,
          dinerIdsLocked: input.dinerIdsLocked,
          members: modelMembers,
          fixtureIds: {
            foods: input.fixtureDirectory.foods,
            templates: input.fixtureDirectory.templates,
            planTags: input.fixtureDirectory.planTags ?? [],
            caregiverRecipientLabels:
              input.fixtureDirectory.caregiverRecipientLabels ?? [
                "家庭保姆",
                "保姆",
                "阿姨"
              ]
          }
        })
      }
    ];
    let messages = baseMessages;
    const formatRetryReasons: string[] = [];
    let formatRetryTool: AgentToolName | null = null;
    // Allow more than one control-schema recovery so illegal missingFields can
    // fail closed once, then a follow-up "slots already in user text" recovery
    // can still push the model to finalize_meal_plan.
    const MAX_NATIVE_PROTOCOL_RETRIES = 2;
    let nativeProtocolRetries = 0;

    while (true) {
      const canRetryWithinTurn =
        input.currentTurn.modelRequestCount +
          formatRetryReasons.length +
          1 <
        input.currentTurn.maxModelRequests;
      const mode = input.currentTurn.mode;
      const forcedTool: AgentToolName | null =
        mode === "ACTION_ALLOWED" ? formatRetryTool : null;
      const requestTools = selectProviderTools(
        mode,
        forcedTool,
        input.availableActions
      );
      // Envelope only on control modes by default: ACTION_ALLOWED keeps native
      // tools (full oneOf + large prompts can whitespace-pad until max_tokens).
      const useToolEnvelope = shouldUseStructuredToolEnvelope(mode);
      const requestMessages = useToolEnvelope
        ? [
            ...messages,
            {
              role: "system" as const,
              content: envelopeInstructionForTools(requestTools)
            }
          ]
        : messages;
      const requestBody = useToolEnvelope
        ? {
            model: this.model,
            messages: requestMessages,
            temperature: 0,
            stream: false,
            max_tokens: 768,
            structured_outputs: {
              json: buildToolEnvelopeSchema(requestTools)
            }
          }
        : {
            model: this.model,
            messages: requestMessages,
            tools: requestTools,
            tool_choice: forcedTool
              ? {
                  type: "function" as const,
                  function: { name: forcedTool }
                }
              : ("required" as const),
            temperature: 0,
            stream: false,
            max_tokens: 2048
          };
      let response: Response;
      try {
        response = await this.fetchImpl(this.endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {})
          },
          body: JSON.stringify(requestBody),
          signal: AbortSignal.timeout(this.timeoutMs)
        });
      } catch {
        throw new ModelProviderError(
          "MODEL_HTTP_ERROR",
          "Local vLLM request failed."
        );
      }

      if (!response.ok) {
        throw new ModelProviderError(
          "MODEL_HTTP_ERROR",
          `Local vLLM returned HTTP ${response.status}.`
        );
      }

      let payload: z.infer<typeof ToolCallResponseSchema>;
      try {
        const raw = (await response.json()) as Record<string, unknown>;
        if (useToolEnvelope) {
          const choice = (
            raw.choices as
              | Array<{ message?: { content?: string | null } }>
              | undefined
          )?.[0];
          const content = choice?.message?.content ?? null;
          const envelope = parseToolEnvelopeContent(content);
          payload = ToolCallResponseSchema.parse(
            synthesizeOpenAiToolCallResponse({
              model: this.model,
              content,
              envelope: envelope
                ? {
                    name: envelope.name,
                    argumentsJson: envelope.argumentsJson
                  }
                : null,
              usage:
                raw.usage && typeof raw.usage === "object"
                  ? (raw.usage as Record<string, unknown>)
                  : {}
            })
          );
        } else {
          payload = ToolCallResponseSchema.parse(raw);
        }
      } catch {
        throw new ModelProviderError(
          "MODEL_RESPONSE_INVALID",
          "Local vLLM returned an invalid response payload."
        );
      }
      const toolCalls = payload.choices[0]!.message.tool_calls ?? [];
      if (toolCalls.length === 0) {
        const content = payload.choices[0]!.message.content;
        const protocolInContent = contentLooksLikeProtocolObject(content);
        const finalGoal = trustedFinalContentGoal(input);
        if (
          mode === "FINAL_ONLY" &&
          typeof content === "string" &&
          content.trim().length > 0 &&
          !protocolInContent &&
          finalGoal
        ) {
          return {
            kind: "final",
            goal: finalGoal,
            message: content.trim(),
            reasonCode: null,
            transport: "content_final",
            model: this.model,
            privacy_violation: requestPrivacyViolation,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
        if (nativeProtocolRetries < MAX_NATIVE_PROTOCOL_RETRIES && canRetryWithinTurn) {
          nativeProtocolRetries += 1;
          formatRetryReasons.push(
            protocolInContent
              ? "pseudo_tool_content_not_native"
              : "missing_native_function_call"
          );
          messages = createNativeFunctionRetryMessages(
            baseMessages,
            content,
            mode
          );
          continue;
        }
        // Fail closed: never execute pseudo JSON in content as a Domain tool.
        return {
          kind: "refuse",
          goal: "unsupported",
          message:
            "模型未返回合法的原生函数决策，本轮未执行任何业务操作。请换一种说法重试。",
          reasonCode: "UNSUPPORTED_OR_UNCLEAR",
          model: this.model,
          privacy_violation: requestPrivacyViolation,
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }

      const call = toolCalls[0]!.function;
      const textPrivacyViolation =
        requestPrivacyViolation ||
        detectPrivacyLeakInToolArgumentText(
          call.arguments,
          input.memberDirectory,
          input.userText
        );

      if (isControlDecisionName(call.name)) {
        if (
          mode === "ACTION_ALLOWED" &&
          forcedTool &&
          !isControlDecisionName(forcedTool)
        ) {
          // Schema recovery is locked to the business tool being repaired.
          return {
            kind: "refuse",
            goal: "unsupported",
            message: "模型在格式重试中更换了决策函数，本轮未执行。",
            reasonCode: "UNSUPPORTED_OR_UNCLEAR",
            model: this.model,
            privacy_violation: textPrivacyViolation,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
        if (mode === "FINAL_ONLY" && call.name === "refuse_request") {
          // FINAL_ONLY is for grounded completion after tools, not a fresh refuse.
          if (nativeProtocolRetries < MAX_NATIVE_PROTOCOL_RETRIES && canRetryWithinTurn) {
            nativeProtocolRetries += 1;
            formatRetryReasons.push("refuse_forbidden_in_final_only");
            messages = createNativeFunctionRetryMessages(
              baseMessages,
              call.arguments,
              "FINAL_ONLY",
              {
                reason: "refuse_forbidden_in_final_only",
                validationErrors: [
                  "refuse_request is not allowed in FINAL_ONLY; call finish_turn (preferred) or ask_user with real missingFields"
                ]
              }
            );
            continue;
          }
        }
        if (
          mode !== "ACTION_ALLOWED" &&
          call.name !== "ask_user" &&
          call.name !== "finish_turn" &&
          call.name !== "refuse_request"
        ) {
          return {
            kind: "refuse",
            goal: "unsupported",
            message: "当前回合不允许该控制决策。",
            reasonCode: "UNSUPPORTED_OR_UNCLEAR",
            model: this.model,
            privacy_violation: textPrivacyViolation,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
        let controlArgs: Record<string, unknown>;
        try {
          controlArgs = parseJsonObject(call.arguments);
        } catch {
          if (nativeProtocolRetries < MAX_NATIVE_PROTOCOL_RETRIES && canRetryWithinTurn) {
            nativeProtocolRetries += 1;
            formatRetryReasons.push("control_arguments_invalid");
            messages = createNativeFunctionRetryMessages(
              baseMessages,
              call.arguments,
              mode,
              {
                reason: "control_arguments_invalid",
                validationErrors: [
                  "control decision arguments must be one valid JSON object"
                ]
              }
            );
            continue;
          }
          return {
            kind: "refuse",
            goal: "unsupported",
            message: "控制决策参数无效，本轮未执行任何业务操作。",
            reasonCode: "UNSUPPORTED_OR_UNCLEAR",
            model: this.model,
            privacy_violation: textPrivacyViolation,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
        try {
          const control = parseControlDecisionArguments(
            call.name as ControlDecisionName,
            controlArgs
          );
          if (control.kind === "ask_user") {
            // Drop slots already answerable from this userText via existing product
            // slot resolvers (no inventing). Remaining empty → schema retry so the
            // model continues with Domain tools (e.g. compose after 规划午餐).
            let askFields = [...control.missingFields];
            const alreadyPresent: string[] = [];
            if (askFields.includes("mealType")) {
              const meal = resolveMealTypeSlot(input.userText);
              if (meal.status === "ok") {
                alreadyPresent.push(`mealType=${meal.value}`);
                askFields = askFields.filter((field) => field !== "mealType");
              }
            }
            if (askFields.includes("recipientLabel")) {
              const recipient = resolveHandoffRecipient(input.userText);
              if (recipient.status === "ok") {
                alreadyPresent.push(`recipientLabel=${recipient.value}`);
                askFields = askFields.filter(
                  (field) => field !== "recipientLabel"
                );
              }
            }
            if (askFields.length === 0) {
              if (nativeProtocolRetries < MAX_NATIVE_PROTOCOL_RETRIES && canRetryWithinTurn) {
                nativeProtocolRetries += 1;
                formatRetryReasons.push("ask_user_slots_already_in_user_text");
                messages = createNativeFunctionRetryMessages(
                  baseMessages,
                  call.arguments,
                  mode,
                  {
                    reason: "ask_user_slots_already_in_user_text",
                    validationErrors: [
                      `ask_user.missingFields are already present in the user request (${alreadyPresent.join(", ") || "resolved"}). Do not ask again.`,
                      "If the goal is compose_meal, call finalize_meal_plan with the known mealType/dinerIds. If the goal is revise_meal and activePlan exists, call finalize_meal_plan."
                    ]
                  }
                );
                continue;
              }
              return {
                kind: "refuse",
                goal: "unsupported",
                message:
                  "模型提出了无明确缺失字段的追问，本轮未执行。请直接说明具体需求。",
                reasonCode: "UNSUPPORTED_OR_UNCLEAR",
                model: this.model,
                privacy_violation: textPrivacyViolation,
                format_retry_count: formatRetryReasons.length,
                format_retry_reasons: formatRetryReasons
              };
            }
            return {
              kind: "ask_user",
              goal: control.goal,
              tool: null,
              message: control.message,
              missingFields: askFields,
              raw_model_arguments: controlArgs,
              normalized_model_arguments: {
                goal: control.goal,
                message: control.message,
                missingFields: askFields
              },
              effective_arguments: null,
              policy: {
                status: "needs_clarification",
                effective: null,
                privacy_violation: textPrivacyViolation,
                reasons: askFields.map((field) => `${field}_missing`)
              },
              privacy_violation: textPrivacyViolation,
              model: this.model,
              reasons: askFields.map((field) => `${field}_missing`),
              format_retry_count: formatRetryReasons.length,
              format_retry_reasons: formatRetryReasons
            };
          }
          if (control.kind === "final") {
            return {
              kind: "final",
              goal: control.goal,
              message: control.message,
              reasonCode: null,
              transport: "native_function",
              model: this.model,
              privacy_violation: textPrivacyViolation,
              format_retry_count: formatRetryReasons.length,
              format_retry_reasons: formatRetryReasons
            };
          }
          return {
            kind: "refuse",
            goal: "unsupported",
            message: control.message,
            reasonCode: control.reasonCode,
            model: this.model,
            privacy_violation: textPrivacyViolation,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        } catch (error) {
          if (nativeProtocolRetries < MAX_NATIVE_PROTOCOL_RETRIES && canRetryWithinTurn) {
            nativeProtocolRetries += 1;
            formatRetryReasons.push("control_schema_invalid");
            messages = createNativeFunctionRetryMessages(
              baseMessages,
              call.arguments,
              mode,
              {
                reason: "control_schema_invalid",
                validationErrors: describeSchemaErrors(error),
                controlName: call.name
              }
            );
            continue;
          }
          return {
            kind: "refuse",
            goal: "unsupported",
            message: "控制决策未通过合同校验，本轮未执行任何业务操作。",
            reasonCode: "UNSUPPORTED_OR_UNCLEAR",
            model: this.model,
            privacy_violation: textPrivacyViolation,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
      }

      if (!(AGENT_TOOL_ALLOWLIST as readonly string[]).includes(call.name)) {
        return {
          kind: "refuse",
          goal: "unsupported",
          message: "模型请求了不受支持的工具，本轮未执行任何操作。",
          reasonCode: "UNSUPPORTED_TOOL",
          model: this.model,
          privacy_violation: textPrivacyViolation,
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }

      // Domain tools only in ACTION_ALLOWED.
      if (mode !== "ACTION_ALLOWED") {
        if (nativeProtocolRetries < MAX_NATIVE_PROTOCOL_RETRIES && canRetryWithinTurn) {
          nativeProtocolRetries += 1;
          formatRetryReasons.push("domain_tool_forbidden_in_mode");
          messages = createNativeFunctionRetryMessages(
            baseMessages,
            call.arguments,
            mode
          );
          continue;
        }
        return {
          kind: "refuse",
          goal: "unsupported",
          message: "当前回合不允许业务工具调用，本轮未执行。",
          reasonCode: "UNSUPPORTED_OR_UNCLEAR",
          model: this.model,
          privacy_violation: textPrivacyViolation,
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }

      const tool = call.name as AgentToolName;
      if (forcedTool && tool !== forcedTool) {
        const policy: PolicyResult = {
          status: "needs_clarification",
          effective: null,
          privacy_violation: textPrivacyViolation,
          reasons: [
            formatRetryTool
              ? "format_retry_tool_changed"
              : "pending_clarification_tool_changed"
          ]
        };
        return {
          kind: "ask_user",
          goal: fallbackGoalForAttempt(tool, input.pendingClarification),
          tool,
          message: "模型步骤不符合当前待处理操作，请补充信息后重试。",
          missingFields: missingFieldsFromPolicyReasons(policy.reasons),
          raw_model_arguments: null,
          normalized_model_arguments: null,
          effective_arguments: null,
          policy,
          privacy_violation: textPrivacyViolation,
          model: this.model,
          reasons: policy.reasons,
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }
      let parsedArguments: Record<string, unknown>;
      try {
        parsedArguments = parseJsonObject(call.arguments);
      } catch {
        if (
          !textPrivacyViolation &&
          formatRetryReasons.length === 0 &&
          canRetryWithinTurn
        ) {
          formatRetryReasons.push("raw_json_invalid");
          formatRetryTool = tool;
          messages = createFormatRetryMessages(
            baseMessages,
            tool,
            call.arguments,
            "raw_json_invalid",
            ["arguments must be one valid JSON object"]
          );
          continue;
        }
        if (textPrivacyViolation) {
          const policy: PolicyResult = {
            status: "needs_clarification",
            effective: null,
            privacy_violation: true,
            reasons: ["raw_json_invalid"]
          };
          return {
            kind: "ask_user",
            goal: fallbackGoalForAttempt(tool, input.pendingClarification),
            tool,
            message: "检测到隐私风险，本轮不会执行。请缩小请求范围。",
            missingFields: [],
            raw_model_arguments: null,
            normalized_model_arguments: null,
            effective_arguments: null,
            policy,
            privacy_violation: true,
            model: this.model,
            reasons: policy.reasons,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
        throw new ModelProviderError(
          "MODEL_TOOL_ARGUMENT_INVALID",
          "Model tool arguments were not valid JSON after retry."
        );
      }
      const privacy_violation =
        textPrivacyViolation ||
        detectPrivacyLeakInToolArguments(
          parsedArguments,
          input.memberDirectory,
          input.userText
        );
      // Only transport-safe normalization happens inside parseModelToolArguments.
      // Semantic fields must remain visible so an invalid name can trigger a
      // bounded schema retry instead of being silently discarded.
      const argumentsForSchema = parsedArguments;

      let normalized_model_arguments: Record<string, unknown>;
      let modelGoal: AgentGoal;
      try {
        modelGoal = parseModelToolGoal(tool, argumentsForSchema);
        normalized_model_arguments = parseModelToolArguments(
          tool,
          argumentsForSchema
        );
      } catch (error) {
        if (
          !privacy_violation &&
          formatRetryReasons.length === 0 &&
          canRetryWithinTurn
        ) {
          formatRetryReasons.push("raw_schema_invalid");
          formatRetryTool = tool;
          messages = createFormatRetryMessages(
            baseMessages,
            tool,
            call.arguments,
            "raw_schema_invalid",
            describeSchemaErrors(error)
          );
          continue;
        }
        if (privacy_violation) {
          const policy: PolicyResult = {
            status: "needs_clarification",
            effective: null,
            privacy_violation: true,
            reasons: ["raw_schema_invalid"]
          };
          return {
            kind: "ask_user",
            goal: fallbackGoalForAttempt(
              tool,
              input.pendingClarification,
              argumentsForSchema
            ),
            tool,
            message: "检测到隐私风险，本轮不会执行。请缩小请求范围。",
            missingFields: [],
            raw_model_arguments: parsedArguments,
            normalized_model_arguments: argumentsForSchema,
            effective_arguments: null,
            policy,
            privacy_violation: true,
            model: this.model,
            reasons: policy.reasons,
            format_retry_count: formatRetryReasons.length,
            format_retry_reasons: formatRetryReasons
          };
        }
        throw new ModelProviderError(
          "MODEL_TOOL_ARGUMENT_INVALID",
          "Model tool arguments did not match the selected tool schema after retry."
        );
      }

      const dictionary = toPolicyDictionary(input);
      const policy = applyTrustedArgumentPolicy({
        tool,
        userText: input.userText,
        dinerIdsLocked: input.dinerIdsLocked,
        state: {
          dinerIds: input.state.dinerIds,
          activePlanId: input.state.activePlanId,
          activePlanVersion: input.state.activePlanVersion,
          activePlanTemplateIds:
            input.activePlan?.menu.map((item) => item.templateId) ?? [],
          focusedTemplateId: input.focusedTemplateId ?? null,
          expectedRecipientLabel: expectedRecipientLabel(input),
          knownServeAt:
            typeof input.pendingClarification?.known?.serveAt === "string"
              ? input.pendingClarification.known.serveAt
              : null,
          rejectedFoodIds: input.state.rejectedFoodIds,
          rejectedTemplateIds: input.state.rejectedTemplateIds
        },
        dictionary,
        rawArgs: normalized_model_arguments
      });

      const privacyHit = privacy_violation || policy.privacy_violation === true;

      // Already-satisfied revise → finish without Domain write (not a user ask).
      if (
        tool === "finalize_meal_plan" &&
        policy.status === "needs_clarification" &&
        policy.reasons.includes("revision_noop_already_applied")
      ) {
        return {
          kind: "final",
          goal:
            modelGoal === "unsupported" || modelGoal === "no_action"
              ? "revise_meal"
              : (modelGoal as Exclude<AgentGoal, "unsupported">),
          message: "当前拒绝项已在计划中保留，无需再次修改。",
          reasonCode: null,
          transport: "native_function",
          model: this.model,
          privacy_violation: privacyHit,
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }

      if (policy.status !== "ok" || !policy.effective) {
        const reasons =
          privacyHit &&
          !policy.reasons.includes("privacy_violation_blocks_execution")
            ? [...policy.reasons, "privacy_violation_blocks_execution"]
            : policy.reasons;
        return {
          kind: "ask_user",
          goal: modelGoal,
          tool,
          message: "当前参数未通过业务校验，请补充缺少的信息。",
          missingFields: missingFieldsFromPolicyReasons(reasons),
          raw_model_arguments: parsedArguments,
          normalized_model_arguments,
          effective_arguments: null,
          policy,
          privacy_violation: privacyHit,
          model: this.model,
          reasons,
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }

      // Fail closed: privacy violations never return an executable tool decision.
      if (privacyHit) {
        return {
          kind: "ask_user",
          goal: modelGoal,
          tool,
          message: "检测到隐私风险，本轮不会执行。请缩小请求范围。",
          // Privacy blocks are not user-slot clarifications.
          missingFields: [],
          raw_model_arguments: parsedArguments,
          normalized_model_arguments,
          effective_arguments: null,
          policy: {
            status: "needs_clarification",
            effective: null,
            privacy_violation: true,
            reasons: [...policy.reasons, "privacy_violation_blocks_execution"]
          },
          privacy_violation: true,
          model: this.model,
          reasons: [...policy.reasons, "privacy_violation_blocks_execution"],
          format_retry_count: formatRetryReasons.length,
          format_retry_reasons: formatRetryReasons
        };
      }

      return {
        kind: "tool",
        goal: modelGoal,
        tool,
        arguments: policy.effective,
        raw_model_arguments: parsedArguments,
        normalized_model_arguments:
          policy.modelNormalized ?? normalized_model_arguments,
        effective_arguments: policy.effective,
        policy,
        privacy_violation: false,
        model: this.model,
        format_retry_count: formatRetryReasons.length,
        format_retry_reasons: formatRetryReasons
      };
    }
  }
}

function createFormatRetryMessages(
  baseMessages: Array<{ role: string; content: string }>,
  tool: AgentToolName,
  previousArguments: string,
  reason: "raw_json_invalid" | "raw_schema_invalid",
  validationErrors: string[]
) {
  const definition = PRIVATEPLATE_MODEL_TOOLS.find(
    (item) => item.function.name === tool
  );
  if (!definition) {
    throw new Error(`Missing tool definition for format retry: ${tool}`);
  }
  const parameters = definition.function.parameters;
  return [
    ...baseMessages,
    {
      role: "user",
      content: JSON.stringify({
        retryInstruction:
          "Call the same tool once more. Return its arguments as one JSON object (or as {\"name\",\"arguments\"} when using the tool envelope). Remove undeclared properties, add required properties, preserve the original meaning, and do not wrap string values in extra quote characters.",
        reason,
        tool,
        previousArguments: parseArgumentsForRetry(previousArguments),
        validationErrors,
        allowedProperties: Object.keys(parameters.properties),
        requiredProperties: parameters.required
      })
    }
  ];
}

function selectProviderTools(
  mode: AgentLoopMode,
  forcedTool: AgentToolName | null,
  availableActions?: { domainTools: string[]; controlDecisions: string[] }
): Array<(typeof PRIVATEPLATE_MODEL_TOOLS)[number] | (typeof PRIVATEPLATE_CONTROL_TOOLS)[number]> {
  if (forcedTool) {
    return PRIVATEPLATE_MODEL_TOOLS.filter(
      (item) => item.function.name === forcedTool
    );
  }
  const domainAllow = new Set(
    availableActions?.domainTools ??
      (mode === "ACTION_ALLOWED"
        ? PRIVATEPLATE_MODEL_TOOLS.map((item) => item.function.name)
        : [])
  );
  const controlAllow = new Set(
    availableActions?.controlDecisions ??
      (mode === "FINAL_ONLY"
        ? ["finish_turn", "ask_user"]
        : mode === "BLOCKED"
          ? ["finish_turn", "ask_user", "refuse_request"]
          : CONTROL_DECISION_NAMES as unknown as string[])
  );
  const domainTools = PRIVATEPLATE_MODEL_TOOLS.filter((item) =>
    domainAllow.has(item.function.name)
  );
  const controlTools = PRIVATEPLATE_CONTROL_TOOLS.filter((item) =>
    controlAllow.has(item.function.name)
  );
  return [...domainTools, ...controlTools];
}

function createNativeFunctionRetryMessages(
  baseMessages: Array<{ role: string; content: string }>,
  previousContent: string | null | undefined,
  mode: AgentLoopMode | string,
  detail?: {
    reason?: string;
    validationErrors?: string[];
    controlName?: string;
  }
) {
  // Schema / field retries must not claim "not a native function call".
  const schemaRetry =
    detail?.reason === "control_schema_invalid" ||
    detail?.reason === "ask_user_empty_missing_fields" ||
    detail?.reason === "ask_user_slots_already_in_user_text" ||
    detail?.reason === "control_arguments_invalid" ||
    detail?.reason === "refuse_forbidden_in_final_only" ||
    (detail?.validationErrors && detail.validationErrors.length > 0);

  const retryInstruction = schemaRetry
    ? mode === "FINAL_ONLY"
      ? "The previous control decision failed field/schema validation. Call exactly one allowed control function with valid arguments: finish_turn (preferred when toolResults already satisfy the goal) or ask_user with real missingFields from the allowlist. Do not call Domain tools."
      : mode === "BLOCKED"
        ? "The previous control decision failed field/schema validation. Call exactly one control function with valid arguments: finish_turn, ask_user or refuse_request. Do not call Domain tools."
        : "The previous decision failed field/schema validation. Call exactly one supplied function with valid arguments (a Domain tool, ask_user, finish_turn or refuse_request). If the goal is compose_meal, context was already read, and no slots are missing, call finalize_meal_plan. For finalize_meal_plan, cover the three roles first; each role may include more than one dish for a richer table. ask_user.missingFields must be a non-empty subset of the allowlisted slots only."
    : mode === "FINAL_ONLY"
      ? "The previous response was not a native function call. Call exactly one allowed control function now: finish_turn (preferred when toolResults already satisfy the goal) or ask_user. Do not put JSON decisions in plain content. Do not call Domain tools."
      : mode === "BLOCKED"
        ? "The previous response was not a native function call. Call exactly one control function: finish_turn, ask_user or refuse_request. Do not call Domain tools and do not put decisions in plain content."
        : "The previous response was not a native function call. Call exactly one supplied function now (a Domain tool, ask_user, finish_turn or refuse_request). For finalize_meal_plan, cover the three roles first; each role may include more than one dish for a richer table. Do not put tool or decision JSON in plain message content; plain content is never executed.";
  return [
    ...baseMessages,
    {
      role: "assistant",
      content: previousContent ?? ""
    },
    {
      role: "user",
      content: JSON.stringify({
        retryInstruction,
        ...(detail?.reason ? { reason: detail.reason } : {}),
        ...(detail?.controlName ? { controlName: detail.controlName } : {}),
        ...(detail?.validationErrors?.length
          ? { validationErrors: detail.validationErrors }
          : {})
      })
    }
  ];
}

function buildPlanningRecoveryHint(
  turn: ModelTurnContext
): Record<string, unknown> | null {
  const lastFailed = [...turn.toolResults]
    .reverse()
    .find(
      (result) =>
        result.tool === "finalize_meal_plan" && !isSuccessfulToolOutcome(result)
    );
  if (!lastFailed?.data) return null;
  const recovery =
    (lastFailed.data.recovery as Record<string, unknown> | undefined) ??
    (lastFailed.data.details as Record<string, unknown> | undefined) ??
    null;
  if (!recovery) return null;
  return {
    instruction:
      "Previous finalize_meal_plan failed. Reselect with a DIFFERENT selectedDishes and/or mealPortionScale. Do not repeat the failed selection. Follow recommendedActions. If feasibleSuggestion is present, prefer adopting that Domain-verified selection unless soft preferences conflict.",
    code: lastFailed.data.code ?? lastFailed.code ?? null,
    recommendedActions: Array.isArray(recovery.recommendedActions)
      ? recovery.recommendedActions
      : [],
    deficits: Array.isArray(recovery.deficits) ? recovery.deficits : [],
    failureKind: recovery.failureKind ?? null,
    reselectAllowed: recovery.reselectAllowed === true,
    feasibleSuggestion: recovery.feasibleSuggestion ?? null,
    domainSearchExhausted: recovery.domainSearchExhausted === true,
    modeReason: turn.modeReason
  };
}

function trustedFinalContentGoal(
  input: ModelRouteInput
): Exclude<AgentGoal, "no_action" | "unsupported"> | null {
  const currentGoal = input.currentTurn.goal;
  if (isFinalContentGoal(currentGoal)) return currentGoal;

  const objective = input.taskState?.objective;
  return isFinalContentGoal(objective) ? objective : null;
}

function isFinalContentGoal(
  value: unknown
): value is Exclude<AgentGoal, "no_action" | "unsupported"> {
  return (
    value === "inspect_context" ||
    value === "compose_meal" ||
    value === "revise_meal" ||
    value === "retrieve_guidance" ||
    value === "preview_handoff" ||
    value === "send_handoff" ||
    value === "preview_inventory" ||
    value === "update_inventory" ||
    value === "preview_member_memory" ||
    value === "update_member_memory" ||
    value === "preview_meal_completion" ||
    value === "complete_meal"
  );
}

function parseArgumentsForRetry(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function describeSchemaErrors(error: unknown): string[] {
  if (!(error instanceof z.ZodError)) {
    return ["arguments do not match the selected tool schema"];
  }
  return error.issues.map((issue) => {
    const path = issue.path.length > 0 ? issue.path.join(".") : "<root>";
    return `${path}: ${issue.message}`;
  });
}

function fallbackGoalForAttempt(
  tool: AgentToolName,
  pending: ModelPendingClarification | null,
  argumentsForSchema?: Record<string, unknown>
): AgentGoal {
  const explicitGoal = argumentsForSchema?.goal;
  if (
    explicitGoal === "inspect_context" ||
    explicitGoal === "compose_meal" ||
    explicitGoal === "revise_meal" ||
    explicitGoal === "retrieve_guidance" ||
    explicitGoal === "preview_handoff" ||
    explicitGoal === "send_handoff" ||
    explicitGoal === "preview_inventory" ||
    explicitGoal === "update_inventory" ||
    explicitGoal === "preview_member_memory" ||
    explicitGoal === "update_member_memory" ||
    explicitGoal === "preview_meal_completion" ||
    explicitGoal === "complete_meal"
  ) {
    return explicitGoal;
  }
  if (tool === "preview_caregiver_task") {
    return pending?.goal ?? "preview_handoff";
  }
  return goalForTool(tool);
}

function expectedRecipientLabel(input: ModelRouteInput): string | null {
  const allowed =
    input.fixtureDirectory.caregiverRecipientLabels ?? [
      "家庭保姆",
      "保姆",
      "阿姨"
    ];
  const recipient = resolveHandoffRecipient(input.userText, allowed);
  return recipient.status === "ok" ? recipient.value : null;
}

function toPolicyDictionary(input: ModelRouteInput): PolicyDictionary {
  return {
    members: input.memberDirectory,
    foods: input.fixtureDirectory.foods,
    templates: input.fixtureDirectory.templates,
    planTags: input.fixtureDirectory.planTags ?? [],
    caregiverRecipientLabels:
      input.fixtureDirectory.caregiverRecipientLabels ?? [
        "家庭保姆",
        "保姆",
        "阿姨"
      ]
  };
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Model tool arguments must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function isLoopbackHost(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}
