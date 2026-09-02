// CLAUDE LANE — IDE repair API surface.
// Locked under: locks/sentinel/FRONTEND_REPAIR_PANEL_SHELL_LOCK_001.json
//
// Thin TypeScript wrapper around the Tauri commands declared in
// frontend/src-tauri/src/ide_repair_bridge.rs. The wrapper never
// mutates source state on the frontend side; every command call
// returns the JSON-safe IdeRepairResponse and panels render it
// read-only.

export interface IdeRepairResponse {
  command: string;
  status: string;
  payload: Record<string, unknown>;
  source_mutation_authorized: boolean;
  training_eligible: boolean;
  notes: string[];
}

// Closed set of status tokens the panels may render. Mirrors the
// Rust side. Panels MUST refuse to render any token not in this set.
/**
 * Consumed OUTSIDE the TypeScript import graph: Python lock tests read this array
 * out of the source text and assert the set matches the Rust side exactly. knip
 * cannot see that, so without this tag it reports the export as unused -- and
 * deleting it would break those locks while the type-checker stayed green.
 * @public
 */
export const IDE_REPAIR_STATUS_TOKENS = [
  "TAURI_RUST_COMMAND_BRIDGE_READY",
  "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_NO_TAURI_APP",
  "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
  "TAURI_COMMAND_OK",
  "TAURI_COMMAND_TEMP_ONLY",
  "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
  "TAURI_COMMAND_BLOCKED_NOT_OPTED_IN",
  "TAURI_COMMAND_BLOCKED_NO_MODEL",
  "TAURI_COMMAND_BLOCKED_UNKNOWN",
] as const;

export const IDE_REPAIR_COMMANDS = [
  "open_workspace",
  "get_workspace_status",
  "get_model_route_status",
  "diagnose_dry_run",
  "diagnose_live_opt_in",
  "generate_patch_plan",
  "verify_temp_patch",
  "get_human_approval_packet",
  "source_apply_dry_run",
  "get_repair_flow_state",
  "generate_llm_program_advisory",
] as const;

export type IdeRepairCommand = (typeof IDE_REPAIR_COMMANDS)[number];

// Defensive fallback when Tauri runtime is not present (web preview,
// vitest, etc). Returns a BACKEND_MISSING response rather than
// throwing, so panels degrade gracefully and never silently 200.
function backendMissing(command: IdeRepairCommand, reason: string): IdeRepairResponse {
  return {
    command,
    status: "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
    payload: {},
    source_mutation_authorized: false,
    training_eligible: false,
    notes: [reason],
  };
}

// Probe whether the Tauri runtime is reachable. Used by panel shells
// to pick between "live" and "BLOCKED_NO_TAURI_APP" displays.
//
// Was checking window.__TAURI__ -- that global is only ever mounted when
// `app.withGlobalTauri: true` is set in tauri.conf.json (a v1-era convenience
// flag). This app's tauri.conf.json never sets it, so window.__TAURI__ has
// never been populated in any real run -- this check was permanently false,
// meaning the whole Repair Panel showed BLOCKED_FRONTEND_MISSING/BACKEND_MISSING
// unconditionally, every time, including inside the real packaged app.
// Found live 2026-07-19 (Ryan: "repair doesnt work"). The real, always-present
// Tauri v2 IPC marker is window.__TAURI_INTERNALS__ -- same check lib/api.ts's
// isTauri() already uses correctly everywhere else in this app.
export function tauriRuntimePresent(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { __TAURI_INTERNALS__?: { transformCallback?: unknown } };
  return (
    typeof w.__TAURI_INTERNALS__ === "object" &&
    w.__TAURI_INTERNALS__ !== null &&
    typeof w.__TAURI_INTERNALS__.transformCallback === "function"
  );
}

// Invoke a Tauri command. Wrapped so panels never call window directly.
export async function invokeIdeCommand(
  command: IdeRepairCommand,
  args: Record<string, unknown> = {}
): Promise<IdeRepairResponse> {
  if (!tauriRuntimePresent()) {
    return backendMissing(command, "Tauri runtime not present (web preview / test)");
  }
  try {
    // Lazy import so this module is safe to require in a non-Tauri context.
    const { invoke } = await import("@tauri-apps/api/core");
    const res = (await invoke(command, args)) as IdeRepairResponse;
    // Hard refuse: source mutation must never be authorized.
    if (res.source_mutation_authorized) {
      return {
        ...res,
        status: "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        source_mutation_authorized: false,
        notes: [...res.notes, "frontend refused source_mutation_authorized=true from backend"],
      };
    }
    if (res.training_eligible) {
      return {
        ...res,
        training_eligible: false,
        notes: [...res.notes, "frontend refused training_eligible=true from backend"],
      };
    }
    return res;
  } catch (e) {
    return backendMissing(command, `invoke threw: ${(e as Error)?.message ?? "unknown"}`);
  }
}

// Convenience predicate exported for panel tests.
export function isBlocked(r: IdeRepairResponse): boolean {
  return (
    r.status.startsWith("TAURI_RUST_COMMAND_BRIDGE_BLOCKED_") ||
    r.status.startsWith("TAURI_COMMAND_BLOCKED_") ||
    r.status === "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED"
  );
}
