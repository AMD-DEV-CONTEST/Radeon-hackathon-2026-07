import { z } from "zod";
import { MealRoleSchema, MealTypeSchema, PlanStatusSchema } from "./enums.js";
import { MemberConstraintSchema } from "./household.js";
import { GramRangeSchema } from "./quantity.js";
import { NutritionPer100gSchema } from "./food.js";

export const ComposeFamilyMealInputSchema = z.object({
  householdId: z.string().min(1),
  mealSessionId: z.string().min(1),
  dinerIds: z.array(z.string().min(1)).min(1).max(3),
  mealType: MealTypeSchema,
  householdContextVersion: z.number().int().positive(),
  inventoryVersion: z.number().int().positive(),
  mealPolicyVersion: z.string().min(1),
  constraints: z.array(MemberConstraintSchema),
  pinnedTemplateIds: z.array(z.string()),
  rejectedTemplateIds: z.array(z.string()),
  rejectedFoodIds: z.array(z.string()),
  requestedPriorityFoodIds: z.array(z.string()),
  preferLowEffort: z.boolean().default(false)
});

export type ComposeFamilyMealInput = z.infer<typeof ComposeFamilyMealInputSchema>;

export const MemberAllocationItemSchema = z.object({
  templateId: z.string(),
  role: MealRoleSchema,
  foodId: z.string(),
  quantityG: z.number()
});

export const MemberAllocationSchema = z.object({
  memberId: z.string(),
  items: z.array(MemberAllocationItemSchema),
  nutrition: NutritionPer100gSchema,
  portionUnitsByRole: z.record(MealRoleSchema, z.number())
});

export type MemberAllocation = z.infer<typeof MemberAllocationSchema>;

export const MealStructureModeSchema = z.enum(["standard", "simple", "one_pot"]);
export type MealStructureMode = z.infer<typeof MealStructureModeSchema>;

export const MealStructureSchema = z
  .object({
    mode: MealStructureModeSchema,
    requiredRoles: z.array(MealRoleSchema),
    omittedRoles: z.array(MealRoleSchema),
    reason: z.string().max(200).optional()
  })
  .superRefine((structure, ctx) => {
    if (structure.mode !== "standard" && !structure.reason?.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["reason"],
        message: "simple 或 one_pot 必须说明例外原因"
      });
    }
  });

export type MealStructure = z.infer<typeof MealStructureSchema>;

export const PlannedIntakeSchema = z.object({
  byMember: z.array(MemberAllocationSchema),
  householdTotal: NutritionPer100gSchema
});

export type PlannedIntake = z.infer<typeof PlannedIntakeSchema>;

export const PreparedBatchIngredientSchema = z.object({
  templateId: z.string(),
  foodId: z.string(),
  quantityG: z.number().nonnegative()
});

export type PreparedBatchIngredient = z.infer<typeof PreparedBatchIngredientSchema>;

export const SelectionTraceSchema = z.object({
  candidateBundleIds: z.array(z.string()),
  eliminatedBundleIds: z.array(z.string()),
  ranking: z.array(
    z.object({
      bundleId: z.string(),
      hardConstraintsPass: z.boolean(),
      requestedPriorityScore: z.number(),
      priorityConsumeScore: z.number(),
      inventoryCoverageScore: z.number(),
      distinctPurchaseCount: z.number(),
      softPreferenceScore: z.number(),
      effortScore: z.number(),
      tieBreakId: z.string()
    })
  ),
  selectedBundleId: z.string().nullable(),
  foodDataVersion: z.string(),
  templateVersions: z.array(z.string()),
  mealPolicyVersion: z.string(),
  /** Protocol v2: Agent-selected dishes (Domain does not pick a winner). */
  agentSelection: z
    .object({
      candidateSetId: z.string(),
      selectedDishes: z.array(
        z.object({
          templateId: z.string(),
          relativePortion: z.enum(["small", "standard", "large"])
        })
      ),
      mealPortionScale: z.number(),
      mealStructure: MealStructureSchema,
      selectionReason: z.string()
    })
    .optional()
});

export type SelectionTrace = z.infer<typeof SelectionTraceSchema>;

export const ShoppingGapItemSchema = z.object({
  foodId: z.string(),
  required: GramRangeSchema,
  available: GramRangeSchema,
  purchase: GramRangeSchema,
  status: z.enum(["not_needed", "needed", "needs_confirmation"]),
  usedByTemplateIds: z.array(z.string())
});

export type ShoppingGapItem = z.infer<typeof ShoppingGapItemSchema>;

