/**
 * Controllable local product Provider for deterministic loop/E2E tests.
 * Protocol v2 planning + caregiver handoff preview + meal-complete preview.
 * Not model-quality evidence.
 */
import { classifyIntent } from "../policy.js";
import {
  goalForTool,
  missingFieldsFromPolicyReasons,
  normalizeMissingFields,
  normalizeReasonCode,
  type AgentGoal,
  type MissingField
} from "../contracts.js";
import type { AgentToolName } from "../state.js";
import {
  classifyToolOutcome,
  isSuccessfulToolOutcome
} from "../tool-outcome.js";
import {
  extractPriorityFoodIds,
  extractRejectedFoodIds,
  extractRejectedTemplateIds
} from "../slot-extract.js";
import {
  resolveHandoffRecipient,
  resolveMealTypeSlot
} from "../product-semantics.js";
import {
  applyTrustedArgumentPolicy,
  type PolicyDictionary
} from "./argument-policy.js";
import type {
  AgentModelProvider,
  ModelRouteDecision,
  ModelRouteInput
} from "./provider.js";

export type ScriptedRouteStep =
  | { kind: "auto" }
  | {
      kind: "ask_user";
      goal?: AgentGoal;
      tool?: AgentToolName;
      missingFields: MissingField[] | string[];
      message?: string;
      knownArgs?: Record<string, unknown>;
    }
  | {
      kind: "final";
      goal?: Exclude<AgentGoal, "unsupported">;
      message?: string;
    }
  | { kind: "refuse"; reasonCode?: string; message?: string }
  | { kind: "throw"; message: string }
  | {
      kind: "tool";
      tool: AgentToolName;
      goal?: AgentGoal;
      rawArgs?: Record<string, unknown>;
    };

export type ScriptedProductProviderOptions = {
  model?: string;
  steps?: ScriptedRouteStep[];
  turns?: ScriptedRouteStep[][];
};

export function inferToolFromUserText(
  userText: string,
  state: ModelRouteInput["state"],
  pendingClarification: ModelRouteInput["pendingClarification"] = null,
  availableDomainTools?: readonly string[] | null
): AgentToolName | null {
  const allow = (tool: AgentToolName): AgentToolName | null => {
    if (!availableDomainTools) return tool;
    return availableDomainTools.includes(tool) ? tool : null;
  };
  if (pendingClarification?.tool === "preview_caregiver_task") {
    return state.activePlanId ? allow("preview_caregiver_task") : null;
  }
  if (pendingClarification?.tool === "preview_meal_completion") {
    return state.activePlanId ? allow("preview_meal_completion") : null;
  }
  const intent = classifyIntent(userText);
  if (intent.safeStop || intent.injectionFlag) return null;
  if (!intent.allowContinue) return null;
  switch (intent.intent) {
    case "inspect_context":
      if (/买了|采购了|入库|补了|刚买|两盒|一盒|补充库存|进货/.test(userText)) {
        return allow("preview_inventory_change");
      }
      if (/偏好|少油|忌口|注意|健康事实|记住/.test(userText)) {
        return allow("preview_member_memory_change");
      }
      if (/只查看库存|查看库存|库存清单|有什么食材|冰箱里/.test(userText)) {
        return allow("get_inventory");
      }
      return allow("get_day_context");
    case "plan_meal":
      return allow("get_day_context");
    case "revise_meal":
      return state.activePlanId
        ? allow("find_dish_candidates")
        : allow("get_day_context");
    case "handoff_task":
      if (state.hasPendingAction) return null;
      return state.activePlanId ? allow("preview_caregiver_task") : null;
    case "retrieve_guidance":
      return allow("retrieve_local_knowledge");
    default:
      return null;
  }
}

