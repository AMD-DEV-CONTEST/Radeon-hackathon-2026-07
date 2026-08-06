import type { AgentGoal } from "../contracts.js";
import type { AgentToolName } from "../state.js";
import type { ToolGatewayResult } from "../tools/gateway.js";
import type { ModelVisibleToolResult } from "./provider.js";
import {
  classifyToolOutcome,
  isSuccessfulToolOutcome
} from "../tool-outcome.js";

type LoopGoal = Exclude<AgentGoal, "no_action" | "unsupported">;

export function toModelVisibleToolResult(input: {
  step: number;
  goal: LoopGoal;
  tool: AgentToolName;
  outcome: ToolGatewayResult;
}): ModelVisibleToolResult {
  const { result } = input.outcome;
  if (!result.ok) {
    return {
      step: input.step,
      goal: input.goal,
      tool: input.tool,
      ok: false,
      code: result.code,
      retryable: result.retryable,
      data: {
        message: result.userSafeMessage
      }
    };
  }

  const data = compactModelToolData(
    input.tool,
    sanitizeToolData(input.tool, result.data)
  );
  const classification = classifyToolOutcome({
    tool: input.tool,
    ok: true,
    data
  });
  return {
    step: input.step,
    goal: input.goal,
    tool: input.tool,
    ok: classification.kind === "succeeded",
    ...(classification.code ? { code: classification.code } : {}),
    ...(classification.kind === "business_rejected"
      ? { retryable: true }
      : {}),
    data
  };
}

function sanitizeToolData(
  tool: AgentToolName,
  value: unknown
): Record<string, unknown> {
  const data = asRecord(value);
  switch (tool) {
    case "get_day_context":
      return {
        serviceDate: data.serviceDate,
        householdContextVersion: data.householdContextVersion,
        inventoryVersion: data.inventoryVersion,
        intakeVersion: data.intakeVersion,
        mealPolicyVersion: data.mealPolicyVersion,
        householdIntake: data.householdIntake,
        memberIntake: data.memberIntake,
        completedMeals: data.completedMeals,
        inventory: data.inventory,
        members: data.members
      };
    case "get_inventory":
      return {
        inventoryVersion: data.inventoryVersion,
        householdContextVersion: data.householdContextVersion,
        inventory: data.inventory
      };
    case "find_dish_candidates":
      return {
        candidateSetId: data.candidateSetId,
        versionStamp: data.versionStamp,
        candidates: data.candidates,
        byRole: data.byRole,
        selectionGuidance: data.selectionGuidance
      };
    case "finalize_meal_plan":
      return data;
    case "preview_meal_completion":
      return data;
    case "preview_caregiver_task":
      return {
        pendingActionId: data.pendingActionId,
        expiresAt: data.expiresAt,
        taskCard: data.taskCard,
        disclosureCheck: data.disclosureCheck,
        note: data.note
      };
    case "retrieve_local_knowledge":
      return {
        queryId: data.queryId,
        retrievalVersion: data.retrievalVersion,
        embeddingModel: data.embeddingModel,
        embeddingKind: data.embeddingKind,
        hits: data.hits,
        cards: data.cards,
        note: data.note
      };
    case "preview_inventory_change":
    case "preview_member_memory_change":
      return data;
    default:
      return data;
  }
}

export function compactModelToolData(
  tool: AgentToolName,
  data: Record<string, unknown>
): Record<string, unknown> {
  switch (tool) {
    case "get_day_context":
      return compactDayContext(data);
    case "get_inventory":
      return {
        inventoryVersion: data.inventoryVersion,
        householdContextVersion: data.householdContextVersion,
        inventory: data.inventory
      };
    case "find_dish_candidates":
      return compactCandidates(data);
    case "finalize_meal_plan":
      return compactPlanResult(data);
    case "preview_meal_completion":
      return compactMealCompletionPreview(data);
    case "preview_caregiver_task":
      return compactCaregiverPreview(data);
    case "retrieve_local_knowledge":
      return compactRetrieval(data);
    case "preview_inventory_change":
    case "preview_member_memory_change":
      return compactMutationPreview(data);
    default:
      return data;
  }
}

