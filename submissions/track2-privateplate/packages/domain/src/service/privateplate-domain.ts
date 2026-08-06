import { randomUUID } from "node:crypto";
import type {
  CaregiverTaskCard,
  CommitReceipt,
  ComposeFamilyMealResult,
  ConfirmationRequiredEvent,
  ConfirmErrorCode,
  MealPlan,
  PlanDiff
} from "@privateplate/contracts";
import {
  generateConfirmationToken,
  hashPayload,
  hashToken,
  safeEqualHex,
  sha256Hex
} from "../actions/canonical.js";
import {
  deleteAgentCheckpoint,
  loadAgentCheckpoint,
  saveAgentCheckpoint,
  type AgentCheckpoint,
  type JsonObject
} from "../db/checkpoints.js";
import { openDatabase, type Db } from "../db/open-db.js";
import {
  cancelPendingAction,
  commitPendingAction,
  getActivePlanForSession,
  getCaregiverTask,
  getPendingAction,
  getPlan,
  insertPendingAction,
  insertPlanningSession,
  loadHouseholdMembers,
  loadPlannerCatalog,
  savePlan,
  supersedePlan,
  writeAudit,
  findReceiptByIdempotency,
  markPendingCommitted
} from "../db/repositories.js";
import { seedFromFixtures } from "../db/seed.js";
import { DEFAULT_PREP_BUFFER } from "../nutrition-budget.js";
import { composeFamilyMeal } from "../planning/compose.js";
import { replanFamilyMeal } from "../planning/replan.js";
import {
  finalizeAgentMealPlan,
  findDishCandidates,
  type CandidateSet,
  type FinalizeMealResult,
  type SelectedDish
} from "../planning/agent-select.js";
import { buildCaregiverTaskCard } from "../task-card/build-task-card.js";
import {
  getDayContext,
  localServiceDate
} from "../ledger/day-context.js";
import { getInventory, type InventoryQuery } from "../ledger/inventory-query.js";
import type { DayContext } from "../ledger/types.js";
import {
  applyInventoryRestock,
  completeMealAsPlanned
} from "../ledger/meal-completion.js";
import {
  applyMemberMemoryChange,
  type MemberMemoryChangePayload
} from "../ledger/memory-writes.js";
import {
  createEmbeddingClientFromEnv,
  type EmbeddingClient
} from "../rag/embeddings.js";
import {
  ensureRagIndex,
  retrieveFromRagIndex,
  type RagRetrieveResult
} from "../rag/index-store.js";

export type DomainCreateOptions = {
  /** Override embedding client (tests inject HashEmbeddingClient). */
  embedding?: EmbeddingClient;
  /** Prepared-batch buffer; the planner accepts 5%–10%. */
  prepBuffer?: number;
};

export type InventoryRestockPayload = {
  foodId: string;
  deltaG: number;
  rawExpression: string;
  boxes?: number;
  unitLabel?: string;
};

export type TypedPreviewResult = {
  actionType: string;
  preview: Record<string, unknown>;
  confirmation: ConfirmationRequiredEvent;
};

export type PreviewSendResult = {
  preview: CaregiverTaskCard;
  confirmation: ConfirmationRequiredEvent;
};

export type ConfirmResult =
  | { ok: true; receipt: CommitReceipt; task: ReturnType<typeof getCaregiverTask> }
  | { ok: false; code: ConfirmErrorCode; message: string };

export type CancelResult =
  | { ok: true; status: "cancelled" }
  | { ok: false; code: ConfirmErrorCode; message: string };

export class PrivatePlateDomain {
  readonly db: Db;
  householdId = "";
  private embedding: EmbeddingClient;
  private prepBuffer: number;

  private constructor(
    db: Db,
    embedding: EmbeddingClient,
    prepBuffer = DEFAULT_PREP_BUFFER
  ) {
    this.db = db;
    this.embedding = embedding;
    this.prepBuffer = prepBuffer;
  }

  static async create(
    dbPath: string = ":memory:",
    options: DomainCreateOptions = {}
  ): Promise<PrivatePlateDomain> {
    const embedding =
      options.embedding ?? createEmbeddingClientFromEnv(process.env);
    const domain = new PrivatePlateDomain(
      openDatabase(dbPath),
      embedding,
      options.prepBuffer
    );
    const seeded = await seedFromFixtures(domain.db);
    domain.householdId = seeded.householdId;
    // Build local RAG index (hash offline by default; vLLM bge-small when RAG_MODE=vllm).
    try {
      await ensureRagIndex(domain.db, domain.embedding);
    } catch (error) {
      if (embedding.kind === "vllm") {
        const message =
          error instanceof Error ? error.message : String(error);
        throw new Error(
          `Local RAG index build failed with vLLM embeddings (${embedding.modelId}). ` +
            `Start the embedding server (default http://127.0.0.1:8001) or set ` +
            `PRIVATEPLATE_RAG_OFFLINE=yes for hash-only tests. Cause: ${message}`
        );
      }
      throw error;
    }
    return domain;
  }

  getEmbeddingInfo(): {
    kind: "vllm" | "hash";
    modelId: string;
    dimensions: number;
  } {
    return {
      kind: this.embedding.kind,
      modelId: this.embedding.modelId,
      dimensions: this.embedding.dimensions
    };
  }

  /**
   * Real local RAG: embed query → cosine search over corpus chunks.
   * Returns source paths and scores. Not keyword-only card ranking.
   */
  async retrieveLocalKnowledge(input: {
    query: string;
    topK?: number;
  }): Promise<RagRetrieveResult> {
    return retrieveFromRagIndex(this.db, this.embedding, input);
  }

  getCatalog() {
    return loadPlannerCatalog(this.db, this.householdId);
  }

  getMembers() {
    return loadHouseholdMembers(this.db, this.householdId);
  }

  getPlanById(planId: string) {
    return getPlan(this.db, planId);
  }

  /** Read-only inventory snapshot (no intake or member memory). */
  getInventory(): InventoryQuery {
    return getInventory(this.db, this.householdId);
  }

  /** Protocol v2 day context: targets, intake remaining, inventory, memory. */
  getDayContext(input?: {
    serviceDate?: string;
    timeZone?: string;
    dinerIds?: string[];
  }): DayContext {
    return getDayContext(this.db, this.householdId, {
      serviceDate: input?.serviceDate ?? localServiceDate(input?.timeZone),
      timeZone: input?.timeZone ?? "Asia/Shanghai",
      ...(input?.dinerIds ? { dinerIds: input.dinerIds } : {})
    });
  }

