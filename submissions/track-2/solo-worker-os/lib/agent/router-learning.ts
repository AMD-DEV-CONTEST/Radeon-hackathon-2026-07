/**
 * Router self-learning — feedback-driven keyword weight tuning.
 *
 * This module closes the loop between the Trace data we already collect and the
 * FunctionRouter: when a user corrects a routing decision, the correction is
 * fed back into keyword weights so the same message pattern routes better next
 * time.
 *
 * Two collaborators:
 *   1. FeedbackStore      — in-memory ring buffer of user corrections.
 *   2. KeywordWeightAdjuster — recomputes per-(subagent, keyword) weight
 *                              multipliers from the feedback history.
 *
 * Persistence: weight adjustments are asynchronously persisted to the
 * `router_weights` table so they survive server restarts. On startup, weights
 * are lazily loaded from the database on first access. In demo mode (no
 * database), persistence is skipped silently.
 */

import type { SubagentId, RouterFeedback, WeightAdjustment } from './types';
import { getAllSubagents } from './subagents';

// ─── Tuning constants ────────────────────────────────────────────────────────

/** Maximum feedback records kept in memory (oldest evicted first). */
const MAX_FEEDBACK = 1000;

/** Neutral multiplier — no learning signal yet. */
const DEFAULT_WEIGHT = 1.0;

/** Lower/upper clamp for any keyword weight. */
const WEIGHT_MIN = 0.1;
const WEIGHT_MAX = 2.0;

/** Per-correction nudge applied to a *correct* subagent's matched keyword. */
const CORRECT_BOOST = 0.1;

/** Per-correction penalty applied to the *wrong* subagent's matched keyword. */
const WRONG_PENALTY = 0.05;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

/**
 * Return the routing keywords of a subagent that actually appear (case-folded)
 * inside a message. Used to decide which keywords a piece of feedback should
 * nudge.
 */
function matchedKeywords(subagentId: SubagentId, lowerMessage: string): string[] {
  const config = getAllSubagents().find((s) => s.id === subagentId);
  if (!config) return [];
  return config.routingKeywords.filter((kw) =>
    lowerMessage.includes(kw.toLowerCase())
  );
}

// ─── FeedbackStore ───────────────────────────────────────────────────────────

/**
 * In-memory store for user routing corrections.
 *
 * Records are kept newest-last and auto-evicted once we exceed `maxRecords`
 * (default 1000), mirroring the bounded-growth strategy of TraceCollector.
 */
export class FeedbackStore {
  private records: RouterFeedback[] = [];
  private readonly maxRecords: number;

  constructor(maxRecords: number = MAX_FEEDBACK) {
    this.maxRecords = maxRecords;
  }

  /**
   * Record one correction. `correctSubagent` is what the user thinks should
   * have routed; `originalSubagent` is what the router actually picked.
   */
  addFeedback(
    message: string,
    correctSubagent: SubagentId,
    originalSubagent: SubagentId,
  ): RouterFeedback {
    const record: RouterFeedback = {
      message,
      correctSubagent,
      originalSubagent,
      timestamp: Date.now(),
    };
    this.records.push(record);

    // Evict oldest entries to stay within the cap.
    while (this.records.length > this.maxRecords) {
      this.records.shift();
    }
    return record;
  }

  /**
   * Return feedback history, newest first. Pass `limit` to cap the result.
   * A defensive copy is returned so callers cannot mutate internal state.
   *
   * Ordering is by insertion (chronological) order rather than a raw timestamp
   * sort: `addFeedback` always appends with `Date.now()`, so the array is
   * already in non-decreasing time order, and reversing it is deterministic
   * even when multiple records share the same millisecond timestamp.
   */
  getFeedbackHistory(limit?: number): RouterFeedback[] {
    // records are in insertion (chronological) order; newest is last.
    const newestFirst = [...this.records].reverse();
    return typeof limit === 'number' ? newestFirst.slice(0, limit) : newestFirst;
  }

  /**
   * Summary of how often routes were corrected.
   * `rate` = corrected / total (0 when empty).
   */
  getCorrectionRate(): { total: number; corrected: number; rate: number } {
    const total = this.records.length;
    if (total === 0) {
      return { total: 0, corrected: 0, rate: 0 };
    }
    const corrected = this.records.filter(
      (r) => r.correctSubagent !== r.originalSubagent,
    ).length;
    return { total, corrected, rate: corrected / total };
  }

  /** Number of records currently stored. */
  size(): number {
    return this.records.length;
  }

  /** Drop all feedback (useful for tests / admin reset). */
  clear(): void {
    this.records = [];
  }
}

// ─── KeywordWeightAdjuster ───────────────────────────────────────────────────

