// CLAUDE LANE — IDE panel ↔ command bindings.
// Locked under: locks/sentinel/FRONTEND_PANEL_COMMAND_WIRING_LOCK_001.json
//
// Single source of truth mapping each visible repair-panel to the
// Tauri command(s) it is expected to call. The Python audit pins this
// table against each panel's TSX source so the wiring cannot drift
// silently. Closed set, alphabetized by panel name.

import { IdeRepairCommand } from "./ide-repair-api";

export const FRONTEND_PANEL_COMMAND_WIRING_STATUS_TOKENS = [
  "FRONTEND_PANEL_COMMAND_WIRING_READY",
  "FRONTEND_DRY_RUN_DEFAULT_CONFIRMED",
  "FRONTEND_LIVE_OPT_IN_REQUIRED",
  "FRONTEND_SOURCE_MUTATION_BLOCKED",
] as const;

export interface PanelBinding {
  panel: string;
  // Commands the panel must call. The audit checks each command name
  // appears as a literal string somewhere in the panel TSX source.
  commands: readonly IdeRepairCommand[];
  // Default mode the panel must operate in.
  defaultMode: "DRY_RUN" | "OPT_IN_REQUIRED" | "READ_ONLY" | "FIXTURE_ONLY";
  // Hard rule: this panel must never authorize source mutation.
  sourceMutation: "BLOCKED";
}

export const PANEL_COMMAND_BINDINGS: readonly PanelBinding[] = [
  {
    panel: "DiagnoseAndPatchPlanPanel",
    commands: ["diagnose_dry_run", "diagnose_live_opt_in", "generate_patch_plan"],
    defaultMode: "DRY_RUN",
    sourceMutation: "BLOCKED",
  },
  {
    panel: "EvidenceViewerPanel",
    commands: ["get_repair_flow_state"],
    defaultMode: "READ_ONLY",
    sourceMutation: "BLOCKED",
  },
  {
    panel: "HumanApprovalPanel",
    commands: ["get_human_approval_packet"],
    defaultMode: "FIXTURE_ONLY",
    sourceMutation: "BLOCKED",
  },
  {
    panel: "ModelRoutePanel",
    commands: ["get_model_route_status"],
    defaultMode: "READ_ONLY",
    sourceMutation: "BLOCKED",
  },
  {
    panel: "SourceApplyDryRunPanel",
    commands: ["source_apply_dry_run"],
    defaultMode: "DRY_RUN",
    sourceMutation: "BLOCKED",
  },
  {
    panel: "TempVerifyPanel",
    commands: ["verify_temp_patch"],
    defaultMode: "FIXTURE_ONLY",
    sourceMutation: "BLOCKED",
  },
  {
    panel: "WorkspaceStatusPanel",
    commands: ["get_workspace_status"],
    defaultMode: "READ_ONLY",
    sourceMutation: "BLOCKED",
  },
] as const;
