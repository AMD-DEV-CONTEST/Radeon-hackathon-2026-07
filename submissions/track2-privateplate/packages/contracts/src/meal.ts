import { z } from "zod";
import { MealRoleSchema } from "./enums.js";

export const MealTemplateIngredientSchema = z.object({
  foodId: z.string().min(1),
  /** Preferred standard-serving grams. */
  edibleQuantityG: z.number().positive(),
  /** Optional scalable range so batch totals can fit inventory without 10g buys. */
  edibleQuantityGMin: z.number().positive().optional(),
  edibleQuantityGMax: z.number().positive().optional(),
  preparationTag: z.string().optional()
});

export const MealTemplateSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  role: MealRoleSchema,
  ingredientsPerStandardServing: z.array(MealTemplateIngredientSchema).min(1),
  tags: z.object({
    cuisine: z.array(z.string()),
    cookingMethods: z.array(z.string()),
    effortLevel: z.enum(["low", "medium"]),
    oilLevel: z.enum(["low", "standard"]),
    lowSodiumVariant: z.boolean(),
    /** Metadata for compound dishes that cover more than their primary role. */
    coversRoles: z.array(MealRoleSchema).min(1).optional()
  }),
  instructionsSummary: z.string().min(1),
  sourceId: z.string().min(1),
  licenseId: z.string().min(1),
  templateVersion: z.string().min(1)
});

export type MealTemplate = z.infer<typeof MealTemplateSchema>;

export const MealBundleTemplateSchema = z
  .object({
    id: z.string().min(1),
    templateIds: z.tuple([z.string(), z.string(), z.string()]),
    bundleVersion: z.string().min(1),
    sourceId: z.string().min(1),
    licenseId: z.string().min(1)
  });

export type MealBundleTemplate = z.infer<typeof MealBundleTemplateSchema>;
