import { bindEvent, unionScope } from "./bind.js";
import { recalcConfidence } from "./confidence.js";
import { DEFAULT_CONSTANTS } from "./constants.js";
import {
  applySessionEndSweep,
  applyTransition,
  makeLink,
  pushLink,
} from "./transition.js";
import type {
  AggregatorConstants,
  Event,
  Goal,
  OutcomeCandidate,
  OutcomeType,
  SessionStore,
} from "./types.js";
import { RULES_VER, SCHEMA_VERSION, emptyScope } from "./types.js";
import {
  jaccard,
  titleFromClaim,
  titleSimilarity,
  touchSummaryBlob,
  typeFromClaimHints,
  typesCompatible,
} from "./util.js";

export interface AggregatorOptions {
  constants?: Partial<AggregatorConstants>;
  /** Deterministic id factory for tests. */
  idFactory?: () => string;
}

let seq = 0;
function defaultId(): string {
  seq += 1;
  return `gen_${seq.toString(36)}`;
}

export function resetIdSeq(): void {
  seq = 0;
}

export function createStore(
  sessionId: string,
  opts?: AggregatorOptions,
): SessionStore {
  const constants: AggregatorConstants = {
    ...DEFAULT_CONSTANTS,
    ...opts?.constants,
    r_c3_enabled: false,
    online_merge_rm1: true,
  };
  return {
    schema_version: SCHEMA_VERSION,
    session_id: sessionId,
    aggregator_version: RULES_VER,
    status: "open",
    updated_at: new Date(0).toISOString(),
    goals: [],
    outcomes: [],
    orphan_event_ids: [],
    counters: { events_seen: 0, high_signal_seen: 0 },
    constants,
    _events: [],
  };
}

function nextId(opts?: AggregatorOptions): string {
  return opts?.idFactory?.() ?? defaultId();
}

function setFocus(store: SessionStore, id: string | undefined): void {
  store.focus_outcome_id = id;
}

function clearFocusIfTerminal(store: SessionStore, o: OutcomeCandidate): void {
  if (
    store.focus_outcome_id === o.id &&
    (o.status === "abandoned" || o.status === "superseded")
  ) {
    setFocus(store, undefined);
  }
}

function attachGoalOutcome(store: SessionStore, goalId: string | undefined, oid: string): void {
  if (!goalId) return;
  const g = store.goals.find((x) => x.id === goalId);
  if (g && !g.outcome_ids.includes(oid)) g.outcome_ids.push(oid);
}

function createOutcome(
  store: SessionStore,
  e: Event,
  opts: {
    type: OutcomeType;
    title: string;
    goal_id?: string;
    status?: OutcomeCandidate["status"];
    conf?: number;
  },
  aggOpts?: AggregatorOptions,
): OutcomeCandidate {
  const id = nextId(aggOpts);
  const o: OutcomeCandidate = {
    schema_version: SCHEMA_VERSION,
    id,
    session_id: store.session_id,
    goal_id: opts.goal_id ?? store.active_goal_id,
    type: opts.type,
    title: opts.title,
    status: opts.status ?? "claimed",
    confidence: opts.conf ?? store.constants.C_claim,
    confidence_raw: opts.conf ?? store.constants.C_claim,
    clamp_reason: "none",
    evidence_links: [],
    counter_evidence: [],
    scope: emptyScope(),
    started_at: e.ts,
    updated_at: e.ts,
    merge_of: [],
    aggregator_version: RULES_VER,
    summary_blob: "",
    tags: [],
    once_verified: false,
    verification_anchors: [],
  };
  touchSummaryBlob(o);
  store.outcomes.push(o);
  attachGoalOutcome(store, o.goal_id, o.id);
  return o;
}

