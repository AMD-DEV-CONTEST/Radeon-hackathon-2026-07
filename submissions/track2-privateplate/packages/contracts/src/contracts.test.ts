import { describe, expect, it } from "vitest";
import { GramRangeSchema } from "./quantity.js";
import { MealBundleTemplateSchema, MealTemplateSchema } from "./meal.js";
import { FoodSchema } from "./food.js";
import {
  CaregiverRecipientLabelSchema,
  CaregiverServeAtSchema
} from "./task-card.js";

describe("GramRangeSchema", () => {
  it("accepts exact equal grams", () => {
    const parsed = GramRangeSchema.parse({
      estimateG: 100,
      minG: 100,
      maxG: 100,
      confidence: "exact",
      conversionRuleId: "rule-1"
    });
    expect(parsed.confidence).toBe("exact");
  });

  it("rejects exact with mismatched bounds", () => {
    const result = GramRangeSchema.safeParse({
      estimateG: 100,
      minG: 90,
      maxG: 110,
      confidence: "exact",
      conversionRuleId: null
    });
    expect(result.success).toBe(false);
  });

  it("accepts approximate ranges", () => {
    const parsed = GramRangeSchema.parse({
      estimateG: 250,
      minG: 200,
      maxG: 300,
      confidence: "approximate",
      conversionRuleId: "cabbage-half"
    });
    expect(parsed.minG).toBe(200);
  });

  it.each([
    { estimateG: -1, minG: 0, maxG: 10 },
    { estimateG: 5, minG: -1, maxG: 10 },
    { estimateG: 5, minG: 0, maxG: -1 }
  ])("rejects negative grams: %j", (range) => {
    expect(
      GramRangeSchema.safeParse({
        ...range,
        confidence: "approximate",
        conversionRuleId: null
      }).success
    ).toBe(false);
  });

  it("rejects reversed bounds", () => {
    const result = GramRangeSchema.safeParse({
      estimateG: 100,
      minG: 110,
      maxG: 90,
      confidence: "approximate",
      conversionRuleId: null
    });
    expect(result.success).toBe(false);
  });

  it.each([
    { estimateG: 80, minG: 90, maxG: 110 },
    { estimateG: 120, minG: 90, maxG: 110 }
  ])("rejects estimates outside their bounds: %j", (range) => {
    expect(
      GramRangeSchema.safeParse({
        ...range,
        confidence: "approximate",
        conversionRuleId: null
      }).success
    ).toBe(false);
  });

  it("accepts an unknown range with only a known lower bound", () => {
    const parsed = GramRangeSchema.parse({
      estimateG: null,
      minG: 100,
      maxG: null,
      confidence: "unknown",
      conversionRuleId: null
    });
    expect(parsed.minG).toBe(100);
  });
});

describe("caregiver preview boundaries", () => {
  it.each(["家庭保姆", "保姆", "阿姨"])(
    "accepts the generic caregiver label %s",
    (label) => {
      expect(CaregiverRecipientLabelSchema.parse(label)).toBe(label);
    }
  );

  it("rejects labels that disclose household health information", () => {
    expect(
      CaregiverRecipientLabelSchema.safeParse("需要控血糖的爸爸").success
    ).toBe(false);
  });

  it.each([
    "unspecified",
    "今天 12:30",
    "2026-07-26T18:30:00+08:00"
  ])("accepts the supported serve time %s", (serveAt) => {
    expect(CaregiverServeAtSchema.parse(serveAt)).toBe(serveAt);
  });

  it("rejects invalid or free-form serve times", () => {
    expect(CaregiverServeAtSchema.safeParse("高血压用餐时间").success).toBe(
      false
    );
    expect(
      CaregiverServeAtSchema.safeParse("2026-99-99T18:30:00+08:00").success
    ).toBe(false);
  });
});

describe("Food and meal contracts", () => {
  it("parses a food record", () => {
    const food = FoodSchema.parse({
      id: "food-tofu",
      canonicalName: "北豆腐",
      aliases: ["豆腐"],
      nutritionPer100g: {
        energyKcal: 80,
        carbohydrateG: 2,
        proteinG: 8,
        fatG: 4,
        sodiumMg: 7
      },
      allergenTags: ["soy"],
      sourceId: "src-synthetic-demo",
      licenseId: "lic-privateplate-synthetic-1",
      dataVersion: "1.0.0"
    });
    expect(food.id).toBe("food-tofu");
  });

  it("parses a template and bundle", () => {
    const template = MealTemplateSchema.parse({
      id: "tpl-tofu-cabbage",
      name: "白菜豆腐煲",
      role: "shared_main",
      ingredientsPerStandardServing: [{ foodId: "food-tofu", edibleQuantityG: 120 }],
      tags: {
        cuisine: ["home"],
        cookingMethods: ["braise"],
        effortLevel: "low",
        oilLevel: "low",
        lowSodiumVariant: true
      },
      instructionsSummary: "豆腐与白菜一起炖。",
      sourceId: "src-synthetic-demo",
      licenseId: "lic-privateplate-synthetic-1",
      templateVersion: "1.0.0"
    });
    expect(template.role).toBe("shared_main");

    const bundle = MealBundleTemplateSchema.parse({
      id: "bundle-1",
      templateIds: ["a", "b", "c"],
      bundleVersion: "1.0.0",
      sourceId: "src-synthetic-demo",
      licenseId: "lic-privateplate-synthetic-1"
    });
    expect(bundle.templateIds).toHaveLength(3);
  });
});
