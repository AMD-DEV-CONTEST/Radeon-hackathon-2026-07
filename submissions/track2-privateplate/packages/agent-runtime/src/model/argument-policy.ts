import { CaregiverServeAtSchema } from "@privateplate/contracts";
import type { AgentToolName } from "../state.js";
import { canonicalizeCaregiverServeAt } from "../product-semantics.js";
import {
  filterAllowedMemberTags,
  type PrivacyMember
} from "./privacy-context.js";

export type PolicyFood = { id: string; name: string; aliases?: string[] };
export type PolicyTemplate = {
  id: string;
  name: string;
  aliases?: string[];
  ingredientFoodIds?: string[];
};
export type PolicyPlanTag = { id: string; label: string };

export type PolicyDictionary = {
  members: PrivacyMember[];
  foods: PolicyFood[];
  templates: PolicyTemplate[];
  planTags: PolicyPlanTag[];
  caregiverRecipientLabels: string[];
};

export type PolicyState = {
  dinerIds: string[];
  activePlanId?: string | null;
  activePlanVersion?: number | null;
  activePlanTemplateIds?: string[];
  /** Trusted dish referent for anaphora; never a secret. */
  focusedTemplateId?: string | null;
  expectedRecipientLabel?: string | null;
  knownServeAt?: string | null;
  rejectedFoodIds?: string[];
  rejectedTemplateIds?: string[];
};

export type PolicyResult =
  | {
      status: "ok";
      effective: Record<string, unknown>;
      /** Semantic normalization only; must not contain trusted-state repairs. */
      modelNormalized?: Record<string, unknown>;
      privacy_violation: boolean;
      reasons: string[];
    }
  | {
      status: "needs_clarification";
      effective: null;
      privacy_violation: boolean;
      reasons: string[];
    };

type PolicyInput = {
  tool: AgentToolName;
  userText: string;
  dinerIdsLocked: boolean;
  state: PolicyState;
  dictionary: PolicyDictionary;
  rawArgs: Record<string, unknown> | null;
};

/**
 * The model owns language understanding and proposes complete tool arguments.
 * This layer only enforces trusted ids, data contracts and privacy boundaries.
 */
