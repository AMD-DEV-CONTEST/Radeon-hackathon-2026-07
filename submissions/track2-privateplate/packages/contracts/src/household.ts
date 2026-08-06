import { z } from "zod";
import {
  ConstraintKindSchema,
  InventoryStateSchema,
  MealRoleSchema,
  MealTypeSchema,
  SessionPreferenceKindSchema
} from "./enums.js";
import { InventoryQuantitySchema } from "./quantity.js";

export const MemberGenderSchema = z.enum(["male", "female", "other", "unknown"]);
export type MemberGender = z.infer<typeof MemberGenderSchema>;

export const MemberActivityLevelSchema = z.enum(["low", "moderate", "high"]);
export type MemberActivityLevel = z.infer<typeof MemberActivityLevelSchema>;

export const MemberWeightGoalSchema = z.enum(["maintain", "loss", "gain"]);
export type MemberWeightGoal = z.infer<typeof MemberWeightGoalSchema>;

export const MemberNutritionProfileSchema = z
  .object({
    gender: MemberGenderSchema,
    age: z.number().int().min(1).max(120).optional(),
    birthYear: z.number().int().min(1900).max(2100).optional(),
    heightCm: z.number().positive().min(50).max(250),
    weightKg: z.number().positive().min(10).max(400),
    activityLevel: MemberActivityLevelSchema,
    weightGoal: MemberWeightGoalSchema
  })
  .refine((profile) => profile.age != null || profile.birthYear != null, {
    message: "age 或 birthYear 至少填写一个",
    path: ["age"]
  });

export type MemberNutritionProfile = z.infer<typeof MemberNutritionProfileSchema>;

export const HouseholdMemberSchema = z.object({
  id: z.string().min(1),
  displayName: z.string().min(1),
  roleLabel: z.enum(["admin", "father", "mother", "member"]),
  healthTags: z.array(z.string()),
  nutritionProfile: MemberNutritionProfileSchema.optional(),
  notes: z.string().optional()
});

export type HouseholdMember = z.infer<typeof HouseholdMemberSchema>;

export const MemberConstraintSchema = z.object({
  id: z.string().min(1),
  memberId: z.string().min(1),
  kind: ConstraintKindSchema,
  targetId: z.string().min(1),
  source: z.enum(["fixture", "session_input"]),
  ruleVersion: z.string().min(1)
});

export type MemberConstraint = z.infer<typeof MemberConstraintSchema>;

export const FrozenPreferenceSchema = z.object({
  memberId: z.string().min(1),
  kind: SessionPreferenceKindSchema,
  note: z.string().min(1),
  source: z.enum(["fixture", "session_input"]),
  ruleVersion: z.string().min(1)
});

export type FrozenPreference = z.infer<typeof FrozenPreferenceSchema>;

export const MemberMealPolicySchema = z.object({
  memberId: z.string().min(1),
  mealType: MealTypeSchema,
  portionUnitsByRole: z.record(MealRoleSchema, z.number().positive()),
  guardrails: z.object({
    energyKcal: z.object({ min: z.number(), max: z.number() }),
    carbohydrateG: z.object({ min: z.number(), max: z.number() }),
    proteinG: z.object({ min: z.number().nonnegative(), max: z.number().positive() }).optional(),
    sodiumMgMax: z.number().positive()
  }),
  source: z.literal("demo_fixture"),
  ruleVersion: z.string().min(1)
});

export type MemberMealPolicy = z.infer<typeof MemberMealPolicySchema>;

export const InventoryItemSchema = z.object({
  id: z.string().min(1),
  foodId: z.string().min(1),
  quantity: InventoryQuantitySchema,
  state: InventoryStateSchema,
  priorityConsume: z.boolean(),
  notes: z.string().optional()
});

export type InventoryItem = z.infer<typeof InventoryItemSchema>;

export const HouseholdFixtureSchema = z.object({
  schemaVersion: z.string().min(1),
  household: z.object({
    id: z.string().min(1),
    displayName: z.string().min(1),
    locale: z.string().min(1),
    contextVersion: z.number().int().positive(),
    inventoryVersion: z.number().int().positive(),
    mealPolicyVersion: z.string().min(1),
    members: z.array(HouseholdMemberSchema).min(1).max(3),
    constraints: z.array(MemberConstraintSchema),
    frozenPreferences: z.array(FrozenPreferenceSchema).default([]),
    mealPolicies: z.array(MemberMealPolicySchema).min(1),
    inventory: z.array(InventoryItemSchema),
    sourceId: z.string().min(1),
    licenseId: z.string().min(1),
    dataVersion: z.string().min(1)
  })
});

export type HouseholdFixture = z.infer<typeof HouseholdFixtureSchema>;