export function projectModelToolResultsForNextDecision(
  results: ModelVisibleToolResult[]
): ModelVisibleToolResult[] {
  const last = results.at(-1);
  if (!last || !last.ok) return results;

  if (last.tool === "finalize_meal_plan" && isSuccessfulToolOutcome(last)) {
    return [last];
  }
  if (
    last.tool === "get_day_context" ||
    last.tool === "get_inventory" ||
    last.tool === "retrieve_local_knowledge" ||
    last.tool === "preview_inventory_change" ||
    last.tool === "preview_member_memory_change" ||
    last.tool === "preview_meal_completion"
  ) {
    return [last];
  }
  if (last.tool === "preview_caregiver_task") {
    const retrieval = [...results]
      .reverse()
      .find(
        (result) => result.ok && result.tool === "retrieve_local_knowledge"
      );
    return retrieval && retrieval !== last ? [retrieval, last] : [last];
  }
  if (last.tool === "find_dish_candidates") {
    const context = [...results]
      .reverse()
      .find((result) => result.ok && result.tool === "get_day_context");
    const failedFinalize = [...results]
      .reverse()
      .find(
        (result) =>
          result.tool === "finalize_meal_plan" &&
          !isSuccessfulToolOutcome(result)
      );
    return [
      ...(context ? [context] : []),
      ...(failedFinalize && failedFinalize !== context
        ? [failedFinalize]
        : []),
      last
    ];
  }
  return results;
}

const NUTRITION_FIELDS = [
  "energyKcal",
  "carbohydrateG",
  "proteinG",
  "fatG",
  "sodiumMg"
] as const;
const QUANTITY_FIELDS = [
  "estimateG",
  "minG",
  "maxG",
  "confidence",
  "conversionRuleId"
] as const;
const MAX_TEXT_LENGTH = 360;

function compactDayContext(data: Record<string, unknown>): Record<string, unknown> {
  return compactRecord({
    serviceDate: data.serviceDate,
    householdContextVersion: data.householdContextVersion,
    inventoryVersion: data.inventoryVersion,
    intakeVersion: data.intakeVersion,
    householdIntake: compactIntake(data.householdIntake),
    memberIntake: asRecords(data.memberIntake).slice(0, 8).map((item) =>
      compactRecord({
        memberId: item.memberId,
        target: compactFields(item.target, NUTRITION_FIELDS),
        consumed: compactFields(item.consumed, NUTRITION_FIELDS),
        remaining: compactFields(item.remaining, NUTRITION_FIELDS),
        nutritionBudget: compactNutritionBudget(item.nutritionBudget)
      })
    ),
    inventory: asRecords(data.inventory).slice(0, 32).map((item) =>
      compactRecord({
        id: item.id,
        foodId: item.foodId,
        rawName: item.rawName,
        priorityUse: item.priorityUse,
        quantity: compactFields(item.quantity, QUANTITY_FIELDS)
      })
    ),
    members: asRecords(data.members).slice(0, 8).map((member) =>
      compactRecord({
        id: member.id,
        displayName: member.displayName,
        roleLabel: member.roleLabel,
        preferences: asRecords(member.preferences).slice(0, 12).map((preference) =>
          compactRecord({
            id: preference.id,
            kind: preference.kind,
            note: preference.note,
            summary: preference.summary,
            polarity: preference.polarity,
            targetType: preference.targetType,
            targetId: preference.targetId
          })
        ),
        hardConstraints: asRecords(member.hardConstraints).slice(0, 12).map((constraint) =>
          compactRecord({
            id: constraint.id,
            kind: constraint.kind,
            targetId: constraint.targetId,
            summary: constraint.summary
          })
        )
      })
    ),
    completedMeals: asRecords(data.completedMeals).slice(0, 12).map((meal) =>
      compactRecord({
        id: meal.id,
        planId: meal.planId,
        mealType: meal.mealType,
        serviceDate: meal.serviceDate,
        status: meal.status,
        menu: compactMenu(meal.menu)
      })
    ),
    unitConversionRules: asRecords(data.unitConversionRules)
      .slice(0, 32)
      .map((rule) =>
        compactRecord({
          foodId: rule.foodId,
          rawUnit: rule.rawUnit,
          gramsPerUnit: rule.gramsPerUnit
        })
      )
  });
}

