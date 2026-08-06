import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import type { CaregiverTaskCard } from "@privateplate/contracts";
import type { PrivatePlateDomain } from "@privateplate/domain";
import type { AgentState, AgentToolName } from "../state.js";
import { assertToolAllowed } from "../policy.js";
import { toolFailure, toolSuccess, type ToolResult } from "./types.js";

export type UiOnlySideChannel = {
  confirmationToken: string;
  payloadHash: string;
  expiresAt: string;
  pendingActionId: string;
  actionType?: string;
  confirmLabel?: string;
  taskCard?: CaregiverTaskCard;
  preview?: Record<string, unknown>;
};

type UnmeasuredToolGatewayResult = {
  result: ToolResult<unknown>;
  statePatch: Partial<AgentState>;
  /** Never enter AgentState / model messages / logs as plaintext long-term. */
  uiOnly?: UiOnlySideChannel;
};

export type ToolGatewayResult = UnmeasuredToolGatewayResult & {
  durationMs: number;
};

export class ToolGateway {
  constructor(private readonly domain: PrivatePlateDomain) {}

  async invoke(
    state: AgentState,
    toolName: string,
    args: Record<string, unknown>,
    sourceUtterance = "",
    availableDomainTools?: readonly AgentToolName[]
  ): Promise<ToolGatewayResult> {
    const startedAt = performance.now();
    const outcome = await this.invokeNow(
      state,
      toolName,
      args,
      sourceUtterance,
      availableDomainTools
    );
    return {
      ...outcome,
      durationMs: Math.max(0, performance.now() - startedAt)
    };
  }

  private async invokeNow(
    state: AgentState,
    toolName: string,
    args: Record<string, unknown>,
    sourceUtterance: string,
    availableDomainTools?: readonly AgentToolName[]
  ): Promise<UnmeasuredToolGatewayResult> {
    const auditRef = `tool-${randomUUID()}`;
    // Single authorization source: precomputed available Domain tools.
    const allowed = assertToolAllowed(
      state.phase,
      toolName,
      availableDomainTools
    );
    if (!allowed.ok) {
      return {
        result: toolFailure(toolName, allowed.code, allowed.message, auditRef, false),
        statePatch: { lastToolStatus: "failure", errorCode: allowed.code }
      };
    }

    if (state.toolSteps >= state.maxToolSteps) {
      return {
        result: toolFailure(
          toolName,
          "RISK_GUARD_TRIGGERED",
          "本轮工具调用次数已达上限。",
          auditRef,
          false
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "MAX_STEPS" }
      };
    }

    try {
      switch (allowed.tool) {
        case "get_day_context":
          return this.getDayContext(state, args, auditRef);
        case "get_inventory":
          return this.getInventory(state, auditRef);
        case "find_dish_candidates":
          return this.findDishCandidates(state, args, auditRef);
        case "finalize_meal_plan":
          return this.finalizeMealPlan(state, args, auditRef);
        case "preview_meal_completion":
          return this.previewMealCompletion(state, args, auditRef);
        case "preview_caregiver_task":
          return this.previewCaregiverTask(state, args, auditRef);
        case "retrieve_local_knowledge":
          return await this.retrieveLocalKnowledge(state, args, auditRef);
        case "preview_inventory_change":
          return this.previewInventoryChange(state, args, auditRef);
        case "preview_member_memory_change":
          return this.previewMemberMemoryChange(state, args, auditRef);
        default:
          return {
            result: toolFailure(toolName, "VALIDATION_ERROR", "未知工具", auditRef),
            statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
          };
      }
    } catch (error) {
      const code =
        error && typeof error === "object" && "code" in error
          ? String((error as { code: string }).code)
          : "INTERNAL_ERROR";
      const mapped =
        code === "STALE_CONTEXT"
          ? "STALE_CONTEXT"
          : code === "GUARD_CONFIG_MISSING"
            ? "GUARD_CONFIG_MISSING"
            : "INTERNAL_ERROR";
      return {
        result: toolFailure(
          toolName,
          mapped,
          mapped === "STALE_CONTEXT"
            ? "家庭或库存版本已变化，请重新读取上下文。"
            : "工具执行失败，请稍后重试。",
          auditRef,
          mapped === "STALE_CONTEXT"
        ),
        statePatch: { lastToolStatus: "failure", errorCode: mapped }
      };
    }
  }

