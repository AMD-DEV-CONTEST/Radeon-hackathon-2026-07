// CLAUDE LANE — Unified product shell API surface.
// Locked under:
//   locks/sentinel/DETERMINEX_TAURI_UNIFIED_PRODUCT_COMMAND_SURFACE_LOCK_001.json
//
// Thin TypeScript wrapper around the 8 read-only Tauri commands
// added in rung 1 of DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES.
// The wrapper NEVER mutates source, NEVER grants approval, NEVER
// opens training. Every response is treated as a non-authorizing
// snapshot rendered read-only.

export interface UnifiedProductResponse {
  command: string;
  status: string;
  payload: Record<string, unknown>;
  source_mutation_authorized: boolean;
  training_eligible: boolean;
  notes: string[];
}

export const UNIFIED_PRODUCT_COMMANDS = [
  "get_unified_product_navigation_model",
  "get_idea_lab_workflow_state",
  "get_repo_clinic_workflow_state",
  "get_maintenance_bay_workflow_state",
  "get_learning_studio_workflow_state",
  // Rung 7 of DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES: Learning Studio content
  // generation. Takes {mode, context, workspace?} args (unlike the zero-arg view-model
  // snapshots above); every response is still gated through learning_studio_workflow.evaluate()
  // on the backend before it reaches this wrapper, and the wrapper's own
  // source_mutation_authorized / training_eligible refusal still applies.
  "generate_learning_studio_content",
  // Maintenance Bay live scan: composes 5 existing security_gate.py scanners into one
  // read-only advisory result. Explicit opt-in only (not auto-fetched) -- can take
  // several seconds. Never applies an update, never authorizes anything.
  "run_maintenance_bay_scan",
  "get_proof_operator_center_state",
  "get_user_level_teaching_windows",
  "get_unified_splash_demo_spec",
  // DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001 (rung 2).
  // Read-only scoped status of the Codex Idea Lab verified Python CLI demo.
  "get_idea_lab_verified_demo_status",
  // DETERMINEX_REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.
  // Read-only scoped status of the Codex Repo Clinic fixture-repair demo.
  "get_repo_clinic_verified_demo_status",
  // DETERMINEX_REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.
  // Read-only scoped status of the Codex Maintenance Bay dry-run/update demo.
  "get_maintenance_bay_verified_demo_status",
  // DETERMINEX_REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.
  // Read-only scoped status of the Codex Learning Studio teaching splash demo.
  "get_learning_studio_verified_demo_status",
  // DETERMINEX_REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_LOCK_001.
  // Read-only milestone-dashboard view of the Codex Proof / Operator Center.
  // The dashboard DISPLAYS authority; it does not grant authority. Source
  // mutation, approval, proof-execution, training, release, broad claims
  // all remain false. Roadmap items (Cathedral Index, Columbia House,
  // Scale-to-100, Full Cathedral, Windows-first matrix) stay pending/draft.
  "get_proof_operator_center_milestone_dashboard_status",
  // DETERMINEX_REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_LOCK_001.
  // Read-only Universal 100 Matrix Probe Batch 001 status view. The panel
  // DISPLAYS fixture-local probe evidence; it does not grant authority and
  // it does not claim universal/release/production support. Blocked cells
  // remain visible with their exact missing rung.
  "get_universal_100_matrix_probe_batch_status",
  // DETERMINEX_REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_002_BINDING_LOCK_001.
  // Read-only Universal 100 Matrix Probe Batch 002 status view. Same
  // invariants as Batch 001: fixture-local, no release/production claim,
  // no authority grant, blocked cells visible.
  "get_universal_100_matrix_probe_batch_002_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_VISUAL_BINDING_LOCK_001.
  // Read-only Universal 100 Support Map Delta Batch 002 view. Displays
  // the Codex-computed delta layered on top of the base support map.
  // Same invariants: fixture-local, no release/production claim, blocked
  // cells visible, no authority grant.
  "get_universal_100_support_map_delta_batch_002_status",
  // DETERMINEX_REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_003_BINDING_LOCK_001.
  // Read-only Universal 100 Matrix Probe Batch 003 status view (12 probed /
  // 11 promoted / 1 blocked TypeScript adapter / 0 release_supported).
  // Same invariants as Batch 001/002. Blocked TypeScript-Node-CLI cell
  // remains visible with missing rung DETERMINEX_TYPESCRIPT_NODE_CLI_ADAPTER_LOCK_001.
  "get_universal_100_matrix_probe_batch_003_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_003_VISUAL_BINDING_LOCK_001.
  // Read-only Universal 100 Support Map Delta Batch 003 view. Codex-
  // computed delta covering 11 promoted + 1 blocked + 0 release_supported.
  // Same invariants: fixture-local, blocked cells visible, no authority.
  "get_universal_100_support_map_delta_batch_003_status",
  // DETERMINEX_REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_004_BINDING_LOCK_001.
  // Read-only Universal 100 Matrix Probe Batch 004 status view (10 probed /
  // 10 promoted / 0 blocked / 0 release_supported). Unlocked by the new
  // TypeScript Node CLI adapter (DETERMINEX_TYPESCRIPT_NODE_CLI_ADAPTER_LOCK_001
  // — local tsc + ambient declarations, no network/npm/Docker install).
  // Smoke-supported only; not release-supported. Fixture-local caveats.
  "get_universal_100_matrix_probe_batch_004_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_004_VISUAL_BINDING_LOCK_001.
  // Read-only Universal 100 Support Map Delta Batch 004 view (10 promoted /
  // 0 blocked / 0 release_supported). Same invariants: fixture-local,
  // smoke_supported is not release_supported, no authority grant.
  "get_universal_100_support_map_delta_batch_004_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_LOCK_001.
  // Read-only sector state ladder + sector registry (11 sectors, 24
  // lifecycle states, 14 blocker-missing-rung states). No promotion;
  // displays Codex's recorded sector definitions and ladder only.
  "get_universal_100_sector_state_ladder_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_005_BINDING_LOCK_001.
  // Read-only sector gulp Batch 005 (cli_file_data_sector +
  // node_typescript_cli_sector, 12 tagged/classified/routed/promoted,
  // 0 blocked, 12 smoke_supported, 0 release_supported).
  "get_universal_100_sector_gulp_batch_005_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_005_VISUAL_BINDING_LOCK_001.
  // Read-only Support Map Delta Batch 005 (12 promoted / 0 blocked /
  // 0 release_supported / 3 IMPLEMENTED_WITH_CAVEATS + 9 PARTIAL).
  "get_universal_100_support_map_delta_batch_005_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_006_BINDING_LOCK_001.
  // Read-only sector gulp Batch 006 (react_vite_static_app_sector +
  // static_web_sector + python_fastapi_local_api_sector, 18 tagged/
  // classified/routed/promoted, 0 blocked, 18 smoke_supported,
  // 0 release_supported).
  "get_universal_100_sector_gulp_batch_006_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_006_VISUAL_BINDING_LOCK_001.
  // Read-only Support Map Delta Batch 006 (18 promoted / 0 blocked /
  // 0 release_supported / 12 IMPLEMENTED_WITH_CAVEATS + 6 PARTIAL).
  "get_universal_100_support_map_delta_batch_006_status",
  // DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_LOCK_001.
  // Read-only reconciliation 005 absorption record (354 absorbed
  // checkpoint -> 355 reconciled spine). Reconciliation absorbs display
  // evidence; it does not promote capability.
  "get_tandem_post_claude_binding_reconciliation_005_status",
  // DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_LOCK_001.
  // Read-only support-depth ledger (accounting, not promotion).
  // 59 known cells / 34 fixture-local smoke-supported / 7 test /
  // 3 repair / 1 maintain / 1 teach / 0 user-ready / 0 release.
  "get_universal_100_support_depth_ledger_status",
  // DETERMINEX_REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_LOCK_001.
  // Read-only all-sector taxonomy (40 top-level sector families).
  // Routing only — every sector defaults to NOT_CLAIMED / classified.
  "get_universal_100_all_sector_taxonomy_status",
  // DETERMINEX_REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_LOCK_001.
  // Read-only conveyor backlog + depth-promotion planning surface.
  // 75 known cells / 62 depth candidates / 52 packaging candidates /
  // 45 user-ready candidates / 13 blocked / 17 roadmap / 0 forbidden.
  "get_universal_100_conveyor_backlog_and_depth_queue_status",
  // Universal 100 sector-gulp wave Batches 007-010 read-only bindings.
  "get_universal_100_sector_gulp_batch_007_status",
  "get_universal_100_support_map_delta_batch_007_status",
  "get_universal_100_sector_gulp_batch_008_status",
  "get_universal_100_support_map_delta_batch_008_status",
  "get_universal_100_sector_gulp_batch_009_status",
  "get_universal_100_support_map_delta_batch_009_status",
  "get_universal_100_sector_gulp_batch_010_status",
  "get_universal_100_support_map_delta_batch_010_status",
  // DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_LOCK_001.
  // Read-only 40-family scoreboard + execution plan. Routing/accounting,
  // not promotion. 40/40 routed != 40/40 supported.
  "get_universal_100_top_level_sector_completion_campaign_status",
  // DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_007_BINDING_LOCK_001.
  // Read-only reconciliation 007 absorption record (prior Codex 370 ->
  // Claude display 379 -> reconciled spine 380).
  "get_tandem_post_claude_binding_reconciliation_007_status",
  // Universal 100 sector-gulp wave Batches 011-013 read-only bindings.
  "get_universal_100_sector_gulp_batch_011_status",
  "get_universal_100_support_map_delta_batch_011_status",
  "get_universal_100_sector_gulp_batch_012_status",
  "get_universal_100_support_map_delta_batch_012_status",
  "get_universal_100_sector_gulp_batch_013_status",
  "get_universal_100_support_map_delta_batch_013_status",
  // DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_BINDING_LOCK_001.
  // Read-only blocker inventory (10 blockers classified by category,
  // family, sector, local resolvability, safe next rung, forbidden
  // shortcut). Inventory classifies; it does not promote.
  "get_universal_100_top_level_blocker_inventory_status",
  // DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_GAP_CLOSURE_WAVE_001_BINDING_LOCK_001.
  // Read-only wave aggregate (batches 014/015/016 + their deltas + 10
  // blockers attempted, 0 closed, 6 partially closed, 10 remaining).
  "get_universal_100_top_level_sector_gap_closure_wave_001_status",
  // DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_NNN_BINDING_LOCK_001.
  // Read-only gap-closure batches 014/015/016 + their support map
  // deltas. Each batch attempts a cluster of blockers, closes none
  // fully, partially closes some, leaves others routed to operator.
  "get_universal_100_top_level_gap_closure_batch_014_status",
  "get_universal_100_support_map_delta_batch_014_status",
  "get_universal_100_top_level_gap_closure_batch_015_status",
  "get_universal_100_support_map_delta_batch_015_status",
  "get_universal_100_top_level_gap_closure_batch_016_status",
  "get_universal_100_support_map_delta_batch_016_status",
  // DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_BINDING_LOCK_001.
  // Read-only 40-family coverage scoreboard (40/40 routed, 0/40 release-
  // supported, 1/40 user-ready-with-caveats). Coverage = routing.
  "get_universal_100_top_level_sector_coverage_scoreboard_status",
  // DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_LOCK_001.
  // Read-only reconciliation 008 absorption record (prior Codex 387 ->
  // Claude display 395 -> reconciled spine 396, 8 absorbed Claude locks).
  "get_tandem_post_claude_binding_reconciliation_008_status",
  // DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_CANDIDATE_INVENTORY_BINDING_LOCK_001.
  // Read-only depth-promotion candidate inventory (40 candidates each
  // with current depth, easiest next rung, missing rung, local-proof
  // feasibility). Inventory classifies; it does NOT promote.
  "get_universal_100_depth_promotion_candidate_inventory_status",
  // DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_WAVE_001_BINDING_LOCK_001.
  // Read-only wave 001 aggregate (batches 017/018/019 + deltas, 9
  // probed, 8 promoted, 1 blocked, families_with_any_evidence 18 -> 26).
  "get_universal_100_depth_promotion_wave_001_status",
  // DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_NNN_BINDING_LOCK_001.
  // Read-only depth-promotion batches 017/018/019 + support map deltas.
  // 017 = infra-as-code / data-science / ML inference (local/static).
  // 018 = swift_ios / kotlin_android / mobile_cross_platform (no
  // simulator/device claim). 019 = c_cpp / embedded_iot / unknown-novel
  // catch-all (CONCRETE_FIXTURE_REQUIRED blocked).
  "get_universal_100_depth_promotion_batch_017_status",
  "get_universal_100_support_map_delta_batch_017_status",
  "get_universal_100_depth_promotion_batch_018_status",
  "get_universal_100_support_map_delta_batch_018_status",
  "get_universal_100_depth_promotion_batch_019_status",
  "get_universal_100_support_map_delta_batch_019_status",
  // DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_SCOREBOARD_BINDING_LOCK_001.
  // Read-only post-wave scoreboard: 40/40 Level 1, families with any
  // evidence 18 -> 26, depth distribution, release_supported = 0.
  "get_universal_100_depth_promotion_scoreboard_status",
  // DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_009_BINDING_LOCK_001.
  // Read-only reconciliation 009 absorption record (prior Codex 405 ->
  // Claude display 415 -> reconciled spine 416, 10 absorbed Claude locks).
  "get_tandem_post_claude_binding_reconciliation_009_status",
  // DETERMINEX_REACT_PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_BINDING_LOCK_001.
  // Read-only public flagship flow certification (10 flagship journeys,
  // 9 false-claim scanner phrases, 12 proof report fields).
  "get_public_tidal_wave_flagship_flow_certification_status",
  // DETERMINEX_REACT_PUBLIC_PROOF_REPORT_EXPORT_BINDING_LOCK_001.
  // Read-only proof report export contract (25 fields, 5 sample reports,
  // 7 route outcomes, 11 forbidden report claims).
  "get_public_proof_report_export_status",
  // DETERMINEX_REACT_PUBLIC_PROOF_REPORT_SAMPLE_REPORTS_BINDING_LOCK_001.
  // Read-only 5-sample-report panel covering supported / blocked-by-
  // missing-rung / authority-gated / unknown-novel / refused-contained
  // archetypes.
  "get_public_proof_report_sample_reports_status",
  // DETERMINEX_REACT_PUBLIC_FALSE_CLAIM_SCANNER_BINDING_LOCK_001.
  // Read-only false-claim / claim-boundary scanner (combined 20 phrases:
  // 9 flagship-side + 11 export-contract-side). All BLOCKED_OR_FLAGGED.
  "get_public_false_claim_scanner_status",
  // DETERMINEX_REACT_PUBLIC_AUTHORITY_BOUNDARY_BINDING_LOCK_001.
  // Read-only authority-boundary panel. release_supported = 0 / 0,
  // all authority flags remain false, proof_report_export is NOT
  // release readiness, report schema is NOT runtime execution proof.
  "get_public_authority_boundary_status",
  // DETERMINEX_REACT_PUBLIC_UNKNOWN_NOVEL_ROUTE_BINDING_LOCK_001.
  // Read-only unknown_novel_intake_route panel. Routed but NOT_CLAIMED,
  // blocked by CONCRETE_FIXTURE_REQUIRED.
  "get_public_unknown_novel_route_status",
  // DETERMINEX_REACT_PUBLIC_READINESS_SPINE_DASHBOARD_BINDING_LOCK_001.
  // Read-only public readiness spine dashboard (live evidence_index,
  // chain_valid, mutation_detected, validation_errors, release_supported
  // = 0 / 0, universal support not claimed).
  "get_public_readiness_spine_dashboard_status",
  // Direct corpus query surface (2026-07-16): the ONE canonical read-only corpus API
  // (scripts/determinex_corpus_api.py -- ask/maturity_report/timeline) exposed as its
  // own command. Takes {corpus_query, corpus_mode?} args (unlike the zero-arg view-model
  // snapshots above); real per-call computation, not a static snapshot. Never mutates
  // build_knowledge.json, never authorizes anything.
  "query_corpus",
] as const;