function compactCandidates(data: Record<string, unknown>): Record<string, unknown> {
  const byRole = asRecord(data.byRole);
  return compactRecord({
    candidateSetId: data.candidateSetId,
    versionStamp: data.versionStamp,
    candidates: asRecords(data.candidates).slice(0, 32).map((candidate) =>
      compactRecord({
        templateId: candidate.templateId,
        name: candidate.name,
        role: candidate.role,
        coversRoles: stringArray(candidate.coversRoles),
        ingredients: asRecords(candidate.ingredients).slice(0, 16).map((ingredient) =>
          compactRecord({
            foodId: ingredient.foodId,
            edibleQuantityG: ingredient.edibleQuantityG,
            edibleQuantityGMin: ingredient.edibleQuantityGMin,
            edibleQuantityGMax: ingredient.edibleQuantityGMax
          })
        ),
        inventoryFacts: compactRecord({
          coveredFoodIds: stringArray(asRecord(candidate.inventoryFacts).coveredFoodIds),
          missingFoodIds: stringArray(asRecord(candidate.inventoryFacts).missingFoodIds),
          priorityFoodIds: stringArray(asRecord(candidate.inventoryFacts).priorityFoodIds)
        }),
        nutritionPerStandardServing: compactFields(
          candidate.nutritionPerStandardServing,
          NUTRITION_FIELDS
        ),
        effortFacts: compactFields(candidate.effortFacts, [
          "effortLevel",
          "oilLevel",
          "lowSodiumVariant"
        ] as const)
      })
    ),
    byRole: Object.fromEntries(
      Object.entries(byRole).map(([role, ids]) => [role, stringArray(ids)])
    ),
    selectionGuidance: compactRecord({
      requiredRoles: stringArray(asRecord(data.selectionGuidance).requiredRoles),
      maxSelectedDishes: asRecord(data.selectionGuidance).maxSelectedDishes,
      selectionCountIsModelDecision:
        asRecord(data.selectionGuidance).selectionCountIsModelDecision,
      candidateCount: asRecord(data.selectionGuidance).candidateCount,
      multipleDishesPerRoleAllowed:
        asRecord(data.selectionGuidance).multipleDishesPerRoleAllowed,
      note: asRecord(data.selectionGuidance).note
    })
  });
}

function compactPlanResult(data: Record<string, unknown>): Record<string, unknown> {
  const recovery =
    !isSuccessfulToolOutcome({
      tool: "finalize_meal_plan",
      ok: true,
      data
    })
      ? compactPlanRecovery(data)
      : undefined;
  return compactRecord({
    code: data.code,
    message: data.message,
    status: data.status,
    selectionReason: data.selectionReason,
    mealPortionScale: data.mealPortionScale,
    recovery,
    plan: compactPlan(data.plan),
    shoppingGap: compactShoppingGap(data.shoppingGap)
  });
}

function compactPlanRecovery(
  data: Record<string, unknown>
): Record<string, unknown> {
  const details = asRecord(data.details);
  return compactRecord({
    memberResults: asRecords(details.memberResults)
      .filter((member) => member.pass === false)
      .slice(0, 8)
      .map((member) =>
        compactRecord({
          memberId: member.memberId,
          pass: member.pass,
          failures: compactTextArray(member.failures)
        })
      ),
    deficits: asRecords(details.deficits).slice(0, 8).map((deficit) =>
      compactRecord({
        memberId: deficit.memberId,
        nutrient: deficit.nutrient,
        actual: deficit.actual,
        min: deficit.min,
        max: deficit.max,
        deficit: deficit.deficit,
        excess: deficit.excess ?? deficit.surplus
      })
    ),
    mealPortionScale: details.mealPortionScale ?? data.mealPortionScale,
    mealStructure: details.mealStructure,
    reselectAllowed: details.reselectAllowed,
    failureKind: details.failureKind,
    shareOnlyAdjustmentEffective: details.shareOnlyAdjustmentEffective,
    recommendedActions: stringArray(details.recommendedActions),
    feasibleSuggestion:
      details.feasibleSuggestion ?? asRecord(details.recovery).feasibleSuggestion,
    domainSearchExhausted:
      details.domainSearchExhausted === true ||
      asRecord(details.recovery).domainSearchExhausted === true
  });
}

