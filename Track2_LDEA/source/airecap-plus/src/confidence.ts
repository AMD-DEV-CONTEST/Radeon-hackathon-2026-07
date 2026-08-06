import type {
  ClampReason,
  EvidenceLink,
  OutcomeCandidate,
  OutcomeStatus,
  OutcomeType,
} from "./types.js";
import type { AggregatorConstants } from "./types.js";

function clamp01(n: number): number {
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

function maxConf(links: EvidenceLink[], pred: (l: EvidenceLink) => boolean): number {
  let m = 0;
  for (const l of links) {
    if (pred(l) && l.confidence > m) m = l.confidence;
  }
  return m;
}

function hoursBetween(fromIso: string, toIso: string): number {
  const a = Date.parse(fromIso);
  const b = Date.parse(toIso);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.max(0, (b - a) / 3_600_000);
}

/** §3.2 formula → confidence_raw (0..1 bound only). */
export function computeConfidenceRaw(
  o: OutcomeCandidate,
  nowIso: string,
  constants: AggregatorConstants,
): number {
  const supports = o.evidence_links.filter(
    (l) => l.relation === "supports" || l.relation === "defines" || l.relation === "verifies",
  );
  const refutes = [
    ...o.counter_evidence,
    ...o.evidence_links.filter((l) => l.relation === "refutes"),
  ];

  // S_claim: any claim-like supports from user/agent is encoded as defines/supports with note or just presence of defines
  // We treat method∈{structured,user,focus,time_scope,llm} defines/supports from claim events as claim signal
  // Approximation: defines relation counts as claim; also any supports with method user
  const S_claim =
    supports.some((l) => l.relation === "defines") ||
    supports.some((l) => l.method === "user")
      ? 1
      : 0;

  const S_struct = maxConf(supports, (l) => l.method === "structured");
  const S_focus = maxConf(supports, (l) => l.method === "focus");
  const S_scope = maxConf(supports, (l) => l.method === "time_scope");
  const S_llm = maxConf(supports, (l) => l.method === "llm");
  const S_user = maxConf(supports, (l) => l.method === "user");
  const R_refute = maxConf(refutes, () => true);
  const V_closed = o.status === "verified" ? 1 : 0;
  const nonLlm = supports.filter((l) => l.method !== "llm").length;
  const N_support = Math.min(1, nonLlm / 3);
  const age_hours = hoursBetween(o.updated_at, nowIso);
  const T_fresh = Math.exp(-age_hours / constants.tau_hours);

  let base =
    0.1 +
    0.15 * S_claim +
    0.3 * S_struct +
    0.25 * S_focus +
    0.15 * S_scope +
    0.05 * S_llm +
    0.2 * S_user +
    0.1 * N_support;

  if (V_closed) base += 0.25;
  base = base * (1 - 0.8 * R_refute);

  if (o.status === "claimed") {
    base = base * (0.7 + 0.3 * T_fresh);
  }

  return clamp01(base);
}

/** §3.3 status clamp + feature cap → display confidence + reason. */
export function applyStatusClamp(
  status: OutcomeStatus,
  type: OutcomeType,
  raw: number,
  constants: AggregatorConstants,
  opts?: { r_refute?: number },
): { confidence: number; clamp_reason: ClampReason } {
  let confidence = raw;
  let clamp_reason: ClampReason = "none";
  const rRefute = opts?.r_refute ?? 0;

  switch (status) {
    case "claimed": {
      if (confidence > 0.45) {
        confidence = 0.45;
        clamp_reason = "ceiling_claimed";
      } else if (confidence < 0.05) {
        confidence = 0.05;
        // floor is soft default for empty; keep none if we only floored from near-zero creation
        if (raw < 0.05) clamp_reason = "none";
      }
      break;
    }
    case "evidenced": {
      if (confidence < 0.3 && rRefute <= 0) {
        confidence = 0.3;
        clamp_reason = "floor_evidenced";
      } else if (confidence > 0.75) {
        confidence = 0.75;
        clamp_reason = "ceiling_evidenced";
      }
      break;
    }
    case "verified": {
      if (confidence < 0.7) {
        confidence = 0.7;
        clamp_reason = "floor_verified";
      }
      if (
        type === "feature" &&
        confidence > constants.C_feat_verified_cap
      ) {
        confidence = constants.C_feat_verified_cap;
        clamp_reason = "feat_verified_cap";
      }
      break;
    }
    case "contradicted": {
      if (confidence > 0.4) {
        confidence = 0.4;
        clamp_reason = "ceiling_contradicted";
      }
      break;
    }
    case "abandoned":
    case "superseded":
      // freeze: leave as-is
      break;
  }

  confidence = clamp01(confidence);
  if (clamp_reason === "none" && Math.abs(confidence - raw) < 1e-12) {
    return { confidence: raw, clamp_reason: "none" };
  }
  return { confidence, clamp_reason };
}

export function recalcConfidence(
  o: OutcomeCandidate,
  nowIso: string,
  constants: AggregatorConstants,
): void {
  const raw = computeConfidenceRaw(o, nowIso, constants);
  const refutes = [
    ...o.counter_evidence,
    ...o.evidence_links.filter((l) => l.relation === "refutes"),
  ];
  const r_refute = maxConf(refutes, () => true);
  const { confidence, clamp_reason } = applyStatusClamp(
    o.status,
    o.type,
    raw,
    constants,
    { r_refute },
  );
  o.confidence_raw = raw;
  o.confidence = confidence;
  o.clamp_reason = clamp_reason;
}
