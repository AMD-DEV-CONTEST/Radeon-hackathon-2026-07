import type {
  Food,
  FrozenPreference,
  InventoryItem,
  MealBundleTemplate,
  MealPlan,
  MealTemplate,
  MemberConstraint,
  MemberMealPolicy,
  HouseholdMember,
  CaregiverTaskCard,
  MemberNutritionProfile,
  CommitResult
} from "@privateplate/contracts";
import type { Db } from "./open-db.js";
import type { PlannerCatalog } from "../planning/compose.js";

type SqlValue = null | number | bigint | string | Uint8Array;

function rows<T>(db: Db, sql: string, params: SqlValue[] = []): T[] {
  return db.prepare(sql).all(...params) as T[];
}

function row<T>(db: Db, sql: string, params: SqlValue[] = []): T | undefined {
  return db.prepare(sql).get(...params) as T | undefined;
}

export function loadPlannerCatalog(db: Db, householdId: string): PlannerCatalog {
  const household = row<{
    id: string;
    version: number;
    inventory_version: number;
    meal_policy_version: string;
  }>(db, `SELECT * FROM households WHERE id = ?`, [householdId]);
  if (!household) {
    throw new Error(`Household not found: ${householdId}`);
  }

  const members = rows<{
    id: string;
    display_name: string;
    relation_label: string;
    health_tags_json: string;
    notes: string | null;
  }>(
    db,
    `SELECT * FROM household_members WHERE household_id = ? AND active = 1`,
    [householdId]
  );

  const memberIds = members.map((m) => m.id);
  const constraints =
    memberIds.length === 0
      ? []
      : rows<{
          id: string;
          member_id: string;
          kind: string;
          target_id: string;
          source: string;
          rule_version: string;
        }>(
          db,
          `SELECT * FROM member_constraints WHERE member_id IN (${memberIds
            .map(() => "?")
            .join(",")})`,
          memberIds
        );

  const policies = rows<{
    member_id: string;
    meal_type: string;
    portion_units_json: string;
    guardrails_json: string;
    rule_version: string;
    source: string;
  }>(
    db,
    `SELECT * FROM member_meal_policies WHERE member_id IN (${memberIds
      .map(() => "?")
      .join(",")})`,
    memberIds
  );

  const prefs = rows<{
    member_id: string | null;
    kind: string;
    value_json: string;
    rule_version: string;
  }>(db, `SELECT * FROM fixture_preferences WHERE household_id = ?`, [householdId]);

  const foods = rows<{
    id: string;
    canonical_name: string;
    nutrition_json: string;
    allergen_tags_json: string;
    source_id: string;
    license_id: string;
    data_version: string;
  }>(db, `SELECT * FROM foods`);

  const aliases = rows<{ alias: string; food_id: string }>(db, `SELECT * FROM food_aliases`);
  const aliasesByFood = new Map<string, string[]>();
  for (const alias of aliases) {
    const list = aliasesByFood.get(alias.food_id) ?? [];
    list.push(alias.alias);
    aliasesByFood.set(alias.food_id, list);
  }

  const templates = rows<{
    id: string;
    name: string;
    role: string;
    tags_json: string;
    instructions_summary: string;
    source_id: string;
    license_id: string;
    template_version: string;
  }>(db, `SELECT * FROM meal_templates WHERE active = 1`);

  const ingredients = rows<{
    template_id: string;
    food_id: string;
    edible_quantity_g: number;
    preparation_tag: string;
  }>(db, `SELECT * FROM meal_template_ingredients`);

  const ingredientsByTemplate = new Map<string, typeof ingredients>();
  for (const ing of ingredients) {
    const list = ingredientsByTemplate.get(ing.template_id) ?? [];
    list.push(ing);
    ingredientsByTemplate.set(ing.template_id, list);
  }

  const bundles = rows<{
    id: string;
    template_ids_json: string;
    bundle_version: string;
    source_id: string;
    license_id: string;
  }>(db, `SELECT * FROM meal_bundle_templates WHERE active = 1`);

  const inventory = rows<{
    id: string;
    food_id: string | null;
    raw_quantity_expression: string;
    normalized_gram_range_json: string;
    state: string;
    priority_use: number;
    notes: string | null;
  }>(db, `SELECT * FROM inventory_items WHERE household_id = ?`, [householdId]);

  const foodModels: Food[] = foods.map((f) => ({
    id: f.id,
    canonicalName: f.canonical_name,
    aliases: aliasesByFood.get(f.id) ?? [],
    nutritionPer100g: JSON.parse(f.nutrition_json),
    allergenTags: JSON.parse(f.allergen_tags_json),
    sourceId: f.source_id,
    licenseId: f.license_id,
    dataVersion: f.data_version
  }));

  const templateModels: MealTemplate[] = templates.map((t) => ({
    id: t.id,
    name: t.name,
    role: t.role as MealTemplate["role"],
    ingredientsPerStandardServing: (ingredientsByTemplate.get(t.id) ?? []).map(
      (ing) => {
        let preparationTag: string | undefined;
        let edibleQuantityGMin: number | undefined;
        let edibleQuantityGMax: number | undefined;
        const raw = ing.preparation_tag ?? "";
        if (raw.startsWith("{")) {
          try {
            const meta = JSON.parse(raw) as {
              preparationTag?: string;
              edibleQuantityGMin?: number | null;
              edibleQuantityGMax?: number | null;
            };
            preparationTag = meta.preparationTag || undefined;
            if (meta.edibleQuantityGMin != null) {
              edibleQuantityGMin = meta.edibleQuantityGMin;
            }
            if (meta.edibleQuantityGMax != null) {
              edibleQuantityGMax = meta.edibleQuantityGMax;
            }
          } catch {
            preparationTag = raw || undefined;
          }
        } else if (raw) {
          preparationTag = raw;
        }
        return {
          foodId: ing.food_id,
          edibleQuantityG: ing.edible_quantity_g,
          ...(preparationTag ? { preparationTag } : {}),
          ...(edibleQuantityGMin != null ? { edibleQuantityGMin } : {}),
          ...(edibleQuantityGMax != null ? { edibleQuantityGMax } : {})
        };
      }
    ),
    tags: JSON.parse(t.tags_json),
    instructionsSummary: t.instructions_summary,
    sourceId: t.source_id,
    licenseId: t.license_id,
    templateVersion: t.template_version
  }));

  const bundleModels: MealBundleTemplate[] = bundles.map((b) => ({
    id: b.id,
    templateIds: JSON.parse(b.template_ids_json),
    bundleVersion: b.bundle_version,
    sourceId: b.source_id,
    licenseId: b.license_id
  }));

  const inventoryModels: InventoryItem[] = inventory.map((item) => ({
    id: item.id,
    foodId: item.food_id ?? "unknown",
    quantity: {
      rawExpression: item.raw_quantity_expression,
      normalized: JSON.parse(item.normalized_gram_range_json)
    },
    state: item.state as InventoryItem["state"],
    priorityConsume: item.priority_use === 1,
    ...(item.notes ? { notes: item.notes } : {})
  }));

  const constraintModels: MemberConstraint[] = constraints.map((c) => ({
    id: c.id,
    memberId: c.member_id,
    kind: c.kind as MemberConstraint["kind"],
    targetId: c.target_id,
    source: c.source as MemberConstraint["source"],
    ruleVersion: c.rule_version
  }));

  const policyModels: MemberMealPolicy[] = policies.map((p) => ({
    memberId: p.member_id,
    mealType: p.meal_type as MemberMealPolicy["mealType"],
    portionUnitsByRole: JSON.parse(p.portion_units_json),
    guardrails: JSON.parse(p.guardrails_json),
    source: "demo_fixture",
    ruleVersion: p.rule_version
  }));

  const frozenPreferences: FrozenPreference[] = prefs.map((p) => {
    const value = JSON.parse(p.value_json) as { note?: string; source?: string };
    return {
      memberId: p.member_id ?? "",
      kind: p.kind as FrozenPreference["kind"],
      note: value.note ?? p.kind,
      source: (value.source as FrozenPreference["source"]) ?? "fixture",
      ruleVersion: p.rule_version
    };
  });

  return {
    foods: foodModels,
    templates: templateModels,
    bundles: bundleModels,
    inventory: inventoryModels,
    members: members.map((m) => ({ id: m.id })),
    constraints: constraintModels,
    mealPolicies: policyModels,
    frozenPreferences,
    householdContextVersion: household.version,
    inventoryVersion: household.inventory_version,
    mealPolicyVersion: household.meal_policy_version,
    foodDataVersion: foodModels[0]?.dataVersion ?? "1.0.0"
  };
}