function compactPlan(value: unknown): Record<string, unknown> {
  const plan = asRecord(value);
  return compactRecord({
    id: plan.id,
    version: plan.version,
    status: plan.status,
    dinerIds: stringArray(plan.dinerIds),
    bundleId: plan.bundleId,
    menu: compactMenu(plan.menu),
    memberNutrition: asRecords(plan.memberNutrition).slice(0, 8).map((item) =>
      compactRecord({
        memberId: item.memberId,
        ...compactFields(item.nutrition ?? item, NUTRITION_FIELDS)
      })
    ),
    rejectedFoodIds: stringArray(plan.rejectedFoodIds),
    rejectedTemplateIds: stringArray(plan.rejectedTemplateIds),
    pinnedTemplateIds: stringArray(plan.pinnedTemplateIds),
    requestedPriorityFoodIds: stringArray(plan.requestedPriorityFoodIds),
    preferLowEffort: plan.preferLowEffort,
    prepBuffer: plan.prepBuffer,
    plannedIntake: plan.plannedIntake,
    preparedBatch: asRecords(plan.preparedBatch ?? plan.batchIngredients).slice(0, 32).map((item) =>
      compactRecord({
        templateId: item.templateId,
        foodId: item.foodId,
        quantityG: item.quantityG
      })
    )
  });
}

function compactShoppingGap(value: unknown): Record<string, unknown>[] {
  return asRecords(value).slice(0, 32).map((item) =>
    compactRecord({
      foodId: item.foodId,
      status: item.status,
      required: compactFields(item.required, QUANTITY_FIELDS),
      available: compactFields(item.available, QUANTITY_FIELDS),
      purchase: compactFields(item.purchase, QUANTITY_FIELDS),
      usedByTemplateIds: stringArray(item.usedByTemplateIds)
    })
  );
}

function compactMealCompletionPreview(
  data: Record<string, unknown>
): Record<string, unknown> {
  const preview = asRecord(data.preview);
  return compactRecord({
    mode: data.mode,
    actionType: data.actionType,
    pendingActionId: data.pendingActionId,
    preview: compactRecord({
      actionType: preview.actionType,
      planId: preview.planId,
      planVersion: preview.planVersion,
      serviceDate: preview.serviceDate,
      willRecordIntake: asRecords(preview.willRecordIntake).slice(0, 8).map((item) =>
        compactRecord({
          memberId: item.memberId,
          nutrition: compactFields(item.nutrition, NUTRITION_FIELDS)
        })
      ),
      willDebitInventory: asRecords(preview.willDebitInventory).slice(0, 32).map((item) =>
        compactRecord({
          templateId: item.templateId,
          foodId: item.foodId,
          quantityG: item.quantityG
        })
      ),
      note: preview.note
    }),
    note: data.note
  });
}

function compactCaregiverPreview(data: Record<string, unknown>): Record<string, unknown> {
  const card = asRecord(data.taskCard);
  return compactRecord({
    pendingActionId: data.pendingActionId,
    expiresAt: data.expiresAt,
    taskCard: compactRecord({
      planId: card.planId,
      planVersion: card.planVersion,
      recipientLabel: card.recipientLabel,
      serveAt: card.serveAt,
      menu: compactMenu(card.menu),
      useFromInventory: asRecords(card.useFromInventory).slice(0, 32).map((item) =>
        compactRecord({
          foodId: item.foodId,
          quantity: compactFields(item.quantity, QUANTITY_FIELDS)
        })
      ),
      shoppingItems: compactShoppingGap(card.shoppingItems),
      executionNotes: compactTextArray(card.executionNotes),
      disclosurePolicyVersion: card.disclosurePolicyVersion
    }),
    disclosureCheck: data.disclosureCheck,
    note: data.note
  });
}

