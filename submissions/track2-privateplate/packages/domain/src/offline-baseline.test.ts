import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { canSubtractFromInventory } from "@privateplate/contracts";
import { buildFoodAliasIndex, resolveFoodId } from "./aliases.js";
import {
  collectHardExclusions,
  filterFeasibleBundles,
  resolveBundleTemplates,
  bundleRolesValid
} from "./bundle-filter.js";
import { loadFixtureBundle } from "./load-fixtures.js";
import { computeTemplateNutrition } from "./nutrition.js";
import { fixturePath, projectRootFromDomainPackage } from "./paths.js";

describe("C1 offline domain baseline", () => {
  it("loads and validates all required fixtures", async () => {
    const bundle = await loadFixtureBundle();

    expect(bundle.foods.length).toBeGreaterThanOrEqual(12);
    expect(bundle.foods.length).toBeLessThanOrEqual(20);
    expect(bundle.templates.length).toBeGreaterThanOrEqual(8);
    expect(bundle.bundles.length).toBeGreaterThanOrEqual(6);
    expect(bundle.household.household.members).toHaveLength(3);
    expect(bundle.knowledgeCards.length).toBeGreaterThanOrEqual(8);
  });

  it("resolves food aliases", async () => {
    const { foods } = await loadFixtureBundle();
    const index = buildFoodAliasIndex(foods);
    expect(resolveFoodId(index, "豆腐")).toBe("food-tofu");
    expect(resolveFoodId(index, "鸡腿肉")).toBe("food-chicken-leg");
    expect(resolveFoodId(index, "不存在的菜")).toBeNull();
  });

  it("computes template nutrition only from foods × grams", async () => {
    const { foods, templates } = await loadFixtureBundle();
    const foodsById = new Map(foods.map((f) => [f.id, f]));
    const tofuMain = templates.find((t) => t.id === "tpl-cabbage-tofu-braise");
    expect(tofuMain).toBeTruthy();
    const nutrition = computeTemplateNutrition(tofuMain!, foodsById);
    expect(nutrition.energyKcal).toBeGreaterThan(0);
    expect(nutrition.proteinG).toBeGreaterThan(0);
    // hand-check one ingredient contribution roughly: 120g tofu ≈ 0.97*81
    expect(nutrition.energyKcal).toBeGreaterThan(80);
  });

  it("enforces exact/approximate inventory semantics", async () => {
    const { household } = await loadFixtureBundle();
    const tofu = household.household.inventory.find((i) => i.foodId === "food-tofu");
    const cabbage = household.household.inventory.find((i) => i.foodId === "food-cabbage");
    expect(tofu).toBeTruthy();
    expect(cabbage).toBeTruthy();
    expect(canSubtractFromInventory(tofu!.quantity.normalized)).toBe(true);
    expect(canSubtractFromInventory(cabbage!.quantity.normalized)).toBe(false);
  });

  it("every bundle is main+side+staple with known templates", async () => {
    const { bundles, templates } = await loadFixtureBundle();
    const templatesById = new Map(templates.map((t) => [t.id, t]));
    for (const bundle of bundles) {
      const resolved = resolveBundleTemplates(bundle, templatesById);
      expect(resolved, bundle.id).not.toBeNull();
      expect(bundleRolesValid(resolved!), bundle.id).toBe(true);
    }
  });

  it("still has feasible alternatives after rejecting chicken then steamed egg", async () => {
    const { bundles, templates, foods, household } = await loadFixtureBundle();

    const afterChicken = filterFeasibleBundles({
      bundles,
      templates,
      foods,
      exclusions: collectHardExclusions(household.household.constraints, ["food-chicken-leg"], [])
    });
    expect(afterChicken.length).toBeGreaterThanOrEqual(2);
    expect(afterChicken.every((b) => !b.templateIds.includes("tpl-potato-chicken"))).toBe(true);

    const afterEggSide = filterFeasibleBundles({
      bundles,
      templates,
      foods,
      exclusions: collectHardExclusions(
        household.household.constraints,
        ["food-chicken-leg"],
        ["tpl-shiitake-egg"]
      )
    });
    expect(afterEggSide.length).toBeGreaterThanOrEqual(1);
    expect(afterEggSide.some((b) => b.templateIds.includes("tpl-cabbage-tofu-braise"))).toBe(
      true
    );
  });

  it("mother beef avoid excludes tomato-beef bundles", async () => {
    const { bundles, templates, foods, household } = await loadFixtureBundle();
    const feasible = filterFeasibleBundles({
      bundles,
      templates,
      foods,
      exclusions: collectHardExclusions(household.household.constraints)
    });
    expect(feasible.some((b) => b.id === "bundle-beef-carrot-rice")).toBe(false);
  });

  it("allergy target tags exclude every food carrying that allergen", async () => {
    const { bundles, templates, foods } = await loadFixtureBundle();
    const eggAllergy = {
      id: "cst-egg-allergy",
      memberId: "mem-admin",
      kind: "allergy" as const,
      targetId: "egg",
      source: "session_input" as const,
      ruleVersion: "test"
    };
    const feasible = filterFeasibleBundles({
      bundles,
      templates,
      foods,
      exclusions: collectHardExclusions([eggAllergy])
    });
    const templatesById = new Map(templates.map((template) => [template.id, template]));

    expect(feasible.length).toBeGreaterThan(0);
    for (const bundle of feasible) {
      const selectedTemplates = resolveBundleTemplates(bundle, templatesById);
      expect(selectedTemplates).not.toBeNull();
      expect(
        selectedTemplates!.some((template) =>
          template.ingredientsPerStandardServing.some(
            (ingredient) => ingredient.foodId === "food-egg"
          )
        )
      ).toBe(false);
    }
  });

  it("every fixture file listed in manifest has matching sha256", async () => {
    const root = projectRootFromDomainPackage();
    const manifestPath = path.join(root, "fixtures/MANIFEST.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as {
      files: Array<{ path: string; sha256: string }>;
    };

    expect(manifest.files.length).toBeGreaterThanOrEqual(6);
    for (const entry of manifest.files) {
      const abs = path.join(root, entry.path);
      const bytes = await readFile(abs);
      const digest = createHash("sha256").update(bytes).digest("hex");
      expect(digest, entry.path).toBe(entry.sha256);
    }
  });

  it("meal policies exist for all three members and both meal types", async () => {
    const { household } = await loadFixtureBundle();
    const memberIds = household.household.members.map((m) => m.id);
    for (const memberId of memberIds) {
      for (const mealType of ["lunch", "dinner"] as const) {
        const policy = household.household.mealPolicies.find(
          (p) => p.memberId === memberId && p.mealType === mealType
        );
        expect(policy, `${memberId}/${mealType}`).toBeTruthy();
        expect(policy!.source).toBe("demo_fixture");
      }
    }
  });
});

describe("fixture path helper", () => {
  it("points at repo fixtures", async () => {
    const foods = await readFile(fixturePath("foods", "foods.json"), "utf8");
    expect(foods).toContain("food-tofu");
  });
});