function nextAutoAfterTool(input: ModelRouteInput): ScriptedRouteStep | null {
  const last = input.currentTurn.toolResults.at(-1);
  if (!last) return null;
  const intent = classifyIntent(input.userText).intent;
  const allow = (tool: AgentToolName): boolean =>
    !input.availableActions?.domainTools ||
    input.availableActions.domainTools.includes(tool);
  const lastOutcome = classifyToolOutcome(last);
  const finalizeFailed =
    last.tool === "finalize_meal_plan" &&
    lastOutcome.kind !== "succeeded";
  const staleCodes = new Set([
    "STALE_CONTEXT",
    "STALE_CANDIDATE_SET",
    "CANDIDATE_SET_MISMATCH",
    "UNKNOWN_CANDIDATE_SET",
    "MISSING_CANDIDATE_SET"
  ]);
  const failureCode =
    lastOutcome.kind === "succeeded" ? "" : lastOutcome.code;

  if (
    finalizeFailed &&
    staleCodes.has(failureCode) &&
    allow("get_day_context")
  ) {
    return { kind: "tool", tool: "get_day_context" };
  }

  if (lastOutcome.kind === "invocation_failed") return null;

  if (
    last.tool === "get_day_context" &&
    (intent === "plan_meal" ||
      intent === "revise_meal" ||
      input.currentTurn.goal === "compose_meal" ||
      input.currentTurn.goal === "revise_meal")
  ) {
    return allow("find_dish_candidates")
      ? { kind: "tool", tool: "find_dish_candidates" }
      : null;
  }

  if (last.tool === "find_dish_candidates") {
    if (!allow("finalize_meal_plan")) return null;
    const data = last.data ?? {};
    const recoveryProbe =
      /满足所有硬约束/.test(input.userText) &&
      !input.currentTurn.toolResults.some(
        (result) =>
          result.tool === "finalize_meal_plan" &&
          !isSuccessfulToolOutcome(result)
      );
    return finalizeFromCandidates(input, data, recoveryProbe);
  }

  if (finalizeFailed && allow("finalize_meal_plan")) {
    const candidateResult = input.currentTurn.toolResults
      .slice()
      .reverse()
      .find(
        (result) =>
          result.tool === "find_dish_candidates" &&
          isSuccessfulToolOutcome(result)
      );
    if (candidateResult) {
      return finalizeFromCandidates(input, candidateResult.data ?? {}, false);
    }
  }

  if (finalizeFailed && allow("find_dish_candidates")) {
    return { kind: "tool", tool: "find_dish_candidates" };
  }

  return null;
}