  /** Protocol v2: hard-filter dish candidates (no ranking/winner). */
  findDishCandidates(input: {
    dinerIds: string[];
    rejectedFoodIds?: string[];
    rejectedTemplateIds?: string[];
    serviceDate?: string;
  }): CandidateSet {
    const day = this.getDayContext({
      ...(input.serviceDate ? { serviceDate: input.serviceDate } : {}),
      dinerIds: input.dinerIds
    });
    const set = findDishCandidates(this.getCatalog(), {
      dinerIds: input.dinerIds,
      ...(input.rejectedFoodIds
        ? { rejectedFoodIds: input.rejectedFoodIds }
        : {}),
      ...(input.rejectedTemplateIds
        ? { rejectedTemplateIds: input.rejectedTemplateIds }
        : {}),
      intakeVersion: day.intakeVersion
    });
    this.db
      .prepare(
        `INSERT INTO meal_candidate_sets
         (id, household_id, service_date, meal_type, diner_ids_json, version_stamp_json, candidates_json, created_at)
         VALUES (?, ?, ?, 'unspecified', ?, ?, ?, ?)`
      )
      .run(
        set.candidateSetId,
        this.householdId,
        input.serviceDate ?? localServiceDate(),
        JSON.stringify(input.dinerIds),
        JSON.stringify(set.versionStamp),
        JSON.stringify(set.candidates),
        new Date().toISOString()
      );
    return set;
  }

  /** Protocol v2: finalize Agent dish selection (IDs preserved). */
  finalizeMealPlan(input: {
    sessionId: string;
    dinerIds: string[];
    mealType: "lunch" | "dinner";
    candidateSetId: string;
    selectedDishes: SelectedDish[];
    mealPortionScale: number;
    mealStructure?: import("@privateplate/contracts").MealStructure;
    selectionReason: string;
    parentPlan?: { id: string; version: number };
    rejectedFoodIds?: string[];
    rejectedTemplateIds?: string[];
    bannedFoodIds?: string[];
    bannedTemplateIds?: string[];
    pinnedSelection?: SelectedDish[];
    noAdditionalDishes?: boolean;
    maxDishCount?: number;
    maxHouseholdEnergyKcal?: number;
  }): FinalizeMealResult {
    const catalog = this.getCatalog();
    const unitRules = (
      this.db
        .prepare(
          `SELECT id, food_id, raw_unit, grams_per_unit FROM unit_conversion_rules`
        )
        .all() as Array<{
        id: string;
        food_id: string;
        raw_unit: string;
        grams_per_unit: number;
      }>
    ).map((r) => ({
      id: r.id,
      foodId: r.food_id,
      rawUnit: r.raw_unit,
      gramsPerUnit: r.grams_per_unit
    }));

    const day = this.getDayContext({ dinerIds: input.dinerIds });
    const stored = this.db
      .prepare(
        `SELECT id, diner_ids_json, version_stamp_json, candidates_json FROM meal_candidate_sets WHERE id = ?`
      )
      .get(input.candidateSetId) as
      | {
          id: string;
          diner_ids_json: string;
          version_stamp_json: string;
          candidates_json: string;
        }
      | undefined;
    if (!stored) {
      return {
        status: "failed",
        code: "UNKNOWN_CANDIDATE_SET",
        message: "候选集不存在或已过期，请重新 find_dish_candidates。",
        details: { candidateSetId: input.candidateSetId }
      };
    }
    const storedDiners = JSON.parse(stored.diner_ids_json) as string[];
    const dinerSet = new Set(storedDiners);
    if (
      input.dinerIds.length !== storedDiners.length ||
      input.dinerIds.some((id) => !dinerSet.has(id))
    ) {
      return {
        status: "failed",
        code: "DINER_MISMATCH",
        message: "finalize 的成员与候选集不一致。",
        details: { candidateDiners: storedDiners, finalizeDiners: input.dinerIds }
      };
    }
    const storedCandidates = JSON.parse(stored.candidates_json) as unknown[];
    const candidateSet: CandidateSet = {
      candidateSetId: stored.id,
      versionStamp: JSON.parse(stored.version_stamp_json),
      candidates: storedCandidates as CandidateSet["candidates"],
      byRole: {},
      selectionGuidance: {
        requiredRoles: ["shared_main", "shared_side", "staple"],
        maxSelectedDishes: 12,
        selectionCountIsModelDecision: true,
        candidateCount: storedCandidates.length,
        multipleDishesPerRoleAllowed: true,
        note: "candidates is the full hard-filtered pool, not a 3-dish shortlist. Cover requiredRoles; each role may include multiple dishes. byRole only groups ids for readability."
      }
    };
    const currentVersionStamp = {
      household: day.householdContextVersion,
      inventory: day.inventoryVersion,
      intake: day.intakeVersion,
      policy: day.mealPolicyVersion
    };

    // Parent plan must still be valid at finalize; supersede only after save.
    if (input.parentPlan) {
      const parent = getPlan(this.db, input.parentPlan.id);
      if (
        !parent ||
        parent.status !== "valid" ||
        parent.version !== input.parentPlan.version
      ) {
        return {
          status: "failed",
          code: "STALE_PARENT_PLAN",
          message: "父计划不存在或版本不匹配，无法修订。",
          details: { parentPlan: input.parentPlan }
        };
      }
    }

    const remainingNutritionByMember = new Map<string, import("../ledger/types.js").NutritionSnapshot>();
    const mealBudgetsByMemberId = new Map<string, import("@privateplate/contracts").MemberNutritionBudget>();
    for (const m of day.memberIntake) {
      if (!input.dinerIds.includes(m.memberId)) continue;
      remainingNutritionByMember.set(m.memberId, m.remaining);
      mealBudgetsByMemberId.set(m.memberId, m.nutritionBudget);
    }

    const result = finalizeAgentMealPlan(catalog, {
      ...input,
      householdId: this.householdId,
      intakeVersion: day.intakeVersion,
      unitRules,
      candidateSet,
      currentVersionStamp,
      remainingNutritionByMember,
      mealBudgetsByMemberId,
      prepBuffer: this.prepBuffer
    });

    if (result.status === "ok") {
      const now = new Date().toISOString();
      const existingSession = this.db
        .prepare(`SELECT id FROM meal_planning_sessions WHERE id = ?`)
        .get(input.sessionId) as { id: string } | undefined;
      if (!existingSession) {
        insertPlanningSession(this.db, {
          id: input.sessionId,
          householdId: this.householdId,
          mealType: input.mealType,
          dinerIds: input.dinerIds,
          activeConstraints: {},
          now
        });
      }
      // Persist child plan first, then supersede parent (success-only).
      savePlan(this.db, result.plan);
      if (input.parentPlan) {
        supersedePlan(this.db, input.parentPlan.id);
      }
      writeAudit(this.db, {
        id: `audit-finalize-${result.plan.id}-v${result.plan.version}`,
        householdId: this.householdId,
        sessionId: input.sessionId,
        toolName: "finalize_meal_plan",
        actionType: "finalize_agent_selection",
        status: "valid",
        resultSummary: `dishes=${input.selectedDishes.map((d) => d.templateId).join(",")}`,
        createdAt: now
      });
    }
    return result;
  }

