import { z } from "zod";

export const QuantityConfidenceSchema = z.enum(["exact", "approximate", "unknown"]);
export type QuantityConfidence = z.infer<typeof QuantityConfidenceSchema>;

export const ConstraintKindSchema = z.enum([
  "allergy",
  "avoid_ingredient",
  "avoid_dish"
]);
export type ConstraintKind = z.infer<typeof ConstraintKindSchema>;

export const SessionPreferenceKindSchema = z.enum([
  "reject_template",
  "reject_food",
  "priority_use",
  "low_oil_preference",
  "low_effort_preference"
]);
export type SessionPreferenceKind = z.infer<typeof SessionPreferenceKindSchema>;

export const InventoryStateSchema = z.enum([
  "unopened",
  "opened",
  "cooked_leftover",
  "fresh"
]);
export type InventoryState = z.infer<typeof InventoryStateSchema>;

export const MealRoleSchema = z.enum(["shared_main", "shared_side", "staple"]);
export type MealRole = z.infer<typeof MealRoleSchema>;

export const PlanStatusSchema = z.enum(["draft", "valid", "infeasible", "superseded"]);
export type PlanStatus = z.infer<typeof PlanStatusSchema>;

export const PendingActionStatusSchema = z.enum([
  "pending",
  "cancelled",
  "expired",
  "committed",
  "failed"
]);
export type PendingActionStatus = z.infer<typeof PendingActionStatusSchema>;

export const MealTypeSchema = z.enum(["lunch", "dinner"]);
export type MealType = z.infer<typeof MealTypeSchema>;

export const ErrorCodeSchema = z.enum([
  "VALIDATION_ERROR",
  "STALE_CONTEXT",
  "GUARD_CONFIG_MISSING",
  "NO_FEASIBLE_PLAN",
  "UNKNOWN_FOOD",
  "FIXTURE_INTEGRITY_ERROR",
  "UNAUTHORIZED_ACTION"
]);
export type ErrorCode = z.infer<typeof ErrorCodeSchema>;