function finalizeFromCandidates(
  input: ModelRouteInput,
  data: Record<string, unknown>,
  recoveryProbe: boolean
): ScriptedRouteStep {
  const candidates = Array.isArray(data.candidates)
    ? (data.candidates as Array<{ templateId: string; role: string }>)
    : [];
  const rejectedFoods = new Set(extractRejectedFoodIds(input.userText));
  const rejectedTemplates = new Set(
    extractRejectedTemplateIds(input.userText)
  );
  const filtered = candidates.filter(
    (candidate) =>
      !rejectedTemplates.has(candidate.templateId) &&
      !(rejectedFoods.has("food-chicken-leg") &&
        candidate.templateId.includes("chicken"))
  );
  const preferredTemplateIds: Record<string, string[]> = {
    shared_main: [
      "tpl-pork-cabbage",
      "tpl-steamed-fish",
      "tpl-potato-chicken"
    ],
    shared_side: [
      "tpl-shiitake-egg",
      "tpl-garlic-spinach",
      "tpl-cucumber-salad"
    ],
    staple: ["tpl-leftover-rice", "tpl-plain-rice", "tpl-millet-porridge"]
  };
  const byRole = (role: string) =>
    preferredTemplateIds[role]?.find((templateId) =>
      filtered.some((candidate) => candidate.templateId === templateId)
    ) ?? filtered.find((candidate) => candidate.role === role)?.templateId;
  const prioritizesTofu =
    extractPriorityFoodIds(input.userText).includes("food-tofu") ||
    /豆腐/.test(input.userText) ||
    (/入库/.test(input.userText) && /规划/.test(input.userText));
  const asksForRicherMeal = /丰富一点|多一道蔬菜|多做两个菜|多做几道菜|菜多一点|再来一道/.test(
    input.userText
  );
  const preferredMain = prioritizesTofu
    ? filtered.find((candidate) => candidate.templateId.includes("tofu"))
        ?.templateId
    : undefined;
  const preferredSide = prioritizesTofu
    ? filtered.find((candidate) => candidate.templateId === "tpl-shiitake-egg")
        ?.templateId ?? byRole("shared_side")
    : byRole("shared_side");
  const additionalSide = prioritizesTofu
    ? filtered.find((candidate) => candidate.templateId === "tpl-steamed-fish")
        ?.templateId
    : undefined;
  const richerSide = asksForRicherMeal
    ? filtered.find(
        (candidate) =>
          candidate.role === "shared_side" &&
          candidate.templateId !== preferredSide
      )?.templateId
    : undefined;
  const dishes = [
    preferredMain ?? byRole("shared_main"),
    preferredSide,
    additionalSide,
    richerSide,
    byRole("staple")
  ].filter((id): id is string => Boolean(id));
  const unique = [...new Set(dishes)].slice(0, 5);
  if (unique.length === 0 && filtered[0]) {
    unique.push(filtered[0].templateId);
  }
  const mealType = resolveMealTypeSlot(input.userText);
  return {
    kind: "tool",
    tool: "finalize_meal_plan",
    rawArgs: {
      dinerIds: mockDinerIds(input),
      mealType: mealType.status === "ok" ? mealType.value : "lunch",
      candidateSetId: String(data.candidateSetId ?? "cset-scripted"),
      selectedDishes: recoveryProbe
        ? [{ templateId: "tpl-tomato-beef", relativePortion: "standard" }]
        : unique.map((templateId) => ({
            templateId,
            relativePortion: "standard"
          })),
      mealPortionScale: 1,
      mealStructure: {
        mode: "standard",
        requiredRoles: ["shared_main", "shared_side", "staple"],
        omittedRoles: []
      },
      selectionReason: "脚本测试：基于候选与拒绝项提交完整菜单。"
    }
  };
}

function buildCoarseRawArgs(
  tool: AgentToolName,
  input: ModelRouteInput
): Record<string, unknown> {
  const text = input.userText;
  switch (tool) {
    case "get_day_context":
      return { dinerIds: mockDinerIds(input) };
    case "get_inventory":
      return {};
    case "find_dish_candidates":
      return {
        dinerIds: mockDinerIds(input),
        rejectedFoodIds: extractRejectedFoodIds(text),
        rejectedTemplateIds: extractRejectedTemplateIds(text)
      };
    case "finalize_meal_plan": {
      const mealType = resolveMealTypeSlot(text);
      return {
        dinerIds: mockDinerIds(input),
        mealType: mealType.status === "ok" ? mealType.value : "lunch",
        candidateSetId: "cset-scripted",
        selectedDishes: [
          {
            templateId: "tpl-cabbage-tofu-braise",
            relativePortion: "standard"
          },
          { templateId: "tpl-shiitake-egg", relativePortion: "standard" },
          { templateId: "tpl-leftover-rice", relativePortion: "standard" }
        ],
        mealPortionScale: 0.4,
        mealStructure: {
          mode: "standard",
          requiredRoles: ["shared_main", "shared_side", "staple"],
          omittedRoles: []
        },
        selectionReason: "脚本默认菜单。"
      };
    }
    case "preview_meal_completion":
      return { mode: "as_planned" };
    case "preview_caregiver_task": {
      const recipient =
        /阿姨/.test(text) ? "阿姨" : /保姆|家庭保姆/.test(text) ? "保姆" : "保姆";
      return {
        recipientLabel: recipient,
        serveAt: "unspecified"
      };
    }
    case "retrieve_local_knowledge":
      return {
        query: text.slice(0, 500),
        topK: 3
      };
    case "preview_inventory_change": {
      const qtyMatch = text.match(/([一二两三四1234])\s*盒/);
      const map: Record<string, number> = {
        一: 1,
        二: 2,
        两: 2,
        三: 3,
        四: 4,
        "1": 1,
        "2": 2,
        "3": 3,
        "4": 4
      };
      const quantity = qtyMatch ? map[qtyMatch[1]!] ?? 2 : 2;
      return {
        foodId: "food-tofu",
        quantity,
        unit: "盒"
      };
    }
    case "preview_member_memory_change":
      return {
        memberId: /爸|父/.test(text)
          ? "mem-father"
          : /妈|母/.test(text)
            ? "mem-mother"
            : "mem-admin",
        kind: "preference",
        summary: /少油|清淡/.test(text) ? "少油清淡" : text.slice(0, 80),
        polarity: "prefer"
      };
    default:
      return {};
  }
}