/**
 * Maintains a per-(subagent, keyword) weight multiplier derived from the
 * FeedbackStore.
 *
 * The weight map is rebuilt from scratch (idempotent) whenever the underlying
 * feedback changes. For every correction (correctSubagent != originalSubagent):
 *   - keywords of the *correct* subagent that matched the message: +CORRECT_BOOST
 *   - keywords of the *wrong*  subagent that matched the message: -WRONG_PENALTY
 * Each resulting weight is clamped to [WEIGHT_MIN, WEIGHT_MAX].
 */
export class KeywordWeightAdjuster {
  private readonly store: FeedbackStore;
  /** subagentId -> keyword -> WeightAdjustment */
  private weights = new Map<SubagentId, Map<string, WeightAdjustment>>();
  private dirty = true;

  constructor(store: FeedbackStore) {
    this.store = store;
  }

  /** Rebuild the full weight map from the feedback history. Idempotent. */
  recompute(): void {
    const history = this.store.getFeedbackHistory();
    const map = new Map<SubagentId, Map<string, WeightAdjustment>>();

    for (const fb of history) {
      // Only corrections carry a learning signal.
      if (fb.correctSubagent === fb.originalSubagent) continue;

      const lower = fb.message.toLowerCase();

      // Boost the correct subagent's matched keywords.
      for (const keyword of matchedKeywords(fb.correctSubagent, lower)) {
        this.applyDelta(map, fb.correctSubagent, keyword, CORRECT_BOOST);
      }

      // Penalize the wrong (original) subagent's matched keywords.
      for (const keyword of matchedKeywords(fb.originalSubagent, lower)) {
        this.applyDelta(map, fb.originalSubagent, keyword, -WRONG_PENALTY);
      }
    }

    this.weights = map;
    this.dirty = false;
  }

  /** Apply a single delta to a (subagent, keyword) entry, clamping the result. */
  private applyDelta(
    map: Map<SubagentId, Map<string, WeightAdjustment>>,
    subagentId: SubagentId,
    keyword: string,
    delta: number,
  ): void {
    let kwMap = map.get(subagentId);
    if (!kwMap) {
      kwMap = new Map();
      map.set(subagentId, kwMap);
    }

    const existing = kwMap.get(keyword);
    const baseWeight = existing ? existing.weight : DEFAULT_WEIGHT;
    const adjusted = clamp(baseWeight + delta, WEIGHT_MIN, WEIGHT_MAX);

    kwMap.set(keyword, {
      subagentId,
      keyword,
      weight: Math.round(adjusted * 1000) / 1000,
      adjustmentCount: (existing?.adjustmentCount ?? 0) + 1,
    });
  }

  /**
   * Get the learned multiplier for a (subagent, keyword) pair.
   * Returns DEFAULT_WEIGHT (1.0) when there is no learning signal yet.
   * Lazily recomputes if the underlying feedback has changed.
   */
  getAdjustedWeight(subagentId: SubagentId, keyword: string): number {
    if (this.dirty) this.recompute();
    const kwMap = this.weights.get(subagentId);
    if (!kwMap) return DEFAULT_WEIGHT;
    const entry = kwMap.get(keyword);
    return entry ? entry.weight : DEFAULT_WEIGHT;
  }

  /** All non-default weight adjustments across every subagent. */
  getAdjustments(): WeightAdjustment[] {
    if (this.dirty) this.recompute();
    const result: WeightAdjustment[] = [];
    for (const kwMap of this.weights.values()) {
      for (const adj of kwMap.values()) {
        result.push(adj);
      }
    }
    return result;
  }

  /** All weight adjustments scoped to a single subagent. */
  getAdjustmentsForSubagent(subagentId: SubagentId): WeightAdjustment[] {
    if (this.dirty) this.recompute();
    const kwMap = this.weights.get(subagentId);
    if (!kwMap) return [];
    return [...kwMap.values()];
  }

  /** Mark the weight map as stale so the next access triggers a recompute. */
  markDirty(): void {
    this.dirty = true;
  }

  /** Whether there is any learned adjustment at all. */
  hasAdjustments(): boolean {
    if (this.dirty) this.recompute();
    return this.weights.size > 0;
  }

  /**
   * Overlay a persisted weight from the database onto the in-memory map.
   * Called during startup to restore previously learned adjustments.
   *
   * If the in-memory map already has an entry for this (subagent, keyword),
   * the persisted value is only applied if it has a higher adjustment count
   * (i.e., more feedback history). Otherwise the persisted value is inserted
   * directly.
   */
  overlayPersistedWeight(
    subagentId: SubagentId,
    keyword: string,
    weight: number,
    adjustmentCount: number,
  ): void {
    if (this.dirty) this.recompute();

    let kwMap = this.weights.get(subagentId);
    if (!kwMap) {
      kwMap = new Map();
      this.weights.set(subagentId, kwMap);
    }

    const existing = kwMap.get(keyword);
    if (!existing || adjustmentCount > existing.adjustmentCount) {
      kwMap.set(keyword, {
        subagentId,
        keyword,
        weight: clamp(weight, WEIGHT_MIN, WEIGHT_MAX),
        adjustmentCount,
      });
    }
  }
}

