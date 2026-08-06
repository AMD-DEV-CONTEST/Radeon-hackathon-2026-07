import { recalcConfidence } from "./confidence.js";
import type {
  BindHit,
  BindMethod,
  Event,
  EvidenceLink,
  EvidenceRelation,
  OutcomeCandidate,
  SessionStore,
  TestResultPayload,
  VerificationResultPayload,
} from "./types.js";
import { unionScope } from "./bind.js";
import { touchSummaryBlob } from "./util.js";

function pushLink(o: OutcomeCandidate, link: EvidenceLink): void {
  const bucket =
    link.relation === "refutes" ? o.counter_evidence : o.evidence_links;
  // dedupe by event_id+relation
  const exists = bucket.some(
    (l) => l.event_id === link.event_id && l.relation === link.relation,
  );
  if (!exists) bucket.push(link);
}

function makeLink(
  e: Event,
  hit: BindHit,
  relation: EvidenceRelation,
): EvidenceLink {
  return {
    event_id: e.id,
    relation,
    method: hit.method,
    confidence: hit.confidence,
  };
}

/** Non-LLM work evidence for R-AB2. `defines` (the claim itself) does not count. */
function countNonLlmSupports(o: OutcomeCandidate): number {
  return o.evidence_links.filter(
    (l) =>
      l.method !== "llm" &&
      (l.relation === "supports" || l.relation === "verifies"),
  ).length;
}

function hasNonClaimEvidence(o: OutcomeCandidate): boolean {
  return o.evidence_links.some(
    (l) =>
      l.method !== "llm" &&
      (l.relation === "supports" || l.relation === "verifies"),
  );
}

function anchorKeyMatch(a: string, b: string): boolean {
  if (a === b) return true;
  // repro_key "pytest path::test" vs nodeid "path::test"
  if (a.endsWith(b) || b.endsWith(a)) return true;
  const tail = (s: string) => {
    const i = s.lastIndexOf("::");
    return i >= 0 ? s.slice(i + 2) : s;
  };
  return tail(a) === tail(b) && tail(a).length > 0;
}

function priorFailForAnchor(
  store: SessionStore,
  o: OutcomeCandidate,
  key: string,
): Event | undefined {
  const events = store._events ?? [];
  for (const ev of events) {
    if (ev.id === undefined) continue;
    if (ev.kind !== "test_result") continue;
    // must be linked or same session earlier
    const linked = o.evidence_links.some((l) => l.event_id === ev.id);
    if (!linked) continue;
    const p = ev.payload;
    const failed = p.tests.filter((t) => t.status === "fail");
    if (failed.length === 0 && p.suite_status !== "fail") continue;
    if (p.repro_key && anchorKeyMatch(p.repro_key, key)) return ev;
    if (failed.some((t) => anchorKeyMatch(t.name, key))) return ev;
    // suite-level fail with empty tests still counts when keys match-ish
    if (p.suite_status === "fail" && failed.length === 0 && p.repro_key === key) {
      return ev;
    }
  }
  return undefined;
}

function priorPassAnchor(
  _store: SessionStore,
  o: OutcomeCandidate,
  key: string,
): boolean {
  return o.verification_anchors.some((a) => anchorKeyMatch(a.key, key));
}

