import { randomUUID } from "node:crypto";
import type { PrivatePlateDomain } from "@privateplate/domain";
import {
  collectAllowedNumbers,
  collectAllowedDates,
  collectGroundedTexts,
  collectIds,
  extractDates,
  extractNumbers,
  hasCurrencyEvidence,
  validateFinalAnswer
} from "./answer-validate.js";
import {
  buildTaskOutcome,
  type AgentGoal,
  type AgentModelStep,
  type ModelDecisionKind,
  type ModelDecisionTransport,
  type TaskOutcome
} from "./contracts.js";
import {
  resolveLoopTransition,
  type AgentLoopMode
} from "./loop-mode.js";
import type {
  AgentModelProvider,
  ModelActivePlan,
  ModelConversationTurn,
  ModelPendingClarification,
  ModelRouteDecision,
  ModelRouteInput,
  ModelTurnContext,
  ModelVisibleToolResult
} from "./model/provider.js";
import { renderDeterministicFinal, renderStructuredInfeasible } from "./model/deterministic-final.js";
import { modelProviderErrorCode } from "./model/errors.js";
import {
  resolveFinalizationMode,
  type FinalizationMode,
  type TurnFinalizationMode
} from "./model/finalization-mode.js";
import {
  projectModelToolResultsForNextDecision,
  toModelVisibleToolResult
} from "./model/tool-result.js";
import {
  isTrustedPresenterTool,
  renderTrustedPresenter
} from "./model/trusted-presenter.js";
import { capabilityBoundaryGate } from "./capability-boundary.js";
import { hardSafetyGate } from "./policy.js";
import {
  applyTaskTransition,
  beginUserTurnTaskState,
  computeAvailableActions,
  createEmptyTaskState,
  phaseAfterToolFailure,
  successfulToolCallKey,
  toModelVisibleTaskState,
  type TaskState
} from "./task-state.js";
import {
  buildCheckpointV2,
  parseCheckpointPayload,
  type AgentCheckpointV2
} from "./checkpoint-v2.js";
import {
  createInitialState,
  type AgentIntent,
  type AgentState,
  type AgentToolName,
  type GraphPhase
} from "./state.js";
import {
  ToolGateway,
  type ToolGatewayResult,
  type UiOnlySideChannel
} from "./tools/gateway.js";
import type { ToolResult } from "./tools/types.js";
import {
  classifyToolOutcome,
  isSuccessfulToolOutcome,
  type ToolOutcomeLike
} from "./tool-outcome.js";

import {
  resolveHandoffRecipient,
  resolveHandoffServeAt,
  SAFE_DEFAULTS,
  type RoutingEvidenceKind
} from "./product-semantics.js";

export type AgentTurnResult = {
  answer: string;
  state: AgentState;
  phase: GraphPhase;
  toolTrace: Array<{
    tool: string;
    ok: boolean;
    durationMs: number;
    code?: string;
  }>;
  uiOnly?: UiOnlySideChannel;
  validationOk: boolean;
  validationReasons?: string[];
  modelSteps: AgentModelStep[];
  taskOutcome: TaskOutcome;
  finalizationMode?: TurnFinalizationMode;
  /**
   * Evidence classification for evals/submission.
   * model_routed / model_clarification for evals.
   */
  routingEvidenceKind?: RoutingEvidenceKind;
  /** Present when a model/scripted provider was invoked this turn. */
  modelTrace?: {
    providerMode: string;
    model: string;
    decisionKind: ModelRouteDecision["kind"];
    transport: ModelDecisionTransport;
    tool: string | null;
    raw_model_arguments: Record<string, unknown> | null;
    normalized_model_arguments: Record<string, unknown> | null;
    effective_arguments: Record<string, unknown> | null;
    privacy_violation: boolean;
    policy_reasons: string[];
    format_retry_count: number;
    format_retry_reasons: string[];
  };
};

type PendingPreviewMetadata = Omit<
  UiOnlySideChannel,
  "confirmationToken"
>;

type LoopGoal = Exclude<AgentGoal, "no_action" | "unsupported">;

export type PrivatePlateAgentOptions = {
  finalizationMode?: FinalizationMode;
};

const MAX_MODEL_REQUESTS_PER_TURN = 10;
const MAX_PLAN_ATTEMPTS_PER_TURN = 3;
const MAX_ANSWER_REGENERATIONS = 1;
const MAX_HISTORY_ASSISTANT_LENGTH = 600;

export class PrivatePlateAgentCore {
  readonly domain: PrivatePlateDomain;
  readonly gateway: ToolGateway;
  state: AgentState;
  pendingPreviewMetadata: PendingPreviewMetadata | null = null;
  private pendingClarification: ModelPendingClarification | null = null;
  private conversationHistory: ModelConversationTurn[] = [];
  private lastToolPayloads: unknown[] = [];
  private lastRetrievalIds: string[] = [];
  private readonly modelProvider: AgentModelProvider | null;
  private readonly finalizationMode: FinalizationMode;
  private currentGoal: AgentGoal = "unsupported";
  private currentDecision: ModelDecisionKind | undefined;
  private currentBlockingReasons: string[] = [];
  private currentModelSteps: AgentModelStep[] = [];
  private currentFallbackCodes: string[] = [];
  private currentFinalizationMode: TurnFinalizationMode | undefined;
  private focusedTemplateId: string | null = null;
  private taskState: TaskState = createEmptyTaskState();

  constructor(
    domain: PrivatePlateDomain,
    sessionId = `agent-${randomUUID()}`,
    modelProvider: AgentModelProvider | null = null,
    options: PrivatePlateAgentOptions = {}
  ) {
    this.domain = domain;
    this.gateway = new ToolGateway(domain);
    this.modelProvider = modelProvider;
    this.finalizationMode =
      options.finalizationMode ?? resolveFinalizationMode();
    const members = domain.getMembers();
    this.state = createInitialState({
      sessionId,
      householdId: domain.householdId,
      dinerIds: members.map((member) => member.id)
    });
    this.taskState = createEmptyTaskState();
  }

  getTaskState(): TaskState {
    return {
      ...this.taskState,
      knownSlots: { ...this.taskState.knownSlots },
      unresolvedSlots: [...this.taskState.unresolvedSlots]
    };
  }

  /** Read-only source ids from the most recent model turn for eval telemetry. */
  getLastRetrievalIds(): string[] {
    return [...this.lastRetrievalIds];
  }

  /** Seed a prior domain failure (e.g. Public Golden infeasible fixtures). */
  seedLastDomainFailure(code: string): void {
    this.taskState = {
      ...this.taskState,
      lastDomainFailureCode: code,
      status: "blocked"
    };
    this.state = {
      ...this.state,
      lastToolStatus: "failure",
      errorCode: code
    };
  }

  exportCheckpoint(): AgentCheckpointV2 {
    return buildCheckpointV2(this.state, {
      ...this.taskState,
      focusedTemplateId: this.focusedTemplateId,
      pendingActionId:
        this.taskState.pendingActionId ?? this.state.pendingActionId
    });
  }

  async handleUserMessage(
    userText: string,
    lockedDinerIds?: string[]
  ): Promise<AgentTurnResult> {
    const turn = await this.handleUserMessageInternal(userText, lockedDinerIds);
    this.rememberConversationTurn(userText, turn);
    return turn;
  }

  setFocusedTemplateId(templateId: string | null): void {
    if (
      templateId &&
      !this.activePlanForModel()?.menu.some(
        (item) => item.templateId === templateId
      )
    ) {
      throw new Error("Focused template must belong to the active plan.");
    }
    this.focusedTemplateId = templateId;
    this.taskState = applyTaskTransition(this.taskState, {
      type: "set_focus",
      templateId
    });
  }

  private async handleUserMessageInternal(
    userText: string,
    lockedDinerIds?: string[]
  ): Promise<AgentTurnResult> {
    const priorOutcome = {
      phase: this.state.phase,
      lastToolStatus: this.state.lastToolStatus,
      errorCode: this.state.errorCode
    };
    this.state = {
      ...this.state,
      phase: "CLASSIFYING",
      toolSteps: 0,
      errorCode: null
    };
    this.lastToolPayloads = [];
    this.lastRetrievalIds = [];
    this.currentDecision = undefined;
    this.currentBlockingReasons = [];
    this.currentModelSteps = [];
    this.currentFallbackCodes = [];
    this.currentFinalizationMode = undefined;
    // New-turn lifecycle: only resume objective when waiting_user + real slots.
    this.taskState = beginUserTurnTaskState(this.taskState);
    if (
      this.taskState.status === "waiting_user" &&
      this.taskState.unresolvedSlots.length > 0
    ) {
      this.currentGoal = this.taskState.objective ?? "unsupported";
    } else if (this.taskState.status !== "waiting_confirmation") {
      this.currentGoal = "unsupported";
    }

    // Model-routed path: hard safety + capability boundary, then model loop.
    if (this.modelProvider) {
      const safety = hardSafetyGate(userText);
      if (!safety.allowed) {
        this.currentGoal = "unsupported";
        this.currentDecision = "refuse";
        this.currentBlockingReasons = [safety.reason];
        this.state.phase = "SAFE_STOP";
        return this.finalize(safety.userMessage, []);
      }

      // Chat cannot confirm-send or reuse stale previews — refuse before model.
      const boundary = capabilityBoundaryGate(userText, this.state);
      if (boundary) {
        this.currentGoal = boundary.goal;
        this.currentDecision = "refuse";
        this.currentBlockingReasons = [boundary.reasonCode.toLowerCase()];
        this.state.phase = "AWAITING_USER";
        this.taskState = applyTaskTransition(this.taskState, {
          type: "block_task",
          reasonCode: boundary.reasonCode,
          keepSlots: false
        });
        this.currentModelSteps.push({
          index: 0,
          providerMode: this.modelProvider.mode,
          model: this.modelProvider.model,
          decision: "refuse",
          goal: boundary.goal,
          tool: null,
          rawArguments: null,
          normalizedArguments: null,
          effectiveArguments: null,
          policy: {
            status: "not_applicable",
            reasons: [boundary.reasonCode],
            privacyViolation: false
          },
          missingFields: []
        });
        return {
          ...this.finalize(boundary.message, []),
          routingEvidenceKind: "model_clarification"
        };
      }

      // pendingClarification lifecycle is owned by the model decision loop.
      // The model sees pendingClarification in its context and decides whether
      // the user is clarifying or starting a new goal.

      const turn = await this.runModelRoutedTurn(
        userText,
        lockedDinerIds,
        priorOutcome
      );
      return {
        ...turn,
        routingEvidenceKind:
          turn.routingEvidenceKind ??
          (turn.phase === "AWAITING_USER" && turn.toolTrace.length === 0
            ? "model_clarification"
            : "model_routed")
      };
    }

    throw new Error(
      "Agent requires a non-null model provider. Deterministic simulator has been removed; use PrivatePlateAgent with local_vllm or ScriptedProductProvider."
    );
  }