// ─── Module-level singletons ─────────────────────────────────────────────────

/**
 * Shared singletons, mirroring the `traceCollector` pattern in trace.ts.
 * One FeedbackStore + one KeywordWeightAdjuster live for the lifetime of the
 * server process.
 */
export const feedbackStore = new FeedbackStore();
export const keywordWeightAdjuster = new KeywordWeightAdjuster(feedbackStore);

// ─── Database persistence ────────────────────────────────────────────────────

/** Whether we've attempted to load persisted weights from the database. */
let persistedLoaded = false;

/**
 * Lazily load weight adjustments from the `router_weights` table into the
 * in-memory adjuster. Called on first access after server start. In demo mode
 * or when the database is unavailable, this is a no-op.
 *
 * This is deliberately non-blocking: if the DB call fails, we continue with
 * empty weights — routing still works via the default keyword matching.
 */
export async function loadPersistedWeights(): Promise<void> {
  if (persistedLoaded) return;
  persistedLoaded = true;

  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') return;

  try {
    const { createServiceClient } = await import('@/lib/supabase-service');
    const supabase = createServiceClient();
    const { data, error } = await supabase
      .from('router_weights')
      .select('subagent_id, keyword, weight, adjustment_count');

    if (error || !data) return;

    // Seed the in-memory adjuster with persisted weights via a private
    // method on the adjuster. We use the public recompute() to rebuild
    // from feedback, then overlay persisted weights on top.
    for (const row of data) {
      keywordWeightAdjuster.overlayPersistedWeight(
        row.subagent_id as SubagentId,
        row.keyword as string,
        row.weight as number,
        row.adjustment_count as number,
      );
    }
  } catch {
    // Database unavailable — continue with in-memory only.
  }
}

/**
 * Asynchronously persist the current weight adjustments to the database.
 * Called after each feedback submission. Non-blocking: errors are swallowed
 * so the chat flow is never interrupted by a DB write failure.
 *
 * @param userId - The user who submitted the feedback (null for anonymous/demo)
 */
async function persistWeightsToDB(userId: string | null): Promise<void> {
  if (process.env.NEXT_PUBLIC_DEMO_MODE === 'true') return;

  try {
    const { createServiceClient } = await import('@/lib/supabase-service');
    const supabase = createServiceClient();
    const adjustments = keywordWeightAdjuster.getAdjustments();

    // Upsert each adjustment — the table has a unique constraint on
    // (user_id, subagent_id, keyword).
    const rows = adjustments.map((adj) => ({
      user_id: userId,
      subagent_id: adj.subagentId,
      keyword: adj.keyword,
      weight: adj.weight,
      adjustment_count: adj.adjustmentCount,
      updated_at: new Date().toISOString(),
    }));

    if (rows.length === 0) return;

    const { error } = await supabase
      .from('router_weights')
      .upsert(rows, { onConflict: 'user_id,subagent_id,keyword' });

    if (error) {
      // Silently log — don't break the chat flow
      console.warn('[router-learning] Failed to persist weights:', error.message);
    }
  } catch {
    // Database unavailable — weights remain in-memory only.
  }
}

/**
 * Convenience: record a correction and immediately refresh the weight map.
 *
 * Returns the stored feedback record. This is the single entry point the API
 * and UI should use to submit corrections — it keeps the store and adjuster in
 * sync so a subsequent `routeMessageWithLearning()` sees the new signal.
 *
 * @param userId - Optional user ID for database persistence (null in demo mode)
 */
export function submitFeedback(
  message: string,
  correctSubagent: SubagentId,
  originalSubagent: SubagentId,
  userId?: string | null,
): RouterFeedback {
  const record = feedbackStore.addFeedback(
    message,
    correctSubagent,
    originalSubagent,
  );
  // New feedback invalidates the cached weight map.
  keywordWeightAdjuster.recompute();

  // Asynchronously persist to database — fire and forget, non-blocking.
  void persistWeightsToDB(userId ?? null);

  return record;
}

/**
 * Aggregate snapshot for the GET /api/router-feedback endpoint and the trace UI.
 * Bundles correction stats, all weight adjustments and recent feedback in one
 * response so the dashboard can render without multiple round-trips.
 */
export interface RouterLearningStats {
  feedbackCount: number;
  correctionRate: { total: number; corrected: number; rate: number };
  adjustmentCount: number;
  adjustments: WeightAdjustment[];
  recentFeedback: RouterFeedback[];
}

export function getRouterLearningStats(recentLimit = 50): RouterLearningStats {
  return {
    feedbackCount: feedbackStore.size(),
    correctionRate: feedbackStore.getCorrectionRate(),
    adjustmentCount: keywordWeightAdjuster.getAdjustments().length,
    adjustments: keywordWeightAdjuster.getAdjustments(),
    recentFeedback: feedbackStore.getFeedbackHistory(recentLimit),
  };
}
