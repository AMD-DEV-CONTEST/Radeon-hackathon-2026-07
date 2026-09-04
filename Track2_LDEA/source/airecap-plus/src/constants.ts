import type { AggregatorConstants } from "./types.js";

/** Default knobs from outcome-state-machine.md §3.4 / §11 (rules@1.2). */
export const DEFAULT_CONSTANTS: AggregatorConstants = {
  C_claim: 0.2,
  C_orphan_ev: 0.35,
  C_feat_verified_cap: 0.85,
  C_focus_bind: 0.9,
  T_evidence: 0.5,
  T_bind_auto: 0.6,
  T_bind_llm: 0.75,
  T_merge_sim: 0.8,
  tau_hours: 72,
  W_after_min: 30,
  W_idle_hours: 2,
  r_c3_enabled: false,
  online_merge_rm1: true,
  /** S default: loose focus (always allow). M may set true. */
  focus_strict_scope: false,
};

export const STRUCTURED_BIND_CONF = 0.98;
export const USER_BIND_CONF = 0.95;
