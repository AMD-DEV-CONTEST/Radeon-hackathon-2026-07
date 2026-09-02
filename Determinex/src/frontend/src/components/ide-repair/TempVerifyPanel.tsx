// CLAUDE LANE — Temp verify panel.
// Locked under: locks/sentinel/FRONTEND_TEMP_VERIFY_PANEL_LOCK_001.json

"use client";
import * as React from "react";

import { IdeRepairResponse, invokeIdeCommand } from "@/lib/ide-repair-api";

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set matches the Rust side.
 * knip cannot see that, so without this tag it reports the export as unused --
 * and deleting it would break the lock while the type-checker stayed green.
 * @public
 */
export const TEMP_VERIFY_PANEL_STATUS_TOKENS = [
  "TEMP_VERIFY_PANEL_READY",
  "TEMP_VERIFY_FAILED_VISIBLE",
  "TEMP_VERIFY_PASSED_TEMP_ONLY_VISIBLE",
  "TEMP_VERIFY_HUMAN_APPROVAL_REQUIRED_VISIBLE",
] as const;

interface Props {
  workspacePath: string;
}

export function TempVerifyPanel({ workspacePath }: Props) {
  const [resp, setResp] = React.useState<IdeRepairResponse | null>(null);

  const runVerify = React.useCallback(async () => {
    const r = await invokeIdeCommand("verify_temp_patch", { workspace: workspacePath });
    setResp(r);
  }, [workspacePath]);

  const payload = (resp?.payload ?? {}) as Record<string, unknown>;
  const verifierStatus = String(payload.verifier_status ?? "");
  const diffSummary = String(payload.unified_diff ?? "")
    .split("\n")
    .slice(0, 30)
    .join("\n");
  const passed = verifierStatus === "PATCH_VERIFIER_PASSED_TEMP_ONLY";
  const failed = verifierStatus === "PATCH_VERIFIER_FAILED";

  const status = !resp
    ? "TEMP_VERIFY_PANEL_READY"
    : failed
      ? "TEMP_VERIFY_FAILED_VISIBLE"
      : passed
        ? "TEMP_VERIFY_PASSED_TEMP_ONLY_VISIBLE"
        : "TEMP_VERIFY_HUMAN_APPROVAL_REQUIRED_VISIBLE";

  return (
    <section
      data-testid="temp-verify-panel"
      data-status={status}
      className="rounded border p-3 text-sm space-y-2"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium">Temp Workspace Verification</h3>
        <button
          type="button"
          onClick={() => void runVerify()}
          className="rounded border px-2 py-1 text-xs"
          data-testid="temp-verify-button"
        >
          Run verify (temp only)
        </button>
      </header>

      <div className="text-xs opacity-80" data-testid="temp-verify-source-unchanged-note">
        The patch is applied to a temp copy. Your original files were not modified.
      </div>

      {resp && (
        <>
          <div className="text-xs" data-testid="temp-verify-verifier-status">
            Verifier: <span className="font-mono">{verifierStatus || "(none)"}</span>
          </div>

          {failed && (
            <div
              className="rounded border border-red-500/40 bg-red-500/5 px-3 py-2 text-xs"
              data-testid="temp-verify-failed-note"
            >
              Verifier failed on the temp workspace. The temp tree was rolled back.
            </div>
          )}
          {passed && (
            <div
              className="rounded border border-emerald-500/40 bg-emerald-500/5 px-3 py-2 text-xs"
              data-testid="temp-verify-passed-note"
            >
              Verifier passed in the temp workspace only. The original repo is unchanged.
            </div>
          )}

          {diffSummary && (
            <pre
              className="overflow-auto rounded bg-muted/40 p-2 text-xs"
              data-testid="temp-verify-diff-summary"
            >
              {diffSummary}
            </pre>
          )}
        </>
      )}

      <div
        className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs"
        data-testid="temp-verify-human-approval-required-note"
      >
        Human approval is required before any change leaves the temp workspace.
      </div>
    </section>
  );
}
