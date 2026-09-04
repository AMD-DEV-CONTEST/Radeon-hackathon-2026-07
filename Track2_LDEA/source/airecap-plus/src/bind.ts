import { STRUCTURED_BIND_CONF, USER_BIND_CONF } from "./constants.js";
import type {
  BindHit,
  BindMethod,
  Event,
  OutcomeCandidate,
  OutcomeStatus,
  PathChange,
  Scope,
  SessionStore,
} from "./types.js";

const BINDABLE: ReadonlySet<OutcomeStatus> = new Set([
  "claimed",
  "evidenced",
  "verified",
  "contradicted",
]);

function payloadOutcomeId(e: Event): string | undefined {
  const p = e.payload as { outcome_id?: string };
  return p.outcome_id;
}

export function eventPaths(e: Event): string[] {
  if (e.kind === "file_change") {
    return e.payload.paths.map((p) => p.path);
  }
  if (e.kind === "test_result") {
    return e.payload.tests
      .map((t) => t.file)
      .filter((f): f is string => typeof f === "string" && f.length > 0);
  }
  return [];
}

/** Directory/prefix overlap in [0,1]. */
export function pathOverlapScore(a: string[], b: string[]): number {
  if (a.length === 0 || b.length === 0) return 0;
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/^\/+/, "");
  const A = a.map(norm);
  const B = b.map(norm);
  let hits = 0;
  for (const x of A) {
    const ok = B.some(
      (y) => x === y || x.startsWith(y + "/") || y.startsWith(x + "/"),
    );
    if (ok) hits += 1;
  }
  return hits / A.length;
}

function minutesBetween(fromIso: string, toIso: string): number {
  return (Date.parse(toIso) - Date.parse(fromIso)) / 60_000;
}

function hoursBetween(fromIso: string, toIso: string): number {
  return (Date.parse(toIso) - Date.parse(fromIso)) / 3_600_000;
}

function typeFit(e: Event, o: OutcomeCandidate): number {
  if (e.kind === "test_result") {
    if (o.type === "bugfix" || o.type === "problem") return 1;
    if (o.type === "feature" || o.type === "refactor") return 0.7;
    return 0.4;
  }
  if (e.kind === "file_change") {
    const paths = e.payload.paths.map((p: PathChange) => p.path);
    const docsOnly = paths.every(
      (p) =>
        /\.(md|rst|txt)$/i.test(p) ||
        p.includes("/docs/") ||
        p.startsWith("docs/"),
    );
    if (docsOnly && o.type === "docs") return 1;
    if (docsOnly && (o.type === "feature" || o.type === "bugfix")) return 0.2;
    return 0.6;
  }
  return 0.5;
}

function timeScopeScore(
  e: Event,
  o: OutcomeCandidate,
  store: SessionStore,
): number {
  const c = store.constants;
  // time factor: boost if recent claim/define after claim window
  let time_factor = 0.5;
  const lastClaim = [...o.evidence_links]
    .filter((l) => l.relation === "defines")
    .map((l) => store._events?.find((ev) => ev.id === l.event_id))
    .filter((ev): ev is Event => !!ev)
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))[0];

  if (lastClaim) {
    const mins = minutesBetween(lastClaim.ts, e.ts);
    if (mins >= 0 && mins <= c.W_after_min) time_factor = 1;
    else if (mins > c.W_after_min && mins < c.W_after_min * 2) time_factor = 0.6;
    else time_factor = 0.3;
  } else {
    const idle = hoursBetween(o.updated_at, e.ts);
    if (idle > c.W_idle_hours) time_factor = 0.25;
    else time_factor = 0.55;
  }

  const paths = eventPaths(e);
  const overlap = pathOverlapScore(paths, o.scope.paths);
  // If event has no paths, weak overlap credit when outcome has open focus-like activity
  const overlapEff = paths.length === 0 ? 0.35 : overlap;
  const fit = typeFit(e, o);
  return 0.5 * time_factor + 0.4 * overlapEff + 0.1 * fit;
}

