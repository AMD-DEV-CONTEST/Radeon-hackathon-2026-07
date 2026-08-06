import type {
  Food,
  MealBundleTemplate,
  MealTemplate,
  MemberConstraint
} from "@privateplate/contracts";

export type HardExclusions = {
  foodIds: Set<string>;
  templateIds: Set<string>;
  allergenTags: Set<string>;
};

export function collectHardExclusions(
  constraints: MemberConstraint[],
  sessionRejectedFoodIds: string[] = [],
  sessionRejectedTemplateIds: string[] = []
): HardExclusions {
  const foodIds = new Set<string>(sessionRejectedFoodIds);
  const templateIds = new Set<string>(sessionRejectedTemplateIds);
  const allergenTags = new Set<string>();

  for (const constraint of constraints) {
    if (constraint.kind === "allergy") {
      allergenTags.add(constraint.targetId);
    }
    if (constraint.kind === "avoid_ingredient") {
      foodIds.add(constraint.targetId);
    }
    if (constraint.kind === "avoid_dish") {
      templateIds.add(constraint.targetId);
    }
  }

  return { foodIds, templateIds, allergenTags };
}

export function templateContainsExcludedFood(
  template: MealTemplate,
  excludedFoodIds: Set<string>
): boolean {
  return template.ingredientsPerStandardServing.some((item) =>
    excludedFoodIds.has(item.foodId)
  );
}

export function resolveBundleTemplates(
  bundle: MealBundleTemplate,
  templatesById: Map<string, MealTemplate>
): MealTemplate[] | null {
  const resolved: MealTemplate[] = [];
  for (const id of bundle.templateIds) {
    const template = templatesById.get(id);
    if (!template) return null;
    resolved.push(template);
  }
  return resolved;
}

export function bundleRolesValid(templates: MealTemplate[]): boolean {
  const roles = templates.map((t) => t.role).sort().join(",");
  return roles === "shared_main,shared_side,staple";
}

export function filterFeasibleBundles(input: {
  bundles: MealBundleTemplate[];
  templates: MealTemplate[];
  foods: Food[];
  exclusions: HardExclusions;
}): MealBundleTemplate[] {
  const templatesById = new Map(input.templates.map((t) => [t.id, t]));
  const allergenByFood = new Map(input.foods.map((f) => [f.id, new Set(f.allergenTags)]));

  return input.bundles.filter((bundle) => {
    const templates = resolveBundleTemplates(bundle, templatesById);
    if (!templates || !bundleRolesValid(templates)) return false;

    for (const template of templates) {
      if (input.exclusions.templateIds.has(template.id)) return false;
      if (templateContainsExcludedFood(template, input.exclusions.foodIds)) return false;

      for (const ingredient of template.ingredientsPerStandardServing) {
        if (input.exclusions.foodIds.has(ingredient.foodId)) return false;
        const tags = allergenByFood.get(ingredient.foodId);
        if (!tags) return false;
        if ([...tags].some((tag) => input.exclusions.allergenTags.has(tag))) {
          return false;
        }
      }
    }
    return true;
  });
}