function compactRetrieval(data: Record<string, unknown>): Record<string, unknown> {
  return compactRecord({
    queryId: data.queryId,
    retrievalVersion: data.retrievalVersion,
    embeddingModel: data.embeddingModel,
    embeddingKind: data.embeddingKind,
    hits: asRecords(data.hits ?? data.cards).slice(0, 5).map((hit) =>
      compactRecord({
        sourceId: hit.sourceId,
        sourcePath: hit.sourcePath,
        title: hit.title,
        score: hit.score,
        content: capText(hit.content),
        relevantContent: capText(hit.relevantContent)
      })
    ),
    note: data.note
  });
}

function compactMutationPreview(data: Record<string, unknown>): Record<string, unknown> {
  const preview = asRecord(data.preview ?? data);
  return compactRecord({
    actionType: data.actionType,
    pendingActionId: data.pendingActionId,
    preview: compactRecord({
      actionType: preview.actionType,
      foodId: preview.foodId,
      foodName: preview.foodName,
      deltaG: preview.deltaG,
      rawExpression: preview.rawExpression,
      beforeEstimateG: preview.beforeEstimateG,
      afterEstimateG: preview.afterEstimateG,
      memberId: preview.memberId,
      memberName: preview.memberName,
      kind: preview.kind,
      summary: preview.summary,
      polarity: preview.polarity,
      note: preview.note
    }),
    note: data.note
  });
}

function compactIntake(value: unknown): Record<string, unknown> {
  const intake = asRecord(value);
  return compactRecord({
    target: compactFields(intake.target, NUTRITION_FIELDS),
    consumed: compactFields(intake.consumed, NUTRITION_FIELDS),
    remaining: compactFields(intake.remaining, NUTRITION_FIELDS),
    mealBudgets: compactMealBudgets(intake.mealBudgets)
  });
}

function compactNutritionBudget(value: unknown): Record<string, unknown> {
  const budget = asRecord(value);
  return compactRecord({
    dailyTarget: compactFields(budget.dailyTarget, NUTRITION_FIELDS),
    mealBudgets: compactMealBudgets(budget.mealBudgets),
    source: budget.source,
    version: budget.version,
    calculation: compactFields(budget.calculation, [
      "method",
      "bmrKcal",
      "tdeeKcal",
      "activityFactor",
      "goalAdjustment"
    ] as const),
    applicability: budget.applicability
  });
}

function compactMealBudgets(value: unknown): Record<string, unknown> {
  const budgets = asRecord(value);
  return Object.fromEntries(
    ["breakfast", "lunch", "dinner", "snack"].map((slot) => {
      const bounds = asRecord(budgets[slot]);
      return [
        slot,
        compactRecord({
          target: compactFields(bounds.target, NUTRITION_FIELDS),
          min: compactFields(bounds.min, NUTRITION_FIELDS),
          max: compactFields(bounds.max, NUTRITION_FIELDS),
          reserve: compactFields(bounds.reserve, NUTRITION_FIELDS)
        })
      ];
    })
  );
}

function compactMenu(value: unknown): Record<string, unknown>[] {
  return asRecords(value).slice(0, 16).map((item) =>
    compactRecord({
      templateId: item.templateId,
      name: item.name,
      displayName: item.displayName,
      role: item.role,
      coversRoles: stringArray(item.coversRoles)
    })
  );
}

function compactFields<const T extends readonly string[]>(
  value: unknown,
  fields: T
): Record<string, unknown> {
  const data = asRecord(value);
  return compactRecord(
    Object.fromEntries(fields.map((field) => [field, data[field]]))
  );
}

function compactRecord(value: Record<string, unknown>): Record<string, unknown> {
  return capRecordStrings(
    Object.fromEntries(
      Object.entries(value).filter(([, nested]) => nested !== undefined)
    )
  );
}

function capRecordStrings(value: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(value).map(([key, nested]) => [
      key,
      typeof nested === "string" ? capText(nested) : nested
    ])
  );
}

function capText(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return value.length <= MAX_TEXT_LENGTH
    ? value
    : `${value.slice(0, MAX_TEXT_LENGTH)}…`;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").slice(0, 32)
    : [];
}

function compactTextArray(value: unknown): string[] {
  return stringArray(value)
    .map((item) => capText(item))
    .filter((item): item is string => item !== undefined);
}


function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}