  private getInventory(
    state: AgentState,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    const data = this.domain.getInventory();
    return {
      result: toolSuccess(
        "get_inventory",
        data,
        auditRef,
        data.householdContextVersion
      ),
      statePatch: {
        lastToolStatus: "success",
        errorCode: null,
        toolSteps: state.toolSteps + 1,
        householdContextVersion: data.householdContextVersion,
        inventoryVersion: data.inventoryVersion
      }
    };
  }

  private getDayContext(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    const dinerIds = Array.isArray(args.dinerIds)
      ? (args.dinerIds as string[])
      : state.dinerIds;
    const data = this.domain.getDayContext({
      dinerIds,
      ...(typeof args.serviceDate === "string"
        ? { serviceDate: args.serviceDate }
        : {})
    });
    return {
      result: toolSuccess("get_day_context", data, auditRef, data.householdContextVersion),
      statePatch: {
        lastToolStatus: "success",
        errorCode: null,
        toolSteps: state.toolSteps + 1,
        dinerIds,
        householdContextVersion: data.householdContextVersion,
        inventoryVersion: data.inventoryVersion,
        mealPolicyVersion: data.mealPolicyVersion
      }
    };
  }

  private findDishCandidates(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    const dinerIds = Array.isArray(args.dinerIds)
      ? (args.dinerIds as string[])
      : state.dinerIds;
    const data = this.domain.findDishCandidates({
      dinerIds,
      rejectedFoodIds: [
        ...state.rejectedFoodIds,
        ...((args.rejectedFoodIds as string[] | undefined) ?? [])
      ],
      rejectedTemplateIds: [
        ...state.rejectedTemplateIds,
        ...((args.rejectedTemplateIds as string[] | undefined) ?? [])
      ]
    });
    return {
      result: toolSuccess("find_dish_candidates", data, auditRef),
      statePatch: {
        lastToolStatus: "success",
        errorCode: null,
        toolSteps: state.toolSteps + 1,
        dinerIds
      }
    };
  }

