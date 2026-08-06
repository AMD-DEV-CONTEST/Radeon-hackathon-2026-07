import { z } from "zod";

export const NutritionPer100gSchema = z.object({
  energyKcal: z.number().nonnegative(),
  carbohydrateG: z.number().nonnegative(),
  proteinG: z.number().nonnegative(),
  fatG: z.number().nonnegative(),
  sodiumMg: z.number().nonnegative()
});

export type NutritionPer100g = z.infer<typeof NutritionPer100gSchema>;

export const FoodSchema = z.object({
  id: z.string().min(1),
  canonicalName: z.string().min(1),
  aliases: z.array(z.string()),
  nutritionPer100g: NutritionPer100gSchema,
  allergenTags: z.array(z.string()),
  sourceId: z.string().min(1),
  licenseId: z.string().min(1),
  dataVersion: z.string().min(1)
});

export type Food = z.infer<typeof FoodSchema>;

export const UnitConversionRuleSchema = z.object({
  id: z.string().min(1),
  foodId: z.string().min(1),
  rawUnit: z.string().min(1),
  gramsPerUnit: z.number().positive(),
  confidence: z.enum(["exact", "approximate"]),
  sourceId: z.string().min(1),
  licenseId: z.string().min(1),
  ruleVersion: z.string().min(1)
});

export type UnitConversionRule = z.infer<typeof UnitConversionRuleSchema>;