function mockDinerIds(input: ModelRouteInput): string[] {
  const text = input.userText;
  if (/全家|一家三口|所有人|大家|我们三个人/.test(text)) {
    return input.memberDirectory.map((member) => member.id);
  }
  if (/爸妈|父母|爸爸和妈妈/.test(text)) {
    return input.memberDirectory
      .filter(
        (member) =>
          member.roleLabel === "father" || member.roleLabel === "mother"
      )
      .map((member) => member.id);
  }
  const mentioned = input.memberDirectory.filter((member) =>
    [member.displayName, ...(member.aliases ?? [])].some((name) =>
      text.includes(name)
    )
  );
  return mentioned.length > 0
    ? mentioned.map((member) => member.id)
    : [...input.state.dinerIds];
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

export class ScriptedProductProvider implements AgentModelProvider {
  readonly mode = "scripted_mock" as const;
  readonly model: string;
  private readonly steps: ScriptedRouteStep[];
  private readonly turns: ScriptedRouteStep[][];
  private userTurnIndex = -1;

  constructor(options: ScriptedProductProviderOptions = {}) {
    this.model = options.model ?? "scripted-mock-product-provider";
    this.steps = options.steps ?? [];
    this.turns = options.turns ?? [];
  }

  reset(): void {
    this.userTurnIndex = -1;
  }

  async route(input: ModelRouteInput): Promise<ModelRouteDecision> {
    if (input.currentTurn.decisionIndex === 0) {
      this.userTurnIndex += 1;
    }
    const decisionIndex = input.currentTurn.decisionIndex;
    const explicitTurn = this.turns[this.userTurnIndex];
    let step = explicitTurn
      ? explicitTurn[decisionIndex] ?? finalStepForCurrentTurn(input)
      : decisionIndex === 0
        ? this.steps[this.userTurnIndex] ??
          ({ kind: "auto" } satisfies ScriptedRouteStep)
        : nextAutoAfterTool(input) ?? finalStepForCurrentTurn(input);

    if (step.kind === "auto" && input.currentTurn.decisionIndex > 0) {
      step = nextAutoAfterTool(input) ?? finalStepForCurrentTurn(input);
    }

    if (step.kind === "throw") {
      throw new Error(step.message);
    }
    if (step.kind === "final") {
      return {
        kind: "final",
        goal: step.goal ?? "no_action",
        message: step.message ?? "好的，本轮不再继续操作。",
        reasonCode: null,
        model: this.model,
        privacy_violation: false,
        format_retry_count: 0,
        format_retry_reasons: []
      };
    }
    if (step.kind === "refuse") {
      return {
        kind: "refuse",
        goal: "unsupported",
        message: step.message ?? "这个请求不在当前支持范围内。",
        reasonCode:
          normalizeReasonCode(step.reasonCode) ?? "UNSUPPORTED_OR_UNCLEAR",
        model: this.model,
        privacy_violation: false,
        format_retry_count: 0,
        format_retry_reasons: []
      };
    }
    if (step.kind === "ask_user") {
      const missingFields = normalizeMissingFields(step.missingFields);
      return {
        kind: "ask_user",
        goal: step.goal
          ? step.goal
          : input.pendingClarification
            ? input.pendingClarification.goal
            : "compose_meal",
        tool: step.tool ?? input.pendingClarification?.tool ?? null,
        message: step.message ?? "请补充完成该操作所需的信息。",
        missingFields,
        raw_model_arguments: step.knownArgs ?? null,
        normalized_model_arguments: step.knownArgs ?? null,
        effective_arguments: null,
        policy: {
          status: "needs_clarification",
          effective: null,
          privacy_violation: false,
          reasons: missingFields.map((field) => `${field}_missing`)
        },
        privacy_violation: false,
        model: this.model,
        reasons: missingFields.map((field) => `${field}_missing`),
        format_retry_count: 0,
        format_retry_reasons: []
      };
    }

    let tool: AgentToolName | null;
    let rawArgs: Record<string, unknown>;
    if (step.kind === "tool") {
      tool = step.tool;
      rawArgs = step.rawArgs ?? buildCoarseRawArgs(tool, input);
    } else {
      tool = inferToolFromUserText(
        input.userText,
        input.state,
        input.pendingClarification,
        input.availableActions?.domainTools
      );
      if (!tool) {
        if (
          input.state.hasPendingAction &&
          classifyIntent(input.userText).intent === "handoff_task"
        ) {
          return {
            kind: "final",
            goal: "preview_handoff",
            message:
              "本餐完成预览已生成；请在可信界面确认后才会写入摄入与库存。",
            reasonCode: null,
            model: this.model,
            privacy_violation: false,
            format_retry_count: 0,
            format_retry_reasons: []
          };
        }
        if (/不用了|不继续|到这里|先这样/.test(input.userText)) {
          return {
            kind: "final",
            goal: "no_action",
            message: "好的，本轮不再继续操作。",
            reasonCode: null,
            model: this.model,
            privacy_violation: false,
            format_retry_count: 0,
            format_retry_reasons: []
          };
        }
        return {
          kind: "refuse",
          goal: "unsupported",
          message: "这个请求不在当前支持范围内。",
          reasonCode: "UNSUPPORTED_OR_UNCLEAR",
          model: this.model,
          privacy_violation: false,
          format_retry_count: 0,
          format_retry_reasons: []
        };
      }
      rawArgs = buildCoarseRawArgs(tool, input);
    }

    const intent = classifyIntent(input.userText).intent;
    const requestedGoal =
      step.kind === "tool" && step.goal
        ? step.goal
        : tool === "preview_caregiver_task"
          ? /直接.*(发送|发给)|替我发|发出去|准备发送|发给/.test(input.userText)
            ? "send_handoff"
            : "preview_handoff"
          : intent === "plan_meal" || intent === "revise_meal"
            ? "compose_meal"
            : goalForTool(tool);

    const allowedRecipients =
      input.fixtureDirectory.caregiverRecipientLabels ?? [
        "家庭保姆",
        "保姆",
        "阿姨"
      ];
    const recipientFromText = resolveHandoffRecipient(
      input.userText,
      allowedRecipients
    );
    const expectedRecipientLabel =
      recipientFromText.status === "ok" ? recipientFromText.value : null;

    // Keep raw args recipient aligned with trusted expected label when present.
    if (
      tool === "preview_caregiver_task" &&
      expectedRecipientLabel &&
      typeof rawArgs.recipientLabel !== "string"
    ) {
      rawArgs = { ...rawArgs, recipientLabel: expectedRecipientLabel };
    }
    if (
      tool === "preview_caregiver_task" &&
      expectedRecipientLabel &&
      typeof rawArgs.recipientLabel === "string"
    ) {
      rawArgs = { ...rawArgs, recipientLabel: expectedRecipientLabel };
    }

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
        expectedRecipientLabel,
        rejectedFoodIds: input.state.rejectedFoodIds,
        rejectedTemplateIds: input.state.rejectedTemplateIds
      },
      dictionary: toPolicyDictionary(input),
      rawArgs
    });

    const privacyHit = policy.privacy_violation === true;

    if (policy.status !== "ok" || !policy.effective) {
      return {
        kind: "ask_user",
        goal: requestedGoal,
        tool,
        message: "请补充完成该操作所需的信息。",
        missingFields: missingFieldsFromPolicyReasons(policy.reasons),
        raw_model_arguments: rawArgs,
        normalized_model_arguments: rawArgs,
        effective_arguments: null,
        policy,
        privacy_violation: privacyHit,
        model: this.model,
        reasons: policy.reasons,
        format_retry_count: 0,
        format_retry_reasons: []
      };
    }

    if (privacyHit) {
      return {
        kind: "ask_user",
        goal: requestedGoal,
        tool,
        message: "检测到隐私风险，本轮不会执行。",
        missingFields: [],
        raw_model_arguments: rawArgs,
        normalized_model_arguments: rawArgs,
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
        format_retry_count: 0,
        format_retry_reasons: []
      };
    }

    return {
      kind: "tool",
      goal: requestedGoal,
      tool,
      arguments: policy.effective,
      raw_model_arguments: rawArgs,
      normalized_model_arguments: policy.modelNormalized ?? rawArgs,
      effective_arguments: policy.effective,
      policy,
      privacy_violation: false,
      model: this.model,
      format_retry_count: 0,
      format_retry_reasons: []
    };
  }
}