  restoreState(payload: AgentState | AgentCheckpointV2): void {
    const isV2 =
      payload &&
      typeof payload === "object" &&
      "schemaVersion" in payload &&
      (payload as AgentCheckpointV2).schemaVersion === 2;

    if (isV2) {
      const v2 = parseCheckpointPayload(payload);
      if (
        v2.agentState.sessionId !== this.state.sessionId ||
        v2.agentState.householdId !== this.domain.householdId
      ) {
        throw new Error("Checkpoint does not belong to this agent session.");
      }
      this.state = { ...v2.agentState };
      this.taskState = {
        ...v2.taskState,
        knownSlots: { ...v2.taskState.knownSlots },
        unresolvedSlots: [...v2.taskState.unresolvedSlots]
      };
      this.focusedTemplateId = v2.taskState.focusedTemplateId;
      // Re-hydrate goal/clarification from TaskState so the next turn can continue.
      this.currentGoal = v2.taskState.objective ?? "unsupported";
      this.pendingClarification = pendingClarificationFromTaskState(
        v2.taskState
      );
    } else {
      const state = payload as AgentState;
      if (
        state.sessionId !== this.state.sessionId ||
        state.householdId !== this.domain.householdId
      ) {
        throw new Error("Checkpoint does not belong to this agent session.");
      }
      this.state = { ...state };
      this.taskState = createEmptyTaskState();
      this.focusedTemplateId = null;
      this.pendingClarification = null;
      this.currentGoal = "unsupported";
    }
    // Tokens and preview UI metadata are session-local only; never restore secrets.
    this.pendingPreviewMetadata = null;
    this.conversationHistory = [];
  }

  selectDiners(dinerIds: string[]):
    | { ok: true }
    | { ok: false; message: string } {
    const memberIds = new Set(this.domain.getMembers().map((member) => member.id));
    const selected = [...new Set(dinerIds)];
    if (
      selected.length === 0 ||
      selected.length > 3 ||
      selected.some((id) => !memberIds.has(id))
    ) {
      return {
        ok: false,
        message: "请选择当前家庭列表中的 1–3 位就餐成员。"
      };
    }

    this.pendingClarification = null;
    const changed =
      selected.length !== this.state.dinerIds.length ||
      selected.some((id) => !this.state.dinerIds.includes(id));
    if (!changed) return { ok: true };

    this.focusedTemplateId = null;
    if (this.state.pendingActionId) {
      this.cancelPending(this.state.pendingActionId);
    }
    // Diner switch reloads household context: old plan/preview constraints do
    // not carry over (members have different constraints/allergies).
    this.state = {
      ...this.state,
      dinerIds: [...selected],
      mealSessionId: null,
      activePlanId: null,
      activePlanVersion: null,
      activeConstraintIds: [],
      rejectedTemplateIds: [],
      rejectedFoodIds: [],
      requestedPriorityFoodIds: [],
      preferLowEffort: false,
      pendingActionId: null,
      lastCommittedActionId: null,
      lastCommittedPayloadHash: null,
      confirmationStatus: "not_started",
      phase: "COLLECTING_CONTEXT"
    };
    this.taskState = applyTaskTransition(this.taskState, {
      type: "replace_objective",
      objective: "compose_meal"
    });
    this.taskState = applyTaskTransition(this.taskState, {
      type: "resolve_slots",
      slots: { dinerIds: [...selected] }
    });
    this.taskState = applyTaskTransition(this.taskState, {
      type: "set_focus",
      templateId: null
    });
    this.pendingClarification = null;
    return { ok: true };
  }