  /**
   * Preview meal completion as planned — creates pending action (no write).
   * Confirm via confirmPendingWrite with actionType meal_completion.
   */
  previewMealCompletion(input: {
    planId: string;
    serviceDate?: string;
    ttlMs?: number;
  }): TypedPreviewResult {
    const plan = getPlan(this.db, input.planId);
    if (!plan || plan.status !== "valid") {
      throw Object.assign(new Error("PLAN_NOT_FOUND"), { code: "PLAN_NOT_FOUND" });
    }
    const serviceDate = input.serviceDate ?? localServiceDate();
    const payload = {
      planId: plan.id,
      planVersion: plan.version,
      serviceDate,
      mode: "as_planned" as const
    };
    const preview = {
      actionType: "meal_completion",
      planId: plan.id,
      planVersion: plan.version,
      dinerIds: plan.dinerIds,
      serviceDate,
      willRecordIntake: plan.memberAllocations.map((a) => ({
        memberId: a.memberId,
        nutrition: a.nutrition
      })),
      willDebitInventory: plan.preparedBatch ?? plan.batchIngredients,
      note: "确认后才会写入摄入、扣减库存并标记本餐完成。"
    };
    return this.createTypedPending("meal_completion", payload, preview, input.ttlMs);
  }

  /**
   * Internal write used only after pending confirm (or tests that inject confirm).
   * Prefer previewMealCompletion + confirmPendingWrite for product path.
   */
  completeMealAsPlanned(input: {
    planId: string;
    serviceDate?: string;
  }) {
    const plan = getPlan(this.db, input.planId);
    if (!plan) {
      return {
        ok: false as const,
        code: "PLAN_NOT_FOUND",
        message: "计划不存在。"
      };
    }
    return completeMealAsPlanned(this.db, {
      householdId: this.householdId,
      plan,
      serviceDate: input.serviceDate ?? localServiceDate()
    });
  }

  restockInventory(input: {
    foodId: string;
    deltaG: number;
    rawExpression: string;
  }) {
    return applyInventoryRestock(this.db, {
      householdId: this.householdId,
      foodId: input.foodId,
      deltaG: input.deltaG,
      rawExpression: input.rawExpression
    });
  }

  /**
   * Preview inventory restock — no DB mutation until confirmPendingWrite.
   * Example: 两盒豆腐 → food-tofu, 700g when rule is 350g/box.
   */
  previewInventoryChange(input: {
    foodId: string;
    quantity?: number;
    unit?: string;
    deltaG?: number;
    rawExpression?: string;
    ttlMs?: number;
  }): TypedPreviewResult {
    const food = this.getCatalog().foods.find((f) => f.id === input.foodId);
    if (!food) {
      throw Object.assign(new Error("FOOD_NOT_FOUND"), { code: "FOOD_NOT_FOUND" });
    }
    let deltaG = input.deltaG;
    let rawExpression = input.rawExpression ?? "";
    let boxes: number | undefined;
    const unit = (input.unit ?? "盒").trim();
    if (deltaG == null) {
      const qty = Number(input.quantity ?? 1);
      const rule = this.db
        .prepare(
          `SELECT grams_per_unit FROM unit_conversion_rules
           WHERE food_id = ? AND raw_unit = ?
           LIMIT 1`
        )
        .get(input.foodId, unit) as { grams_per_unit: number } | undefined;
      const gramsPerUnit = rule?.grams_per_unit ?? (unit === "盒" ? 350 : 1);
      deltaG = qty * gramsPerUnit;
      boxes = qty;
      rawExpression = rawExpression || `${qty}${unit}${food.canonicalName ?? food.id}`;
    }
    if (!Number.isFinite(deltaG) || deltaG <= 0) {
      throw Object.assign(new Error("INVALID_DELTA"), { code: "INVALID_DELTA" });
    }
    const payload: InventoryRestockPayload = {
      foodId: input.foodId,
      deltaG: Math.round(deltaG * 1000) / 1000,
      rawExpression,
      ...(boxes != null ? { boxes, unitLabel: unit } : {})
    };
    const before = this.getDayContext().inventory.find(
      (i) => i.foodId === input.foodId
    );
    const beforeG = before?.quantity?.estimateG ?? 0;
    const preview = {
      actionType: "inventory_restock",
      foodId: payload.foodId,
      foodName: food.canonicalName,
      deltaG: payload.deltaG,
      rawExpression: payload.rawExpression,
      beforeEstimateG: beforeG,
      afterEstimateG: beforeG + payload.deltaG,
      note: "确认入库前不会修改库存。"
    };
    return this.createTypedPending("inventory_restock", payload, preview, input.ttlMs);
  }

  /** Preview member preference / health fact write — no mutation until confirm. */
  previewMemberMemoryChange(input: {
    memberId: string;
    kind: "preference" | "health_fact";
    summary: string;
    polarity?: "prefer" | "avoid" | "note";
    source?: string;
    ttlMs?: number;
  }): TypedPreviewResult {
    const member = this.getMembers().find((m) => m.id === input.memberId);
    if (!member) {
      throw Object.assign(new Error("MEMBER_NOT_FOUND"), {
        code: "MEMBER_NOT_FOUND"
      });
    }
    const summary = input.summary.trim();
    if (!summary) {
      throw Object.assign(new Error("EMPTY_SUMMARY"), { code: "EMPTY_SUMMARY" });
    }
    const payload: MemberMemoryChangePayload = {
      memberId: input.memberId,
      kind: input.kind,
      summary,
      ...(input.polarity ? { polarity: input.polarity } : {}),
      source: input.source ?? "user_stated"
    };
    const preview = {
      actionType: "member_memory_change",
      memberId: payload.memberId,
      memberName: member.displayName,
      kind: payload.kind,
      summary: payload.summary,
      polarity: payload.polarity ?? null,
      note: "确认保存前不会写入家庭记忆。"
    };
    return this.createTypedPending(
      "member_memory_change",
      payload,
      preview,
      input.ttlMs
    );
  }

