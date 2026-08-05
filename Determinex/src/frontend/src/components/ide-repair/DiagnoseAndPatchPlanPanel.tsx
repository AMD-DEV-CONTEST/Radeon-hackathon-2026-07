// CLAUDE LANE — Diagnose + patch plan flow panel.
// Locked under: locks/sentinel/FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_LOCK_001.json

"use client";
import * as React from "react";

import { invoke } from "@tauri-apps/api/core";
import { IdeRepairResponse, invokeIdeCommand } from "@/lib/ide-repair-api";

/** One file the repair engine proposes changing. Source stays untouched. */
type ProposedFile = { path: string; original_content: string; proposed_content: string };

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set matches the Rust side.
 * knip cannot see that, so without this tag it reports the export as unused --
 * and deleting it would break the lock while the type-checker stayed green.
 * @public
 */
export const DIAGNOSE_PATCH_PLAN_STATUS_TOKENS = [
  "FRONTEND_DIAGNOSE_DRY_RUN_READY",
  "FRONTEND_LIVE_DIAGNOSE_OPT_IN_REQUIRED",
  "FRONTEND_PATCH_PLAN_QUARANTINED",
  "FRONTEND_PATCH_PLAN_SOURCE_UNCHANGED",
] as const;

interface Props {
  workspacePath: string;
  taskClass?: string;
}

export function DiagnoseAndPatchPlanPanel({ workspacePath, taskClass = "BUILD_DIAGNOSIS" }: Props) {
  const [diagnoseResp, setDiagnoseResp] = React.useState<IdeRepairResponse | null>(null);
  const [planResp, setPlanResp] = React.useState<IdeRepairResponse | null>(null);
  const [liveOptIn, setLiveOptIn] = React.useState<boolean>(false);
  const [planOptIn, setPlanOptIn] = React.useState<boolean>(false);

  // Tauri's invoke() converts camelCase JS keys to the Rust command's
  // snake_case parameter names -- these three calls passed snake_case
  // keys directly, so Tauri never found a matching argument and every
  // call here failed 100% of the time (get_model_route_status had the
  // identical bug, found live in ModelRoutePanel.tsx).
  const runDryRun = React.useCallback(async () => {
    const r = await invokeIdeCommand("diagnose_dry_run", {
      workspace: workspacePath,
      taskClass,
    });
    setDiagnoseResp(r);
  }, [workspacePath, taskClass]);

  const runLive = React.useCallback(async () => {
    if (!liveOptIn) return;
    const r = await invokeIdeCommand("diagnose_live_opt_in", {
      workspace: workspacePath,
      taskClass,
      optIn: true,
    });
    setDiagnoseResp(r);
  }, [workspacePath, taskClass, liveOptIn]);

  const [staged, setStaged] = React.useState<string | null>(null);

  const runPlan = React.useCallback(async () => {
    if (!planOptIn) return;
    setStaged(null);
    const r = await invokeIdeCommand("generate_patch_plan", {
      workspace: workspacePath,
      optIn: true,
    });
    setPlanResp(r);

    // The patch plan now returns REAL per-file proposals instead of
    // {"mode": "quarantine_only"}. Route them into the Review queue rather than
    // writing anything here: Review already has the human approve/reject step
    // and apply_staged_diff already enforces the workspace boundary. One
    // source-mutation path, and it is the one that is tested.
    const proposed = (r?.payload as { proposed?: ProposedFile[] } | undefined)?.proposed ?? [];
    if (proposed.length === 0) return;
    try {
      for (const f of proposed) {
        await invoke("stage_diff_for_review", {
          diff: {
            id: `repair-${Date.now()}-${f.path}`,
            path: f.path,
            // Rust's StagedDiff is rename_all="camelCase"; snake_case here
            // would deserialize to nothing and stage silently.
            originalContent: f.original_content,
            proposedContent: f.proposed_content,
          },
        });
      }
      setStaged(
        `${proposed.length} file(s) staged in Review — nothing is written until you approve there.`
      );
    } catch (e) {
      setStaged(`Could not stage the proposal: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [workspacePath, planOptIn]);

  return (
    <section
      data-testid="diagnose-and-patch-plan-panel"
      className="rounded border p-3 text-sm space-y-3"
    >
      {staged && (
        <p
          data-testid="patch-plan-staged-note"
          className="rounded border border-emerald-500/25 bg-emerald-950/20 px-2 py-1.5 text-xs text-emerald-300"
        >
          {staged}
        </p>
      )}

      <header>
        <h3 className="font-medium">Diagnosis &amp; Patch Plan</h3>
        <p className="text-xs opacity-70" data-testid="diagnose-advisory-note">
          The model output is advisory. The verifier is the source of truth.
        </p>
      </header>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void runDryRun()}
            className="rounded border px-2 py-1 text-xs"
            data-testid="diagnose-dry-run-button"
          >
            Diagnose (dry-run)
          </button>
          <span className="text-xs opacity-70">no model call</span>
        </div>

        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={liveOptIn}
              onChange={(e) => setLiveOptIn(e.target.checked)}
              data-testid="diagnose-live-opt-in-checkbox"
            />
            I understand the model output is advisory and untrusted.
          </label>
          <button
            type="button"
            onClick={() => void runLive()}
            disabled={!liveOptIn}
            className="rounded border px-2 py-1 text-xs disabled:opacity-50"
            data-testid="diagnose-live-button"
          >
            Diagnose (live, opt-in)
          </button>
        </div>

        {diagnoseResp && (
          <pre
            className="overflow-auto rounded bg-muted/50 p-2 text-xs"
            data-testid="diagnose-result"
          >
            {JSON.stringify(diagnoseResp, null, 2)}
          </pre>
        )}
      </div>

      <hr className="opacity-40" />

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={planOptIn}
              onChange={(e) => setPlanOptIn(e.target.checked)}
              data-testid="patch-plan-opt-in-checkbox"
            />
            I understand the plan is quarantined and will not be applied.
          </label>
          <button
            type="button"
            onClick={() => void runPlan()}
            disabled={!planOptIn}
            className="rounded border px-2 py-1 text-xs disabled:opacity-50"
            data-testid="patch-plan-button"
          >
            Generate patch plan (quarantine only)
          </button>
        </div>

        {planResp && (
          <pre
            className="overflow-auto rounded bg-muted/50 p-2 text-xs"
            data-testid="patch-plan-result"
          >
            {JSON.stringify(planResp, null, 2)}
          </pre>
        )}

        <div className="text-xs opacity-80" data-testid="patch-plan-quarantined-note">
          Patch plans are quarantined. No diff is applied here. Your files were not modified.
        </div>
      </div>
    </section>
  );
}