  private async runModelRoutedTurn(
    userText: string,
    lockedDinerIds: string[] | undefined,
    priorOutcome: NonNullable<ModelTurnContext["priorOutcome"]>
  ): Promise<AgentTurnResult> {
    const toolTrace: AgentTurnResult["toolTrace"] = [];
    const modelToolResults: ModelVisibleToolResult[] = [];
    // Do not pre-lock loopGoal from TaskState: that would treat a resumed
    // objective as already established this turn and false-flag legitimate
    // goal switches (clarify → inspect, preview → send). The model still sees
    // taskState + pendingClarification and should continue when appropriate.
    let loopGoal: LoopGoal | null = null;
    let loopMode: AgentLoopMode = "ACTION_ALLOWED";
    let loopModeReason = "goal_not_established";
    let modelRequestCount = 0;
    let decisionIndex = 0;
    let toolCallCount = 0;
    let planAttemptCount = 0;
    let answerRegenerationCount = 0;
    const successfulToolKeys = new Set<string>();
    let answerValidationFailure: {
      reasons: string[];
      regenerationAttempt: number;
    } | null = null;
    let uiOnly: UiOnlySideChannel | undefined;
    let lastModelTrace: AgentTurnResult["modelTrace"];

    while (modelRequestCount < MAX_MODEL_REQUESTS_PER_TURN) {
      let decision: ModelRouteDecision;
      try {
        decision = await this.modelProvider!.route(
          this.buildModelRouteInput({
            userText,
            ...(lockedDinerIds ? { lockedDinerIds } : {}),
            loopGoal,
            loopMode,
            loopModeReason,
            decisionIndex,
            modelRequestCount,
            modelToolResults,
            answerValidationFailure,
            priorOutcome
          })
        );
      } catch (error) {
        const errorCode = modelProviderErrorCode(error);
        if (
          loopMode !== "ACTION_ALLOWED" &&
          loopGoal &&
          modelToolResults.some(isSuccessfulToolOutcome)
        ) {
          const stopped = this.finishWithDeterministicFallback({
            goal: loopGoal,
            sourceCode: errorCode,
            loopMode,
            loopModeReason,
            toolResults: modelToolResults,
            toolTrace,
            ...(uiOnly ? { uiOnly } : {})
          });
          return {
            ...stopped,
            routingEvidenceKind: "model_routed",
            ...(lastModelTrace ? { modelTrace: lastModelTrace } : {})
          };
        }
        this.currentDecision = undefined;
        this.currentBlockingReasons = [errorCode];
        // Preserve any established loop goal; if none, use no_action so
        // buildTaskOutcome does not misclassify provider error as unsupported.
        this.currentGoal = loopGoal ?? "no_action";
        this.state = {
          ...this.state,
          phase: "ERROR",
          errorCode
        };
        const failed = this.finalize(
          errorCode === "MODEL_HTTP_ERROR"
            ? "本地模型暂时不可用，本轮不会继续执行。已完成的工具步骤会保留，请检查模型服务后重试。"
            : "模型输出未通过结构协议，本轮已安全停止。已完成的工具步骤会保留，请重试。",
          toolTrace,
          uiOnly
        );
        return {
          ...failed,
          routingEvidenceKind: "model_routed",
          ...(lastModelTrace ? { modelTrace: lastModelTrace } : {})
        };
      }

      decisionIndex += 1;
      modelRequestCount += 1 + decision.format_retry_count;

      // Domain already proved infeasible: normalize generic refuse to PLAN_INFEASIBLE.
      if (
        decision.kind === "refuse" &&
        (this.taskState.lastDomainFailureCode === "NO_FEASIBLE_PLAN" ||
          this.state.errorCode === "NO_FEASIBLE_PLAN") &&
        (decision.reasonCode === "UNSUPPORTED_OR_UNCLEAR" ||
          decision.reasonCode === "UNSUPPORTED")
      ) {
        decision = {
          ...decision,
          reasonCode: "PLAN_INFEASIBLE"
        };
      }

      const newSteps = toModelSteps(
        decision,
        this.modelProvider!.mode
      ).map((step, offset) => ({
        ...step,
        index: this.currentModelSteps.length + offset
      }));
      this.currentModelSteps.push(...newSteps);
      lastModelTrace = modelTraceForDecision(
        decision,
        this.modelProvider!.mode
      );

      // Tool-name default goals (get_day_context → inspect) must not freeze a
      // planning turn: stage gate requires day context first, then candidates.
      const decisionGoal = remapDecisionGoalForTurn({
        decision,
        rawGoal: actionableGoal(decision.goal),
        hasActivePlan: Boolean(this.state.activePlanId),
        taskObjective: this.taskState.objective
      });
      const currentPlanningGoal =
        this.taskState.objective === "compose_meal" ||
        this.taskState.objective === "revise_meal";
      const nextPlanningGoal =
        decisionGoal === "compose_meal" || decisionGoal === "revise_meal";
      const existingPlanningStage =
        this.taskState.workflowStage === "day_context" ||
        this.taskState.workflowStage === "candidates" ||
        this.taskState.workflowStage === "plan_ready";
      const switchesTaskLifecycle =
        decisionGoal !== null &&
        !loopGoal &&
        this.taskState.pendingActionId === null &&
        this.state.pendingActionId === null &&
        ((this.taskState.objective === null &&
          !(nextPlanningGoal && existingPlanningStage)) ||
          (this.taskState.objective !== null &&
            this.taskState.objective !== decisionGoal &&
            !(currentPlanningGoal && nextPlanningGoal)));
      if (
        decision.kind !== "refuse" &&
        switchesTaskLifecycle
      ) {
        this.taskState = applyTaskTransition(this.taskState, {
          type: "replace_objective",
          objective: decisionGoal
        });
      }
      if (decision.kind !== "refuse") {
        if (loopGoal && decisionGoal && decisionGoal !== loopGoal) {
          // preview_handoff and send_handoff are the same product path at model
          // layer (preview only; real send is UI). Treat them as aliases.
          const handoffAlias =
            (loopGoal === "preview_handoff" || loopGoal === "send_handoff") &&
            (decisionGoal === "preview_handoff" ||
              decisionGoal === "send_handoff");
          // Allow only legitimate post-success progression (e.g. compose →
          // ask recipient for send_handoff, or inspect → compose after day context).
          const canAdvance =
            handoffAlias ||
            mayAdvanceLoopGoal({
              from: loopGoal,
              to: decisionGoal,
              decision,
              modelToolResults,
              hasActivePlan: Boolean(this.state.activePlanId)
            });
          if (!canAdvance) {
            this.currentDecision = decision.kind;
            this.currentGoal = loopGoal;
            this.currentBlockingReasons = ["goal_changed_during_turn"];
            this.state.phase = "AWAITING_USER";
            const blocked = this.finalize(
              "模型在同一请求中改变了目标，本轮已安全停止，请重新描述要完成的目标。",
              toolTrace,
              uiOnly
            );
            return {
              ...blocked,
              routingEvidenceKind: "model_clarification",
              modelTrace: lastModelTrace
            };
          }
          if (!handoffAlias) {
            loopGoal = decisionGoal;
            this.taskState = applyTaskTransition(this.taskState, {
              type: "set_objective",
              objective: decisionGoal
            });
          }
        }
        if (!loopGoal && decisionGoal) {
          loopGoal = decisionGoal;
          this.taskState = applyTaskTransition(this.taskState, {
            type: "set_objective",
            objective: decisionGoal
          });
        }
      }
      this.currentGoal = loopGoal ?? decision.goal;
      this.currentDecision = decision.kind;

      if (
        (loopMode === "FINAL_ONLY" &&
          decision.kind !== "final" &&
          decision.kind !== "ask_user") ||
        (loopMode === "BLOCKED" && decision.kind === "tool")
      ) {
        const stopped = this.finishWithDeterministicFallback({
          goal: loopGoal ?? requireActionableGoal(decision.goal),
          sourceCode: "MODEL_FINAL_PROTOCOL_VIOLATION",
          loopMode,
          loopModeReason,
          toolResults: modelToolResults,
          toolTrace,
          ...(uiOnly ? { uiOnly } : {})
        });
        return {
          ...stopped,
          routingEvidenceKind: "model_routed",
          modelTrace: lastModelTrace
        };
      }

      if (decision.kind === "final") {
        this.pendingClarification = null;
        const validation = this.validateAnswer(decision.message, toolTrace);
        const finalStep = this.currentModelSteps.at(-1);
        if (finalStep) {
          finalStep.answerValidation = {
            ok: validation.ok,
            reasons: validation.ok ? [] : validation.reasons
          };
        }
        if (!validation.ok && answerRegenerationCount < MAX_ANSWER_REGENERATIONS) {
          answerRegenerationCount += 1;
          answerValidationFailure = {
            reasons: validation.reasons,
            regenerationAttempt: answerRegenerationCount
          };
          continue;
        }
        if (
          !validation.ok &&
          modelToolResults.some(isSuccessfulToolOutcome)
        ) {
          // Prefer grounded tool presentation over deterministic_fallback when
          // the model already satisfied the goal but failed answer validation
          // (e.g. invented calorie figures). Fallback remains if presenter cannot render.
          const fallbackGoal = loopGoal ?? requireActionableGoal(decision.goal);
          if (
            goalSatisfiedBySuccessfulTools(fallbackGoal, modelToolResults)
          ) {
            const presented = this.finishWithTrustedPresenter({
              goal: fallbackGoal,
              results: modelToolResults,
              toolTrace,
              ...(uiOnly ? { uiOnly } : {})
            });
            return {
              ...presented,
              routingEvidenceKind: "model_routed",
              modelTrace: lastModelTrace
            };
          }
          const completed = this.finishWithDeterministicFallback({
            goal: fallbackGoal,
            sourceCode: "ANSWER_VALIDATION_FAILED",
            loopMode,
            loopModeReason,
            toolResults: modelToolResults,
            toolTrace,
            ...(uiOnly ? { uiOnly } : {})
          });
          return {
            ...completed,
            routingEvidenceKind: "model_routed",
            modelTrace: lastModelTrace
          };
        }
        const completed = this.finishCompletedTurn({
          goal: decision.goal,
          answer: decision.message,
          toolTrace,
          uiOnly,
          mode: "model"
        });
        return {
          ...completed,
          routingEvidenceKind: "model_routed",
          modelTrace: lastModelTrace
        };
      }

      if (decision.kind === "refuse") {
        // Only coerce refuse→final when a *goal-satisfying* Domain tool already
        // ran (plan write / preview). Context-only success must not end compose.
        if (
          modelToolResults.some(isSuccessfulToolOutcome) &&
          goalSatisfiedBySuccessfulTools(
            loopGoal ?? actionableGoal(decision.goal),
            modelToolResults
          )
        ) {
          const fallbackGoal =
            loopGoal ??
            (modelToolResults.some((r) => r.tool === "preview_caregiver_task")
              ? "preview_handoff"
              : modelToolResults.some((r) => r.tool === "finalize_meal_plan")
                ? "compose_meal"
                : modelToolResults.some(
                      (r) => r.tool === "get_day_context"
                    )
                  ? "inspect_context"
                  : "inspect_context");
          const stopped = this.finishWithTrustedPresenter({
            goal: fallbackGoal,
            results: modelToolResults,
            toolTrace,
            ...(uiOnly ? { uiOnly } : {})
          });
          return {
            ...stopped,
            routingEvidenceKind: "model_routed",
            modelTrace: lastModelTrace
          };
        }
        this.pendingClarification = null;
        this.state.phase = "AWAITING_USER";
        this.state.intent = "unknown";
        this.currentBlockingReasons = [decision.reasonCode];
        this.taskState = applyTaskTransition(this.taskState, {
          type: "refuse",
          reasonCode: decision.reasonCode
        });
        const refused = this.finalize(decision.message, toolTrace, uiOnly);
        return {
          ...refused,
          routingEvidenceKind: "model_routed",
          modelTrace: lastModelTrace
        };
      }

      if (decision.kind === "ask_user") {
        // Goal already satisfied by a successful tool: only allow real handoff
        // recipient clarify. Spurious currentPreview/softPreference asks become final.
        if (
          loopMode === "FINAL_ONLY" &&
          modelToolResults.some(isSuccessfulToolOutcome)
        ) {
          const handoffRecipientOnly =
            decision.missingFields.length > 0 &&
            decision.missingFields.every((field) => field === "recipientLabel");
          if (!handoffRecipientOnly) {
            const stopped = this.finishWithTrustedPresenter({
              goal: loopGoal ?? requireActionableGoal(decision.goal),
              results: modelToolResults,
              toolTrace,
              ...(uiOnly ? { uiOnly } : {})
            });
            return {
              ...stopped,
              routingEvidenceKind: "model_routed",
              modelTrace: lastModelTrace
            };
          }
        }
        // Recipient slot with an active plan is always the send_handoff objective
        // (product path: preview/send handoff after a plan exists).
        if (
          decision.missingFields.includes("recipientLabel") &&
          this.state.activePlanId
        ) {
          decision = {
            ...decision,
            goal: "send_handoff"
          };
          loopGoal = "send_handoff";
          this.currentGoal = "send_handoff";
        }
        // No real missing slots → do not invent a clarification wait state.
        if (decision.missingFields.length === 0) {
          this.currentBlockingReasons = decision.reasons ?? [
            "ask_user_empty_missing_fields"
          ];
          this.state.phase = "AWAITING_USER";
          // Empty ask after known infeasible domain failure → PLAN_INFEASIBLE.
          if (
            this.taskState.lastDomainFailureCode === "NO_FEASIBLE_PLAN" ||
            this.state.errorCode === "NO_FEASIBLE_PLAN"
          ) {
            this.currentBlockingReasons = ["PLAN_INFEASIBLE"];
            this.currentDecision = "refuse";
            this.currentGoal = "unsupported";
            this.taskState = applyTaskTransition(this.taskState, {
              type: "refuse",
              reasonCode: "PLAN_INFEASIBLE"
            });
          }
          const blocked = this.finalize(
            decision.message ||
              "当前没有需要补充的具体字段。请直接说明用餐成员、餐次或收件人。",
            toolTrace,
            uiOnly
          );
          return {
            ...blocked,
            routingEvidenceKind: "model_clarification",
            modelTrace: lastModelTrace
          };
        }
        this.state.phase = "AWAITING_USER";
        const reasons = decision.reasons ?? [];
        this.currentBlockingReasons = decision.missingFields.map(
          (field) => `${field}_missing`
        );
        // Single reducer event: objective + waiting_user + slots together.
        this.taskState = applyTaskTransition(this.taskState, {
          type: "ask_user",
          missingFields: decision.missingFields,
          ...(decision.goal && decision.goal !== "unsupported"
            ? { objective: decision.goal }
            : {}),
          known: {
            ...(typeof decision.normalized_model_arguments?.serveAt === "string"
              ? { serveAt: decision.normalized_model_arguments.serveAt }
              : {}),
            ...(typeof decision.normalized_model_arguments?.recipientLabel ===
            "string"
              ? {
                  recipientLabel: String(
                    decision.normalized_model_arguments.recipientLabel
                  )
                }
              : {})
          }
        });
        if (decision.goal && decision.goal !== "unsupported") {
          this.currentGoal = decision.goal;
          const advanced = actionableGoal(decision.goal);
          if (advanced) {
            loopGoal = advanced;
          }
        }
        if (
          decision.tool === "preview_caregiver_task" ||
          decision.missingFields.includes("recipientLabel")
        ) {
          this.pendingClarification = handoffPendingClarification(
            userText,
            decision.normalized_model_arguments?.serveAt,
            decision.goal
          );
        } else {
          const pendingGoal = actionableGoal(decision.goal);
          this.pendingClarification = pendingGoal
            ? {
                tool: decision.tool,
                goal: pendingGoal,
                missing: [...decision.missingFields],
                known: decision.normalized_model_arguments ?? {}
              }
            : null;
        }
        const clarification = this.finalize(
          decision.message,
          toolTrace,
          uiOnly
        );
        return {
          ...clarification,
          routingEvidenceKind: "model_clarification",
          modelTrace: lastModelTrace
        };
      }

      if (
        toolCallCount >= this.state.maxToolSteps ||
        modelRequestCount >= MAX_MODEL_REQUESTS_PER_TURN
      ) {
        this.currentBlockingReasons = ["step_limit_reached"];
        this.state.phase = "AWAITING_USER";
        const limited = this.finalize(
          "本轮已达到安全步骤上限，已停止继续调用工具。请基于当前结果发起下一条请求。",
          toolTrace,
          uiOnly
        );
        return {
          ...limited,
          routingEvidenceKind: "model_routed",
          modelTrace: lastModelTrace
        };
      }
      if (
        decision.tool === "finalize_meal_plan" &&
        planAttemptCount >= MAX_PLAN_ATTEMPTS_PER_TURN
      ) {
        const infeasible = this.finishWithStructuredInfeasible({
          toolResults: modelToolResults,
          toolTrace,
          uiOnly,
          trigger: "plan_retry_limit_reached",
          loopGoal
        });
        return {
          ...infeasible,
          routingEvidenceKind: "model_routed",
          modelTrace: lastModelTrace
        };
      }

      // Same-turn dedupe: identical successful tool+args must not re-run.
      const toolKey = successfulToolCallKey(
        decision.tool,
        decision.effective_arguments
      );
      const isReselectAfterFinalizeFailure =
        modelToolResults.at(-1)?.tool === "finalize_meal_plan" &&
        !isSuccessfulToolOutcome(modelToolResults.at(-1)!);
      if (successfulToolKeys.has(toolKey) && !isReselectAfterFinalizeFailure) {
        // Do not emit another successful tool_call fact (scorer treats that as
        // repeated_successful_tool). Close with grounded final immediately.
        const stopped = this.finishWithDeterministicFallback({
          goal: loopGoal ?? requireActionableGoal(decision.goal),
          sourceCode: "DUPLICATE_SUCCESSFUL_TOOL_SUPPRESSED",
          loopMode: "FINAL_ONLY",
          loopModeReason: "duplicate_successful_tool_suppressed",
          toolResults: modelToolResults,
          toolTrace,
          ...(uiOnly ? { uiOnly } : {})
        });
        return {
          ...stopped,
          routingEvidenceKind: "model_routed",
          modelTrace: lastModelTrace
        };
      }

      const outcome = await this.executeModelTool(
        decision,
        userText,
        lockedDinerIds,
        toolTrace,
        modelToolResults
      );
      const toolOutcome = classifyToolOutcome(
        toToolOutcomeLike(decision.tool, outcome.result)
      );
      toolCallCount += 1;
      if (decision.tool === "finalize_meal_plan") {
        planAttemptCount += 1;
      }
      if (outcome.uiOnly) uiOnly = outcome.uiOnly;

      const toolStep = [...this.currentModelSteps]
        .reverse()
        .find((step) => step.decision === "tool");
      if (toolStep) {
        const resultData =
          outcome.result.ok &&
          outcome.result.data &&
          typeof outcome.result.data === "object" &&
          !Array.isArray(outcome.result.data)
            ? (outcome.result.data as Record<string, unknown>)
            : null;
        toolStep.toolResult = {
          tool: decision.tool,
          ok: toolOutcome.kind === "succeeded",
          ...(toolOutcome.code ? { code: toolOutcome.code } : {}),
          ...(typeof resultData?.status === "string"
            ? { status: resultData.status }
            : {})
        };
      }
      modelToolResults.push(
        toModelVisibleToolResult({
          step: modelToolResults.length,
          goal: loopGoal ?? requireActionableGoal(decision.goal),
          tool: decision.tool,
          outcome
        })
      );
      this.updateLoopBlockingReasons(decision.tool, outcome);
      if (toolOutcome.kind !== "succeeded") {
        successfulToolKeys.clear();
      }
      if (toolOutcome.kind === "succeeded") {
        successfulToolKeys.add(toolKey);
        // The model's semantic goal decides preview vs send intent. Real
        // external send remains UI-only; the goal only affects the outcome.
        if (decision.tool === "preview_caregiver_task") {
          const handoffGoal =
            decision.goal === "send_handoff"
              ? "send_handoff"
              : "preview_handoff";
          loopGoal = handoffGoal;
          this.currentGoal = handoffGoal;
          this.taskState = applyTaskTransition(this.taskState, {
            type: "set_objective",
            objective: handoffGoal
          });
        }
        // compose vs revise is determined by whether a parent plan already
        // existed before this finalize (gateway injects parentPlan).
        // Do not flip first successful compose into revise_meal.
      }
      const transition = resolveLoopTransition({
        goal: loopGoal ?? requireActionableGoal(decision.goal),
        tool: decision.tool,
        result: outcome.result
      });
      loopMode = transition.mode;
      loopModeReason = transition.reason;
      if (loopMode === "BLOCKED") {
        this.currentBlockingReasons = [loopModeReason];
        // confirmation_required is waiting_confirmation (set by tool_succeeded),
        // not a generic blocked task wipe.
        if (loopModeReason !== "confirmation_required") {
          this.taskState = applyTaskTransition(this.taskState, {
            type: "block_task",
            reasonCode: loopModeReason,
            keepSlots: false
          });
        }
      }
      answerValidationFailure = null;

      if (
        this.finalizationMode === "trusted_presenter" &&
        loopMode === "FINAL_ONLY" &&
        toolOutcome.kind === "succeeded" &&
        isTrustedPresenterTool(decision.tool) &&
        goalSatisfiedBySuccessfulTools(
          loopGoal ?? actionableGoal(decision.goal),
          modelToolResults
        )
      ) {
        const presented = this.finishWithTrustedPresenter({
          goal: loopGoal ?? requireActionableGoal(decision.goal),
          results: modelToolResults,
          toolTrace,
          uiOnly
        });
        return {
          ...presented,
          routingEvidenceKind: "model_routed",
          ...(lastModelTrace ? { modelTrace: lastModelTrace } : {})
        };
      }
    }

    this.currentDecision = undefined;
    this.currentBlockingReasons = ["model_step_limit_reached"];
    this.state.phase = "AWAITING_USER";
    const limited = this.finalize(
      "本轮模型决策次数已达到安全上限，已停止继续处理。请发起下一条请求。",
      toolTrace,
      uiOnly
    );
    return {
      ...limited,
      routingEvidenceKind: "model_routed",
      ...(lastModelTrace ? { modelTrace: lastModelTrace } : {})
    };
  }