export function loadHouseholdMembers(db: Db, householdId: string): HouseholdMember[] {
  const members = rows<{
    id: string;
    display_name: string;
    relation_label: string;
    health_tags_json: string;
    notes: string | null;
    gender: MemberNutritionProfile["gender"] | null;
    age: number | null;
    birth_year: number | null;
    height_cm: number | null;
    weight_kg: number | null;
    activity_level: MemberNutritionProfile["activityLevel"] | null;
    weight_goal: MemberNutritionProfile["weightGoal"] | null;
  }>(
    db,
    `SELECT m.*, p.gender, p.age, p.birth_year, p.height_cm, p.weight_kg,
            p.activity_level, p.weight_goal
     FROM household_members m
     LEFT JOIN member_nutrition_profiles p ON p.member_id = m.id
     WHERE m.household_id = ? AND m.active = 1`,
    [householdId]
  );
  return members.map((m) => ({
    id: m.id,
    displayName: m.display_name,
    roleLabel: m.relation_label as HouseholdMember["roleLabel"],
    healthTags: JSON.parse(m.health_tags_json),
    ...(m.gender && m.height_cm != null && m.weight_kg != null &&
    m.activity_level && m.weight_goal
      ? {
          nutritionProfile: {
            gender: m.gender,
            ...(m.age != null ? { age: m.age } : {}),
            ...(m.birth_year != null ? { birthYear: m.birth_year } : {}),
            heightCm: m.height_cm,
            weightKg: m.weight_kg,
            activityLevel: m.activity_level,
            weightGoal: m.weight_goal
          }
        }
      : {}),
    ...(m.notes ? { notes: m.notes } : {})
  }));
}