/** Apply §2 transitions for one bound event→outcome. */
export function applyTransition(
  store: SessionStore,
  o: OutcomeCandidate,
  e: Event,
  hit: BindHit,
): void {
  const now = e.ts;

  // --- claim_made on existing ---
  if (e.kind === "claim_made") {
    pushLink(o, makeLink(e, hit, "supports"));
    // R-X4 soft: negation phrases
    const t = e.payload.text.toLowerCase();
    if (
      /没修好|没好|打回|not fixed|still broken|reopen|doesn't work|does not work/.test(
        t,
      )
    ) {
      pushLink(o, {
        event_id: e.id,
        relation: "refutes",
        method: hit.method,
        confidence: hit.confidence,
      });
      if (o.status === "verified") {
        o.status = "contradicted";
        o.terminal_reason = "user_or_agent_negation";
      }
    }
    o.scope = unionScope(o.scope, e);
    o.updated_at = now;
    recalcConfidence(o, now, store.constants);
    touchSummaryBlob(o);
    return;
  }

  // --- file_change ---
  if (e.kind === "file_change") {
    const isRevert = !!e.payload.is_revert;
    if (isRevert && (o.status === "verified" || o.status === "evidenced")) {
      pushLink(o, makeLink(e, hit, "refutes"));
      o.status = "contradicted";
      o.terminal_reason = "reverted";
      o.verified_at = undefined;
    } else {
      const methodOk =
        hit.method === "structured" ||
        hit.method === "user" ||
        hit.method === "focus" ||
        hit.method === "time_scope";
      const hasDiff =
        e.payload.paths.length > 0 &&
        e.payload.paths.some(
          (p) => (p.plus ?? 0) + (p.minus ?? 0) > 0 || p.change !== "mod",
        );
      // empty diffstat still counts if paths present (R-E1 path set non-empty)
      const pathNonEmpty = e.payload.paths.length > 0;

      if (
        methodOk &&
        pathNonEmpty &&
        (o.status === "claimed" || o.status === "contradicted")
      ) {
        // R-E1 / R-R1
        o.status = "evidenced";
        o.verified_at = undefined;
        o.terminal_reason = undefined;
      }
      pushLink(o, makeLink(e, hit, "supports"));
    }
    o.scope = unionScope(o.scope, e);
    o.updated_at = now;
    recalcConfidence(o, now, store.constants);
    touchSummaryBlob(o);
    return;
  }

  // --- command_result ---
  if (e.kind === "command_result") {
    const cls = e.payload.classification;
    const mutation = cls === "build" || cls === "repro" || cls === "test";
    if (mutation && (o.status === "claimed" || o.status === "contradicted")) {
      o.status = "evidenced"; // R-E2 / R-R1
      o.verified_at = undefined;
      o.terminal_reason = undefined;
    }
    pushLink(o, makeLink(e, hit, "supports"));
    o.scope = unionScope(o.scope, e);
    o.updated_at = now;
    recalcConfidence(o, now, store.constants);
    touchSummaryBlob(o);
    return;
  }

  // --- test_result ---
  if (e.kind === "test_result") {
    handleTestResult(store, o, e, hit);
    return;
  }

  // --- verification_result ---
  if (e.kind === "verification_result") {
    handleVerification(store, o, e, hit);
    return;
  }

  // --- decision_made bound ---
  if (e.kind === "decision_made") {
    pushLink(o, makeLink(e, hit, "supports"));
    if (
      (o.type === "decision" ||
        o.type === "spike" ||
        o.type === "investigation") &&
      (e.payload.conclusion || e.payload.decision)
    ) {
      // R-V6 → evidenced (not verified unless user)
      if (o.status === "claimed") o.status = "evidenced";
    }
    o.updated_at = now;
    recalcConfidence(o, now, store.constants);
    touchSummaryBlob(o);
    return;
  }

  // --- blocker_found ---
  if (e.kind === "blocker_found") {
    pushLink(o, makeLink(e, hit, "supports"));
    // R-X5: lower confidence only via recalc + optional refute weight
    o.updated_at = now;
    recalcConfidence(o, now, store.constants);
    touchSummaryBlob(o);
    return;
  }
}

function handleTestResult(
  store: SessionStore,
  o: OutcomeCandidate,
  e: Event & { kind: "test_result"; payload: TestResultPayload },
  hit: BindHit,
): void {
  const now = e.ts;
  const p = e.payload;

  // R-E3 / R-R1: any bound test → evidenced if claimed/contradicted
  if (o.status === "claimed" || o.status === "contradicted") {
    o.status = "evidenced";
    o.verified_at = undefined;
    o.terminal_reason = undefined;
  }

  const failed = p.tests.filter((t) => t.status === "fail");
  const passed = p.tests.filter((t) => t.status === "pass");

  // R-X2 regression: prior pass anchor now fail
  for (const t of failed) {
    const key = p.repro_key ?? t.name;
    if (
      (o.status === "verified" || o.status === "evidenced") &&
      priorPassAnchor(store, o, key)
    ) {
      pushLink(o, makeLink(e, hit, "refutes"));
      o.status = "contradicted";
      o.terminal_reason = "test_regressed";
      o.verified_at = undefined;
      // strip anchor
      o.verification_anchors = o.verification_anchors.filter(
        (a) => a.key !== key,
      );
    }
  }

  // R-V1 bugfix/problem fail→pass (suite pass, or mixed with a matching pass case)
  if (
    o.status !== "contradicted" &&
    (o.type === "bugfix" || o.type === "problem") &&
    (p.suite_status === "pass" || passed.length > 0)
  ) {
    for (const t of passed) {
      const keys = [t.name];
      if (p.repro_key) keys.unshift(p.repro_key);
      let closed = false;
      for (const key of keys) {
        const prior = priorFailForAnchor(store, o, key);
        if (!prior) continue;
        pushLink(o, makeLink(e, hit, "verifies"));
        o.status = "verified";
        o.verified_at = now;
        o.once_verified = true;
        o.terminal_reason = undefined;
        const anchorKey = p.repro_key ?? t.name;
        if (!o.verification_anchors.some((a) => a.key === anchorKey)) {
          o.verification_anchors.push({
            kind: "test",
            key: anchorKey,
            event_id: e.id,
          });
        }
        closed = true;
        break;
      }
      if (closed) break;
    }
  }

  // R-V4 feature/refactor: associated tests pass
  if (
    o.status !== "contradicted" &&
    o.status !== "verified" &&
    (o.type === "feature" || o.type === "refactor") &&
    p.suite_status === "pass" &&
    passed.length > 0
  ) {
    // need some non-claim evidence (file change ideally)
    if (hasNonClaimEvidence(o) || o.scope.paths.length > 0) {
      pushLink(o, makeLink(e, hit, "verifies"));
      o.status = "verified";
      o.verified_at = now;
      o.once_verified = true;
      const key = p.repro_key ?? passed[0]!.name;
      if (!o.verification_anchors.some((a) => a.key === key)) {
        o.verification_anchors.push({ kind: "test", key, event_id: e.id });
      }
    } else {
      pushLink(o, makeLink(e, hit, "supports"));
    }
  } else if (o.status !== "verified") {
    // default support link if not already verifies
    const hasVerifies = o.evidence_links.some(
      (l) => l.event_id === e.id && l.relation === "verifies",
    );
    if (!hasVerifies) pushLink(o, makeLink(e, hit, "supports"));
  } else {
    // already verified path may still add supports for extra passes
    const hasLink = o.evidence_links.some((l) => l.event_id === e.id);
    if (!hasLink) pushLink(o, makeLink(e, hit, "supports"));
  }

  // weak multi-link R-E4 already covered if sum conf — skip explicit for S

  o.scope = unionScope(o.scope, e);
  o.updated_at = now;
  recalcConfidence(o, now, store.constants);
  touchSummaryBlob(o);
}