  private buildModelRouteInput(input: {
    userText: string;
    lockedDinerIds?: string[];
    loopGoal: LoopGoal | null;
    loopMode: AgentLoopMode;
    loopModeReason: string;
    decisionIndex: number;
    modelRequestCount: number;
    modelToolResults: ModelVisibleToolResult[];
    answerValidationFailure: {
      reasons: string[];
      regenerationAttempt: number;
    } | null;
    priorOutcome: NonNullable<ModelTurnContext["priorOutcome"]>;
  }): ModelRouteInput {
    const fixtureContext = this.domain.getMealContext({
      dinerIds: this.state.dinerIds
    });
    const available = computeAvailableActions(
      this.state,
      this.taskState,
      input.loopMode,
      input.modelToolResults
    );
    // Prefer resumed TaskState objective when the turn has not locked a goal yet.
    const turnGoal =
      input.loopGoal ??
      actionableGoal(this.taskState.objective ?? "unsupported");
    return {
      userText: input.userText,
      conversationHistory: [...this.conversationHistory],
      currentTurn: {
        goal: turnGoal,
        mode: input.loopMode,
        modeReason: input.loopModeReason,
        decisionIndex: input.decisionIndex,
        modelRequestCount: input.modelRequestCount,
        maxModelRequests: MAX_MODEL_REQUESTS_PER_TURN,
        toolResults: projectModelToolResultsForNextDecision(
          input.modelToolResults
        ),
        answerValidationFailure: input.answerValidationFailure,
        priorOutcome: input.priorOutcome
      },
      activePlan: this.activePlanForModel(),
      focusedTemplateId:
        this.taskState.focusedTemplateId ?? this.focusedTemplateId,
      pendingClarification:
        this.pendingClarification ??
        pendingClarificationFromTaskState(this.taskState),
      // Required single-source action set for Provider tool exposure.
      availableActions: {
        domainTools: available.domainTools,
        controlDecisions: available.controlDecisions
      },
      // Privacy-safe TaskState so the model can continue multi-turn work.
      taskState: toModelVisibleTaskState(this.taskState, this.state),
      state: {
        phase: this.state.phase,
        dinerIds: this.state.dinerIds,
        activePlanId: this.state.activePlanId,
        activePlanVersion: this.state.activePlanVersion,
        rejectedFoodIds: this.state.rejectedFoodIds,
        rejectedTemplateIds: this.state.rejectedTemplateIds,
        hasPendingAction: this.state.pendingActionId !== null
      },
      requestContext: {
        handoffRecipient: resolveHandoffRecipient(
          input.userText,
          ["家庭保姆", "保姆", "阿姨"]
        )
      },
      dinerIdsLocked: Boolean(input.lockedDinerIds),
      memberDirectory: this.domain.getMembers().map((member) => ({
        id: member.id,
        displayName: member.displayName,
        roleLabel: member.roleLabel,
        healthTags: member.healthTags ?? []
      })),
      fixtureDirectory: {
        foods: fixtureContext.foods.map((food) => ({
          id: food.id,
          name: food.canonicalName,
          aliases: food.aliases
        })),
        templates: fixtureContext.templates.map((template) => ({
          id: template.id,
          name: template.name,
          aliases: templateAliases(template.name),
          ingredientFoodIds: [...template.ingredientFoodIds]
        })),
        planTags: [
          { id: "planning", label: "初次规划" },
          { id: "replan", label: "重规划" },
          { id: "privacy", label: "隐私" },
          { id: "handoff", label: "任务交接" }
        ],
        caregiverRecipientLabels: ["家庭保姆", "保姆", "阿姨"]
      }
    };
  }