export function insertPlanningSession(
  db: Db,
  input: {
    id: string;
    householdId: string;
    mealType: string;
    dinerIds: string[];
    activeConstraints: unknown;
    now: string;
  }
): void {
  db.prepare(
    `INSERT INTO meal_planning_sessions
     (id, household_id, meal_type, diner_ids_json, active_constraints_json, status, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, 'active', ?, ?)`
  ).run(
    input.id,
    input.householdId,
    input.mealType,
    JSON.stringify(input.dinerIds),
    JSON.stringify(input.activeConstraints),
    input.now,
    input.now
  );
}

export function savePlan(db: Db, plan: MealPlan): void {
  db.prepare(
    `INSERT INTO meal_plans
     (id, session_id, version, parent_plan_id, status, household_context_version, inventory_version, meal_policy_version, plan_json)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    plan.id,
    plan.sessionId,
    plan.version,
    plan.parentPlanId,
    plan.status,
    plan.householdContextVersion,
    plan.inventoryVersion,
    plan.mealPolicyVersion,
    JSON.stringify(plan)
  );

  for (const gap of plan.shoppingGap) {
    db.prepare(
      `INSERT INTO shopping_gap_items
       (plan_id, food_id, required_json, available_json, purchase_json, status, used_by_template_ids_json)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    ).run(
      plan.id,
      gap.foodId,
      JSON.stringify(gap.required),
      JSON.stringify(gap.available),
      JSON.stringify(gap.purchase),
      gap.status,
      JSON.stringify(gap.usedByTemplateIds)
    );
  }
}

