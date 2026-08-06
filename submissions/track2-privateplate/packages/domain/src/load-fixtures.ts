import { readFile } from "node:fs/promises";
import { z } from "zod";
import {
  FoodSchema,
  HouseholdFixtureSchema,
  KnowledgeCardSchema,
  MealBundleTemplateSchema,
  MealTemplateSchema,
  UnitConversionRuleSchema,
  type Food,
  type HouseholdFixture,
  type KnowledgeCard,
  type MealBundleTemplate,
  type MealTemplate,
  type UnitConversionRule
} from "@privateplate/contracts";
import { fixturePath } from "./paths.js";

const FoodsFileSchema = z.object({
  schemaVersion: z.string(),
  sourceId: z.string(),
  licenseId: z.string(),
  dataVersion: z.string(),
  foods: z.array(FoodSchema).min(12)
});

const ConversionsFileSchema = z.object({
  schemaVersion: z.string(),
  rules: z.array(UnitConversionRuleSchema).min(1)
});

const TemplatesFileSchema = z.object({
  schemaVersion: z.string(),
  templates: z.array(MealTemplateSchema).min(8)
});

const BundlesFileSchema = z.object({
  schemaVersion: z.string(),
  bundles: z.array(MealBundleTemplateSchema).min(6)
});

const KnowledgeFileSchema = z.object({
  schemaVersion: z.string(),
  cards: z.array(KnowledgeCardSchema).min(8)
});

export type FixtureBundle = {
  foods: Food[];
  conversions: UnitConversionRule[];
  templates: MealTemplate[];
  bundles: MealBundleTemplate[];
  household: HouseholdFixture;
  knowledgeCards: KnowledgeCard[];
};

async function readJson(relativePath: string): Promise<unknown> {
  const text = await readFile(fixturePath(...relativePath.split("/")), "utf8");
  return JSON.parse(text) as unknown;
}

export async function loadFixtureBundle(): Promise<FixtureBundle> {
  const foodsFile = FoodsFileSchema.parse(await readJson("foods/foods.json"));
  const conversionsFile = ConversionsFileSchema.parse(
    await readJson("foods/unit-conversions.json")
  );
  const templatesFile = TemplatesFileSchema.parse(
    await readJson("meal-templates/templates.json")
  );
  const bundlesFile = BundlesFileSchema.parse(
    await readJson("meal-templates/bundles.json")
  );
  const household = HouseholdFixtureSchema.parse(
    await readJson("household/demo-household.json")
  );
  const knowledgeFile = KnowledgeFileSchema.parse(
    await readJson("knowledge/cards.json")
  );

  return {
    foods: foodsFile.foods,
    conversions: conversionsFile.rules,
    templates: templatesFile.templates,
    bundles: bundlesFile.bundles,
    household,
    knowledgeCards: knowledgeFile.cards
  };
}