  /**
   * Unified confirm for caregiver / inventory / memory pending actions.
   * Chat never calls this — only UI/CLI side channel.
   */
  confirmPendingWrite(input: {
    pendingActionId: string;
    confirmationToken: string;
    idempotencyKey: string;
    expectedPayloadHash: string;
  }):
    | {
        ok: true;
        actionType: string;
        receipt: {
          pendingActionId: string;
          idempotencyKey: string;
          payloadHash: string;
          result: unknown;
          resultHash: string;
          committedAt: string;
          replayed: boolean;
        };
        result: unknown;
      }
    | { ok: false; code: ConfirmErrorCode; message: string } {
    const pending = getPendingAction(this.db, input.pendingActionId);
    if (!pending) {
      return { ok: false, code: "TOKEN_INVALID", message: "pending action not found" };
    }
    if (pending.payload_hash !== input.expectedPayloadHash) {
      return {
        ok: false,
        code: "PAYLOAD_HASH_MISMATCH",
        message: "expected payload hash does not match stored payload"
      };
    }
    const expectedHash = hashToken(input.confirmationToken);
    if (!safeEqualHex(expectedHash, pending.confirmation_token_hash)) {
      return { ok: false, code: "TOKEN_INVALID", message: "confirmation token invalid" };
    }

    const existing = findReceiptByIdempotency(
      this.db,
      pending.household_id,
      input.idempotencyKey,
      pending.action_type
    );
    if (existing && existing.status === "committed") {
      if (
        existing.id !== pending.id ||
        existing.payload_hash !== pending.payload_hash
      ) {
        return {
          ok: false,
          code: "IDEMPOTENCY_CONFLICT",
          message: "idempotency key reused with different payload hash"
        };
      }
      const result = JSON.parse(existing.commit_result_json ?? "{}");
      return {
        ok: true,
        actionType: pending.action_type,
        receipt: {
          pendingActionId: existing.id,
          idempotencyKey: input.idempotencyKey,
          payloadHash: existing.payload_hash,
          result,
          resultHash: existing.commit_result_hash ?? "",
          committedAt: existing.committed_at ?? "",
          replayed: true
        },
        result
      };
    }

    if (pending.status === "committed") {
      return {
        ok: false,
        code: "ACTION_ALREADY_COMMITTED",
        message: "action already committed with a different idempotency key"
      };
    }
    if (pending.status !== "pending") {
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: "pending action is no longer active"
      };
    }
    if (new Date(pending.expires_at).getTime() < Date.now()) {
      return { ok: false, code: "TOKEN_EXPIRED", message: "confirmation token expired" };
    }

    if (pending.action_type === "caregiver_task_send") {
      const caregiver = this.confirmCaregiverSend(input);
      if (!caregiver.ok) return caregiver;
      return {
        ok: true,
        actionType: "caregiver_task_send",
        receipt: {
          pendingActionId: caregiver.receipt.pendingActionId,
          idempotencyKey: caregiver.receipt.idempotencyKey,
          payloadHash: caregiver.receipt.payloadHash,
          result: caregiver.receipt.result,
          resultHash: caregiver.receipt.resultHash,
          committedAt: caregiver.receipt.committedAt,
          replayed: caregiver.receipt.replayed
        },
        result: caregiver.receipt.result
      };
    }

    const committedAt = new Date().toISOString();
    let result: Record<string, unknown>;