export function applyTrustedArgumentPolicy(input: PolicyInput): PolicyResult {
  if (!input.rawArgs) {
    return needsClarification("model_arguments_missing");
  }

  switch (input.tool) {
    case "get_day_context":
      return policyGetMealContext(input);
    case "get_inventory":
      return ok({});
    case "find_dish_candidates": {
      const diners = validatedDinerIds(input);
      if (!diners.ok) return needsClarification(diners.reason);
      const rejectedFoodIds = validatedIdList(
        input.rawArgs!.rejectedFoodIds,
        input.dictionary.foods.map((item) => item.id),
        "rejected_food_ids_invalid"
      );
      if (!rejectedFoodIds.ok) return needsClarification(rejectedFoodIds.reason);
      const rejectedTemplateIds = validatedIdList(
        input.rawArgs!.rejectedTemplateIds,
        input.dictionary.templates.map((item) => item.id),
        "rejected_template_ids_invalid"
      );
      if (!rejectedTemplateIds.ok) {
        return needsClarification(rejectedTemplateIds.reason);
      }
      return ok({
        dinerIds: diners.value,
        rejectedFoodIds: rejectedFoodIds.value,
        rejectedTemplateIds: rejectedTemplateIds.value
      });
    }
    case "finalize_meal_plan": {
      const diners = validatedDinerIds(input);
      if (!diners.ok) return needsClarification(diners.reason);
      const raw = input.rawArgs!;
      if (raw.mealType !== "lunch" && raw.mealType !== "dinner") {
        return needsClarification("meal_type_invalid");
      }
      if (typeof raw.candidateSetId !== "string" || !raw.candidateSetId) {
        return needsClarification("candidate_set_missing");
      }
      if (!Array.isArray(raw.selectedDishes) || raw.selectedDishes.length === 0) {
        return needsClarification("selected_dishes_missing");
      }
      const dishes: Array<{
        templateId: string;
        relativePortion: "small" | "standard" | "large";
      }> = [];
      for (const item of raw.selectedDishes as Array<Record<string, unknown>>) {
        const templateId = String(item.templateId ?? "");
        if (
          !input.dictionary.templates.some((template) => template.id === templateId)
        ) {
          return needsClarification("selected_template_invalid");
        }
        const portion = item.relativePortion;
        dishes.push({
          templateId,
          relativePortion:
            portion === "small" || portion === "large" ? portion : "standard"
        });
      }
      const mealPortionScale = Number(raw.mealPortionScale);
      if (!Number.isFinite(mealPortionScale) || mealPortionScale <= 0 || mealPortionScale > 1.5) {
        return needsClarification("meal_portion_scale_invalid");
      }
      const mealStructure = raw.mealStructure;
      const mealStructureRecord =
        mealStructure &&
        typeof mealStructure === "object" &&
        !Array.isArray(mealStructure)
          ? (mealStructure as Record<string, unknown>)
          : null;
      if (
        mealStructureRecord &&
        (mealStructureRecord.mode === "simple" ||
          mealStructureRecord.mode === "one_pot") &&
        (typeof mealStructureRecord.reason !== "string" ||
          !mealStructureRecord.reason.trim())
      ) {
        return needsClarification("meal_structure_exception_reason_missing");
      }
      return ok({
        dinerIds: diners.value,
        mealType: raw.mealType,
        candidateSetId: String(raw.candidateSetId),
        selectedDishes: dishes,
        mealPortionScale,
        ...(mealStructure ? { mealStructure } : {}),
        selectionReason: String(raw.selectionReason ?? "")
      });
    }
    case "preview_meal_completion":
      return ok({ mode: "as_planned" });
    case "preview_caregiver_task":
      return policyPreview(input);
    case "retrieve_local_knowledge": {
      const raw = input.rawArgs!;
      if (typeof raw.query !== "string" || raw.query.trim().length === 0) {
        return needsClarification("query_missing");
      }
      const topK =
        typeof raw.topK === "number" && Number.isFinite(raw.topK)
          ? Math.min(5, Math.max(1, Math.trunc(raw.topK)))
          : 3;
      return ok({
        query: raw.query.trim().slice(0, 500),
        topK
      });
    }
    case "preview_inventory_change": {
      const raw = input.rawArgs!;
      const foodId = String(raw.foodId ?? "");
      if (!input.dictionary.foods.some((f) => f.id === foodId)) {
        return needsClarification("food_id_invalid");
      }
      const quantity =
        typeof raw.quantity === "number" && raw.quantity > 0 ? raw.quantity : 1;
      const unit = typeof raw.unit === "string" && raw.unit ? raw.unit : "盒";
      return ok({ foodId, quantity, unit });
    }
    case "preview_member_memory_change": {
      const raw = input.rawArgs!;
      const memberId = String(raw.memberId ?? "");
      if (!input.dictionary.members.some((m) => m.id === memberId)) {
        return needsClarification("member_id_invalid");
      }
      const summary = String(raw.summary ?? "").trim();
      if (!summary) return needsClarification("summary_missing");
      const kind = raw.kind === "health_fact" ? "health_fact" : "preference";
      return ok({
        memberId,
        kind,
        summary: summary.slice(0, 300),
        ...(raw.polarity === "prefer" ||
        raw.polarity === "avoid" ||
        raw.polarity === "note"
          ? { polarity: raw.polarity }
          : {})
      });
    }
  }
}

function policyGetMealContext(input: PolicyInput): PolicyResult {
  const diners = validatedDinerIds(input);
  if (!diners.ok) return needsClarification(diners.reason);

  const serviceDate = input.rawArgs?.serviceDate;
  if (serviceDate !== undefined && typeof serviceDate !== "string") {
    return needsClarification("service_date_invalid");
  }

  const effective = {
    dinerIds: diners.value,
    ...(typeof serviceDate === "string" ? { serviceDate } : {})
  };
  return ok(
    effective,
    input.dinerIdsLocked ? ["diner_ids_locked"] : [],
    effective
  );
}

