// CLAUDE LANE — Source apply dry-run panel.
// Locked under: locks/sentinel/FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_LOCK_001.json
//
// Read-only panel for the source apply gate. NO real apply button is
// rendered here. The panel surfaces whether the gate would allow a
// write IF a real approval were present, but explicitly disables the
// notion of writing.

"use client";
import * as React from "react";
import { Ban, CheckCircle2 } from "lucide-react";

import { IdeRepairResponse, invokeIdeCommand } from "@/lib/ide-repair-api";

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set matches the Rust side.
 * knip cannot see that, so without this tag it reports the export as unused --
 * and deleting it would break the lock while the type-checker stayed green.
 * @public
 */
export const SOURCE_APPLY_DRY_RUN_PANEL_STATUS_TOKENS = [
  "SOURCE_APPLY_DRY_RUN_PANEL_READY",
  "SOURCE_APPLY_BLOCKED_VISIBLE",
  "SOURCE_APPLY_SOURCE_UNCHANGED_VISIBLE",
  "SOURCE_APPLY_REAL_WRITE_DISABLED",
] as const;

// SCREAMING_SNAKE_CASE backend status tokens, humanized for display only --
// the raw token still drives `blocked` and is still what data-testid
// consumers/tests read (unchanged). Ryan (2026-07-21): "low tech and a lot
// of text" -- a font-mono enum dump isn't a UI.
function humanizeStatus(token: string): string {
  return token
    .split("_")
    .map((w) => (w ? w.charAt(0) + w.slice(1).toLowerCase() : w))
    .join(" ");
}

interface Props {
  workspacePath: string;
}

export function SourceApplyDryRunPanel({ workspacePath }: Props) {
  const [resp, setResp] = React.useState<IdeRepairResponse | null>(null);

  const refresh = React.useCallback(async () => {
    const r = await invokeIdeCommand("source_apply_dry_run", { workspace: workspacePath });
    setResp(r);
  }, [workspacePath]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const payload = (resp?.payload ?? {}) as Record<string, unknown>;
  const sourceMutationStatus = String(payload.source_mutation ?? "BLOCKED_PENDING_HUMAN_APPROVAL");
  const blocked = !sourceMutationStatus.includes("READY");

  return (
    <section
      data-testid="source-apply-dry-run-panel"
      className="rounded-xl border border-white/10 bg-white/[0.02] p-3.5 text-sm space-y-2.5"
    >
      <header>
        <h3 className="font-medium text-gray-200 text-body">Source Apply (dry-run only)</h3>
      </header>

      <div
        className="rounded-lg border border-amber-500/20 bg-amber-500/[0.05] px-3 py-2 text-xs text-gray-400"
        data-testid="source-apply-real-write-disabled-note"
      >
        Real source mutation is disabled in this build. This panel shows what the gate WOULD decide
        if a real approval were submitted. No file is written here.
      </div>

      <div className="flex items-center justify-between text-xs">
        <dt className="text-gray-500">Source mutation</dt>
        <dd
          className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 text-label font-medium ${
            blocked
              ? "bg-red-500/10 text-red-300 border border-red-500/30"
              : "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
          }`}
          data-testid="source-apply-gate-status"
          title={sourceMutationStatus}
        >
          {blocked ? <Ban size={11} /> : <CheckCircle2 size={11} />}
          {humanizeStatus(sourceMutationStatus)}
        </dd>
      </div>

      {blocked && (
        <div
          className="rounded-lg border border-red-500/20 bg-red-500/[0.05] p-2 text-xs text-gray-400"
          data-testid="source-apply-blocked-note"
        >
          Apply is blocked. Possible reasons: no signed approval, stale source, diff mismatch,
          verifier not passed. See evidence viewer for the full gate decision record.
        </div>
      )}

      <div className="text-xs text-gray-500" data-testid="source-apply-source-unchanged-note">
        Your original files are unchanged. Rollback note: any temp workspace produced by an earlier
        verify step is automatically discarded on verifier failure.
      </div>
    </section>
  );
}