function handleGoalSet(
  store: SessionStore,
  e: Event & { kind: "goal_set" },
  aggOpts?: AggregatorOptions,
): void {
  const p = e.payload;
  const id = p.goal_id ?? nextId(aggOpts);
  if (p.supersedes_goal_id) {
    const old = store.goals.find((g) => g.id === p.supersedes_goal_id);
    if (old && old.status === "open") {
      old.status = "superseded";
      old.updated_at = e.ts;
      // R-AB1 soft: abandon open outcomes of old goal when direction changes
      for (const oid of old.outcome_ids) {
        const o = store.outcomes.find((x) => x.id === oid);
        if (o && (o.status === "claimed" || o.status === "evidenced")) {
          o.status = "abandoned";
          o.terminal_reason = "user_abandoned";
          o.updated_at = e.ts;
          touchSummaryBlob(o);
          clearFocusIfTerminal(store, o);
        }
      }
    }
  }
  const goal: Goal = {
    schema_version: SCHEMA_VERSION,
    id,
    session_id: store.session_id,
    stable_key: p.stable_key,
    statement: p.statement,
    success_criteria: p.success_criteria ?? [],
    non_goals: p.non_goals ?? [],
    status: "open",
    outcome_ids: [],
    supersedes: p.supersedes_goal_id,
    source_event_id: e.id,
    created_at: e.ts,
    updated_at: e.ts,
  };
  store.goals.push(goal);
  store.active_goal_id = id;
}

function handleClaimCreate(
  store: SessionStore,
  e: Event & { kind: "claim_made" },
  aggOpts?: AggregatorOptions,
): OutcomeCandidate {
  const p = e.payload;
  const type = typeFromClaimHints(p.claim_kind, p.type_hint);
  const title = titleFromClaim(p.text, p.title_hint);
  const o = createOutcome(
    store,
    e,
    {
      type,
      title,
      goal_id: p.goal_id ?? store.active_goal_id,
      status: "claimed",
      conf: store.constants.C_claim,
    },
    aggOpts,
  );
  if (p.scope_hint) o.scope = emptyScope(p.scope_hint);
  pushLink(o, {
    event_id: e.id,
    relation: "defines",
    method: p.outcome_id ? "structured" : "focus",
    confidence: p.outcome_id ? 0.98 : store.constants.C_focus_bind,
  });
  o.scope = unionScope(o.scope, e);
  recalcConfidence(o, e.ts, store.constants);
  touchSummaryBlob(o);
  setFocus(store, o.id);
  return o;
}

function handleDecisionCreate(
  store: SessionStore,
  e: Event & { kind: "decision_made" },
  aggOpts?: AggregatorOptions,
): OutcomeCandidate {
  const p = e.payload;
  const o = createOutcome(
    store,
    e,
    {
      type: "decision",
      title: titleFromClaim(p.decision, undefined, 200),
      goal_id: p.goal_id ?? store.active_goal_id,
      status: "claimed",
    },
    aggOpts,
  );
  pushLink(o, {
    event_id: e.id,
    relation: "defines",
    method: "focus",
    confidence: store.constants.C_focus_bind,
  });
  if (p.conclusion) {
    o.status = "evidenced"; // R-V6-ish on create with conclusion
  }
  recalcConfidence(o, e.ts, store.constants);
  touchSummaryBlob(o);
  setFocus(store, o.id);
  return o;
}