  private finalizeMealPlan(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    const mealType = args.mealType;
    if (mealType !== "lunch" && mealType !== "dinner") {
      return {
        result: toolFailure(
          "finalize_meal_plan",
          "VALIDATION_ERROR",
          "缺少有效的用餐时段（lunch/dinner）。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
    type RelativePortion = "small" | "standard" | "large";
    const selectedDishes: Array<{
      templateId: string;
      relativePortion: RelativePortion;
    }> = Array.isArray(args.selectedDishes)
      ? (args.selectedDishes as Array<{
          templateId: string;
          relativePortion?: string;
        }>).map((d) => {
          const relativePortion: RelativePortion =
            d.relativePortion === "small" || d.relativePortion === "large"
              ? d.relativePortion
              : "standard";
          return {
            templateId: String(d.templateId),
            relativePortion
          };
        })
      : [];
    const candidateSetId = String(args.candidateSetId ?? "");
    const mealPortionScale =
      typeof args.mealPortionScale === "number"
        ? args.mealPortionScale
        : Number(args.mealPortionScale);
    const selectionReason = String(args.selectionReason ?? "");
    const dinerIds = Array.isArray(args.dinerIds)
      ? (args.dinerIds as string[])
      : state.dinerIds;

    const mealStructure =
      args.mealStructure && typeof args.mealStructure === "object"
        ? (args.mealStructure as import("@privateplate/contracts").MealStructure)
        : undefined;
    const maxDishCount =
      mealStructure?.mode === "one_pot"
        ? 1
        : typeof args.maxDishCount === "number"
          ? args.maxDishCount
          : undefined;

    const result = this.domain.finalizeMealPlan({
      sessionId: state.mealSessionId ?? `meal-${randomUUID()}`,
      dinerIds,
      mealType,
      candidateSetId,
      selectedDishes,
      mealPortionScale: Number.isFinite(mealPortionScale) ? mealPortionScale : 1,
      ...(mealStructure ? { mealStructure } : {}),
      selectionReason:
        selectionReason || "Agent 提交的本餐选择。",
      ...(state.activePlanId && state.activePlanVersion
        ? {
            parentPlan: {
              id: state.activePlanId,
              version: state.activePlanVersion
            }
          }
        : {}),
      rejectedFoodIds: [...state.rejectedFoodIds],
      rejectedTemplateIds: [...state.rejectedTemplateIds],
      bannedFoodIds: [...state.rejectedFoodIds],
      bannedTemplateIds: [...state.rejectedTemplateIds],
      ...(maxDishCount !== undefined ? { maxDishCount } : {})
    });

    if (result.status !== "ok") {
      return {
        result: toolSuccess("finalize_meal_plan", result, auditRef),
        statePatch: {
          lastToolStatus: "success",
          errorCode: result.code,
          toolSteps: state.toolSteps + 1
        }
      };
    }

    return {
      result: toolSuccess(
        "finalize_meal_plan",
        {
          status: "ok",
          plan: summarizePlan(result.plan),
          shoppingGap: result.shoppingGap,
          selectionReason: result.selectionReason,
          mealPortionScale: result.mealPortionScale
        },
        auditRef
      ),
      statePatch: {
        lastToolStatus: "success",
        errorCode: null,
        toolSteps: state.toolSteps + 1,
        phase: "PRESENTING_PLAN",
        mealSessionId: result.plan.sessionId,
        activePlanId: result.plan.id,
        activePlanVersion: result.plan.version,
        dinerIds: result.plan.dinerIds,
        householdContextVersion: result.plan.householdContextVersion,
        inventoryVersion: result.plan.inventoryVersion,
        mealPolicyVersion: result.plan.mealPolicyVersion
      }
    };
  }

  private previewMealCompletion(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    if (!state.activePlanId) {
      return {
        result: toolFailure(
          "preview_meal_completion",
          "VALIDATION_ERROR",
          "没有活动计划，无法预览餐后记录。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
    const plan = this.domain.getPlanById(state.activePlanId);
    if (!plan) {
      return {
        result: toolFailure(
          "preview_meal_completion",
          "STALE_CONTEXT",
          "计划已不存在。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "STALE_CONTEXT" }
      };
    }
    const mode = args.mode === "as_planned" || !args.mode ? "as_planned" : String(args.mode);
    if (mode !== "as_planned") {
      return {
        result: toolFailure(
          "preview_meal_completion",
          "VALIDATION_ERROR",
          "当前仅支持 as_planned 餐后确认。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
    // Creates pending meal_completion — write only via confirmPendingWrite.
    try {
      const out = this.domain.previewMealCompletion({ planId: plan.id });
      return {
        result: toolSuccess(
          "preview_meal_completion",
          {
            mode: "as_planned",
            actionType: out.actionType,
            preview: out.preview,
            pendingActionId: out.confirmation.pendingActionId,
            note: "确认后才会写入摄入、扣减库存；聊天确认不会提交。"
          },
          auditRef
        ),
        statePatch: {
          lastToolStatus: "success",
          errorCode: null,
          toolSteps: state.toolSteps + 1,
          phase: "PREVIEWING_WRITE",
          confirmationStatus: "previewed",
          pendingActionId: out.confirmation.pendingActionId
        },
        uiOnly: {
          confirmationToken: out.confirmation.confirmationToken,
          payloadHash: out.confirmation.payloadHash,
          expiresAt: out.confirmation.expiresAt,
          pendingActionId: out.confirmation.pendingActionId,
          actionType: "meal_completion",
          confirmLabel: "确认本餐已按计划吃完",
          preview: out.preview
        }
      };
    } catch (error) {
      return {
        result: toolFailure(
          "preview_meal_completion",
          "VALIDATION_ERROR",
          error instanceof Error ? error.message : "预览餐后写入失败",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
  }

  /**
   * Preview min-disclosure caregiver / shopping task card for the active plan.
   * Does not send. UI confirm writes via trusted side channel.
   * Shopping items come from plan.shoppingGap (Domain nutrition + gap math).
   */
  private previewCaregiverTask(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    if (!state.activePlanId) {
      return {
        result: toolFailure(
          "preview_caregiver_task",
          "VALIDATION_ERROR",
          "没有活动计划，无法预览任务卡。",
          auditRef,
          false
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }

    if (
      typeof args.recipientLabel !== "string" ||
      args.recipientLabel.length === 0
    ) {
      return {
        result: toolFailure(
          "preview_caregiver_task",
          "VALIDATION_ERROR",
          "缺少接收人标签，无法预览任务卡。",
          auditRef,
          false
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }

    const preview = this.domain.previewCaregiverSend({
      planId: state.activePlanId,
      recipientLabel: args.recipientLabel,
      serveAt:
        typeof args.serveAt === "string" && args.serveAt.length > 0
          ? args.serveAt
          : "unspecified"
    });

    // Model-visible payload must NOT include confirmation token.
    const modelData = {
      pendingActionId: preview.confirmation.pendingActionId,
      payloadHash: preview.confirmation.payloadHash,
      expiresAt: preview.confirmation.expiresAt,
      taskCard: preview.preview,
      disclosureCheck: {
        policyVersion: preview.preview.disclosurePolicyVersion,
        forbiddenDiseaseNamesPresent: false
      },
      note: "确认令牌仅通过 UI 侧通道交付；Agent 不能提交 commit。"
    };

    return {
      result: toolSuccess("preview_caregiver_task", modelData, auditRef),
      statePatch: {
        lastToolStatus: "success",
        errorCode: null,
        toolSteps: state.toolSteps + 1,
        pendingActionId: preview.confirmation.pendingActionId,
        lastCommittedActionId: null,
        lastCommittedPayloadHash: null,
        phase: "PREVIEWING_WRITE",
        confirmationStatus: "previewed"
      },
      uiOnly: {
        confirmationToken: preview.confirmation.confirmationToken,
        payloadHash: preview.confirmation.payloadHash,
        expiresAt: preview.confirmation.expiresAt,
        pendingActionId: preview.confirmation.pendingActionId,
        actionType: "caregiver_task_send",
        confirmLabel: "确认发送（模拟）",
        taskCard: preview.preview
      }
    };
  }

  private previewInventoryChange(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    const foodId = String(args.foodId ?? "");
    if (!foodId) {
      return {
        result: toolFailure(
          "preview_inventory_change",
          "VALIDATION_ERROR",
          "缺少 foodId。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
    try {
      const out = this.domain.previewInventoryChange({
        foodId,
        ...(typeof args.quantity === "number" ? { quantity: args.quantity } : {}),
        ...(typeof args.unit === "string" ? { unit: args.unit } : {}),
        ...(typeof args.deltaG === "number" ? { deltaG: args.deltaG } : {}),
        ...(typeof args.rawExpression === "string"
          ? { rawExpression: args.rawExpression }
          : {})
      });
      return {
        result: toolSuccess(
          "preview_inventory_change",
          {
            actionType: out.actionType,
            preview: out.preview,
            pendingActionId: out.confirmation.pendingActionId,
            note: "确认入库后才会修改库存；聊天确认不会提交。"
          },
          auditRef
        ),
        statePatch: {
          lastToolStatus: "success",
          errorCode: null,
          toolSteps: state.toolSteps + 1,
          pendingActionId: out.confirmation.pendingActionId,
          phase: "PREVIEWING_WRITE",
          confirmationStatus: "previewed"
        },
        uiOnly: {
          confirmationToken: out.confirmation.confirmationToken,
          payloadHash: out.confirmation.payloadHash,
          expiresAt: out.confirmation.expiresAt,
          pendingActionId: out.confirmation.pendingActionId,
          actionType: "inventory_restock",
          confirmLabel: "确认入库",
          preview: out.preview
        }
      };
    } catch (error) {
      return {
        result: toolFailure(
          "preview_inventory_change",
          "VALIDATION_ERROR",
          error instanceof Error ? error.message : "预览入库失败",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
  }

  private previewMemberMemoryChange(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): UnmeasuredToolGatewayResult {
    const memberId = String(args.memberId ?? "");
    const kind =
      args.kind === "health_fact" ? "health_fact" : "preference";
    const summary = String(args.summary ?? "").trim();
    if (!memberId || !summary) {
      return {
        result: toolFailure(
          "preview_member_memory_change",
          "VALIDATION_ERROR",
          "缺少 memberId 或 summary。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
    try {
      const out = this.domain.previewMemberMemoryChange({
        memberId,
        kind,
        summary,
        ...(args.polarity === "prefer" ||
        args.polarity === "avoid" ||
        args.polarity === "note"
          ? { polarity: args.polarity }
          : {})
      });
      return {
        result: toolSuccess(
          "preview_member_memory_change",
          {
            actionType: out.actionType,
            preview: out.preview,
            pendingActionId: out.confirmation.pendingActionId,
            note: "确认保存后才会写入家庭记忆。"
          },
          auditRef
        ),
        statePatch: {
          lastToolStatus: "success",
          errorCode: null,
          toolSteps: state.toolSteps + 1,
          pendingActionId: out.confirmation.pendingActionId,
          phase: "PREVIEWING_WRITE",
          confirmationStatus: "previewed"
        },
        uiOnly: {
          confirmationToken: out.confirmation.confirmationToken,
          payloadHash: out.confirmation.payloadHash,
          expiresAt: out.confirmation.expiresAt,
          pendingActionId: out.confirmation.pendingActionId,
          actionType: "member_memory_change",
          confirmLabel: "确认保存家庭资料",
          preview: out.preview
        }
      };
    } catch (error) {
      return {
        result: toolFailure(
          "preview_member_memory_change",
          "VALIDATION_ERROR",
          error instanceof Error ? error.message : "预览家庭资料失败",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
  }

  /** Local embedding RAG over fixtures/knowledge/corpus. */
  private async retrieveLocalKnowledge(
    state: AgentState,
    args: Record<string, unknown>,
    auditRef: string
  ): Promise<UnmeasuredToolGatewayResult> {
    const query = String(args.query ?? "").trim();
    if (!query) {
      return {
        result: toolFailure(
          "retrieve_local_knowledge",
          "VALIDATION_ERROR",
          "缺少检索 query。",
          auditRef,
          true
        ),
        statePatch: { lastToolStatus: "failure", errorCode: "VALIDATION_ERROR" }
      };
    }
    const topKRaw = Number(args.topK ?? 3);
    const topK = Number.isFinite(topKRaw) ? topKRaw : 3;
    const data = await this.domain.retrieveLocalKnowledge({ query, topK });
    return {
      result: toolSuccess("retrieve_local_knowledge", data, auditRef),
      statePatch: {
        lastToolStatus: "success",
        errorCode: null,
        toolSteps: state.toolSteps + 1
      }
    };
  }
}

function summarizePlan(plan: {
  id: string;
  version: number;
  status: string;
  dinerIds: string[];
  bundleId: string;
  sharedTemplates: Array<{
    templateId: string;
    name: string;
    role: string;
    coversRoles?: string[] | undefined;
  }>;
  memberAllocations: Array<{
    memberId: string;
    nutrition: {
      energyKcal: number;
      carbohydrateG: number;
      proteinG: number;
      fatG: number;
      sodiumMg: number;
    };
  }>;
  plannedIntake: unknown;
  preparedBatch?: Array<{ foodId: string; quantityG: number }>;
  batchIngredients?: Array<{ foodId: string; quantityG: number }>;
  prepBuffer?: number | undefined;
  nutritionSummary: unknown;
  shoppingGap: unknown;
  rejectedFoodIds: string[];
  rejectedTemplateIds: string[];
  pinnedTemplateIds: string[];
  requestedPriorityFoodIds: string[];
  preferLowEffort: boolean;
  selectionTrace: { selectedBundleId: string | null };
}) {
  const preparedBatch = plan.preparedBatch ?? plan.batchIngredients ?? [];
  const includedFoodIds = new Set(preparedBatch.map((item) => item.foodId));
  const requestedPriorityFoodIds = [...plan.requestedPriorityFoodIds];
  return {
    id: plan.id,
    version: plan.version,
    status: plan.status,
    dinerIds: plan.dinerIds,
    bundleId: plan.bundleId,
    menu: plan.sharedTemplates.map((t) => ({
      templateId: t.templateId,
      name: t.name,
      role: t.role,
      ...(t.coversRoles ? { coversRoles: t.coversRoles } : {})
    })),
    memberNutrition: plan.memberAllocations.map((m) => ({
      memberId: m.memberId,
      energyKcal: m.nutrition.energyKcal,
      carbohydrateG: m.nutrition.carbohydrateG,
      proteinG: m.nutrition.proteinG,
      fatG: m.nutrition.fatG,
      sodiumMg: m.nutrition.sodiumMg
    })),
    plannedIntake: plan.plannedIntake,
    preparedBatch,
    ...(plan.prepBuffer == null ? {} : { prepBuffer: plan.prepBuffer }),
    shoppingGap: plan.shoppingGap,
    rejectedFoodIds: plan.rejectedFoodIds,
    rejectedTemplateIds: plan.rejectedTemplateIds,
    pinnedTemplateIds: plan.pinnedTemplateIds,
    requestedPriorityFoodIds,
    priorityFoodOutcome: {
      requestedFoodIds: requestedPriorityFoodIds,
      includedFoodIds: requestedPriorityFoodIds.filter((id) =>
        includedFoodIds.has(id)
      ),
      omittedFoodIds: requestedPriorityFoodIds.filter(
        (id) => !includedFoodIds.has(id)
      )
    },
    preferLowEffort: plan.preferLowEffort,
    selectedBundleId: plan.selectionTrace.selectedBundleId
  };
}