function finalStepForCurrentTurn(input: ModelRouteInput): ScriptedRouteStep {
  return {
    kind: "final",
    goal: input.currentTurn.goal ?? "no_action",
    message: scriptedFinalMessage(input)
  };
}

function scriptedFinalMessage(input: ModelRouteInput): string {
  const result = input.currentTurn.toolResults.at(-1);
  if (!result) return "好的，本轮不再继续操作。";
  if (!isSuccessfulToolOutcome(result)) {
    return "工具未能完成当前操作，本轮已停止。";
  }
  switch (result.tool) {
    case "get_day_context":
      return "已读取当日目标、剩余额度、库存与家庭记忆。";
    case "get_inventory":
      return "已读取当前库存快照。";
    case "find_dish_candidates":
      return "已返回候选菜品事实（无排名）。";
    case "finalize_meal_plan":
      return "已根据 Agent 选择生成家庭餐计划，尚未写入摄入或扣库存。";
    case "preview_meal_completion":
      return "已预览本餐完成后的写入影响；请在界面确认。";
    case "preview_caregiver_task":
      return `已预览给执行者的任务卡与采购清单；请在界面确认后才会写入。${
        retrievedSourceSuffix(input)
      }`;
    case "retrieve_local_knowledge":
      return `已从本地知识库检索到相关片段（依据：${sourceIdsFromResult(result).join(
        "、"
      ) || "本地知识库"}）。`;
    case "preview_inventory_change":
      return "已预览库存入库；请在界面确认后才会写入。";
    case "preview_member_memory_change":
      return "已预览家庭资料变更；请在界面确认后才会写入。";
    default:
      return "好的，本轮不再继续操作。";
  }
}