    if (pending.action_type === "meal_completion") {
      const payload = JSON.parse(pending.payload_json) as {
        planId: string;
        serviceDate?: string;
      };
      const applied = this.completeMealAsPlanned({
        planId: payload.planId,
        ...(payload.serviceDate ? { serviceDate: payload.serviceDate } : {})
      });
      if (!applied.ok) {
        return {
          ok: false,
          code: "INTERNAL_ERROR",
          message: applied.message
        };
      }
      result = { ...applied };
    } else if (pending.action_type === "inventory_restock") {
      const payload = JSON.parse(pending.payload_json) as InventoryRestockPayload;
      const applied = applyInventoryRestock(this.db, {
        householdId: this.householdId,
        foodId: payload.foodId,
        deltaG: payload.deltaG,
        rawExpression: payload.rawExpression,
        reason: "user_restock",
        relatedPendingActionId: pending.id
      });
      if (!applied.ok) {
        return {
          ok: false,
          code: "INTERNAL_ERROR",
          message: applied.message
        };
      }
      result = {
        foodId: payload.foodId,
        deltaG: payload.deltaG,
        inventoryVersion: applied.inventoryVersion
      };
    } else if (pending.action_type === "member_memory_change") {
      const payload = JSON.parse(
        pending.payload_json
      ) as MemberMemoryChangePayload;
      const applied = applyMemberMemoryChange(this.db, {
        householdId: this.householdId,
        change: payload
      });
      if (!applied.ok) {
        return {
          ok: false,
          code: "INTERNAL_ERROR",
          message: applied.message
        };
      }
      result = {
        recordId: applied.id,
        memberId: payload.memberId,
        kind: payload.kind,
        ...(applied.enforcedConstraintId
          ? { enforcedConstraintId: applied.enforcedConstraintId }
          : {})
      };
    } else {
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: `unsupported action type: ${pending.action_type}`
      };
    }

    const resultHash = sha256Hex(JSON.stringify(result));
    const mark = markPendingCommitted(this.db, {
      pendingActionId: pending.id,
      idempotencyKey: input.idempotencyKey,
      result,
      resultHash,
      committedAt
    });
    if (mark !== "committed") {
      return {
        ok: false,
        code: mark === "expired" ? "TOKEN_EXPIRED" : "STALE_CONTEXT",
        message: "pending action changed before commit"
      };
    }
    writeAudit(this.db, {
      id: `audit-confirm-${pending.id}`,
      householdId: this.householdId,
      toolName: "confirm_pending_action",
      actionType: pending.action_type,
      status: "committed",
      parameterHash: resultHash,
      resultSummary: JSON.stringify(result).slice(0, 200),
      createdAt: committedAt
    });
    return {
      ok: true,
      actionType: pending.action_type,
      receipt: {
        pendingActionId: pending.id,
        idempotencyKey: input.idempotencyKey,
        payloadHash: pending.payload_hash,
        result,
        resultHash,
        committedAt,
        replayed: false
      },
      result
    };
  }

  private createTypedPending(
    actionType: string,
    payload: unknown,
    preview: Record<string, unknown>,
    ttlMs?: number
  ): TypedPreviewResult {
    const pendingActionId = `pending-${randomUUID()}`;
    const token = generateConfirmationToken();
    const tokenHash = hashToken(token);
    const payloadHash = hashPayload(payload);
    const createdAt = new Date().toISOString();
    const expiresAt = new Date(
      Date.now() + (ttlMs ?? 15 * 60_000)
    ).toISOString();
    insertPendingAction(this.db, {
      id: pendingActionId,
      householdId: this.householdId,
      actionType,
      payload,
      preview,
      payloadHash,
      tokenHash,
      expiresAt,
      createdAt
    });
    writeAudit(this.db, {
      id: `audit-preview-${pendingActionId}`,
      householdId: this.householdId,
      toolName: `preview_${actionType}`,
      actionType: "preview",
      status: "pending",
      parameterHash: payloadHash,
      resultSummary: `pending=${pendingActionId}`,
      createdAt
    });
    return {
      actionType,
      preview,
      confirmation: {
        pendingActionId,
        confirmationToken: token,
        payloadHash,
        expiresAt
      }
    };
  }

  /** Read-only household snapshot for HTTP/UI (not a model tool). */
  getMealContext(input?: { dinerIds?: string[] }) {
    const catalog = this.getCatalog();
    const members = this.getMembers();
    const dinerIds =
      input?.dinerIds ?? members.map((m) => m.id).slice(0, 3);
    return {
      householdId: this.householdId,
      householdContextVersion: catalog.householdContextVersion,
      inventoryVersion: catalog.inventoryVersion,
      mealPolicyVersion: catalog.mealPolicyVersion,
      members: members.filter((m) => dinerIds.includes(m.id)),
      allMembers: members,
      constraints: catalog.constraints.filter((c) => dinerIds.includes(c.memberId)),
      frozenPreferences: catalog.frozenPreferences.filter((p) =>
        dinerIds.includes(p.memberId)
      ),
      mealPolicies: catalog.mealPolicies.filter((p) => dinerIds.includes(p.memberId)),
      inventory: catalog.inventory,
      foods: catalog.foods.map((f) => ({
        id: f.id,
        canonicalName: f.canonicalName,
        aliases: f.aliases
      })),
      templates: catalog.templates.map((t) => ({
        id: t.id,
        name: t.name,
        role: t.role,
        ingredientFoodIds: t.ingredientsPerStandardServing.map(
          (ingredient) => ingredient.foodId
        )
      }))
    };
  }

  /**
   * Legacy ranking/bundle compose (domain tests / historical path only).
   * Product Agent uses findDishCandidates + finalizeMealPlan.
   */
  composeMeal(input: {
    sessionId?: string;
    dinerIds?: string[];
    mealType?: "lunch" | "dinner";
    rejectedFoodIds?: string[];
    rejectedTemplateIds?: string[];
    requestedPriorityFoodIds?: string[];
    pinnedTemplateIds?: string[];
    preferLowEffort?: boolean;
  }): ComposeFamilyMealResult & { sessionId: string } {
    const catalog = this.getCatalog();
    const sessionId = input.sessionId ?? `session-${randomUUID()}`;
    const dinerIds =
      input.dinerIds ?? catalog.members.map((m) => m.id).slice(0, 3);
    const mealType = input.mealType ?? "lunch";
    const now = new Date().toISOString();

    const existingSession = this.db
      .prepare(`SELECT id FROM meal_planning_sessions WHERE id = ?`)
      .get(sessionId) as { id: string } | undefined;
    if (!existingSession) {
      insertPlanningSession(this.db, {
        id: sessionId,
        householdId: this.householdId,
        mealType,
        dinerIds,
        activeConstraints: {
          rejectedFoodIds: input.rejectedFoodIds ?? [],
          rejectedTemplateIds: input.rejectedTemplateIds ?? [],
          requestedPriorityFoodIds: input.requestedPriorityFoodIds ?? []
        },
        now
      });
    }

    const result = composeFamilyMeal(
      catalog,
      {
        householdId: this.householdId,
        mealSessionId: sessionId,
        dinerIds,
        mealType,
        householdContextVersion: catalog.householdContextVersion,
        inventoryVersion: catalog.inventoryVersion,
        mealPolicyVersion: catalog.mealPolicyVersion,
        constraints: [],
        pinnedTemplateIds: input.pinnedTemplateIds ?? [],
        rejectedTemplateIds: input.rejectedTemplateIds ?? [],
        rejectedFoodIds: input.rejectedFoodIds ?? [],
        requestedPriorityFoodIds: input.requestedPriorityFoodIds ?? [],
        preferLowEffort: input.preferLowEffort ?? false
      },
      { requirePins: true }
    );

    if (result.status === "valid") {
      savePlan(this.db, result.plan);
      writeAudit(this.db, {
        id: `audit-plan-${result.plan.id}`,
        householdId: this.householdId,
        sessionId,
        toolName: "compose_family_meal",
        actionType: "compose",
        status: "valid",
        resultSummary: `bundle=${result.plan.bundleId};version=${result.plan.version}`,
        createdAt: now
      });
    }

    return { ...result, sessionId };
  }

  /**
   * Main demo step 1: plan lunch for all diners with priority tofu and reject chicken.
   */
  planInitialDemo(input?: {
    sessionId?: string;
    dinerIds?: string[];
    mealType?: "lunch" | "dinner";
  }): ComposeFamilyMealResult & { sessionId: string } {
    const args: {
      sessionId?: string;
      dinerIds?: string[];
      mealType?: "lunch" | "dinner";
      rejectedFoodIds?: string[];
      requestedPriorityFoodIds?: string[];
    } = {
      mealType: input?.mealType ?? "lunch",
      rejectedFoodIds: ["food-chicken-leg"],
      requestedPriorityFoodIds: ["food-tofu"]
    };
    if (input?.sessionId) args.sessionId = input.sessionId;
    if (input?.dinerIds) args.dinerIds = input.dinerIds;
    return this.composeMeal(args);
  }

  reviseMeal(input: {
    sessionId: string;
    parentPlanId: string;
    constraintDelta: Array<{
      operation: "add" | "remove";
      kind: "reject_template" | "reject_food" | "prefer_low_effort" | "pin_template";
      targetId: string;
      sourceUtterance: string;
    }>;
  }):
    | { status: "valid"; plan: MealPlan; diff: PlanDiff; shoppingGap: MealPlan["shoppingGap"] }
    | { status: "infeasible"; code: "NO_FEASIBLE_PLAN" } {
    const catalog = this.getCatalog();
    const parent = getPlan(this.db, input.parentPlanId);
    if (!parent || parent.status !== "valid") {
      throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
    }

    const result = replanFamilyMeal(catalog, parent, {
      mealSessionId: input.sessionId,
      parentPlanId: parent.id,
      parentPlanVersion: parent.version,
      constraintDelta: input.constraintDelta,
      householdContextVersion: catalog.householdContextVersion,
      inventoryVersion: catalog.inventoryVersion,
      mealPolicyVersion: catalog.mealPolicyVersion
    });

    if (result.status === "infeasible") {
      return { status: "infeasible", code: "NO_FEASIBLE_PLAN" };
    }

    this.db.exec("BEGIN IMMEDIATE");
    try {
      const currentParent = getPlan(this.db, parent.id);
      if (
        !currentParent ||
        currentParent.status !== "valid" ||
        currentParent.version !== parent.version
      ) {
        throw Object.assign(new Error("STALE_CONTEXT"), {
          code: "STALE_CONTEXT"
        });
      }
      if (!supersedePlan(this.db, parent.id)) {
        throw Object.assign(new Error("STALE_CONTEXT"), {
          code: "STALE_CONTEXT"
        });
      }
      savePlan(this.db, result.plan);
      writeAudit(this.db, {
        id: `audit-replan-${result.plan.id}`,
        householdId: this.householdId,
        sessionId: input.sessionId,
        toolName: "replan_family_meal",
        actionType: "replan",
        status: "valid",
        resultSummary: `from=${parent.version};to=${result.plan.version};removed=${result.diff.removedTemplateIds.join(",")}`,
        createdAt: new Date().toISOString()
      });
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }

    return result;
  }

  /**
   * Main demo step 2: reject steamed-egg template and replan.
   */
  replanRejectTemplate(input: {
    sessionId: string;
    parentPlanId: string;
    rejectedTemplateId: string;
    sourceUtterance: string;
  }):
    | { status: "valid"; plan: MealPlan; diff: PlanDiff; shoppingGap: MealPlan["shoppingGap"] }
    | { status: "infeasible"; code: "NO_FEASIBLE_PLAN" } {
    return this.reviseMeal({
      sessionId: input.sessionId,
      parentPlanId: input.parentPlanId,
      constraintDelta: [
        {
          operation: "add",
          kind: "reject_template",
          targetId: input.rejectedTemplateId,
          sourceUtterance: input.sourceUtterance
        }
      ]
    });
  }

  retrieveApprovedGuidance(input: {
    query: string;
    memberTags?: string[];
    planTags?: string[];
    topK?: number;
  }) {
    const topK = Math.min(3, Math.max(1, input.topK ?? 3));
    const rows = this.db
      .prepare(
        `SELECT id, title, content, tags_json, applicability_json, exclusions_json,
                risk_level, source_year
         FROM knowledge_cards WHERE review_status = 'approved'`
      )
      .all() as Array<{
      id: string;
      title: string;
      content: string;
      tags_json: string;
      applicability_json: string;
      exclusions_json: string;
      risk_level: string;
      source_year: number | null;
    }>;

    const queryTokens = tokenize(input.query);
    const memberTags = new Set((input.memberTags ?? []).map(normalizeTag));
    const planTags = new Set((input.planTags ?? []).map(normalizeTag));
    const hasPlanTags = planTags.size > 0;
    const applicabilityTags = new Set(["answer", ...memberTags, ...planTags]);
    if (planTags.has("planning")) applicabilityTags.add("compose");
    if (planTags.has("replan")) applicabilityTags.add("replan");
    if (planTags.has("handoff") || planTags.has("privacy")) {
      applicabilityTags.add("task_card");
    }
    if (planTags.has("shopping")) applicabilityTags.add("shopping_gap");

    const candidates = rows
      .filter((row) => {
        if (row.risk_level !== "low") return false;
        const appliesTo = (JSON.parse(row.applicability_json) as string[]).map(
          normalizeTag
        );
        const exclusions = (JSON.parse(row.exclusions_json) as string[]).map(
          normalizeTag
        );
        const isExcluded = exclusions.some((tag) =>
          applicabilityTags.has(tag)
        );
        if (isExcluded) return false;
        if (!hasPlanTags) return true;
        return (
          appliesTo.length === 0 ||
          appliesTo.some((tag) => applicabilityTags.has(tag))
        );
      })
      .map((row) => {
        const tags: string[] = JSON.parse(row.tags_json);
        const normalizedTags = tags.map(normalizeTag);
        const title = String(row.title).toLowerCase();
        const content = String(row.content).toLowerCase();
        const tagHay = tags.join(" ").toLowerCase();
        let tagScore = 0;
        const queryScore = scoreQueryTokens(
          queryTokens,
          title,
          content,
          tagHay
        );
        for (const tag of normalizedTags) {
          if (memberTags.has(tag)) tagScore += 4;
          // planTags are soft boosts only; natural query must drive ranking
          if (planTags.has(tag)) tagScore += 1;
        }
        const score = queryScore + tagScore;
        return {
          sourceId: row.id,
          title: row.title,
          year: row.source_year,
          relevantContent: row.content,
          matchedTags: tags.filter((tag) => {
            const normalized = normalizeTag(tag);
            return (
              memberTags.has(normalized) ||
              planTags.has(normalized) ||
              queryTokens.some(
                (queryToken) =>
                  normalized.includes(queryToken) ||
                  queryToken.includes(normalized)
              )
            );
          }),
          queryScore,
          score
        };
      });
    const bestQueryScore = candidates.reduce(
      (best, card) => Math.max(best, card.queryScore),
      0
    );
    const minimumRelevantScore =
      bestQueryScore > 0
        ? Math.max(3, Math.ceil(bestQueryScore * 0.4))
        : Number.POSITIVE_INFINITY;
    const scored = candidates
      // Prefer cards that match the natural query; planTags alone are insufficient.
      .filter(
        (c) =>
          c.queryScore >= minimumRelevantScore ||
          (queryTokens.length === 0 && c.score > 0)
      )
      .sort(
        (a, b) =>
          b.queryScore - a.queryScore ||
          b.score - a.score ||
          a.sourceId.localeCompare(b.sourceId)
      )
      .slice(0, topK);

    return {
      queryId: `rq-${randomUUID()}`,
      cards: scored.map(
        ({
          score: _s,
          queryScore: _q,
          ...card
        }) => card
      ),
      retrievalVersion: "rag-deterministic-1.2.0"
    };
  }

  /** Preview only — does not write caregiver_tasks. */
  previewCaregiverSend(input: {
    planId: string;
    recipientLabel: string;
    serveAt?: string | "unspecified";
    ttlMs?: number;
  }): PreviewSendResult {
    const plan = getPlan(this.db, input.planId);
    if (!plan || plan.status !== "valid") {
      throw Object.assign(new Error("STALE_CONTEXT"), { code: "STALE_CONTEXT" });
    }

    const members = loadHouseholdMembers(this.db, this.householdId);
    const catalog = this.getCatalog();
    const card = buildCaregiverTaskCard({
      plan,
      recipientLabel: input.recipientLabel,
      serveAt: input.serveAt ?? "unspecified",
      members,
      constraints: catalog.constraints
    });

    const pendingActionId = `pending-${randomUUID()}`;
    const token = generateConfirmationToken();
    const tokenHash = hashToken(token);
    const payloadHash = hashPayload(card);
    const createdAt = new Date().toISOString();
    const expiresAt = new Date(Date.now() + (input.ttlMs ?? 15 * 60_000)).toISOString();

    insertPendingAction(this.db, {
      id: pendingActionId,
      householdId: this.householdId,
      payload: card,
      preview: card,
      payloadHash,
      tokenHash,
      expiresAt,
      createdAt
    });

    writeAudit(this.db, {
      id: `audit-preview-${pendingActionId}`,
      householdId: this.householdId,
      toolName: "preview_caregiver_task_send",
      actionType: "preview",
      status: "pending",
      parameterHash: payloadHash,
      resultSummary: `pending=${pendingActionId}`,
      createdAt
    });

    return {
      preview: card,
      confirmation: {
        pendingActionId,
        confirmationToken: token,
        payloadHash,
        expiresAt
      }
    };
  }

  confirmCaregiverSend(input: {
    pendingActionId: string;
    confirmationToken: string;
    idempotencyKey: string;
    expectedPayloadHash: string;
  }): ConfirmResult {
    const pending = getPendingAction(this.db, input.pendingActionId);
    if (!pending) {
      return { ok: false, code: "TOKEN_INVALID", message: "pending action not found" };
    }

    if (pending.payload_hash !== input.expectedPayloadHash) {
      return {
        ok: false,
        code: "PAYLOAD_HASH_MISMATCH",
        message: "expected payload hash does not match stored payload"
      };
    }

    const expectedHash = hashToken(input.confirmationToken);
    if (!safeEqualHex(expectedHash, pending.confirmation_token_hash)) {
      return { ok: false, code: "TOKEN_INVALID", message: "confirmation token invalid" };
    }

    // Idempotent replay is valid only for this exact action, token and payload.
    const existing = findReceiptByIdempotency(
      this.db,
      pending.household_id,
      input.idempotencyKey
    );
    if (existing && existing.status === "committed") {
      if (
        existing.id !== pending.id ||
        existing.payload_hash !== pending.payload_hash
      ) {
        return {
          ok: false,
          code: "IDEMPOTENCY_CONFLICT",
          message: "idempotency key reused with different payload hash"
        };
      }
      const result = JSON.parse(existing.commit_result_json ?? "{}");
      return {
        ok: true,
        receipt: {
          pendingActionId: existing.id,
          idempotencyKey: input.idempotencyKey,
          payloadHash: existing.payload_hash,
          result,
          resultHash: existing.commit_result_hash ?? "",
          committedAt: existing.committed_at ?? "",
          replayed: true
        },
        task: getCaregiverTask(this.db, result.caregiverTaskId)
      };
    }

    if (pending.status === "committed") {
      return {
        ok: false,
        code: "ACTION_ALREADY_COMMITTED",
        message: "action already committed with a different idempotency key"
      };
    }

    if (pending.status !== "pending") {
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: "pending action is no longer active"
      };
    }

    if (new Date(pending.expires_at).getTime() < Date.now()) {
      return { ok: false, code: "TOKEN_EXPIRED", message: "confirmation token expired" };
    }

    const card = JSON.parse(pending.payload_json) as CaregiverTaskCard;
    const plan = getPlan(this.db, card.planId);
    if (!plan || plan.status !== "valid" || plan.version !== card.planVersion) {
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: "preview plan is no longer active"
      };
    }

    const committedAt = new Date().toISOString();
    const caregiverTaskId = `task-${randomUUID()}`;
    const result = {
      caregiverTaskId,
      channel: "simulated_local_inbox" as const,
      status: "queued" as const
    };
    const resultHash = sha256Hex(JSON.stringify(result));

    const commitStatus = commitPendingAction(this.db, {
      pendingActionId: pending.id,
      idempotencyKey: input.idempotencyKey,
      result,
      resultHash,
      committedAt,
      taskCard: card,
      householdId: pending.household_id
    });
    if (commitStatus === "expired") {
      return {
        ok: false,
        code: "TOKEN_EXPIRED",
        message: "confirmation token expired"
      };
    }
    if (commitStatus === "stale") {
      const racedReceipt = findReceiptByIdempotency(
        this.db,
        pending.household_id,
        input.idempotencyKey
      );
      if (
        racedReceipt?.status === "committed" &&
        racedReceipt.id === pending.id &&
        racedReceipt.payload_hash === pending.payload_hash
      ) {
        const racedResult = JSON.parse(
          racedReceipt.commit_result_json ?? "{}"
        );
        return {
          ok: true,
          receipt: {
            pendingActionId: racedReceipt.id,
            idempotencyKey: input.idempotencyKey,
            payloadHash: racedReceipt.payload_hash,
            result: racedResult,
            resultHash: racedReceipt.commit_result_hash ?? "",
            committedAt: racedReceipt.committed_at ?? "",
            replayed: true
          },
          task: getCaregiverTask(this.db, racedResult.caregiverTaskId)
        };
      }
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: "pending action changed before commit"
      };
    }

    return {
      ok: true,
      receipt: {
        pendingActionId: pending.id,
        idempotencyKey: input.idempotencyKey,
        payloadHash: pending.payload_hash,
        result,
        resultHash,
        committedAt,
        replayed: false
      },
      task: getCaregiverTask(this.db, caregiverTaskId)
    };
  }

  cancelCaregiverSend(input: { pendingActionId: string }): CancelResult {
    const pending = getPendingAction(this.db, input.pendingActionId);
    if (!pending) {
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: "pending action not found"
      };
    }
    if (pending.status === "cancelled") {
      return { ok: true, status: "cancelled" };
    }
    if (pending.status === "committed") {
      return {
        ok: false,
        code: "ACTION_ALREADY_COMMITTED",
        message: "committed action cannot be cancelled"
      };
    }
    if (!cancelPendingAction(this.db, pending.id)) {
      return {
        ok: false,
        code: "STALE_CONTEXT",
        message: "pending action is no longer active"
      };
    }
    writeAudit(this.db, {
      id: `audit-cancel-${pending.id}`,
      householdId: pending.household_id,
      toolName: "cancel_pending_action",
      actionType: "caregiver_task_send",
      status: "cancelled",
      parameterHash: pending.payload_hash,
      resultSummary: `pending=${pending.id}`,
      createdAt: new Date().toISOString()
    });
    return { ok: true, status: "cancelled" };
  }

  readCaregiverTask(taskId: string) {
    return getCaregiverTask(this.db, taskId);
  }

  getActivePlan(sessionId: string) {
    return getActivePlanForSession(this.db, sessionId);
  }

  saveAgentCheckpoint<TState extends object>(
    sessionId: string,
    state: TState
  ): AgentCheckpoint<TState> {
    return saveAgentCheckpoint(this.db, {
      sessionId,
      householdId: this.householdId,
      state,
      updatedAt: new Date().toISOString()
    });
  }

  loadAgentCheckpoint<TState = JsonObject>(
    sessionId: string
  ): AgentCheckpoint<TState> | null {
    return loadAgentCheckpoint<TState>(this.db, this.householdId, sessionId);
  }

  deleteAgentCheckpoint(sessionId: string): boolean {
    return deleteAgentCheckpoint(this.db, this.householdId, sessionId);
  }

  close(): void {
    this.db.close();
  }
}