function policyCompose(input: PolicyInput): PolicyResult {
  const raw = input.rawArgs!;
  const modelDiners = validatedIdList(
    raw.dinerIds,
    input.dictionary.members.map((member) => member.id),
    "diner_ids_invalid",
    true
  );
  if (!modelDiners.ok) return needsClarification(modelDiners.reason);
  const effectiveDinerIds = input.dinerIdsLocked
    ? [...input.state.dinerIds]
    : modelDiners.value;

  if (raw.mealType !== "lunch" && raw.mealType !== "dinner") {
    return needsClarification("meal_type_invalid");
  }

  const rejectedFoodIds = validatedIdList(
    raw.rejectedFoodIds,
    input.dictionary.foods.map((item) => item.id),
    "rejected_food_ids_invalid"
  );
  if (!rejectedFoodIds.ok) {
    return needsClarification(rejectedFoodIds.reason);
  }

  const rejectedTemplateIds = validatedIdList(
    raw.rejectedTemplateIds,
    input.dictionary.templates.map((item) => item.id),
    "rejected_template_ids_invalid"
  );
  if (!rejectedTemplateIds.ok) {
    return needsClarification(rejectedTemplateIds.reason);
  }

  const requestedPriorityFoodIds = validatedIdList(
    raw.requestedPriorityFoodIds,
    input.dictionary.foods.map((item) => item.id),
    "priority_food_ids_invalid"
  );
  if (!requestedPriorityFoodIds.ok) {
    return needsClarification(requestedPriorityFoodIds.reason);
  }

  const pinnedTemplateIds = validatedIdList(
    raw.pinnedTemplateIds ?? [],
    input.dictionary.templates.map((item) => item.id),
    "pinned_template_ids_invalid"
  );
  if (!pinnedTemplateIds.ok) {
    return needsClarification(pinnedTemplateIds.reason);
  }

  const conflictingPins = templatesContainingFoods(
    pinnedTemplateIds.value,
    rejectedFoodIds.value,
    input.dictionary.templates
  );
  if (conflictingPins.length > 0) {
    return needsClarification(
      `pinned_dish_conflicts_with_rejected_ingredient:${conflictingPins.join(",")}`
    );
  }

  if (typeof raw.preferLowEffort !== "boolean") {
    return needsClarification("prefer_low_effort_invalid");
  }

  // Priority foods are not dish pins. When the model both prioritizes a food and
  // pins a template that contains that food, demote the pin in effective args only.
  const priorityPinConflicts = templatesContainingFoods(
    pinnedTemplateIds.value,
    requestedPriorityFoodIds.value,
    input.dictionary.templates
  );
  const effectivePinnedTemplateIds = pinnedTemplateIds.value.filter(
    (id) => !priorityPinConflicts.includes(id)
  );
  const demoteReasons =
    priorityPinConflicts.length > 0
      ? [`priority_food_not_pin:${priorityPinConflicts.join(",")}`]
      : [];

  const modelNormalized = {
    dinerIds: modelDiners.value,
    mealType: raw.mealType,
    rejectedFoodIds: rejectedFoodIds.value,
    rejectedTemplateIds: rejectedTemplateIds.value,
    pinnedTemplateIds: pinnedTemplateIds.value,
    requestedPriorityFoodIds: requestedPriorityFoodIds.value,
    preferLowEffort: raw.preferLowEffort
  };

  return ok(
    {
      ...modelNormalized,
      dinerIds: effectiveDinerIds,
      pinnedTemplateIds: effectivePinnedTemplateIds
    },
    [
      ...(input.dinerIdsLocked ? ["diner_ids_locked"] : []),
      ...demoteReasons
    ],
    modelNormalized
  );
}