export type UnifiedProductCommand = (typeof UNIFIED_PRODUCT_COMMANDS)[number];

// Closed set of status tokens the panels may render.
/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set exactly
 * (tests/ide_frontend/test_unguarded_status_token_sets_lock.py). knip cannot see
 * that, so without this tag it reports the export as unused.
 * @public
 */
export const UNIFIED_PRODUCT_STATUS_TOKENS = [
  "TAURI_COMMAND_OK",
  "TAURI_COMMAND_BLOCKED_UNKNOWN",
  "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
] as const;

function backendMissing(command: UnifiedProductCommand, reason: string): UnifiedProductResponse {
  return {
    command,
    status: "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
    payload: {},
    source_mutation_authorized: false,
    training_eligible: false,
    notes: [reason],
  };
}

// Was checking window.__TAURI__ -- that global is only ever mounted when
// `app.withGlobalTauri: true` is set in tauri.conf.json (a v1-era convenience
// flag this app's config never sets), so it has never been populated in any
// real run. This check was permanently false, meaning the ENTIRE ide-product-
// shell command family (Repo Clinic, Maintenance Bay, Learning Studio,
// Unified Navigation, User-Level Teaching, Proof Operator Center) has always
// hit the immediate backendMissing() fallback in the real app, never the
// actual backend -- the identical bug ide-repair-api.ts's tauriRuntimePresent
// already had fixed (found live 2026-07-19, "repair doesnt work") but this
// sibling file was never brought in line with. The real, always-present
// Tauri v2 IPC marker is window.__TAURI_INTERNALS__, same as lib/api.ts's
// isTauri() and ide-repair-api.ts's corrected check.
export function tauriRuntimePresent(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { __TAURI_INTERNALS__?: { transformCallback?: unknown } };
  return (
    typeof w.__TAURI_INTERNALS__ === "object" &&
    w.__TAURI_INTERNALS__ !== null &&
    typeof w.__TAURI_INTERNALS__.transformCallback === "function"
  );
}

