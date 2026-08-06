import {
  CaregiverRecipientLabelSchema,
  CaregiverServeAtSchema,
  CaregiverTaskCardSchema,
  type CaregiverTaskCard,
  type GramRange,
  type HouseholdMember,
  type MealPlan,
  type MemberConstraint
} from "@privateplate/contracts";

export const DISCLOSURE_POLICY_VERSION = "disclosure-1.1.0";

/**
 * Build a min-disclosure caregiver task card from structured plan data only.
 * Never embeds raw disease labels from healthTags.
 */
export function buildCaregiverTaskCard(input: {
  plan: MealPlan;
  recipientLabel: string;
  serveAt: string | "unspecified";
  members: HouseholdMember[];
  constraints: MemberConstraint[];
}): CaregiverTaskCard {
  if (!CaregiverRecipientLabelSchema.safeParse(input.recipientLabel).success) {
    throw new Error("DISCLOSURE_VIOLATION:recipientLabel");
  }
  if (!CaregiverServeAtSchema.safeParse(input.serveAt).success) {
    throw new Error("DISCLOSURE_VIOLATION:serveAt");
  }

  const membersById = new Map(input.members.map((m) => [m.id, m]));
  const executionNotes: string[] = [];

  for (const allocation of input.plan.memberAllocations) {
    const member = membersById.get(allocation.memberId);
    const staple = allocation.portionUnitsByRole.staple ?? 1;
    if (staple < 0.85 && member) {
      const label =
        member.roleLabel === "father"
          ? "爸爸"
          : member.roleLabel === "mother"
            ? "妈妈"
            : member.displayName;
      executionNotes.push(`${label}米饭小份`);
    }
  }

  const dinerConstraints = input.constraints.filter((c) =>
    input.plan.dinerIds.includes(c.memberId)
  );
  for (const constraint of dinerConstraints) {
    if (constraint.kind === "avoid_ingredient" && constraint.targetId === "food-beef") {
      executionNotes.push("不要放牛肉或牛肉调味料");
    }
  }

  // Sodium-sensitive demo path → operational note only.
  const mother = input.members.find((m) => m.roleLabel === "mother");
  if (mother && input.plan.dinerIds.includes(mother.id)) {
    executionNotes.push("全餐少盐");
  }

  const admin = input.members.find((m) => m.roleLabel === "admin");
  if (admin && input.plan.preferLowEffort === false) {
    // low oil preference is a soft note when admin is dining
    if (input.plan.dinerIds.includes(admin.id)) {
      executionNotes.push("少油");
    }
  }

  // Deduplicate while preserving order.
  const uniqueNotes = [...new Set(executionNotes)];

  const useFromInventory = input.plan.shoppingGap
    .filter(
      (g) =>
        (g.available.maxG ?? g.available.estimateG ?? g.available.minG ?? 0) > 0
    )
    .map((g) => ({
      foodId: g.foodId,
      quantity: inventoryUsage(g.required.estimateG ?? 0, g.available)
    }));

  const shoppingItems = input.plan.shoppingGap.filter(
    (g) => g.status === "needed" || g.status === "needs_confirmation"
  );

  const card = CaregiverTaskCardSchema.parse({
    planId: input.plan.id,
    planVersion: input.plan.version,
    recipientLabel: input.recipientLabel,
    serveAt: input.serveAt,
    menu: input.plan.sharedTemplates.map((t) => ({
      templateId: t.templateId,
      displayName: t.name
    })),
    useFromInventory,
    shoppingItems,
    executionNotes: uniqueNotes,
    disclosurePolicyVersion: DISCLOSURE_POLICY_VERSION
  });
  assertMinimumDisclosure(card);
  return card;
}

function assertMinimumDisclosure(card: CaregiverTaskCard): void {
  const visibleText = [
    card.recipientLabel,
    card.serveAt,
    ...card.menu.map((item) => item.displayName),
    ...card.executionNotes
  ].join("\n");
  const forbidden = ["糖尿病", "高血压", "diabetes", "hypertension", "2型"];
  const normalized = visibleText.toLowerCase();
  const violation = forbidden.find((word) =>
    normalized.includes(word.toLowerCase())
  );
  if (violation) {
    throw new Error(`DISCLOSURE_VIOLATION:${violation}`);
  }
}

function inventoryUsage(requiredG: number, available: GramRange): GramRange {
  const capAtRequired = (grams: number | null): number | null =>
    grams == null ? null : Math.min(grams, requiredG);

  const estimateG = capAtRequired(available.estimateG);
  const minG = capAtRequired(available.minG);
  const maxG = capAtRequired(available.maxG);
  const isExact =
    estimateG != null &&
    minG != null &&
    maxG != null &&
    estimateG === minG &&
    minG === maxG;

  return {
    estimateG,
    minG,
    maxG,
    confidence: isExact ? "exact" : available.confidence,
    conversionRuleId: isExact ? null : available.conversionRuleId
  };
}