function policyRevise(input: PolicyInput): PolicyResult {
  if (!input.state.activePlanId) {
    return needsClarification("active_plan_missing");
  }

  const raw = input.rawArgs!;
  // This-turn arrays only. Never invent rejects from prior session state here.
  const templateAllow = input.state.activePlanTemplateIds?.length
    ? input.state.activePlanTemplateIds
    : input.dictionary.templates.map((item) => item.id);
  const rejectTemplateIds = validatedIdList(
    raw.rejectTemplateIds,
    templateAllow,
    "reject_template_ids_invalid"
  );
  if (!rejectTemplateIds.ok) {
    return needsClarification(rejectTemplateIds.reason);
  }

  const rejectFoodIds = validatedIdList(
    raw.rejectFoodIds,
    input.dictionary.foods.map((item) => item.id),
    "reject_food_ids_invalid"
  );
  if (!rejectFoodIds.ok) {
    return needsClarification(rejectFoodIds.reason);
  }

  if (typeof raw.preferLowEffort !== "boolean") {
    return needsClarification("prefer_low_effort_invalid");
  }

  if (
    rejectTemplateIds.value.length === 0 &&
    rejectFoodIds.value.length === 0 &&
    !raw.preferLowEffort
  ) {
    return needsClarification("revision_target_missing");
  }

  const modelNormalized = {
    rejectTemplateIds: rejectTemplateIds.value,
    rejectFoodIds: rejectFoodIds.value,
    preferLowEffort: raw.preferLowEffort
  };

  // Trusted dish referent: when focus is on the active plan, a single-dish
  // (or effort-only) revise targets the focused template, not a guessed id.
  const focusId = input.state.focusedTemplateId ?? null;
  const focusOnPlan =
    typeof focusId === "string" &&
    focusId.length > 0 &&
    templateAllow.includes(focusId);
  let effectiveRejectTemplates = rejectTemplateIds.value;
  const focusReasons: string[] = [];
  if (focusOnPlan) {
    const singleDishRevise =
      rejectTemplateIds.value.length === 1 ||
      (rejectTemplateIds.value.length === 0 &&
        rejectFoodIds.value.length === 0 &&
        raw.preferLowEffort === true);
    if (singleDishRevise) {
      effectiveRejectTemplates = [focusId!];
      if (
        rejectTemplateIds.value.length === 1 &&
        rejectTemplateIds.value[0] !== focusId
      ) {
        focusReasons.push("focused_template_overrides_reject_template");
      } else if (rejectTemplateIds.value.length === 0) {
        focusReasons.push("focused_template_applied_to_revise");
      }
    }
  }

  // Already-applied rejects only (no new effort flip) → no Domain write needed.
  const priorFoods = new Set(input.state.rejectedFoodIds ?? []);
  const priorTemplates = new Set(input.state.rejectedTemplateIds ?? []);
  const foodsAlready = rejectFoodIds.value.every((id) => priorFoods.has(id));
  const templatesAlready = effectiveRejectTemplates.every((id) =>
    priorTemplates.has(id)
  );
  if (
    foodsAlready &&
    templatesAlready &&
    raw.preferLowEffort === false &&
    (rejectFoodIds.value.length > 0 || effectiveRejectTemplates.length > 0)
  ) {
    return {
      status: "needs_clarification",
      effective: null,
      privacy_violation: false,
      reasons: ["revision_noop_already_applied"]
    };
  }

  return ok(
    {
      rejectTemplateIds: effectiveRejectTemplates,
      rejectFoodIds: rejectFoodIds.value,
      preferLowEffort: raw.preferLowEffort
    },
    focusReasons,
    modelNormalized
  );
}

function policyRetrieve(input: PolicyInput): PolicyResult {
  const raw = input.rawArgs!;
  if (typeof raw.query !== "string" || raw.query.trim().length === 0) {
    return needsClarification("guidance_query_invalid");
  }
  // Interface default for omitted topK is SAFE_DEFAULTS.guidanceTopK (=2).
  // Explicit model values in [1,3] pass through unchanged.
  const topK =
    raw.topK === undefined
      ? 2
      : raw.topK;
  if (
    typeof topK !== "number" ||
    !Number.isInteger(topK) ||
    topK < 1 ||
    topK > 3
  ) {
    return needsClarification("top_k_invalid");
  }

  // Model must not own health tags. Reject legacy memberTags if present.
  if ("memberTags" in raw && raw.memberTags !== undefined) {
    return {
      ...needsClarification("member_tags_not_model_owned"),
      privacy_violation: true
    };
  }

  const planTags = validatedIdList(
    raw.planTags,
    input.dictionary.planTags.map((item) => item.id),
    "plan_tags_invalid"
  );
  if (!planTags.ok) return needsClarification(planTags.reason);

  const memberIds = validatedIdList(
    raw.memberIds,
    input.dictionary.members.map((member) => member.id),
    "member_ids_invalid"
  );
  if (!memberIds.ok) return needsClarification(memberIds.reason);

  // Business layer: resolve health tags from member ids only.
  const memberTags = resolveMemberHealthTags(
    memberIds.value,
    input.dictionary.members,
    input.userText
  );

  return ok(
    {
      query: raw.query.trim(),
      memberIds: memberIds.value,
      memberTags,
      planTags: planTags.value,
      topK
    },
    []
  );
}