/** Online merge R-M1 after scope updates. */
function maybeOnlineMerge(store: SessionStore, touchedId: string, now: string): void {
  if (!store.constants.online_merge_rm1) return;
  const a = store.outcomes.find((o) => o.id === touchedId);
  if (!a) return;
  if (a.status === "superseded" || a.status === "abandoned") return;

  for (const b of store.outcomes) {
    if (b.id === a.id) continue;
    if (b.status === "superseded" || b.status === "abandoned") continue;
    // R-M3: verified + claimed no auto merge
    if (
      (a.status === "verified" && b.status !== "verified") ||
      (b.status === "verified" && a.status !== "verified")
    ) {
      continue;
    }
    if (a.goal_id !== b.goal_id && a.goal_id && b.goal_id) continue;
    if (!typesCompatible(a.type, b.type)) continue; // R-M4
    if (a.title_locked && b.title_locked && a.title !== b.title) continue;

    const pathJ = jaccard(a.scope.paths, b.scope.paths);
    if (pathJ < 0.7) continue;
    const timeProx =
      Math.abs(Date.parse(a.updated_at) - Date.parse(b.updated_at)) <
      2 * 3_600_000
        ? 1
        : 0.3;
    const tSim = titleSimilarity(a.title, b.title);
    const sim = 0.6 * pathJ + 0.2 * timeProx + 0.2 * tSim;
    if (sim < store.constants.T_merge_sim) continue;

    // merge b into a (survivor = a if a newer or verified preference)
    const survivor =
      a.status === "verified"
        ? a
        : b.status === "verified"
          ? b
          : Date.parse(a.updated_at) >= Date.parse(b.updated_at)
            ? a
            : b;
    const victim = survivor === a ? b : a;
    mergeInto(store, survivor, victim, now);
    return;
  }
}

function mergeInto(
  store: SessionStore,
  survivor: OutcomeCandidate,
  victim: OutcomeCandidate,
  now: string,
): void {
  victim.status = "superseded";
  victim.superseded_by = survivor.id;
  victim.terminal_reason = "merged";
  victim.updated_at = now;
  survivor.merge_of = [...new Set([...survivor.merge_of, victim.id, ...victim.merge_of])];
  // evidence union
  for (const l of victim.evidence_links) pushLink(survivor, l);
  for (const l of victim.counter_evidence) {
    if (!survivor.counter_evidence.some((x) => x.event_id === l.event_id)) {
      survivor.counter_evidence.push(l);
    }
  }
  survivor.scope = {
    paths: [...new Set([...survivor.scope.paths, ...victim.scope.paths])],
    symbols: [...new Set([...survivor.scope.symbols, ...victim.scope.symbols])],
    services: [...new Set([...survivor.scope.services, ...victim.scope.services])],
    commands: [...new Set([...survivor.scope.commands, ...victim.scope.commands])],
  };
  const victimWasVerified = victim.once_verified === true || !!victim.verified_at;
  if (victim.once_verified) survivor.once_verified = true;

  // verified inherit if survivor keeps anchors (§5.3)
  if (victim.verification_anchors.length && survivor.status !== "contradicted") {
    for (const a of victim.verification_anchors) {
      if (!survivor.verification_anchors.some((x) => x.key === a.key)) {
        survivor.verification_anchors.push(a);
      }
    }
    if (
      victimWasVerified &&
      survivor.verification_anchors.length > 0 &&
      survivor.status !== "verified" &&
      survivor.status !== "claimed"
    ) {
      survivor.status = "verified";
      survivor.verified_at = victim.verified_at ?? now;
      survivor.once_verified = true;
    }
  }
  survivor.updated_at = now;
  recalcConfidence(survivor, now, store.constants);
  touchSummaryBlob(survivor);
  touchSummaryBlob(victim);
  if (store.focus_outcome_id === victim.id) setFocus(store, survivor.id);
  clearFocusIfTerminal(store, victim);
}

function handleOutcomeUpsert(
  store: SessionStore,
  e: Event & { kind: "outcome_upsert" },
): void {
  const p = e.payload;
  if (p.clear_focus && !p.focus_outcome_id) setFocus(store, undefined);
  if (p.focus_outcome_id) setFocus(store, p.focus_outcome_id);

  if (p.op === "patch" && p.outcome_id) {
    const o = store.outcomes.find((x) => x.id === p.outcome_id);
    if (!o || !p.patch) return;
    // LLM cannot set verified
    if (p.source === "llm" && p.patch.status === "verified") {
      delete p.patch.status;
    }
    Object.assign(o, p.patch);
    if (p.evidence_link) pushLink(o, p.evidence_link);
    o.updated_at = e.ts;
    recalcConfidence(o, e.ts, store.constants);
    touchSummaryBlob(o);
    clearFocusIfTerminal(store, o);
  }

  if (p.op === "session_end_sweep") {
    // already handled by session_end; allow patch markers only
  }
}

