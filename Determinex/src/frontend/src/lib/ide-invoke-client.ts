// CLAUDE LANE — typed IDE invoke client.
// Locked under: locks/sentinel/FRONTEND_COMMAND_INVOKE_CLIENT_LOCK_001.json
//
// A single typed entry point panels use to call Tauri commands.
// - Typed command names (closed set, mirrored from the Rust bridge)
// - Typed request/response shapes per command
// - Pluggable transport so tests can supply a mock
// - Errors surface via the standard IdeRepairResponse.notes channel —
//   panels never throw to the user.
//
// Defensive layering: this module is built on top of the locked
// ide-repair-api.ts wrapper; we never re-implement the source-mutation
// or training-eligibility refusals here.

import {
  IDE_REPAIR_COMMANDS,
  IdeRepairCommand,
  IdeRepairResponse,
  invokeIdeCommand,
  tauriRuntimePresent,
} from "./ide-repair-api";

export const FRONTEND_COMMAND_INVOKE_CLIENT_STATUS_TOKENS = [
  "FRONTEND_COMMAND_INVOKE_CLIENT_READY",
  "FRONTEND_COMMAND_INVOKE_CLIENT_BLOCKED_TAURI_UNAVAILABLE",
  "FRONTEND_COMMAND_ERROR_VISIBLE",
] as const;

// Typed argument shapes per command. Keeping them flat (Record-shaped)
// so the Tauri argv-json mapping in _tauri_driver.py stays trivial.
export interface OpenWorkspaceArgs {
  workspace: string;
}
export interface WorkspaceStatusArgs {
  workspace: string;
}
export interface ModelRouteArgs {
  task_class: string;
}
export interface DiagnoseDryRunArgs {
  workspace: string;
  task_class: string;
}
export interface DiagnoseLiveOptInArgs {
  workspace: string;
  task_class: string;
  opt_in: boolean;
}
export interface GeneratePatchPlanArgs {
  workspace: string;
  opt_in: boolean;
}
export interface VerifyTempPatchArgs {
  workspace: string;
}
export interface HumanApprovalPacketArgs {
  workspace: string;
  unified_diff: string;
}
export interface SourceApplyDryRunArgs {
  workspace: string;
}
export interface RepairFlowStateArgs {
  workspace: string;
}

export type IdeCommandArgs =
  | { command: "open_workspace"; args: OpenWorkspaceArgs }
  | { command: "get_workspace_status"; args: WorkspaceStatusArgs }
  | { command: "get_model_route_status"; args: ModelRouteArgs }
  | { command: "diagnose_dry_run"; args: DiagnoseDryRunArgs }
  | { command: "diagnose_live_opt_in"; args: DiagnoseLiveOptInArgs }
  | { command: "generate_patch_plan"; args: GeneratePatchPlanArgs }
  | { command: "verify_temp_patch"; args: VerifyTempPatchArgs }
  | { command: "get_human_approval_packet"; args: HumanApprovalPacketArgs }
  | { command: "source_apply_dry_run"; args: SourceApplyDryRunArgs }
  | { command: "get_repair_flow_state"; args: RepairFlowStateArgs };

export interface IdeInvokeClient {
  invoke(cmd: IdeCommandArgs): Promise<IdeRepairResponse>;
  isRuntimeReady(): boolean;
}

// Transport interface. Production transport calls the Tauri runtime;
// the mock transport returns canned responses for tests.
export interface IdeInvokeTransport {
  call(command: IdeRepairCommand, args: Record<string, unknown>): Promise<IdeRepairResponse>;
  runtimeReady(): boolean;
}

export const realTauriTransport: IdeInvokeTransport = {
  call: (command, args) => invokeIdeCommand(command, args),
  runtimeReady: () => tauriRuntimePresent(),
};

// Factory: build a client around a transport. Default = real Tauri.
export function makeIdeInvokeClient(
  transport: IdeInvokeTransport = realTauriTransport
): IdeInvokeClient {
  return {
    isRuntimeReady: () => transport.runtimeReady(),
    async invoke(cmd: IdeCommandArgs): Promise<IdeRepairResponse> {
      if (!IDE_REPAIR_COMMANDS.includes(cmd.command)) {
        return {
          command: cmd.command,
          status: "TAURI_COMMAND_BLOCKED_UNKNOWN",
          payload: {},
          source_mutation_authorized: false,
          training_eligible: false,
          notes: [`frontend invoke client rejected unknown command: ${cmd.command}`],
        };
      }
      if (!transport.runtimeReady()) {
        return {
          command: cmd.command,
          status: "FRONTEND_COMMAND_INVOKE_CLIENT_BLOCKED_TAURI_UNAVAILABLE",
          payload: {},
          source_mutation_authorized: false,
          training_eligible: false,
          notes: ["Tauri runtime unavailable; use mock transport for tests"],
        };
      }
      const res = await transport.call(cmd.command, cmd.args as unknown as Record<string, unknown>);
      // Forward as-is; the underlying invokeIdeCommand already strips
      // source_mutation_authorized=true and training_eligible=true.
      return res;
    },
  };
}

// Mock transport for tests. Always returns a deterministic response.
export function makeMockTransport(
  responder: (cmd: IdeRepairCommand, args: Record<string, unknown>) => IdeRepairResponse,
  runtimeReady: boolean = true
): IdeInvokeTransport {
  return {
    runtimeReady: () => runtimeReady,
    call: async (command, args) => responder(command, args),
  };
}