  private async executeModelTool(
    decision: Extract<ModelRouteDecision, { kind: "tool" }>,
    userText: string,
    lockedDinerIds: string[] | undefined,
    trace: AgentTurnResult["toolTrace"],
    turnToolResults: readonly ModelVisibleToolResult[]
  ): Promise<ToolGatewayResult> {
    const args = decision.effective_arguments;
    if (
      decision.tool === "get_day_context" ||
      decision.tool === "finalize_meal_plan"
    ) {
      const dinerIds = lockedDinerIds ?? args.dinerIds;
      if (Array.isArray(dinerIds)) {
        const priorDiners = [...this.state.dinerIds];
        const selected = this.selectDiners(
          dinerIds.filter((id): id is string => typeof id === "string")
        );
        if (!selected.ok) {
          throw new Error("Trusted dinerIds failed household validation.");
        }
        const dinersChanged =
          priorDiners.length !== this.state.dinerIds.length ||
          priorDiners.some((id) => !this.state.dinerIds.includes(id));
        if (dinersChanged) {
          // After member switch, goal is inspect or new compose — not revise.
          const nextGoal =
            decision.tool === "get_day_context"
              ? "inspect_context"
              : "compose_meal";
          this.currentGoal = nextGoal;
          this.taskState = applyTaskTransition(this.taskState, {
            type: "set_objective",
            objective: nextGoal
          });
        }
      }
    }
    // Run first; authorize from pre-invoke trusted state; commit only on success.
    const priorPhase = this.state.phase;
    const available = computeAvailableActions(
      this.state,
      this.taskState,
      "ACTION_ALLOWED",
      turnToolResults
    );
    const replacedPendingActionId =
      this.state.pendingActionId && isPreviewTool(decision.tool)
        ? this.state.pendingActionId
        : null;
    this.state.intent = intentForTool(decision.tool);
    const outcome = await this.gateway.invoke(
      this.state,
      decision.tool,
      args,
      userText,
      available.domainTools
    );
    this.applyTool(outcome, trace);

    const classification = classifyToolOutcome(
      toToolOutcomeLike(decision.tool, outcome.result)
    );
    if (classification.kind !== "succeeded") {
      // Domain rejection is feedback for the next selection, not a committed
      // plan. Preserve the active plan, preview and selection context.
      this.state = {
        ...this.state,
        phase: phaseAfterToolFailure(priorPhase, this.state),
        lastToolStatus: "failure",
        errorCode: classification.code
      };
      this.taskState = applyTaskTransition(this.taskState, {
        type: "tool_failed",
        code: classification.code
      });
      return outcome;
    }

    // Atomic post-success effects only.
    if (
      decision.tool !== "preview_caregiver_task" &&
      decision.tool !== "preview_meal_completion"
    ) {
      this.pendingClarification = null;
    }
    if (
      replacedPendingActionId &&
      replacedPendingActionId !== outcome.uiOnly?.pendingActionId
    ) {
      this.domain.cancelCaregiverSend({
        pendingActionId: replacedPendingActionId
      });
    }
    if (outcome.uiOnly) {
      const { confirmationToken: _confirmationToken, ...metadata } =
        outcome.uiOnly;
      this.pendingPreviewMetadata = metadata;
    }
    if (decision.tool === "finalize_meal_plan") {
      this.cancelActivePreview();
      this.focusedTemplateId = null;
      this.state = {
        ...this.state,
        activeConstraintIds: [],
        rejectedTemplateIds: [],
        rejectedFoodIds: [],
        requestedPriorityFoodIds: [],
        preferLowEffort: false,
        lastCommittedActionId: null,
        lastCommittedPayloadHash: null
      };
      this.taskState = applyTaskTransition(this.taskState, {
        type: "clear_pending_action"
      });
    }

    const data =
      outcome.result.ok &&
      outcome.result.data &&
      typeof outcome.result.data === "object" &&
      !Array.isArray(outcome.result.data)
        ? (outcome.result.data as Record<string, unknown>)
        : {};
    switch (decision.tool) {
      case "get_day_context":
      case "get_inventory":
        this.state.phase = "COLLECTING_CONTEXT";
        break;
      case "find_dish_candidates":
        this.state.phase = "PLANNING";
        break;
      case "finalize_meal_plan":
        this.state.phase = "PRESENTING_PLAN";
        this.focusedTemplateId = null;
        break;
      case "preview_meal_completion":
      case "preview_caregiver_task":
      case "preview_inventory_change":
      case "preview_member_memory_change":
        this.pendingClarification = null;
        this.state = {
          ...this.state,
          phase: "PREVIEWING_WRITE",
          confirmationStatus: "previewed"
        };
        break;
      case "retrieve_local_knowledge":
        // Keep current planning presentation phase when possible.
        if (
          this.state.phase !== "PRESENTING_PLAN" &&
          this.state.phase !== "PLANNING"
        ) {
          this.state.phase = "COLLECTING_CONTEXT";
        }
        break;
    }
    // One success event carries objective so waiting_confirmation is not wiped.
    const toolData =
      outcome.result.ok &&
      outcome.result.data &&
      typeof outcome.result.data === "object" &&
      !Array.isArray(outcome.result.data)
        ? (outcome.result.data as Record<string, unknown>)
        : {};
    // Tool choice implies intent when goal omitted from business tools.
    // Prefer already-remapped turn objective (planning pipeline) over tool default.
    let inferredObjective =
      this.taskState.objective &&
      (this.taskState.objective === "compose_meal" ||
        this.taskState.objective === "revise_meal")
        ? this.taskState.objective
        : decision.goal && decision.goal !== "unsupported"
          ? decision.goal
          : undefined;
    if (!inferredObjective || inferredObjective === "inspect_context") {
      if (
        decision.tool === "find_dish_candidates" ||
        decision.tool === "finalize_meal_plan"
      ) {
        inferredObjective = this.state.activePlanId
          ? "revise_meal"
          : "compose_meal";
      } else if (decision.tool === "get_day_context") {
        if (
          this.taskState.objective === "compose_meal" ||
          this.taskState.objective === "revise_meal"
        ) {
          inferredObjective = this.taskState.objective;
        } else {
          inferredObjective = "inspect_context";
        }
      } else if (decision.tool === "get_inventory") {
        inferredObjective = "inspect_inventory";
      }
    }
    this.taskState = applyTaskTransition(this.taskState, {
      type: "tool_succeeded",
      tool: decision.tool as AgentToolName,
      clearFocus:
        decision.tool === "finalize_meal_plan",
      pendingActionId: outcome.uiOnly?.pendingActionId ?? null,
      pendingActionType: outcome.uiOnly?.actionType ?? null,
      data: toolData,
      ...(typeof toolData.candidateSetId === "string"
        ? { candidateSetId: toolData.candidateSetId }
        : {}),
      ...(inferredObjective ? { objective: inferredObjective } : {})
    });
    // If revise removed the focused dish, drop focus so "这道菜" cannot drift.
    if (decision.tool === "finalize_meal_plan") {
      const rejected = decision.effective_arguments?.rejectTemplateIds;
      if (
        this.focusedTemplateId &&
        Array.isArray(rejected) &&
        rejected.includes(this.focusedTemplateId)
      ) {
        this.focusedTemplateId = null;
        this.taskState = applyTaskTransition(this.taskState, {
          type: "set_focus",
          templateId: null
        });
      }
    }
    return outcome;
  }

  private updateLoopBlockingReasons(
    tool: Extract<ModelRouteDecision, { kind: "tool" }>["tool"],
    outcome: ToolGatewayResult
  ): void {
    const classification = classifyToolOutcome(
      toToolOutcomeLike(tool, outcome.result)
    );
    if (classification.kind !== "succeeded") {
      this.currentBlockingReasons = [classification.code.toLowerCase()];
      return;
    }
    this.currentBlockingReasons = [];
  }

  private settleFinalPhase(goal: Exclude<AgentGoal, "unsupported">): void {
    if (
      this.state.phase === "ERROR" ||
      this.state.phase === "PRESENTING_INFEASIBLE"
    ) {
      return;
    }
    if (this.state.pendingActionId) {
      this.state.phase = "AWAITING_CONFIRMATION";
      return;
    }
    if (
      (goal === "compose_meal" ||
        goal === "revise_meal" ||
        goal === "retrieve_guidance") &&
      this.state.activePlanId
    ) {
      this.state.phase = "PRESENTING_PLAN";
      return;
    }
    this.state.phase = "COMPLETED";
  }

  private finishWithStructuredInfeasible(input: {
    toolResults: ModelVisibleToolResult[];
    toolTrace: AgentTurnResult["toolTrace"];
    uiOnly?: UiOnlySideChannel | undefined;
    trigger: "plan_retry_limit_reached";
    loopGoal: LoopGoal | null;
  }): AgentTurnResult {
    const lastFailed = [...input.toolResults]
      .reverse()
      .find(
        (result) =>
          result.tool === "finalize_meal_plan" && !isSuccessfulToolOutcome(result)
      );
    const data = lastFailed?.data ?? {};
    const recovery =
      (data.recovery as Record<string, unknown> | undefined) ??
      (data.details as Record<string, unknown> | undefined) ??
      {};
    const priorFailureCode =
      typeof data.code === "string"
        ? data.code
        : typeof lastFailed?.code === "string"
          ? lastFailed.code
          : null;
    const deficits = Array.isArray(recovery.deficits)
      ? (recovery.deficits as Array<Record<string, unknown>>)
      : [];
    const recommendedActions = Array.isArray(recovery.recommendedActions)
      ? recovery.recommendedActions.filter(
          (item): item is string => typeof item === "string"
        )
      : [];
    const failureKind =
      typeof recovery.failureKind === "string" ? recovery.failureKind : null;
    const domainSearchExhausted =
      recovery.domainSearchExhausted === true ||
      data.domainSearchExhausted === true;
    const allowedRelaxations = [
      {
        constraintId: "soft_preference_or_portion",
        userFacingQuestion:
          "是否愿意调整软偏好、份量或菜品组合后再试？硬约束和明确拒绝项均未放宽。"
      }
    ];
    const infeasiblePayload = {
      status: "infeasible" as const,
      code: "NO_FEASIBLE_PLAN" as const,
      priorFailureCode,
      trigger: input.trigger,
      failureKind,
      deficits,
      recommendedActions,
      allowedRelaxations,
      domainSearchExhausted,
      message: domainSearchExhausted
        ? "Domain 已穷尽当前硬约束下的可行组合，仍无法形成餐食，已停止继续尝试。"
        : "当前选择在硬约束下无法形成可行餐食，已停止继续尝试。"
    };

    this.state = {
      ...this.state,
      phase: "PRESENTING_INFEASIBLE",
      lastToolStatus: "failure",
      errorCode: "NO_FEASIBLE_PLAN"
    };
    this.currentBlockingReasons = [
      input.trigger,
      "PLAN_INFEASIBLE",
      "NO_FEASIBLE_PLAN"
    ];
    this.currentGoal =
      input.loopGoal ??
      (this.taskState.objective === "revise_meal" ? "revise_meal" : "compose_meal");
    this.currentDecision = "refuse";
    this.taskState = applyTaskTransition(this.taskState, {
      type: "block_task",
      reasonCode: "PLAN_INFEASIBLE",
      keepSlots: true
    });
    // Ensure the oracle/product contract sees NO_FEASIBLE_PLAN as last domain failure.
    this.taskState = {
      ...this.taskState,
      lastDomainFailureCode: "NO_FEASIBLE_PLAN"
    };
    this.lastToolPayloads.push(infeasiblePayload);
    this.currentModelSteps.push({
      index: this.currentModelSteps.length,
      providerMode: this.modelProvider?.mode ?? "unknown",
      model: this.modelProvider?.model ?? "unknown",
      decision: "refuse",
      goal: this.currentGoal,
      tool: null,
      rawArguments: {
        reasonCode: "PLAN_INFEASIBLE",
        code: "NO_FEASIBLE_PLAN"
      },
      normalizedArguments: {
        reasonCode: "PLAN_INFEASIBLE",
        code: "NO_FEASIBLE_PLAN"
      },
      effectiveArguments: null,
      policy: {
        status: "not_applicable",
        reasons: [input.trigger, "NO_FEASIBLE_PLAN", "PLAN_INFEASIBLE"],
        privacyViolation: false
      },
      missingFields: []
    });

    const answer = renderStructuredInfeasible({
      priorFailureCode,
      deficits,
      recommendedActions,
      failureKind,
      allowedRelaxations
    });
    return this.finalize(answer, input.toolTrace, input.uiOnly);
  }