/**
 * Process one L0 event into the session store (hot path).
 * Mutates store; appends to store._events.
 */
export function onEvent(
  store: SessionStore,
  e: Event,
  aggOpts?: AggregatorOptions,
): SessionStore {
  if (store.status === "ended" && e.kind !== "outcome_upsert") {
    // ignore late events except upsert audit
    return store;
  }

  if (!store.started_at) store.started_at = e.ts;
  store.counters.events_seen += 1;
  store.counters.last_event_id = e.id;
  store.updated_at = e.ts;
  store._events = store._events ?? [];
  store._events.push(e);

  if (e.signal !== "high") return store;
  store.counters.high_signal_seen += 1;

  // --- goal_set ---
  if (e.kind === "goal_set") {
    handleGoalSet(store, e, aggOpts);
    return store;
  }

  // --- session_end ---
  if (e.kind === "session_end") {
    applySessionEndSweep(store, e);
    // orphan cold-path obligation is external (LLM); we keep orphan_event_ids
    return store;
  }

  // --- outcome_upsert ---
  if (e.kind === "outcome_upsert") {
    handleOutcomeUpsert(store, e);
    return store;
  }

  // --- claim_made ---
  if (e.kind === "claim_made") {
    if (e.payload.outcome_id) {
      const hits = bindEvent(store, e);
      if (hits.length) {
        for (const hit of hits) {
          const o = store.outcomes.find((x) => x.id === hit.outcome_id);
          if (!o) continue;
          applyTransition(store, o, e, hit);
          setFocus(store, o.id);
        }
        return store;
      }
    }
    // R-C1 create
    handleClaimCreate(store, e, aggOpts);
    return store;
  }

  // --- decision_made ---
  if (e.kind === "decision_made") {
    if (e.payload.outcome_id) {
      const hits = bindEvent(store, e);
      if (hits.length) {
        for (const hit of hits) {
          const o = store.outcomes.find((x) => x.id === hit.outcome_id);
          if (o) applyTransition(store, o, e, hit);
        }
        return store;
      }
    }
    // R-C5
    handleDecisionCreate(store, e, aggOpts);
    return store;
  }

  // --- bindable evidence events ---
  const hits = bindEvent(store, e);
  if (hits.length === 0) {
    if (!store.orphan_event_ids.includes(e.id)) {
      store.orphan_event_ids.push(e.id);
    }
    // R-C3 OFF
    return store;
  }

  // remove from orphan if re-bound
  store.orphan_event_ids = store.orphan_event_ids.filter((id) => id !== e.id);

  for (const hit of hits) {
    const o = store.outcomes.find((x) => x.id === hit.outcome_id);
    if (!o) continue;
    applyTransition(store, o, e, hit);
    maybeOnlineMerge(store, o.id, e.ts);
    clearFocusIfTerminal(store, o);
  }

  return store;
}

/** Replay high-signal stream into a fresh store. */
export function replay(
  sessionId: string,
  events: Event[],
  opts?: AggregatorOptions,
): SessionStore {
  resetIdSeq();
  const store = createStore(sessionId, opts);
  const sorted = [...events].sort(
    (a, b) => Date.parse(a.ts) - Date.parse(b.ts) || a.id.localeCompare(b.id),
  );
  for (const e of sorted) onEvent(store, e, opts);
  return store;
}

/** JSON-serializable store without _events. */
export function toJSONStore(store: SessionStore): Omit<SessionStore, "_events"> {
  const { _events: _, ...rest } = store;
  return structuredClone(rest);
}
