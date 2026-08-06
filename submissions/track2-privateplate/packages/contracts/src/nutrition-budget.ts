import { z } from "zod";
import { MealTypeSchema } from "./enums.js";

export const NutritionSnapshotSchema = z.object({
  energyKcal: z.number().nonnegative(),
  carbohydrateG: z.number().nonnegative(),
  proteinG: z.number().nonnegative(),
  fatG: z.number().nonnegative(),
  sodiumMg: z.number().nonnegative()
});

export type NutritionSnapshot = z.infer<typeof NutritionSnapshotSchema>;

export const MealBudgetBoundsSchema = z.object({
  target: NutritionSnapshotSchema,
  min: NutritionSnapshotSchema,
  max: NutritionSnapshotSchema,
  reserve: NutritionSnapshotSchema
});

export type MealBudgetBounds = z.infer<typeof MealBudgetBoundsSchema>;

export const NutritionCalculationSchema = z.object({
  method: z.enum(["mifflin_st_jeor", "fallback_demo_estimate"]),
  bmrKcal: z.number().nonnegative(),
  tdeeKcal: z.number().nonnegative(),
  activityFactor: z.number().positive(),
  goalAdjustment: z.number().positive()
});

export type NutritionCalculation = z.infer<typeof NutritionCalculationSchema>;

export const MemberNutritionBudgetSchema = z.object({
  memberId: z.string().min(1),
  dailyTarget: NutritionSnapshotSchema,
  mealBudgets: z.object({
    breakfast: MealBudgetBoundsSchema,
    lunch: MealBudgetBoundsSchema,
    dinner: MealBudgetBoundsSchema,
    snack: MealBudgetBoundsSchema
  }),
  calculation: NutritionCalculationSchema,
  source: z.literal("engineering_estimate"),
  version: z.string().min(1),
  applicability: z.object({
    fullySupportedMealTypes: z.array(MealTypeSchema).min(1),
    extensionMealSlots: z.array(z.enum(["breakfast", "snack"])),
    boundary: z.string().min(1)
  })
});

export type MemberNutritionBudget = z.infer<typeof MemberNutritionBudgetSchema>;