  private finishWithDeterministicFallback(input: {
    goal: LoopGoal;
    sourceCode: string;
    loopMode: AgentLoopMode;
    loopModeReason: string;
    toolResults: ModelVisibleToolResult[];
    toolTrace: AgentTurnResult["toolTrace"];
    uiOnly?: UiOnlySideChannel;
  }): AgentTurnResult {
    const answer =
      renderDeterministicFinal({
        goal: input.goal,
        toolResults: input.toolResults,
        ...(input.loopMode === "BLOCKED"
          ? { blockedReason: input.loopModeReason }
          : {})
      }) ?? blockedToolFallbackMessage(input.loopModeReason);

    this.currentGoal = input.goal;
    this.currentDecision = "final";
    this.currentFinalizationMode = "deterministic_fallback";
    if (input.loopMode === "BLOCKED") {
      this.currentBlockingReasons = [input.loopModeReason];
    } else {
      this.currentBlockingReasons = [];
      this.settleFinalPhase(input.goal);
      // Trusted deterministic finals also complete the task lifecycle, except
      // when the successful tool only produced a confirmation-gated preview.
      this.taskState = applyTaskTransition(
        this.taskState,
        this.taskState.status === "waiting_confirmation"
          ? { type: "turn_finished" }
          : { type: "finish" }
      );
    }
    this.currentFallbackCodes.push("DETERMINISTIC_FINAL_FALLBACK_USED");
    this.currentModelSteps.push({
      index: this.currentModelSteps.length,
      providerMode: this.modelProvider?.mode ?? "unknown",
      model: this.modelProvider?.model ?? "unknown",
      decision: "deterministic_fallback",
      goal: input.goal,
      tool: null,
      rawArguments: null,
      normalizedArguments: null,
      effectiveArguments: null,
      policy: {
        status: "not_applicable",
        reasons: [
          input.sourceCode,
          "DETERMINISTIC_FINAL_FALLBACK_USED"
        ],
        privacyViolation: false
      },
      missingFields: []
    });
    return this.finalize(answer, input.toolTrace, input.uiOnly);
  }

  private finishWithTrustedPresenter(input: {
    goal: LoopGoal;
    results: ModelVisibleToolResult[];
    toolTrace: AgentTurnResult["toolTrace"];
    uiOnly?: UiOnlySideChannel | undefined;
  }): AgentTurnResult {
    const answer = renderTrustedPresenter(input.results);
    if (!answer) {
      return this.finishWithDeterministicFallback({
        goal: input.goal,
        sourceCode: "TRUSTED_PRESENTER_INPUT_UNAVAILABLE",
        loopMode: "FINAL_ONLY",
        loopModeReason: "goal_satisfied",
        toolResults: input.results,
        toolTrace: input.toolTrace,
        ...(input.uiOnly ? { uiOnly: input.uiOnly } : {})
      });
    }

    const validation = this.validateAnswer(answer, input.toolTrace);
    if (!validation.ok) {
      return this.finishWithDeterministicFallback({
        goal: input.goal,
        sourceCode: "TRUSTED_PRESENTER_VALIDATION_FAILED",
        loopMode: "FINAL_ONLY",
        loopModeReason: "goal_satisfied",
        toolResults: input.results,
        toolTrace: input.toolTrace,
        ...(input.uiOnly ? { uiOnly: input.uiOnly } : {})
      });
    }

    return this.finishCompletedTurn({
      goal: input.goal,
      answer,
      toolTrace: input.toolTrace,
      uiOnly: input.uiOnly,
      mode: "trusted_presenter"
    });
  }

  private finishCompletedTurn(input: {
    goal: Exclude<AgentGoal, "unsupported">;
    answer: string;
    toolTrace: AgentTurnResult["toolTrace"];
    uiOnly?: UiOnlySideChannel | undefined;
    mode: FinalizationMode;
  }): AgentTurnResult {
    this.pendingClarification = null;
    this.currentGoal = input.goal;
    this.currentDecision = "final";
    this.currentFinalizationMode = input.mode;
    this.currentBlockingReasons = [];
    this.settleFinalPhase(input.goal);
    // A preview ends this turn but remains a pending business task until the
    // UI/CLI confirmation side channel commits it.
    this.taskState = applyTaskTransition(
      this.taskState,
      this.taskState.status === "waiting_confirmation"
        ? { type: "turn_finished" }
        : { type: "finish" }
    );
    return this.finalize(input.answer, input.toolTrace, input.uiOnly);
  }

  /**
   * UI/CLI side channel — not an Agent tool.
   */
  confirmPending(input: {
    confirmationToken: string;
    idempotencyKey: string;
    pendingActionId?: string;
    payloadHash?: string;
  }) {
    const activePendingActionId = this.state.pendingActionId;
    const pendingActionId =
      input.pendingActionId ??
      this.pendingPreviewMetadata?.pendingActionId ??
      activePendingActionId ??
      this.state.lastCommittedActionId;
    const isCurrentPending =
      Boolean(pendingActionId) && pendingActionId === activePendingActionId;
    const isReplay =
      !activePendingActionId &&
      Boolean(pendingActionId) &&
      pendingActionId === this.state.lastCommittedActionId;
    // External previews (HTTP /meal-complete) create Domain pending without
    // attaching agent state. Allow confirm when full token+id+hash are provided;
    // Domain still validates token, hash, expiry, and action type.
    const isExternalCredentialed =
      Boolean(input.pendingActionId) &&
      Boolean(input.payloadHash) &&
      Boolean(input.confirmationToken);
    if (
      !pendingActionId ||
      (!isCurrentPending && !isReplay && !isExternalCredentialed)
    ) {
      if (!isExternalCredentialed) {
        this.pendingPreviewMetadata = null;
      }
      return {
        ok: false as const,
        code: "STALE_CONTEXT" as const,
        message: "该任务卡已不是当前待确认或可重放的动作。"
      };
    }

    const payloadHash =
      input.payloadHash ??
      this.pendingPreviewMetadata?.payloadHash ??
      (isReplay ? this.state.lastCommittedPayloadHash : null) ??
      "";
    if (!payloadHash) {
      return {
        ok: false as const,
        code: "TOKEN_INVALID" as const,
        message: "缺少 pendingAction 或 payloadHash，请先预览任务卡。"
      };
    }
    const result = this.domain.confirmPendingWrite({
      pendingActionId,
      confirmationToken: input.confirmationToken,
      idempotencyKey: input.idempotencyKey,
      expectedPayloadHash: payloadHash
    });
    if (result.ok) {
      this.pendingPreviewMetadata = null;
      this.state = {
        ...this.state,
        phase: "COMPLETED",
        pendingActionId: null,
        lastCommittedActionId: pendingActionId,
        lastCommittedPayloadHash: payloadHash,
        confirmationStatus: "committed"
      };
      this.taskState = applyTaskTransition(this.taskState, {
        type: "clear_pending_action"
      });
      this.taskState = applyTaskTransition(this.taskState, {
        type: "commit_completed"
      });
    }
    return result;
  }

  cancelPending(pendingActionId?: string) {
    const activePendingActionId = this.state.pendingActionId;
    const targetId = pendingActionId ?? activePendingActionId;
    if (!targetId || targetId !== activePendingActionId) {
      return {
        ok: false as const,
        code: "STALE_CONTEXT" as const,
        message: "该任务卡已不是当前待确认版本。"
      };
    }

    const result = this.domain.cancelCaregiverSend({
      pendingActionId: targetId
    });
    if (result.ok) {
      this.invalidatePendingPreview(targetId);
      this.state = {
        ...this.state,
        phase: this.state.activePlanId ? "PRESENTING_PLAN" : "IDLE",
        confirmationStatus: "cancelled"
      };
      this.taskState = applyTaskTransition(this.taskState, {
        type: "clear_pending_action"
      });
    }
    return result;
  }

  invalidatePendingPreview(pendingActionId?: string): boolean {
    if (
      pendingActionId &&
      this.state.pendingActionId &&
      pendingActionId !== this.state.pendingActionId
    ) {
      return false;
    }
    this.pendingPreviewMetadata = null;
    this.state = {
      ...this.state,
      pendingActionId: null,
      confirmationStatus: "not_started"
    };
    return true;
  }

  private cancelActivePreview(): void {
    if (this.state.pendingActionId) {
      this.cancelPending(this.state.pendingActionId);
      return;
    }
    this.invalidatePendingPreview();
  }