/**
 * Map selected member ids → privacy-allowed health tags for local retrieval.
 * No silent fallback: if the user did not discuss a health constraint for that
 * member, tags stay empty even when memberIds are present.
 */
export function resolveMemberHealthTags(
  memberIds: string[],
  members: PrivacyMember[],
  userText: string
): string[] {
  if (!Array.isArray(memberIds) || memberIds.length === 0) {
    return [];
  }
  const selected = new Set(memberIds);
  return unique(
    filterAllowedMemberTags(
      members
        .filter((member) => selected.has(member.id))
        .flatMap((member) => member.healthTags ?? []),
      members,
      userText
    )
  );
}

function policyPreview(input: PolicyInput): PolicyResult {
  const raw = input.rawArgs!;
  if (
    typeof raw.recipientLabel !== "string" ||
    !input.dictionary.caregiverRecipientLabels.includes(raw.recipientLabel)
  ) {
    return needsClarification("recipient_label_invalid");
  }
  if (
    !input.state.expectedRecipientLabel ||
    raw.recipientLabel !== input.state.expectedRecipientLabel
  ) {
    return needsClarification("recipient_label_mismatch");
  }

  const serveAt = canonicalizeCaregiverServeAt(
    raw.serveAt,
    input.userText,
    input.state.knownServeAt ?? undefined
  );
  if (!CaregiverServeAtSchema.safeParse(serveAt).success) {
    return needsClarification("serve_at_invalid");
  }

  return ok({
    recipientLabel: raw.recipientLabel,
    serveAt
  });
}

function validatedDinerIds(
  input: PolicyInput
):
  | { ok: true; value: string[] }
  | { ok: false; reason: string } {
  if (input.dinerIdsLocked) {
    return { ok: true, value: [...input.state.dinerIds] };
  }
  return validatedIdList(
    input.rawArgs?.dinerIds,
    input.dictionary.members.map((member) => member.id),
    "diner_ids_invalid",
    true
  );
}

function validatedIdList(
  value: unknown,
  allowedIds: string[],
  reason: string,
  requireNonEmpty = false
):
  | { ok: true; value: string[] }
  | { ok: false; reason: string } {
  const values = stringList(value);
  if (!values.ok || (requireNonEmpty && values.value.length === 0)) {
    return { ok: false, reason };
  }
  const allowed = new Set(allowedIds);
  if (values.value.some((id) => !allowed.has(id))) {
    return { ok: false, reason };
  }
  return { ok: true, value: unique(values.value) };
}

function stringList(
  value: unknown
):
  | { ok: true; value: string[] }
  | { ok: false } {
  if (!Array.isArray(value)) {
    return { ok: false };
  }
  const strings = value.filter(
    (item): item is string => typeof item === "string"
  );
  return strings.length === value.length
    ? { ok: true, value: strings }
    : { ok: false };
}

function ok(
  effective: Record<string, unknown>,
  reasons: string[] = [],
  modelNormalized?: Record<string, unknown>
): PolicyResult {
  return {
    status: "ok",
    effective,
    ...(modelNormalized ? { modelNormalized } : {}),
    privacy_violation: false,
    reasons
  };
}

function needsClarification(reason: string): PolicyResult {
  return {
    status: "needs_clarification",
    effective: null,
    privacy_violation: false,
    reasons: [reason]
  };
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function templatesContainingFoods(
  templateIds: string[],
  foodIds: string[],
  templates: PolicyTemplate[]
): string[] {
  if (templateIds.length === 0 || foodIds.length === 0) return [];
  const rejectedFoods = new Set(foodIds);
  const byId = new Map(templates.map((template) => [template.id, template]));
  return templateIds.filter((id) =>
    byId
      .get(id)
      ?.ingredientFoodIds?.some((foodId) => rejectedFoods.has(foodId))
  );
}