// Hard frontend invariants: panels MUST refuse any backend response
// that claims source_mutation_authorized or training_eligible.
export async function invokeUnifiedProductCommand(
  command: UnifiedProductCommand,
  args: Record<string, unknown> = {}
): Promise<UnifiedProductResponse> {
  if (!tauriRuntimePresent()) {
    return backendMissing(command, "Tauri runtime not present (web preview / test)");
  }
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const res = (await invoke(command, args)) as UnifiedProductResponse;
    if (res.source_mutation_authorized) {
      return {
        ...res,
        source_mutation_authorized: false,
        notes: [...res.notes, "frontend refused source_mutation_authorized=true"],
      };
    }
    if (res.training_eligible) {
      return {
        ...res,
        training_eligible: false,
        notes: [...res.notes, "frontend refused training_eligible=true"],
      };
    }
    return res;
  } catch (e) {
    return backendMissing(command, `invoke threw: ${(e as Error)?.message ?? "unknown"}`);
  }
}

// The five canonical product surfaces. Order is load-bearing for the
// navigation panel — matches the backend's UNIFIED_PRODUCT_SURFACES.
export const UNIFIED_PRODUCT_SURFACES = [
  "idea_lab",
  "repo_clinic",
  "maintenance_bay",
  "learning_studio",
  "proof_operator_center",
] as const;

export type UnifiedProductSurfaceKey = (typeof UNIFIED_PRODUCT_SURFACES)[number];

// Shared 8-class authority vocabulary. Mirrors the locked Python set.
export const SHARED_AUTHORITY_VOCABULARY = [
  "capability_available",
  "evidence_present",
  "request_pending",
  "admission_present",
  "approval_present",
  "execution_authorized",
  "source_mutation_authorized",
  "training_eligible",
] as const;

// Negative-authority caption the unified shell shows everywhere a
// "ready" badge could be misread as "authorized".
export const READY_DOES_NOT_MEAN_AUTHORIZED = "Ready does NOT mean authorized.";