  private validateDinerIds(
    requestedDinerIds: unknown[]
  ):
    | { ok: true; dinerIds: string[] }
    | { ok: false; result: AgentTurnResult } {
    const memberIds = new Set(this.domain.getMembers().map((member) => member.id));
    const dinerIds = [
      ...new Set(
        requestedDinerIds.filter(
          (value): value is string =>
            typeof value === "string" && memberIds.has(value)
        )
      )
    ];
    if (
      dinerIds.length === 0 ||
      dinerIds.length !== requestedDinerIds.length
    ) {
      this.state.phase = "AWAITING_USER";
      return {
        ok: false,
        result: this.finalize(
          "模型给出的就餐成员不在当前家庭列表中，请重新选择。",
          []
        )
      };
    }
    return { ok: true, dinerIds };
  }

  private activePlanForModel(): ModelActivePlan | null {
    if (!this.state.activePlanId) return null;
    const plan = this.domain.getPlanById(this.state.activePlanId);
    if (!plan) return null;

    return {
      id: plan.id,
      version: plan.version,
      mealType: plan.mealType,
      dinerIds: [...plan.dinerIds],
      menu: plan.sharedTemplates.map((item) => ({
        templateId: item.templateId,
        name: item.name,
        role: item.role,
        ...(item.coversRoles ? { coversRoles: item.coversRoles } : {})
      })),
      rejectedFoodIds: [...plan.rejectedFoodIds],
      rejectedTemplateIds: [...plan.rejectedTemplateIds],
      pinnedTemplateIds: [...plan.pinnedTemplateIds],
      requestedPriorityFoodIds: [...plan.requestedPriorityFoodIds],
      preferLowEffort: plan.preferLowEffort
    };
  }

  private rememberConversationTurn(
    userText: string,
    turn: AgentTurnResult
  ): void {
    this.conversationHistory.push({
      user: userText,
      assistant: compactConversationAnswer(turn.answer),
      tools: turn.toolTrace.map((tool) => ({
        name: tool.tool,
        ok: tool.ok
      }))
    });
    this.conversationHistory = this.conversationHistory.slice(-6);
  }

  private applyTool(
    outcome: Awaited<ReturnType<ToolGateway["invoke"]>>,
    trace: AgentTurnResult["toolTrace"]
  ): void {
    this.state = { ...this.state, ...outcome.statePatch };
    if (outcome.result.ok) {
      this.lastToolPayloads.push(outcome.result.data);
      trace.push({
        tool: outcome.result.tool,
        ok: true,
        durationMs: outcome.durationMs
      });
      if (
        outcome.result.tool === "get_day_context" ||
        outcome.result.tool === "retrieve_local_knowledge"
      ) {
        const packet = outcome.result.data as {
          cards?: Array<{ sourceId: string }>;
          hits?: Array<{ sourcePath?: string; sourceId?: string }>;
        };
        const sourceIds = [
          ...(packet.cards ?? []).map((card) => card.sourceId),
          ...(packet.hits ?? []).flatMap((hit) =>
            typeof hit.sourcePath === "string"
              ? [hit.sourcePath]
              : typeof hit.sourceId === "string"
                ? [hit.sourceId]
                : []
          )
        ];
        this.lastRetrievalIds = [
          ...new Set([
            ...this.lastRetrievalIds,
            ...sourceIds
          ])
        ];
      }
    } else {
      trace.push({
        tool: outcome.result.tool,
        ok: false,
        durationMs: outcome.durationMs,
        code: outcome.result.code
      });
    }
  }

  private finalize(
    answer: string,
    toolTrace: AgentTurnResult["toolTrace"],
    uiOnly?: UiOnlySideChannel
  ): AgentTurnResult {
    const validation = this.validateAnswer(answer, toolTrace);

    if (!validation.ok) {
      this.state = {
        ...this.state,
        phase: "ERROR",
        errorCode: "ANSWER_VALIDATION_FAILED"
      };
      const failed: AgentTurnResult = {
        answer:
          "回答未通过安全校验，已拦截可能不准确或越界的内容。请重试或缩小请求范围。",
        state: this.state,
        phase: "ERROR",
        toolTrace,
        validationOk: false,
        validationReasons: validation.reasons,
        modelSteps: [...this.currentModelSteps],
        taskOutcome: buildTaskOutcome({
          goal: this.currentGoal,
          phase: "ERROR",
          toolTrace,
          validationOk: false,
          blockingReasons: validation.reasons,
          deterministicFallbackCodes: this.currentFallbackCodes,
          ...(this.currentDecision ? { decision: this.currentDecision } : {})
        })
      };
      if (this.currentFinalizationMode) {
        failed.finalizationMode = this.currentFinalizationMode;
      }
      if (uiOnly) failed.uiOnly = uiOnly;
      return failed;
    }

    const ok: AgentTurnResult = {
      answer,
      state: this.state,
      phase: this.state.phase,
      toolTrace,
      validationOk: true,
      modelSteps: [...this.currentModelSteps],
      taskOutcome: buildTaskOutcome({
        goal: this.currentGoal,
        phase: this.state.phase,
        toolTrace,
        validationOk: true,
        blockingReasons: this.currentBlockingReasons,
        deterministicFallbackCodes: this.currentFallbackCodes,
        ...(this.currentDecision ? { decision: this.currentDecision } : {})
      })
    };
    if (this.currentFinalizationMode) {
      ok.finalizationMode = this.currentFinalizationMode;
    }
    if (uiOnly) ok.uiOnly = uiOnly;
    return ok;
  }

  private validateAnswer(
    answer: string,
    toolTrace: AgentTurnResult["toolTrace"]
  ) {
    const toolOk = toolTrace.every((t) => t.ok) || toolTrace.length === 0;
    const allowedNumbers = collectAllowedNumbers(this.lastToolPayloads);
    const allowedDates = collectAllowedDates(this.lastToolPayloads);
    const cited = [...answer.matchAll(/kc-[a-z0-9-]+/gi)].map((m) => m[0]!);
    const mentionedDates = extractDates(answer);
    const mentionedNumbers =
      toolTrace.length === 0 &&
      this.lastToolPayloads.length === 0 &&
      this.currentDecision !== "final"
        ? [] // policy-only replies: do not demand numeric provenance
        : extractNumbers(answer);
    const knownTemplates =
      this.lastToolPayloads.length > 0
        ? this.domain
            .getMealContext({ dinerIds: this.state.dinerIds })
            .templates.map((template) => ({
              id: template.id,
              name: template.name
            }))
        : [];

    // Use structured action status from state (single source of truth).

    return validateFinalAnswer({
      answer,
      toolOk: toolTrace.length === 0 ? true : toolOk,
      claimedSuccessWrite: false,
      // Model turns never commit writes; confirmation receipts are produced by
      // the UI/CLI side channel after this validator runs.
      hasCommitResult: false,
      actionStatus: this.state.confirmationStatus,
      successfulTools: toolTrace.filter((tool) => tool.ok).map((tool) => tool.tool),
      retrievalSourceIds: this.lastRetrievalIds,
      citedSourceIds: cited,
      allowedNumbers,
      mentionedNumbers,
      allowedDates,
      mentionedDates,
      knownTemplates,
      allowedTemplateIds: collectIds(this.lastToolPayloads, "tpl-"),
      groundedTexts: collectGroundedTexts(this.lastToolPayloads),
      hasCurrencyEvidence: hasCurrencyEvidence(this.lastToolPayloads)
    });
  }
}

/**
 * Formal model-routed Agent. Requires a non-null model provider and never
 * requires a model provider (never falls back to a simulator).
 */
export class PrivatePlateAgent extends PrivatePlateAgentCore {
  constructor(
    domain: PrivatePlateDomain,
    sessionId = `agent-${randomUUID()}`,
    modelProvider: AgentModelProvider,
    options: PrivatePlateAgentOptions = {}
  ) {
    if (!modelProvider) {
      throw new Error(
        "PrivatePlateAgent requires a non-null AgentModelProvider (local_vllm or ScriptedProductProvider)."
      );
    }
    super(domain, sessionId, modelProvider, options);
  }
}

function intentForTool(tool: string): AgentIntent {
  switch (tool) {
    case "find_dish_candidates":
    case "finalize_meal_plan":
      return "plan_meal";
    case "preview_meal_completion":
      return "handoff_task";
    case "preview_caregiver_task":
      return "handoff_task";
    case "preview_inventory_change":
    case "preview_member_memory_change":
      return "inspect_context";
    case "retrieve_local_knowledge":
      return "inspect_context";
    case "get_day_context":
      return "inspect_context";
    case "get_inventory":
      return "inspect_context";
    default:
      return "unknown";
  }
}

function isPreviewTool(tool: AgentToolName): boolean {
  return (
    tool === "preview_inventory_change" ||
    tool === "preview_member_memory_change" ||
    tool === "preview_caregiver_task" ||
    tool === "preview_meal_completion"
  );
}

function toToolOutcomeLike(
  tool: AgentToolName,
  result: ToolResult<unknown>
): ToolOutcomeLike {
  if (!result.ok) {
    return { tool, ok: false, code: result.code };
  }
  const data =
    result.data && typeof result.data === "object" && !Array.isArray(result.data)
      ? (result.data as Record<string, unknown>)
      : null;
  return { tool, ok: true, data };
}

function phaseForTool(
  tool: Extract<ModelRouteDecision, { kind: "tool" }>["tool"]
): GraphPhase {
  switch (tool) {
    case "get_day_context":
    case "get_inventory":
    case "retrieve_local_knowledge":
    case "preview_inventory_change":
    case "preview_member_memory_change":
      return "COLLECTING_CONTEXT";
    case "find_dish_candidates":
    case "finalize_meal_plan":
      return "PLANNING";
    case "preview_meal_completion":
    case "preview_caregiver_task":
      return "PREVIEWING_WRITE";
  }
}

function actionableGoal(goal: AgentGoal): LoopGoal | null {
  return goal === "no_action" || goal === "unsupported" ? null : goal;
}

/**
 * Rebuild a non-secret pending clarification from TaskState so checkpoint
 * resume can continue (e.g. recipientLabel after restart).
 */