/** Chinese diet/privacy synonyms so natural queries can hit card text. */
const QUERY_SYNONYMS: Record<string, string[]> = {
  少盐: ["钠", "低盐", "控盐", "钠边界", "全餐少盐"],
  低盐: ["钠", "少盐", "控盐", "钠边界"],
  控盐: ["钠", "少盐", "低盐", "钠边界"],
  控糖: ["碳水", "血糖", "能量"],
  血糖: ["碳水", "控糖"],
  克制: ["碳水", "能量", "主食", "演示", "边界"],
  主食: ["碳水", "米饭", "能量", "边界"],
  饮食: ["碳水", "能量", "演示", "边界"],
  快坏: ["优先消耗", "库存", "豆腐"],
  库存: ["快坏", "优先消耗"],
  交接卡: ["任务卡", "保姆"],
  任务卡: ["交接卡", "保姆"],
  照护: ["任务卡", "保姆", "最小披露", "隐私"],
  健康资料: ["疾病史", "最小披露", "隐私"],
  健康标签: ["疾病史", "最小披露", "隐私", "任务卡"],
  健康信息: ["疾病史", "最小披露", "隐私", "任务卡"],
  医疗信息: ["疾病史", "最小披露", "隐私", "任务卡"],
  病情: ["疾病史", "最小披露", "隐私"],
  必要信息: ["最小披露", "任务卡", "隐私"],
  执行人员: ["保姆", "任务卡", "最小披露"],
  拒绝: ["拒绝项", "重规划", "不再推荐"],
  重规划: ["拒绝项", "replan"],
  隐私: ["最小披露", "任务卡", "交接卡", "疾病史"],
  病历: ["疾病史", "最小披露", "隐私"],
  豆腐: ["快坏", "优先消耗"],
  米饭小份: ["主食小份", "份量差异", "碳水守卫"],
  守卫: ["演示", "医疗处方", "合成"]
};

