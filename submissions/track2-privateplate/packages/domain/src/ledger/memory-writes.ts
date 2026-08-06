/**
 * Confirmable family memory writes (preferences / health facts).
 * When a saved summary clearly avoids exactly one catalog food, also insert a
 * hard member_constraints row so planning enforces it — memory must not be
 * display-only.
 */
import { randomUUID } from "node:crypto";
import type { Db } from "../db/open-db.js";
import { persistAgentMemoryKind } from "./memory-kind.js";

export type MemberMemoryChangePayload = {
  memberId: string;
  kind: "preference" | "health_fact";
  summary: string;
  polarity?: "prefer" | "avoid" | "note";
  source: string;
};

export type ApplyMemberMemoryResult =
  | { ok: true; id: string; enforcedConstraintId?: string }
  | { ok: false; code: string; message: string };

const AVOID_WORD_RE =
  /过敏|忌口|不能吃|不吃|别放|别给|别安排|避免|禁止|不要|戒/;

export function applyMemberMemoryChange(
  db: Db,
  input: {
    householdId: string;
    change: MemberMemoryChangePayload;
  }
): ApplyMemberMemoryResult {
  const now = new Date().toISOString();
  const member = db
    .prepare(
      `SELECT id FROM household_members WHERE id = ? AND household_id = ?`
    )
    .get(input.change.memberId, input.householdId) as { id: string } | undefined;
  if (!member) {
    return { ok: false, code: "MEMBER_NOT_FOUND", message: "成员不存在。" };
  }
  const summary = input.change.summary.trim();
  if (!summary) {
    return { ok: false, code: "EMPTY_SUMMARY", message: "缺少要保存的内容。" };
  }

  db.exec("BEGIN IMMEDIATE");
  try {
    let id: string;
    if (input.change.kind === "health_fact") {
      id = `hf-${randomUUID()}`;
      db.prepare(
        `INSERT INTO member_health_facts
         (id, member_id, household_id, kind, summary, source, effective_from, effective_to, version, active, created_at, updated_at)
         VALUES (?, ?, ?, 'user_stated', ?, ?, ?, NULL, 1, 1, ?, ?)`
      ).run(
        id,
        input.change.memberId,
        input.householdId,
        summary,
        input.change.source || "user_confirmed",
        now,
        now,
        now
      );
    } else {
      id = `pref-${randomUUID()}`;
      const preferenceKind = persistAgentMemoryKind(input.change.kind);
      db.prepare(
        `INSERT INTO member_preferences
         (id, member_id, household_id, kind, target_type, target_id, note, polarity, source, version, active, created_at, updated_at)
         VALUES (?, ?, ?, ?, 'note', NULL, ?, ?, ?, 1, 1, ?, ?)`
      ).run(
        id,
        input.change.memberId,
        input.householdId,
        preferenceKind,
        summary,
        input.change.polarity ?? "prefer",
        input.change.source || "user_confirmed",
        now,
        now
      );
    }

    const enforcedConstraintId = tryEnforceAvoidIngredientConstraint(db, {
      memberId: input.change.memberId,
      summary
    });

    db.prepare(
      `UPDATE households SET version = version + 1, updated_at = ? WHERE id = ?`
    ).run(now, input.householdId);
    db.exec("COMMIT");
    return enforcedConstraintId
      ? { ok: true, id, enforcedConstraintId }
      : { ok: true, id };
  } catch (error) {
    db.exec("ROLLBACK");
    return {
      ok: false,
      code: "MEMORY_WRITE_FAILED",
      message: error instanceof Error ? error.message : String(error)
    };
  }
}

/**
 * Resolve at most one catalog food the summary is avoiding. Zero or multiple
 * matches → no hard constraint (never guess). Longest label wins per food so
 * short aliases like「蛋」do not beat「鸡蛋」when both appear.
 */
export function resolveAvoidedFoodId(
  summary: string,
  catalog: Array<{ foodId: string; labels: string[] }>
): string | null {
  if (!AVOID_WORD_RE.test(summary)) return null;

  const matchedFoodIds = new Set<string>();
  for (const food of catalog) {
    const labels = [...food.labels]
      .filter((label) => label.trim().length > 0)
      .sort((a, b) => b.length - a.length);
    if (labels.some((label) => summary.includes(label))) {
      matchedFoodIds.add(food.foodId);
    }
  }
  if (matchedFoodIds.size !== 1) return null;
  return [...matchedFoodIds][0]!;
}

function loadFoodLabelCatalog(
  db: Db
): Array<{ foodId: string; labels: string[] }> {
  const foods = db
    .prepare(`SELECT id, canonical_name FROM foods`)
    .all() as Array<{ id: string; canonical_name: string }>;
  const aliases = db
    .prepare(`SELECT alias, food_id FROM food_aliases`)
    .all() as Array<{ alias: string; food_id: string }>;

  const byId = new Map<string, string[]>();
  for (const food of foods) {
    byId.set(food.id, [food.canonical_name]);
  }
  for (const alias of aliases) {
    const labels = byId.get(alias.food_id);
    if (labels) labels.push(alias.alias);
    else byId.set(alias.food_id, [alias.alias]);
  }
  return [...byId.entries()].map(([foodId, labels]) => ({ foodId, labels }));
}

function tryEnforceAvoidIngredientConstraint(
  db: Db,
  input: { memberId: string; summary: string }
): string | undefined {
  const foodId = resolveAvoidedFoodId(
    input.summary,
    loadFoodLabelCatalog(db)
  );
  if (!foodId) return undefined;

  const constraintId = `cst-${input.memberId}-avoid-${foodId}`;
  db.prepare(
    `INSERT OR IGNORE INTO member_constraints
     (id, member_id, kind, target_id, source, rule_version)
     VALUES (?, ?, 'avoid_ingredient', ?, 'session_input', '1.0.0')`
  ).run(constraintId, input.memberId, foodId);

  const row = db
    .prepare(
      `SELECT id FROM member_constraints
       WHERE id = ? AND member_id = ? AND kind = 'avoid_ingredient' AND target_id = ?`
    )
    .get(constraintId, input.memberId, foodId) as { id: string } | undefined;
  return row?.id;
}
