import type { Db } from "./open-db.js";
import { loadFixtureBundle } from "../load-fixtures.js";
import { normalizeAlias } from "../aliases.js";
import { DEMO_DAILY_TARGETS } from "../ledger/types.js";
import { calculateMemberNutritionBudget } from "../nutrition-budget.js";
import type {
  MemberNutritionProfile,
  UnitConversionRule
} from "@privateplate/contracts";

function seedUnitConversions(db: Db, rules: UnitConversionRule[]): void {
  for (const rule of rules) {
    db.prepare(
      `INSERT OR IGNORE INTO unit_conversion_rules
       (id, food_id, raw_unit, grams_per_unit, confidence, source_id, license_id, rule_version)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      rule.id,
      rule.foodId,
      rule.rawUnit,
      rule.gramsPerUnit,
      rule.confidence,
      rule.sourceId,
      rule.licenseId,
      rule.ruleVersion
    );
  }
}

function seedHouseholdMemory(
  db: Db,
  householdId: string,
  members: Array<{
    id: string;
    displayName: string;
    healthTags: string[];
    nutritionProfile?: MemberNutritionProfile | undefined;
  }>,
  frozenPreferences: Array<{
    memberId: string;
    kind: string;
    note: string;
    source: string;
    ruleVersion: string;
  }>,
  now: string
): void {
  db.prepare(
    `INSERT OR IGNORE INTO household_intake_versions
     (household_id, intake_version, updated_at) VALUES (?, 1, ?)`
  ).run(householdId, now);

  for (const member of members) {
    for (const [index, tag] of member.healthTags.entries()) {
      db.prepare(
        `INSERT OR IGNORE INTO member_health_facts
         (id, member_id, household_id, kind, summary, source, effective_from, effective_to, version, active, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1, 1, ?, ?)`
      ).run(
        `hf-${member.id}-${index + 1}`,
        member.id,
        householdId,
        tag,
        `家庭记录的健康注意项：${tag}（演示数据，非医疗诊断）`,
        "fixture_seed",
        now,
        now,
        now
      );
    }

    const budget = calculateMemberNutritionBudget(
      member.nutritionProfile,
      member.id
    );
    const target = member.nutritionProfile
      ? budget.dailyTarget
      : DEMO_DAILY_TARGETS[member.id];
    if (target) {
      db.prepare(
        `INSERT OR IGNORE INTO member_daily_targets
         (id, member_id, household_id, service_date, energy_kcal, carbohydrate_g, protein_g, fat_g, sodium_mg, source, version, active, created_at, updated_at)
         VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)`
      ).run(
        `dt-${member.id}`,
        member.id,
        householdId,
        target.energyKcal,
        target.carbohydrateG,
        target.proteinG,
        target.fatG,
        target.sodiumMg,
        member.nutritionProfile
          ? `engineering_estimate:${budget.version}`
          : "demo_fixture_daily_target",
        now,
        now
      );
    }

    if (member.nutritionProfile) {
      db.prepare(
        `INSERT OR IGNORE INTO member_nutrition_profiles
         (member_id, gender, age, birth_year, height_cm, weight_kg, activity_level, weight_goal, source, profile_version, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'demo_fixture', ?, ?, ?)`
      ).run(
        member.id,
        member.nutritionProfile.gender,
        member.nutritionProfile.age ?? null,
        member.nutritionProfile.birthYear ?? null,
        member.nutritionProfile.heightCm,
        member.nutritionProfile.weightKg,
        member.nutritionProfile.activityLevel,
        member.nutritionProfile.weightGoal,
        budget.version,
        now,
        now
      );
    }
  }

  for (const [index, pref] of frozenPreferences.entries()) {
    db.prepare(
      `INSERT OR IGNORE INTO member_preferences
       (id, member_id, household_id, kind, target_type, target_id, note, polarity, source, version, active, created_at, updated_at)
       VALUES (?, ?, ?, ?, 'note', NULL, ?, 'prefer', ?, 1, 1, ?, ?)`
    ).run(
      `mp-${index + 1}`,
      pref.memberId,
      householdId,
      pref.kind,
      pref.note,
      pref.source,
      now,
      now
    );
  }
}

export async function seedFromFixtures(db: Db): Promise<{ householdId: string }> {
  const fixtures = await loadFixtureBundle();
  const now = new Date().toISOString();
  const hh = fixtures.household.household;

  const existingHousehold = db
    .prepare(`SELECT id FROM households WHERE id = ?`)
    .get(hh.id) as { id: string } | undefined;
  if (existingHousehold) {
    // All memory writes are INSERT OR IGNORE so upgraded demo databases can
    // receive the new profile rows without changing existing user facts.
    seedHouseholdMemory(
      db,
      hh.id,
      hh.members,
      hh.frozenPreferences ?? [],
      now
    );
    seedUnitConversions(db, fixtures.conversions);
    return { householdId: existingHousehold.id };
  }

  db.exec("BEGIN");
  try {
    db.prepare(
      `INSERT INTO households (id, name, version, inventory_version, meal_policy_version, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    ).run(
      hh.id,
      hh.displayName,
      hh.contextVersion,
      hh.inventoryVersion,
      hh.mealPolicyVersion,
      now,
      now
    );

    for (const member of hh.members) {
      db.prepare(
        `INSERT INTO household_members
         (id, household_id, display_name, relation_label, health_tags_json, notes, active, created_at)
         VALUES (?, ?, ?, ?, ?, ?, 1, ?)`
      ).run(
        member.id,
        hh.id,
        member.displayName,
        member.roleLabel,
        JSON.stringify(member.healthTags),
        member.notes ?? null,
        now
      );
    }

    for (const constraint of hh.constraints) {
      db.prepare(
        `INSERT INTO member_constraints
         (id, member_id, kind, target_id, source, rule_version)
         VALUES (?, ?, ?, ?, ?, ?)`
      ).run(
        constraint.id,
        constraint.memberId,
        constraint.kind,
        constraint.targetId,
        constraint.source,
        constraint.ruleVersion
      );
    }

    for (const policy of hh.mealPolicies) {
      db.prepare(
        `INSERT INTO member_meal_policies
         (member_id, meal_type, portion_units_json, guardrails_json, rule_version, source)
         VALUES (?, ?, ?, ?, ?, ?)`
      ).run(
        policy.memberId,
        policy.mealType,
        JSON.stringify(policy.portionUnitsByRole),
        JSON.stringify(policy.guardrails),
        policy.ruleVersion,
        policy.source
      );
    }

    for (const [index, pref] of (hh.frozenPreferences ?? []).entries()) {
      db.prepare(
        `INSERT INTO fixture_preferences
         (id, household_id, member_id, kind, value_json, rule_version)
         VALUES (?, ?, ?, ?, ?, ?)`
      ).run(
        `pref-${index + 1}`,
        hh.id,
        pref.memberId,
        pref.kind,
        JSON.stringify({ note: pref.note, source: pref.source }),
        pref.ruleVersion
      );
    }

    for (const food of fixtures.foods) {
      db.prepare(
        `INSERT INTO foods
         (id, canonical_name, nutrition_json, allergen_tags_json, source_id, license_id, data_version)
         VALUES (?, ?, ?, ?, ?, ?, ?)`
      ).run(
        food.id,
        food.canonicalName,
        JSON.stringify(food.nutritionPer100g),
        JSON.stringify(food.allergenTags),
        food.sourceId,
        food.licenseId,
        food.dataVersion
      );

      const aliases = [food.canonicalName, ...food.aliases];
      for (const alias of aliases) {
        db.prepare(
          `INSERT OR IGNORE INTO food_aliases (alias, food_id) VALUES (?, ?)`
        ).run(normalizeAlias(alias), food.id);
      }
    }

    for (const template of fixtures.templates) {
      db.prepare(
        `INSERT INTO meal_templates
         (id, name, role, tags_json, instructions_summary, source_id, license_id, template_version, active)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)`
      ).run(
        template.id,
        template.name,
        template.role,
        JSON.stringify(template.tags),
        template.instructionsSummary,
        template.sourceId,
        template.licenseId,
        template.templateVersion
      );

      for (const [i, ingredient] of template.ingredientsPerStandardServing.entries()) {
        db.prepare(
          `INSERT INTO meal_template_ingredients
           (id, template_id, food_id, edible_quantity_g, preparation_tag)
           VALUES (?, ?, ?, ?, ?)`
        ).run(
          `${template.id}-ing-${i + 1}`,
          template.id,
          ingredient.foodId,
          ingredient.edibleQuantityG,
          JSON.stringify({
            preparationTag: ingredient.preparationTag ?? "",
            edibleQuantityGMin: ingredient.edibleQuantityGMin ?? null,
            edibleQuantityGMax: ingredient.edibleQuantityGMax ?? null
          })
        );
      }
    }

    for (const bundle of fixtures.bundles) {
      db.prepare(
        `INSERT INTO meal_bundle_templates
         (id, template_ids_json, bundle_version, source_id, license_id, active)
         VALUES (?, ?, ?, ?, ?, 1)`
      ).run(
        bundle.id,
        JSON.stringify(bundle.templateIds),
        bundle.bundleVersion,
        bundle.sourceId,
        bundle.licenseId
      );
    }

    for (const item of hh.inventory) {
      db.prepare(
        `INSERT INTO inventory_items
         (id, household_id, food_id, raw_name, raw_quantity_expression, normalized_gram_range_json, state, priority_use, notes, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      ).run(
        item.id,
        hh.id,
        item.foodId,
        item.foodId,
        item.quantity.rawExpression,
        JSON.stringify(item.quantity.normalized),
        item.state,
        item.priorityConsume ? 1 : 0,
        item.notes ?? null,
        now
      );
    }

    for (const card of fixtures.knowledgeCards) {
      db.prepare(
        `INSERT INTO knowledge_cards
         (id, title, content, tags_json, applicability_json, exclusions_json, risk_level, review_status, source_title, source_year, source_url, license_id, content_version)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)`
      ).run(
        card.id,
        card.title,
        card.body,
        JSON.stringify(card.tags),
        JSON.stringify(card.appliesTo),
        JSON.stringify(card.exclusions),
        card.riskLevel,
        card.reviewStatus,
        card.sourceId,
        card.sourceYear,
        card.licenseId,
        card.cardVersion
      );
    }

    seedHouseholdMemory(db, hh.id, hh.members, hh.frozenPreferences ?? [], now);
    seedUnitConversions(db, fixtures.conversions);

    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }

  return { householdId: hh.id };
}