/**
 * Tokenize Chinese without spaces: punctuation split + CJK n-grams + synonyms.
 * Whole unsplit Chinese sentences used to become one token and miss card text.
 * Single-char synonym expansions (e.g. 钠) are kept — length>=2 only applies to
 * raw n-grams, not curated synonym targets.
 */
function tokenize(text: string): string[] {
  const lower = text.toLowerCase().trim();
  if (!lower) return [];
  const tokens = new Set<string>();
  const synonymTokens = new Set<string>();
  const parts = lower
    .split(/[\s,，。！？、；：:？?！!（）()【】\[\]"'“”‘’]+/)
    .map((part) => part.trim())
    .filter(Boolean);

  for (const part of parts) {
    if (part.length >= 2) tokens.add(part);
    if (/[\u4e00-\u9fff]/.test(part)) {
      for (let n = 2; n <= Math.min(4, part.length); n += 1) {
        for (let i = 0; i + n <= part.length; i += 1) {
          tokens.add(part.slice(i, i + n));
        }
      }
    }
  }

  const expandSynonyms = (source: Iterable<string>) => {
    for (const token of source) {
      const extras = QUERY_SYNONYMS[token];
      if (!extras) continue;
      for (const extra of extras) {
        const normalized = extra.toLowerCase();
        tokens.add(normalized);
        synonymTokens.add(normalized);
      }
    }
  };
  expandSynonyms(tokens);
  // Also expand when a synonym key is contained in the raw query.
  for (const [key, extras] of Object.entries(QUERY_SYNONYMS)) {
    if (lower.includes(key)) {
      tokens.add(key);
      for (const extra of extras) {
        const normalized = extra.toLowerCase();
        tokens.add(normalized);
        synonymTokens.add(normalized);
      }
    }
  }

  return [...tokens].filter(
    (token) => token.length >= 2 || synonymTokens.has(token)
  );
}

function scoreQueryTokens(
  queryTokens: string[],
  title: string,
  content: string,
  tags: string
): number {
  const matches = queryTokens
    .map((token) => ({
      token,
      score: title.includes(token)
        ? 5
        : content.includes(token)
          ? 3
          : tags.includes(token)
            ? 1
            : 0
    }))
    .filter((match) => match.score > 0);

  return matches
    .filter(
      (match) =>
        !matches.some(
          (other) =>
            other.token.length > match.token.length &&
            other.token.includes(match.token) &&
            other.score >= match.score
        )
    )
    .reduce((sum, match) => sum + match.score, 0);
}

function normalizeTag(tag: string): string {
  return tag.trim().toLowerCase();
}