function retrievedSourceSuffix(input: ModelRouteInput): string {
  const sourceIds = input.currentTurn.toolResults.flatMap((item) =>
    item.tool === "retrieve_local_knowledge" ? sourceIdsFromResult(item) : []
  );
  return sourceIds.length > 0 ? `依据：${sourceIds.join("、")}` : "";
}

function sourceIdsFromResult(result: { data: Record<string, unknown> | null }): string[] {
  const cards = Array.isArray(result.data?.cards) ? result.data.cards : [];
  const cardSourceIds = cards.flatMap((card) => {
    if (!card || typeof card !== "object") return [];
    const sourceId = (card as { sourceId?: unknown }).sourceId;
    return typeof sourceId === "string" ? [sourceId] : [];
  });
  const hits = Array.isArray(result.data?.hits) ? result.data.hits : [];
  const hitSourceIds = hits.flatMap((hit) => {
    if (!hit || typeof hit !== "object") return [];
    const sourcePath = (hit as { sourcePath?: unknown }).sourcePath;
    if (typeof sourcePath === "string") return [sourcePath];
    const sourceId = (hit as { sourceId?: unknown }).sourceId;
    return typeof sourceId === "string" ? [sourceId] : [];
  });
  return [...new Set([...cardSourceIds, ...hitSourceIds])];
}