export function supersedePlan(db: Db, planId: string): boolean {
  const existing = row<{ plan_json: string; status: string }>(
    db,
    `SELECT plan_json, status FROM meal_plans WHERE id = ?`,
    [planId]
  );
  if (!existing || existing.status !== "valid") return false;
  const plan = JSON.parse(existing.plan_json) as MealPlan;
  plan.status = "superseded";
  const result = db
    .prepare(
      `UPDATE meal_plans
       SET status = 'superseded', plan_json = ?
       WHERE id = ? AND status = 'valid'`
    )
    .run(JSON.stringify(plan), planId);
  return result.changes === 1;
}

export function getPlan(db: Db, planId: string): MealPlan | null {
  const existing = row<{ plan_json: string; status: string }>(
    db,
    `SELECT plan_json, status FROM meal_plans WHERE id = ?`,
    [planId]
  );
  if (!existing) return null;
  const plan = JSON.parse(existing.plan_json) as MealPlan;
  plan.status = existing.status as MealPlan["status"];
  return plan;
}

export function getActivePlanForSession(db: Db, sessionId: string): MealPlan | null {
  const existing = row<{ plan_json: string; status: string }>(
    db,
    `SELECT plan_json, status FROM meal_plans
     WHERE session_id = ? AND status = 'valid'
     ORDER BY version DESC LIMIT 1`,
    [sessionId]
  );
  if (!existing) return null;
  return JSON.parse(existing.plan_json) as MealPlan;
}

export function insertPendingAction(
  db: Db,
  input: {
    id: string;
    householdId: string;
    /** Discriminator: caregiver_task_send | inventory_restock | member_memory_change */
    actionType?: string;
    payload: unknown;
    preview: unknown;
    payloadHash: string;
    tokenHash: string;
    expiresAt: string;
    createdAt: string;
  }
): void {
  db.prepare(
    `INSERT INTO pending_actions
     (id, household_id, action_type, payload_json, preview_json, payload_hash, confirmation_token_hash, status, expires_at, committed_at, idempotency_key, commit_result_json, commit_result_hash, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, NULL, NULL, ?)`
  ).run(
    input.id,
    input.householdId,
    input.actionType ?? "caregiver_task_send",
    JSON.stringify(input.payload),
    JSON.stringify(input.preview),
    input.payloadHash,
    input.tokenHash,
    input.expiresAt,
    input.createdAt
  );
}

export function getPendingAction(db: Db, id: string) {
  return row<{
    id: string;
    household_id: string;
    action_type: string;
    payload_json: string;
    preview_json: string;
    payload_hash: string;
    confirmation_token_hash: string;
    status: string;
    expires_at: string;
    committed_at: string | null;
    idempotency_key: string | null;
    commit_result_json: string | null;
    commit_result_hash: string | null;
    created_at: string;
  }>(db, `SELECT * FROM pending_actions WHERE id = ?`, [id]);
}

export function cancelPendingAction(db: Db, pendingActionId: string): boolean {
  const result = db
    .prepare(
      `UPDATE pending_actions
       SET status = 'cancelled'
       WHERE id = ? AND status = 'pending'`
    )
    .run(pendingActionId);
  return Number(result.changes) === 1;
}

export function findReceiptByIdempotency(
  db: Db,
  householdId: string,
  idempotencyKey: string,
  actionType = "caregiver_task_send"
) {
  return row<{
    id: string;
    payload_hash: string;
    commit_result_json: string | null;
    commit_result_hash: string | null;
    committed_at: string | null;
    status: string;
    action_type: string;
  }>(
    db,
    `SELECT * FROM pending_actions
     WHERE household_id = ? AND action_type = ? AND idempotency_key = ?`,
    [householdId, actionType, idempotencyKey]
  );
}

/** Mark pending as committed without caregiver-specific side effects. */
export function markPendingCommitted(
  db: Db,
  input: {
    pendingActionId: string;
    idempotencyKey: string;
    result: unknown;
    resultHash: string;
    committedAt: string;
  }
): "committed" | "expired" | "stale" {
  const pending = getPendingAction(db, input.pendingActionId);
  if (!pending || pending.status !== "pending") return "stale";
  if (pending.expires_at < input.committedAt) return "expired";
  const update = db
    .prepare(
      `UPDATE pending_actions
       SET status = 'committed',
           committed_at = ?,
           idempotency_key = ?,
           commit_result_json = ?,
           commit_result_hash = ?
       WHERE id = ? AND status = 'pending' AND expires_at >= ?`
    )
    .run(
      input.committedAt,
      input.idempotencyKey,
      JSON.stringify(input.result),
      input.resultHash,
      input.pendingActionId,
      input.committedAt
    );
  return Number(update.changes) === 1 ? "committed" : "stale";
}