function findOutcome(store: SessionStore, id: string): OutcomeCandidate | undefined {
  return store.outcomes.find((o) => o.id === id);
}

function focusHardConflict(e: Event, focus: OutcomeCandidate): boolean {
  const paths = eventPaths(e);
  if (e.kind !== "file_change") return false;
  if (focus.scope.paths.length === 0) return false;
  if (paths.length === 0) return false;
  return pathOverlapScore(paths, focus.scope.paths) === 0;
}

/**
 * Hot-path bind: structured > user > focus > time_scope.
 * Returns 0..n hits (usually 0 or 1). Empty → orphan.
 */
export function bindEvent(store: SessionStore, e: Event): BindHit[] {
  // kinds that don't bind to outcomes
  if (
    e.kind === "goal_set" ||
    e.kind === "session_end" ||
    e.kind === "outcome_upsert"
  ) {
    return [];
  }

  const oid = payloadOutcomeId(e);
  if (oid) {
    const o = findOutcome(store, oid);
    if (o && BINDABLE.has(o.status)) {
      // structured; user actor with explicit id still structured per schema priority
      // (user method is for explicit "this is X" without id — rare in S)
      const method: BindMethod =
        e.actor === "user" && e.kind === "claim_made" ? "user" : "structured";
      const conf = method === "user" ? USER_BIND_CONF : STRUCTURED_BIND_CONF;
      return [{ outcome_id: oid, method, confidence: conf }];
    }
    // invalid id → fall through
  }

  // claim_made without outcome_id is create path, not bind
  if (e.kind === "claim_made") return [];
  if (e.kind === "decision_made" && !oid) return [];

  // focus
  if (store.focus_outcome_id) {
    const focus = findOutcome(store, store.focus_outcome_id);
    if (focus && BINDABLE.has(focus.status)) {
      const strict = store.constants.focus_strict_scope;
      if (!strict || !focusHardConflict(e, focus)) {
        return [
          {
            outcome_id: focus.id,
            method: "focus",
            confidence: store.constants.C_focus_bind,
          },
        ];
      }
    }
  }

  // time_scope
  const cands = store.outcomes.filter((o) => BINDABLE.has(o.status));
  if (cands.length === 0) return [];

  const scored = cands
    .map((o) => ({ o, score: timeScopeScore(e, o, store) }))
    .sort((a, b) => b.score - a.score);

  const top = scored[0];
  if (!top || top.score < store.constants.T_bind_auto) return [];
  const second = scored[1];
  if (second && top.score - second.score < 0.1) return []; // ambiguous

  return [
    {
      outcome_id: top.o.id,
      method: "time_scope",
      confidence: Math.min(1, top.score),
    },
  ];
}

export function unionScope(scope: Scope, e: Event): Scope {
  const next: Scope = {
    paths: [...scope.paths],
    symbols: [...scope.symbols],
    services: [...scope.services],
    commands: [...scope.commands],
  };
  const addPath = (p: string) => {
    const n = p.replace(/\\/g, "/");
    if (n && !next.paths.includes(n)) next.paths.push(n);
  };
  const addCmd = (c: string) => {
    if (c && !next.commands.includes(c)) next.commands.push(c);
  };

  if (e.kind === "file_change") {
    for (const p of e.payload.paths) addPath(p.path);
  } else if (e.kind === "test_result") {
    for (const t of e.payload.tests) {
      if (t.file) addPath(t.file);
    }
    if (e.payload.repro_key) addCmd(e.payload.repro_key);
  } else if (e.kind === "command_result") {
    addCmd(e.payload.cmd_normalized ?? e.payload.cmd);
  } else if (e.kind === "claim_made" && e.payload.scope_hint?.paths) {
    for (const p of e.payload.scope_hint.paths) addPath(p);
  }
  return next;
}