function pendingClarificationFromTaskState(
  taskState: TaskState
): ModelPendingClarification | null {
  if (
    taskState.status !== "waiting_user" ||
    taskState.unresolvedSlots.length === 0
  ) {
    return null;
  }
  const goal = actionableGoal(taskState.objective ?? "unsupported");
  if (!goal) return null;
  const missing = [...taskState.unresolvedSlots];
  const known: Record<string, unknown> = { ...taskState.knownSlots };
  const tool: AgentToolName | null = missing.includes("recipientLabel")
    ? "preview_caregiver_task"
    : missing.includes("mealType") || missing.includes("dinerIds")
      ? "finalize_meal_plan"
      : null;
  return {
    tool,
    goal,
    missing,
    known
  };
}

/**
 * True when the model may change the turn objective after successful work.
 * Used for compose/revise → ask_user(send/preview handoff) without allowing
 * free goal drift (e.g. tool then final no_action).
 */
/** True when successful tools this turn already satisfy the loop goal. */
function goalSatisfiedBySuccessfulTools(
  goal: LoopGoal | null | undefined,
  toolResults: ModelVisibleToolResult[]
): boolean {
  if (!goal) return false;
  const ok = new Set(
    toolResults
      .filter(isSuccessfulToolOutcome)
      .map((result) => result.tool)
  );
  switch (goal) {
    case "inspect_context":
      return ok.has("get_day_context");
    case "inspect_inventory":
      return ok.has("get_inventory");
    case "compose_meal":
    case "revise_meal":
      return ok.has("finalize_meal_plan");
    case "retrieve_guidance":
      return ok.has("retrieve_local_knowledge");
    case "preview_handoff":
    case "send_handoff":
      return ok.has("preview_caregiver_task");
    case "preview_inventory":
    case "update_inventory":
      return ok.has("preview_inventory_change");
    case "preview_member_memory":
    case "update_member_memory":
      return ok.has("preview_member_memory_change");
    case "preview_meal_completion":
    case "complete_meal":
      return ok.has("preview_meal_completion");
  }
}

/**
 * Reconcile a model-declared goal with trusted workflow state.
 * get_day_context remains a neutral observation step. The next model decision
 * (find candidates or finish_turn) determines whether the turn continues.
 */
function remapDecisionGoalForTurn(input: {
  decision: ModelRouteDecision;
  rawGoal: LoopGoal | null;
  hasActivePlan: boolean;
  taskObjective: AgentGoal | null;
}): LoopGoal | null {
  if (!input.rawGoal) return null;
  if (input.decision.kind === "tool") {
    const tool = input.decision.tool;
    if (tool === "get_day_context") {
      if (
        input.taskObjective === "compose_meal" ||
        input.taskObjective === "revise_meal"
      ) {
        return input.taskObjective;
      }
      return input.rawGoal;
    }
    if (tool === "find_dish_candidates" || tool === "finalize_meal_plan") {
      if (input.hasActivePlan || input.rawGoal === "revise_meal") {
        return "revise_meal";
      }
      return "compose_meal";
    }
  }

  // A resumed structured objective may continue across a clarification.
  if (input.rawGoal === "inspect_context") {
    if (
      input.taskObjective === "compose_meal" ||
      input.taskObjective === "revise_meal"
    ) {
      return input.taskObjective;
    }
  }

  return input.rawGoal;
}

function mayAdvanceLoopGoal(input: {
  from: LoopGoal;
  to: LoopGoal;
  decision: ModelRouteDecision;
  modelToolResults: ModelVisibleToolResult[];
  hasActivePlan: boolean;
}): boolean {
  if (input.from === input.to) return true;

  // Planning pipeline: day context → candidates/finalize is legal progression,
  // not mid-turn goal drift (stage gate forces get_day_context first).
  if (
    input.from === "inspect_context" &&
    (input.to === "compose_meal" || input.to === "revise_meal") &&
    input.decision.kind === "tool" &&
    (input.decision.tool === "find_dish_candidates" ||
      input.decision.tool === "finalize_meal_plan" ||
      input.decision.tool === "get_day_context")
  ) {
    return true;
  }
  if (
    input.from === "compose_meal" &&
    input.to === "revise_meal" &&
    input.decision.kind === "tool" &&
    (input.decision.tool === "find_dish_candidates" ||
      input.decision.tool === "finalize_meal_plan") &&
    input.hasActivePlan
  ) {
    return true;
  }

  if (
    input.from === "retrieve_guidance" &&
    (input.to === "preview_handoff" || input.to === "send_handoff") &&
    input.decision.kind === "tool" &&
    input.decision.tool === "preview_caregiver_task" &&
    input.hasActivePlan
  ) {
    return true;
  }

  if (input.decision.kind !== "ask_user") return false;
  if (!input.modelToolResults.some(isSuccessfulToolOutcome)) return false;
  if (!input.hasActivePlan) return false;
  const handoffGoals: LoopGoal[] = ["send_handoff", "preview_handoff"];
  if (!handoffGoals.includes(input.to)) return false;
  const planGoals: LoopGoal[] = [
    "compose_meal",
    "revise_meal",
    "inspect_context",
    "retrieve_guidance",
    "preview_handoff"
  ];
  return planGoals.includes(input.from);
}

function blockedToolFallbackMessage(reason: string): string {
  switch (reason) {
    case "confirmation_required":
      return "任务卡预览已生成，尚未发送，仍需在界面确认。";
    case "plan_infeasible":
      return "当前硬约束和明确拒绝下没有可行计划（NO_FEASIBLE_PLAN）。请说明愿意调整的软偏好后再试；硬约束未被放宽。";
    case "approved_evidence_missing":
      return "当前没有检索到足够的审核依据，本轮已停止，不会编造解释。";
    default:
      return "目标工具结果已经保留，本轮已停止重复调用。";
  }
}

function compactConversationAnswer(answer: string): string {
  return answer.length <= MAX_HISTORY_ASSISTANT_LENGTH
    ? answer
    : `${answer.slice(0, MAX_HISTORY_ASSISTANT_LENGTH)}…`;
}

function requireActionableGoal(goal: AgentGoal): LoopGoal {
  const actionable = actionableGoal(goal);
  if (!actionable) {
    throw new Error("Executable model tool must preserve an actionable goal.");
  }
  return actionable;
}

function modelTraceForDecision(
  decision: ModelRouteDecision,
  providerMode: string
): NonNullable<AgentTurnResult["modelTrace"]> {
  const policyReasons =
    decision.kind === "tool"
      ? decision.policy.reasons
      : decision.kind === "ask_user"
        ? decision.reasons
        : decision.kind === "refuse"
          ? [decision.reasonCode]
          : [];
  return {
    providerMode,
    model: decision.model,
    decisionKind: decision.kind,
    transport:
      decision.kind === "final"
        ? decision.transport ?? "native_function"
        : "native_function",
    tool:
      decision.kind === "tool" || decision.kind === "ask_user"
        ? decision.tool
        : null,
    raw_model_arguments:
      decision.kind === "tool" || decision.kind === "ask_user"
        ? decision.raw_model_arguments
        : null,
    normalized_model_arguments:
      decision.kind === "tool" || decision.kind === "ask_user"
        ? decision.normalized_model_arguments
        : null,
    effective_arguments:
      decision.kind === "tool"
        ? decision.effective_arguments
        : null,
    privacy_violation: decision.privacy_violation,
    policy_reasons: policyReasons,
    format_retry_count: decision.format_retry_count,
    format_retry_reasons: decision.format_retry_reasons
  };
}

function toModelSteps(
  decision: ModelRouteDecision,
  providerMode: string
): AgentModelStep[] {
  const retrySteps: AgentModelStep[] = decision.format_retry_reasons.map(
    (reason, index) => ({
      index,
      providerMode,
      model: decision.model,
      decision: "retry",
      goal: decision.goal,
      tool: "tool" in decision ? decision.tool : null,
      rawArguments: null,
      normalizedArguments: null,
      effectiveArguments: null,
      policy: {
        status: "needs_clarification",
        reasons: [reason],
        privacyViolation: decision.privacy_violation
      },
      missingFields: []
    })
  );
  if (decision.kind === "final" || decision.kind === "refuse") {
    return [...retrySteps, {
      index: retrySteps.length,
      providerMode,
      model: decision.model,
      decision: decision.kind,
      ...(decision.kind === "final"
        ? { transport: decision.transport ?? "native_function" }
        : {}),
      goal: decision.goal,
      tool: null,
      rawArguments: null,
      normalizedArguments: null,
      effectiveArguments: null,
      policy: {
        status: "not_applicable",
        reasons:
          decision.kind === "refuse" && decision.reasonCode
            ? [decision.reasonCode]
            : [],
        privacyViolation: decision.privacy_violation
      },
      missingFields: []
    }];
  }
  return [...retrySteps, {
    index: retrySteps.length,
    providerMode,
    model: decision.model,
    decision: decision.kind,
    goal: decision.goal,
    tool: decision.tool,
    rawArguments: decision.raw_model_arguments,
    normalizedArguments: decision.normalized_model_arguments,
    effectiveArguments: decision.effective_arguments,
    policy: {
      status: decision.policy.status,
      reasons: decision.policy.reasons,
      privacyViolation: decision.privacy_violation
    },
    missingFields:
      decision.kind === "ask_user" ? decision.missingFields : []
  }];
}

function handoffPendingClarification(
  userText: string,
  serveAt: unknown = SAFE_DEFAULTS.handoffServeAt,
  goal: AgentGoal = "preview_handoff"
): ModelPendingClarification {
  const resolved = resolveHandoffServeAt(userText);
  const knownServeAt =
    resolved.status === "ok" && resolved.source === "user_text"
      ? resolved.value
      : typeof serveAt === "string" && serveAt.length > 0
        ? serveAt
        : SAFE_DEFAULTS.handoffServeAt;
  return {
    tool: "preview_caregiver_task",
    goal: goal === "send_handoff" ? "send_handoff" : "preview_handoff",
    missing: ["recipientLabel"],
    known: {
      serveAt: knownServeAt
    }
  };
}

/** Spoken short forms for dish templates in household Chinese. */
function templateAliases(name: string): string[] {
  const aliases: string[] = [];
  if (name.includes("蒸蛋")) aliases.push("蒸蛋");
  if (name.includes("番茄") && name.includes("蛋")) aliases.push("番茄炒蛋");
  if (name.includes("土豆") && name.includes("鸡")) aliases.push("土豆炖鸡腿");
  return aliases;
}