export const MealPlanSchema = z.object({
  id: z.string(),
  sessionId: z.string(),
  version: z.number().int().positive(),
  parentPlanId: z.string().nullable(),
  status: PlanStatusSchema,
  householdId: z.string(),
  mealType: MealTypeSchema,
  dinerIds: z.array(z.string()),
  householdContextVersion: z.number().int(),
  inventoryVersion: z.number().int(),
  mealPolicyVersion: z.string(),
  bundleId: z.string(),
  sharedTemplates: z.array(
    z.object({
      templateId: z.string(),
      name: z.string(),
      role: MealRoleSchema,
      /** Roles covered by the template; compound dishes may cover more than role. */
      coversRoles: z.array(MealRoleSchema).min(1).optional(),
      templateVersion: z.string()
    })
  ),
  memberAllocations: z.array(MemberAllocationSchema),
  plannedIntake: PlannedIntakeSchema,
  preparedBatch: z.array(PreparedBatchIngredientSchema),
  /** Compatibility alias for existing read-only Web surfaces and old fixtures. */
  batchIngredients: z.array(PreparedBatchIngredientSchema),
  /** New plans expose the configured 5%–10% preparation buffer explicitly. */
  prepBuffer: z.number().min(0.05).max(0.1).optional(),
  nutritionSummary: z.object({
    byMember: z.record(z.string(), NutritionPer100gSchema),
    householdTotal: NutritionPer100gSchema
  }),
  validationSummary: z.object({
    guardrailsPass: z.boolean(),
    memberResults: z.array(
      z.object({
        memberId: z.string(),
        pass: z.boolean(),
        failures: z.array(z.string())
      })
    )
  }),
  selectionTrace: SelectionTraceSchema,
  shoppingGap: z.array(ShoppingGapItemSchema),
  activeConstraintIds: z.array(z.string()),
  rejectedTemplateIds: z.array(z.string()),
  rejectedFoodIds: z.array(z.string()),
  pinnedTemplateIds: z.array(z.string()),
  requestedPriorityFoodIds: z.array(z.string()),
  preferLowEffort: z.boolean(),
  createdAt: z.string()
});

export type MealPlan = z.infer<typeof MealPlanSchema>;

export const InfeasiblePlanResultSchema = z.object({
  status: z.literal("infeasible"),
  code: z.literal("NO_FEASIBLE_PLAN"),
  conflictingConstraintIds: z.array(z.string()),
  exhaustedRoles: z.array(MealRoleSchema),
  allowedRelaxations: z.array(
    z.object({
      constraintId: z.string(),
      userFacingQuestion: z.string()
    })
  ),
  selectionTrace: SelectionTraceSchema
});

export type InfeasiblePlanResult = z.infer<typeof InfeasiblePlanResultSchema>;

export const ComposeFamilyMealResultSchema = z.discriminatedUnion("status", [
  z.object({
    status: z.literal("valid"),
    plan: MealPlanSchema,
    shoppingGap: z.array(ShoppingGapItemSchema)
  }),
  InfeasiblePlanResultSchema
]);

export type ComposeFamilyMealResult = z.infer<typeof ComposeFamilyMealResultSchema>;

export const ConstraintDeltaSchema = z.object({
  operation: z.enum(["add", "remove"]),
  kind: z.enum(["reject_template", "reject_food", "prefer_low_effort", "pin_template"]),
  targetId: z.string(),
  sourceUtterance: z.string()
});

export type ConstraintDelta = z.infer<typeof ConstraintDeltaSchema>;

export const ReplanFamilyMealInputSchema = z.object({
  mealSessionId: z.string(),
  parentPlanId: z.string(),
  parentPlanVersion: z.number().int().positive(),
  constraintDelta: z.array(ConstraintDeltaSchema),
  householdContextVersion: z.number().int().positive(),
  inventoryVersion: z.number().int().positive(),
  mealPolicyVersion: z.string()
});

export type ReplanFamilyMealInput = z.infer<typeof ReplanFamilyMealInputSchema>;

export const PlanDiffSchema = z.object({
  retainedTemplateIds: z.array(z.string()),
  removedTemplateIds: z.array(z.string()),
  addedTemplateIds: z.array(z.string()),
  changedAllocations: z.array(
    z.object({
      memberId: z.string(),
      itemId: z.string(),
      before: z.number(),
      after: z.number(),
      unit: z.literal("g")
    })
  ),
  shoppingGapChanged: z.boolean(),
  preservedConstraintIds: z.array(z.string()),
  addedConstraintIds: z.array(z.string())
});

export type PlanDiff = z.infer<typeof PlanDiffSchema>;
