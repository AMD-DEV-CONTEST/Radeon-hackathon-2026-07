import type { Db } from "../db/open-db.js";
import { normalizeAgentPreferenceKind } from "./memory-kind.js";
import { calculateMemberNutritionBudget } from "../nutrition-budget.js";
import {
  addNutritionSnapshots,
  DEMO_DAILY_TARGETS,
  emptyNutritionSnapshot,
  remainingNutrition,
  type DayContext,
  type NutritionSnapshot
} from "./types.js";
import type {
  MealBudgetBounds,
  MemberNutritionProfile
} from "@privateplate/contracts";

function parseJsonArray(text: string): string[] {
  try {
    const value = JSON.parse(text) as unknown;
    return Array.isArray(value) ? value.map(String) : [];
  } catch {
    return [];
  }
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function snap(n: NutritionSnapshot): NutritionSnapshot {
  return {
    energyKcal: round1(n.energyKcal),
    carbohydrateG: round1(n.carbohydrateG),
    proteinG: round1(n.proteinG),
    fatG: round1(n.fatG),
    sodiumMg: round1(n.sodiumMg)
  };
}

function addBudgetBounds(a: MealBudgetBounds, b: MealBudgetBounds): MealBudgetBounds {
  const add = (left: NutritionSnapshot, right: NutritionSnapshot): NutritionSnapshot => ({
    energyKcal: round1(left.energyKcal + right.energyKcal),
    carbohydrateG: round1(left.carbohydrateG + right.carbohydrateG),
    proteinG: round1(left.proteinG + right.proteinG),
    fatG: round1(left.fatG + right.fatG),
    sodiumMg: round1(left.sodiumMg + right.sodiumMg)
  });
  return {
    target: add(a.target, b.target),
    min: add(a.min, b.min),
    max: add(a.max, b.max),
    reserve: add(a.reserve, b.reserve)
  };
}

function emptyBudgetBounds(): MealBudgetBounds {
  return {
    target: emptyNutritionSnapshot(),
    min: emptyNutritionSnapshot(),
    max: emptyNutritionSnapshot(),
    reserve: emptyNutritionSnapshot()
  };
}

/**
 * Compute day context from SQLite. Remaining is always live:
 * remaining = active targets − completed meal intake for serviceDate.
 */
export function getDayContext(
  db: Db,
  householdId: string,
  options: {
    serviceDate: string;
    timeZone?: string;
    dinerIds?: string[];
  }
): DayContext {
  const timeZone = options.timeZone ?? "Asia/Shanghai";
  const serviceDate = options.serviceDate;

  const household = db
    .prepare(
      `SELECT version, inventory_version, meal_policy_version
       FROM households WHERE id = ?`
    )
    .get(householdId) as
    | {
        version: number;
        inventory_version: number;
        meal_policy_version: string;
      }
    | undefined;
  if (!household) {
    throw new Error(`HOUSEHOLD_NOT_FOUND:${householdId}`);
  }

  let intakeVersionRow = db
    .prepare(
      `SELECT intake_version FROM household_intake_versions WHERE household_id = ?`
    )
    .get(householdId) as { intake_version: number } | undefined;
  if (!intakeVersionRow) {
    db.prepare(
      `INSERT OR IGNORE INTO household_intake_versions
       (household_id, intake_version, updated_at) VALUES (?, 1, ?)`
    ).run(householdId, new Date().toISOString());
    intakeVersionRow = { intake_version: 1 };
  }

  const members = db
    .prepare(
      `SELECT id, display_name, relation_label
       FROM household_members
       WHERE household_id = ? AND active = 1
       ORDER BY id`
    )
    .all(householdId) as Array<{
    id: string;
    display_name: string;
    relation_label: string | null;
  }>;

  const focusIds =
    options.dinerIds && options.dinerIds.length > 0
      ? new Set(options.dinerIds)
      : new Set(members.map((m) => m.id));

  const memberViews = members
    .filter((m) => focusIds.has(m.id))
    .map((member) => {
      const healthFacts = db
        .prepare(
          `SELECT id, kind, summary, source
           FROM member_health_facts
           WHERE member_id = ? AND active = 1
           ORDER BY updated_at DESC`
        )
        .all(member.id) as Array<{
        id: string;
        kind: string;
        summary: string;
        source: string;
      }>;

      const preferences = db
        .prepare(
          `SELECT id, kind, note, polarity, target_type, target_id
           FROM member_preferences
           WHERE member_id = ? AND active = 1
           ORDER BY updated_at DESC`
        )
        .all(member.id) as Array<{
        id: string;
        kind: string;
        note: string;
        polarity: string;
        target_type: string;
        target_id: string | null;
      }>;

      const hardConstraints = db
        .prepare(
          `SELECT id, kind, target_id
           FROM member_constraints
           WHERE member_id = ?`
        )
        .all(member.id) as Array<{
        id: string;
        kind: string;
        target_id: string;
        }>;

      const profileRow = db
        .prepare(
          `SELECT gender, age, birth_year, height_cm, weight_kg,
                  activity_level, weight_goal
           FROM member_nutrition_profiles
           WHERE member_id = ?`
        )
        .get(member.id) as
        | {
            gender: MemberNutritionProfile["gender"];
            age: number | null;
            birth_year: number | null;
            height_cm: number;
            weight_kg: number;
            activity_level: MemberNutritionProfile["activityLevel"];
            weight_goal: MemberNutritionProfile["weightGoal"];
          }
        | undefined;
      const nutritionProfile: MemberNutritionProfile | undefined = profileRow
        ? {
            gender: profileRow.gender,
            ...(profileRow.age != null ? { age: profileRow.age } : {}),
            ...(profileRow.birth_year != null
              ? { birthYear: profileRow.birth_year }
              : {}),
            heightCm: profileRow.height_cm,
            weightKg: profileRow.weight_kg,
            activityLevel: profileRow.activity_level,
            weightGoal: profileRow.weight_goal
          }
        : undefined;
      const nutritionBudget = calculateMemberNutritionBudget(
        nutritionProfile,
        member.id
      );

      return {
        id: member.id,
        displayName: member.display_name,
        roleLabel: member.relation_label,
        healthFacts: healthFacts.map((h) => ({
          id: h.id,
          kind: h.kind,
          summary: h.summary,
          source: h.source
        })),
        preferences: preferences.map((p) => ({
          id: p.id,
          kind: normalizeAgentPreferenceKind(p.kind),
          note: p.note,
          polarity: p.polarity,
          targetType: p.target_type,
          targetId: p.target_id
        })),
        hardConstraints: hardConstraints.map((c) => ({
          id: c.id,
          kind: c.kind,
          targetId: c.target_id
        })),
        ...(nutritionProfile ? { nutritionProfile } : {}),
        nutritionBudget
      };
    });

  const inventoryRows = db
    .prepare(
      `SELECT id, food_id, raw_name, priority_use, normalized_gram_range_json
       FROM inventory_items
       WHERE household_id = ?
       ORDER BY id`
    )
    .all(householdId) as Array<{
    id: string;
    food_id: string | null;
    raw_name: string;
    priority_use: number;
    normalized_gram_range_json: string;
  }>;

  const inventory = inventoryRows.map((row) => {
    const qty = JSON.parse(row.normalized_gram_range_json) as {
      estimateG: number | null;
      minG: number | null;
      maxG: number | null;
      confidence: string;
    };
    return {
      id: row.id,
      foodId: row.food_id,
      rawName: row.raw_name,
      priorityUse: row.priority_use === 1,
      quantity: {
        estimateG: qty.estimateG,
        minG: qty.minG,
        maxG: qty.maxG,
        confidence: qty.confidence
      }
    };
  });

  const unitConversionRules = (
    db
      .prepare(
        `SELECT id, food_id, raw_unit, grams_per_unit, confidence
         FROM unit_conversion_rules
         ORDER BY id`
      )
      .all() as Array<{
      id: string;
      food_id: string;
      raw_unit: string;
      grams_per_unit: number;
      confidence: string;
    }>
  ).map((row) => ({
    id: row.id,
    foodId: row.food_id,
    rawUnit: row.raw_unit,
    gramsPerUnit: row.grams_per_unit,
    confidence: row.confidence
  }));

  const completedRows = db
    .prepare(
      `SELECT id, meal_type, plan_id, plan_version, completed_at, diner_ids_json
       FROM meal_records
       WHERE household_id = ? AND service_date = ? AND status = 'completed'
       ORDER BY completed_at ASC, created_at ASC`
    )
    .all(householdId, serviceDate) as Array<{
    id: string;
    meal_type: string;
    plan_id: string | null;
    plan_version: number | null;
    completed_at: string | null;
    diner_ids_json: string;
  }>;

  const completedMeals = completedRows.map((row) => ({
    id: row.id,
    mealType: row.meal_type,
    planId: row.plan_id,
    planVersion: row.plan_version,
    completedAt: row.completed_at,
    dinerIds: parseJsonArray(row.diner_ids_json)
  }));

  const consumedByMember = new Map<string, NutritionSnapshot>();
  for (const member of memberViews) {
    consumedByMember.set(member.id, emptyNutritionSnapshot());
  }

  for (const meal of completedRows) {
    const items = db
      .prepare(
        `SELECT member_id, energy_kcal, carbohydrate_g, protein_g, fat_g, sodium_mg
         FROM meal_record_items WHERE meal_record_id = ?`
      )
      .all(meal.id) as Array<{
      member_id: string;
      energy_kcal: number;
      carbohydrate_g: number;
      protein_g: number;
      fat_g: number;
      sodium_mg: number;
    }>;
    for (const item of items) {
      if (!focusIds.has(item.member_id)) continue;
      const prev =
        consumedByMember.get(item.member_id) ?? emptyNutritionSnapshot();
      consumedByMember.set(
        item.member_id,
        addNutritionSnapshots(prev, {
          energyKcal: item.energy_kcal,
          carbohydrateG: item.carbohydrate_g,
          proteinG: item.protein_g,
          fatG: item.fat_g,
          sodiumMg: item.sodium_mg
        })
      );
    }
  }

  const memberIntake = memberViews.map((member) => {
    const targetRow = db
      .prepare(
        `SELECT energy_kcal, carbohydrate_g, protein_g, fat_g, sodium_mg, source, version
         FROM member_daily_targets
         WHERE member_id = ? AND active = 1
           AND (service_date IS NULL OR service_date = ?)
         ORDER BY CASE WHEN service_date IS NULL THEN 1 ELSE 0 END, version DESC
         LIMIT 1`
      )
      .get(member.id, serviceDate) as
      | {
          energy_kcal: number;
          carbohydrate_g: number;
          protein_g: number;
          fat_g: number;
          sodium_mg: number;
          source: string;
          version: number;
        }
      | undefined;

    const demo = DEMO_DAILY_TARGETS[member.id] ?? {
      energyKcal: 1800,
      carbohydrateG: 200,
      proteinG: 75,
      fatG: 55,
      sodiumMg: 2000
    };

    const profileIsTargetSource =
      member.nutritionProfile != null &&
      (!targetRow ||
        targetRow.source === "demo_fixture_daily_target" ||
        targetRow.source.startsWith("engineering_estimate:"));
    const target: NutritionSnapshot = profileIsTargetSource
      ? member.nutritionBudget.dailyTarget
      : targetRow
        ? {
            energyKcal: targetRow.energy_kcal,
            carbohydrateG: targetRow.carbohydrate_g,
            proteinG: targetRow.protein_g,
            fatG: targetRow.fat_g,
            sodiumMg: targetRow.sodium_mg
          }
        : demo;

    const consumed = consumedByMember.get(member.id) ?? emptyNutritionSnapshot();
    const nutritionBudget = targetRow && !profileIsTargetSource
      ? { ...member.nutritionBudget, dailyTarget: snap(target) }
      : member.nutritionBudget;
    return {
      memberId: member.id,
      target: snap(target),
      consumed: snap(consumed),
      remaining: snap(remainingNutrition(target, consumed)),
      nutritionBudget
    };
  });

  const householdTarget = memberIntake.reduce(
    (acc, row) => addNutritionSnapshots(acc, row.target),
    emptyNutritionSnapshot()
  );
  const householdConsumed = memberIntake.reduce(
    (acc, row) => addNutritionSnapshots(acc, row.consumed),
    emptyNutritionSnapshot()
  );
  const emptyMealBudgets = memberIntake[0]?.nutritionBudget.mealBudgets;
  const householdMealBudgets = {
    breakfast: emptyMealBudgets?.breakfast ?? emptyBudgetBounds(),
    lunch: emptyMealBudgets?.lunch ?? emptyBudgetBounds(),
    dinner: emptyMealBudgets?.dinner ?? emptyBudgetBounds(),
    snack: emptyMealBudgets?.snack ?? emptyBudgetBounds()
  } as DayContext["householdIntake"]["mealBudgets"];
  for (const row of memberIntake.slice(1)) {
    for (const slot of ["breakfast", "lunch", "dinner", "snack"] as const) {
      householdMealBudgets[slot] = addBudgetBounds(
        householdMealBudgets[slot],
        row.nutritionBudget.mealBudgets[slot]
      );
    }
  }

  return {
    householdId,
    serviceDate,
    timeZone,
    householdContextVersion: household.version,
    inventoryVersion: household.inventory_version,
    intakeVersion: intakeVersionRow.intake_version,
    mealPolicyVersion: household.meal_policy_version,
    members: memberViews,
    inventory,
    unitConversionRules,
    completedMeals,
    memberIntake,
    householdIntake: {
      target: snap(householdTarget),
      consumed: snap(householdConsumed),
      remaining: snap(remainingNutrition(householdTarget, householdConsumed)),
      mealBudgets: householdMealBudgets
    }
  };
}

export function localServiceDate(
  timeZone = "Asia/Shanghai",
  now = new Date()
): string {
  // en-CA yields YYYY-MM-DD
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(now);
}