function handleVerification(
  store: SessionStore,
  o: OutcomeCandidate,
  e: Event & { kind: "verification_result"; payload: VerificationResultPayload },
  hit: BindHit,
): void {
  const now = e.ts;
  const p = e.payload;
  const methodOk: BindMethod[] = ["structured", "user", "focus"];
  const bindOk = methodOk.includes(hit.method);

  if (p.verdict === "fail") {
    // R-X3
    pushLink(o, makeLink(e, hit, "refutes"));
    if (o.status === "verified" || o.status === "evidenced" || o.status === "claimed") {
      o.status = "contradicted";
      o.terminal_reason = "verification_failed";
      o.verified_at = undefined;
    }
  } else {
    // pass
    // R-V5 user
    if (e.actor === "user" || p.method === "user_accept") {
      if (bindOk || hit.method === "time_scope") {
        pushLink(o, makeLink(e, hit, "verifies"));
        o.status = "verified";
        o.verified_at = now;
        o.once_verified = true;
        o.terminal_reason = undefined;
        o.verification_anchors.push({
          kind: "user_accept",
          key: p.repro_key ?? "user_accept",
          event_id: e.id,
        });
      }
    } else if (bindOk) {
      // R-V2 agent self needs non-claim evidence
      if (p.method === "agent_self" && !hasNonClaimEvidence(o)) {
        // R-VX4: do not verify
        pushLink(o, makeLink(e, hit, "supports"));
      } else {
        pushLink(o, makeLink(e, hit, "verifies"));
        o.status = "verified";
        o.verified_at = now;
        o.once_verified = true;
        o.terminal_reason = undefined;
      }
    } else {
      pushLink(o, makeLink(e, hit, "supports"));
    }
  }

  o.updated_at = now;
  recalcConfidence(o, now, store.constants);
  touchSummaryBlob(o);
}

export function applySessionEndSweep(store: SessionStore, e: Event): void {
  const apply = e.kind === "session_end" ? e.payload.apply_ab2 !== false : true;
  if (!apply) {
    store.focus_outcome_id = undefined;
    store.status = "ended";
    store.ended_at = e.ts;
    store.updated_at = e.ts;
    return;
  }

  for (const o of store.outcomes) {
    if (o.status !== "claimed") continue;
    if (countNonLlmSupports(o) === 0) {
      // R-AB2
      o.status = "abandoned";
      o.terminal_reason = "session_end_unevidenced_claim";
      o.updated_at = e.ts;
      touchSummaryBlob(o);
    } else {
      // R-AB2b
      o.status = "evidenced";
      o.updated_at = e.ts;
      recalcConfidence(o, e.ts, store.constants);
      touchSummaryBlob(o);
    }
  }

  // clear focus on terminal focus
  if (store.focus_outcome_id) {
    const f = store.outcomes.find((x) => x.id === store.focus_outcome_id);
    if (!f || f.status === "abandoned" || f.status === "superseded") {
      store.focus_outcome_id = undefined;
    }
  }
  store.focus_outcome_id = undefined; // session_end always clear
  store.status = "ended";
  store.ended_at = e.ts;
  store.updated_at = e.ts;
}

export { countNonLlmSupports, pushLink, makeLink };
