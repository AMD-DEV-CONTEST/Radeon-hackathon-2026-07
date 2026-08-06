import type { ClaimKind, Event, OutcomeType } from "../types.js";
import { makeEvent } from "./ids.js";

export interface ClaimIngestOptions {
  sessionId: string;
  text: string;
  claimKind?: ClaimKind;
  typeHint?: OutcomeType;
  titleHint?: string;
  outcomeId?: string;
  goalId?: string;
  scopePaths?: string[];
  actor?: "user" | "agent";
  ts?: string;
  eventId?: string;
}

const TYPE_SET = new Set<OutcomeType>([
  "feature",
  "bugfix",
  "problem",
  "decision",
  "spike",
  "refactor",
  "chore",
  "docs",
  "investigation",
]);

const KIND_SET = new Set<ClaimKind>([
  "completed",
  "fixed",
  "implemented",
  "works_now",
  "progress",
  "other",
]);

export function parseOutcomeType(s: string | undefined): OutcomeType | undefined {
  if (!s) return undefined;
  const v = s.trim().toLowerCase() as OutcomeType;
  return TYPE_SET.has(v) ? v : undefined;
}

export function parseClaimKind(s: string | undefined): ClaimKind | undefined {
  if (!s) return undefined;
  const v = s.trim().toLowerCase() as ClaimKind;
  return KIND_SET.has(v) ? v : undefined;
}

/** Infer claim_kind / type from free text when flags omitted. */
export function inferClaimHints(text: string): {
  claim_kind: ClaimKind;
  type_hint?: OutcomeType;
} {
  const t = text.toLowerCase();
  if (/fix|bug|npe|crash|回归|修复|修好/.test(t)) {
    return { claim_kind: "fixed", type_hint: "bugfix" };
  }
  if (/implement|add\b|feature|新增|实现/.test(t)) {
    return { claim_kind: "implemented", type_hint: "feature" };
  }
  if (/refactor|重构/.test(t)) {
    return { claim_kind: "progress", type_hint: "refactor" };
  }
  if (/done|完成|已完成|works now|ship/.test(t)) {
    return { claim_kind: "completed" };
  }
  return { claim_kind: "progress" };
}

export function ingestClaim(opts: ClaimIngestOptions): Event {
  const inferred = inferClaimHints(opts.text);
  const claim_kind = opts.claimKind ?? inferred.claim_kind;
  const type_hint = opts.typeHint ?? inferred.type_hint;
  return makeEvent({
    id: opts.eventId,
    ts: opts.ts,
    session_id: opts.sessionId,
    actor: opts.actor ?? "user",
    kind: "claim_made",
    payload: {
      text: opts.text,
      claim_kind,
      type_hint,
      title_hint: opts.titleHint,
      outcome_id: opts.outcomeId,
      goal_id: opts.goalId,
      scope_hint: opts.scopePaths?.length
        ? { paths: opts.scopePaths }
        : undefined,
    },
  });
}