export function commitPendingAction(
  db: Db,
  input: {
    pendingActionId: string;
    idempotencyKey: string;
    result: CommitResult;
    resultHash: string;
    committedAt: string;
    taskCard: CaregiverTaskCard;
    householdId: string;
  }
): "committed" | "expired" | "stale" {
  db.exec("BEGIN IMMEDIATE");
  try {
    const pending = getPendingAction(db, input.pendingActionId);
    if (!pending || pending.status !== "pending") {
      db.exec("ROLLBACK");
      return "stale";
    }
    if (pending.expires_at < input.committedAt) {
      db.exec("ROLLBACK");
      return "expired";
    }

    const plan = getPlan(db, input.taskCard.planId);
    if (
      !plan ||
      plan.status !== "valid" ||
      plan.version !== input.taskCard.planVersion
    ) {
      db.exec("ROLLBACK");
      return "stale";
    }

    const update = db.prepare(
      `UPDATE pending_actions
       SET status = 'committed',
           committed_at = ?,
           idempotency_key = ?,
           commit_result_json = ?,
           commit_result_hash = ?
       WHERE id = ? AND status = 'pending' AND expires_at >= ?`
    ).run(
      input.committedAt,
      input.idempotencyKey,
      JSON.stringify(input.result),
      input.resultHash,
      input.pendingActionId,
      input.committedAt
    );
    if (Number(update.changes) !== 1) {
      db.exec("ROLLBACK");
      return "stale";
    }

    db.prepare(
      `INSERT INTO caregiver_tasks
       (id, household_id, plan_id, plan_version, recipient_label, task_card_json, channel, status, created_at)
       VALUES (?, ?, ?, ?, ?, ?, 'simulated_local_inbox', 'queued', ?)`
    ).run(
      input.result.caregiverTaskId,
      input.householdId,
      input.taskCard.planId,
      input.taskCard.planVersion,
      input.taskCard.recipientLabel,
      JSON.stringify(input.taskCard),
      input.committedAt
    );

    db.prepare(
      `INSERT INTO audit_events
       (id, session_id, household_id, tool_name, action_type, status, parameter_hash, result_summary, latency_ms, created_at)
       VALUES (?, NULL, ?, 'confirm_pending_action', 'caregiver_task_send', 'committed', ?, ?, NULL, ?)`
    ).run(
      `audit-${input.pendingActionId}`,
      input.householdId,
      input.resultHash,
      `task=${input.result.caregiverTaskId};channel=simulated_local_inbox`,
      input.committedAt
    );

    db.exec("COMMIT");
    return "committed";
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

export function getCaregiverTask(db: Db, taskId: string) {
  return row<{
    id: string;
    household_id: string;
    plan_id: string;
    plan_version: number;
    recipient_label: string;
    task_card_json: string;
    channel: string;
    status: string;
    created_at: string;
  }>(db, `SELECT * FROM caregiver_tasks WHERE id = ?`, [taskId]);
}

export function writeAudit(
  db: Db,
  input: {
    id: string;
    householdId?: string;
    sessionId?: string;
    toolName?: string;
    actionType: string;
    status: string;
    parameterHash?: string;
    resultSummary?: string;
    latencyMs?: number;
    createdAt: string;
  }
): void {
  db.prepare(
    `INSERT INTO audit_events
     (id, session_id, household_id, tool_name, action_type, status, parameter_hash, result_summary, latency_ms, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    input.id,
    input.sessionId ?? null,
    input.householdId ?? null,
    input.toolName ?? null,
    input.actionType,
    input.status,
    input.parameterHash ?? null,
    input.resultSummary ?? null,
    input.latencyMs ?? null,
    input.createdAt
  );
}
