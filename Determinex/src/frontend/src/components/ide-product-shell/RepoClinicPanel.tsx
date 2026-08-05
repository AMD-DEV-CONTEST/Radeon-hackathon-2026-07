// CLAUDE LANE — Repo Clinic panel.
// Locked under: locks/sentinel/DETERMINEX_REACT_REPO_CLINIC_PANEL_LOCK_001.json
//
// Mounts the existing-repo diagnose / repair / refactor / update
// panel. No "fixed" label without post-apply verifier pass. Diagnosis
// does NOT authorize source mutation. Local model admission does NOT
// authorize source mutation. Approval status is distinct from source
// mutation applied. Blocked verifier-missing state is visible.

"use client";
import * as React from "react";

import {
  invokeUnifiedProductCommand,
  READY_DOES_NOT_MEAN_AUTHORIZED,
  UnifiedProductResponse,
} from "@/lib/ide-product-shell-api";
import { invokeSafe, repairDiagnose, type RepairDiagnosis } from "@/lib/api";

export const REACT_REPO_CLINIC_PANEL_STATUS_TOKENS = [
  "REACT_REPO_CLINIC_PANEL_PASSED",
  "REACT_REPO_CLINIC_PANEL_BLOCKED_FALSE_FIXED_LABEL",
  "REACT_REPO_CLINIC_PANEL_BLOCKED_SOURCE_MUTATION_CONFUSION",
  "REACT_REPO_CLINIC_PANEL_BLOCKED_VERIFIER_MISSING_HIDDEN",
] as const;

interface Props {
  // The workspace to diagnose. Defaults to the SAME real path the rest of the
  // app already tracks (localStorage "explorerRoot") rather than requiring a
  // parent to always pass one -- see the RepairPanelShell fix this mirrors.
  workspacePath?: string;
  // Later-stage flags (patch application / approval) have no session-state
  // source yet -- that flow lives in the separate /ide-repair route. Left
  // undefined here so they honestly default to false, not fabricated.
  verifierCommandPresent?: boolean;
  diagnosisPresent?: boolean;
  tempVerifierPassed?: boolean;
  approvalPresent?: boolean;
  sourceMutationApplied?: boolean;
  postApplyVerifierPassed?: boolean;
  rollbackAvailable?: boolean;
}

export function RepoClinicPanel({
  workspacePath,
  verifierCommandPresent: verifierCommandPresentProp,
  diagnosisPresent: diagnosisPresentProp,
  tempVerifierPassed = false,
  approvalPresent = false,
  sourceMutationApplied = false,
  postApplyVerifierPassed = false,
  rollbackAvailable = false,
}: Props) {
  const [resp, setResp] = React.useState<UnifiedProductResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [liveVerifierPresent, setLiveVerifierPresent] = React.useState(false);
  const [liveDiagnosis, setLiveDiagnosis] = React.useState<RepairDiagnosis | null>(null);

  const resolvedWorkspacePath =
    workspacePath ||
    (typeof window !== "undefined" ? window.localStorage.getItem("explorerRoot") || "" : "");

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await invokeUnifiedProductCommand("get_repo_clinic_workflow_state");
      setResp(r);
      if (resolvedWorkspacePath) {
        const statusRes = await invokeSafe<{ payload?: { supported?: boolean } }>(
          "get_workspace_status",
          { workspace: resolvedWorkspacePath }
        );
        setLiveVerifierPresent(Boolean(statusRes?.payload?.supported));
        const diagnosis = await repairDiagnose(resolvedWorkspacePath);
        setLiveDiagnosis(diagnosis);
      }
    } finally {
      setLoading(false);
    }
  }, [resolvedWorkspacePath]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  // Explicit props (tests, storybook-style overrides) win; otherwise the real
  // workspace read via repair_diagnose / get_workspace_status is the source of truth.
  const verifierCommandPresent = verifierCommandPresentProp ?? liveVerifierPresent;
  const diagnosisPresent =
    diagnosisPresentProp ?? (liveDiagnosis != null && liveDiagnosis.healthy === false);

  // Fixed label only after post-apply verifier passes.
  const fixedLabelEnabled = sourceMutationApplied && postApplyVerifierPassed;

  const renderStatus = !verifierCommandPresent
    ? "REACT_REPO_CLINIC_PANEL_BLOCKED_VERIFIER_MISSING_HIDDEN"
    : "REACT_REPO_CLINIC_PANEL_PASSED";

  return (
    <section
      data-testid="repo-clinic-panel"
      data-status={renderStatus}
      className="rounded border p-3 text-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium">Repo Clinic</h3>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="text-xs underline opacity-80 hover:opacity-100"
          data-testid="repo-clinic-refresh"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <dl className="mt-2 grid grid-cols-2 gap-1">
        <dt data-testid="repo-clinic-repo-analysis-status">Repo analysis</dt>
        {/* Was the bare literal "analyzed" -- the one unconditional row in a table whose other
            eleven rows are all derived. With no workspace open, resolvedWorkspacePath is "" so no
            diagnosis is even attempted, and the panel still reported the repo as analysed. */}
        <dd>
          {!resolvedWorkspacePath
            ? "no workspace open — not analyzed"
            : liveDiagnosis
              ? "analyzed"
              : "analysis pending"}
        </dd>

        <dt data-testid="repo-clinic-toolchain-status">Toolchain</dt>
        <dd>{verifierCommandPresent ? "detected" : "TOOLCHAIN_MISSING"}</dd>

        <dt data-testid="repo-clinic-verifier-status">Verifier</dt>
        <dd data-testid="repo-clinic-verifier-missing-badge">
          {verifierCommandPresent ? "available" : "VERIFIER_MISSING — repair gated"}
        </dd>

        <dt data-testid="repo-clinic-diagnosis-status">Diagnosis</dt>
        <dd data-testid="repo-clinic-diagnosis-summary">
          {diagnosisPresent
            ? `ISSUE_DIAGNOSED_UNVERIFIED — ${liveDiagnosis?.language ?? "?"}, ${liveDiagnosis?.n_failures ?? 0} failure(s)`
            : liveDiagnosis && liveDiagnosis.healthy === true
              ? "oracle passes — nothing to repair"
              : "no diagnosis yet"}
        </dd>

        <dt data-testid="repo-clinic-quarantined-patch-status">Quarantined patch plan</dt>
        <dd>{diagnosisPresent ? "PATCH_PROPOSED_QUARANTINED" : "pending"}</dd>

        <dt data-testid="repo-clinic-temp-verifier-status">Temp verifier</dt>
        <dd>{tempVerifierPassed ? "TEMP_VERIFIER_PASSED" : "not yet run"}</dd>

        <dt data-testid="repo-clinic-approval-requirement">Approval requirement</dt>
        <dd>
          {approvalPresent ? "APPROVAL_REQUIRED — granted" : "APPROVAL_REQUIRED — pending operator"}
        </dd>

        <dt data-testid="repo-clinic-source-mutation-status">Source mutation</dt>
        <dd data-testid="repo-clinic-source-mutation-distinct">
          {sourceMutationApplied
            ? "SOURCE_MUTATION_APPLIED"
            : "BLOCKED_PENDING_HUMAN_APPROVAL — distinct from approval status"}
        </dd>

        <dt data-testid="repo-clinic-post-apply-verifier-status">Post-apply verifier</dt>
        <dd>{postApplyVerifierPassed ? "POST_APPLY_VERIFIER_PASSED" : "not yet run"}</dd>

        <dt data-testid="repo-clinic-rollback-status">Rollback</dt>
        <dd>{rollbackAvailable ? "snapshot available" : "snapshot pending"}</dd>

        <dt data-testid="repo-clinic-evidence-status">Evidence</dt>
        <dd>
          {fixedLabelEnabled ? "post-apply evidence present" : "no evidence of successful repair"}
        </dd>

        <dt data-testid="repo-clinic-training-eligibility-status">Training eligibility</dt>
        <dd>training_eligible: false (remains false)</dd>
      </dl>

      <div className="mt-3 flex items-center gap-2">
        <span
          data-testid="repo-clinic-fixed-label"
          data-enabled={fixedLabelEnabled}
          className={
            "rounded px-2 py-0.5 text-xs " +
            (fixedLabelEnabled ? "bg-emerald-100 text-emerald-900" : "bg-slate-100 text-slate-500")
          }
        >
          {fixedLabelEnabled ? "REPAIR_VERIFIED" : "FIXED_LABEL_DISABLED_NO_POST_APPLY_EVIDENCE"}
        </span>
        <span data-testid="repo-clinic-fixed-meaning" className="text-xs opacity-70">
          &quot;Fixed&quot; requires post-apply verifier pass.
        </span>
      </div>

      <footer
        data-testid="repo-clinic-caveats-footer"
        className="mt-3 border-t pt-2 text-xs opacity-80"
      >
        <div data-testid="repo-clinic-ready-does-not-mean-authorized">
          {READY_DOES_NOT_MEAN_AUTHORIZED}
        </div>
        <div data-testid="repo-clinic-diagnosis-not-authorization">
          Diagnosis does NOT authorize source mutation.
        </div>
        <div data-testid="repo-clinic-admission-not-source-authorization">
          Local model admission does NOT authorize source mutation.
        </div>
        <div data-testid="repo-clinic-generated-is-not-verified">Generated is not verified.</div>
        {diagnosisPresent && (
          <div data-testid="repo-clinic-continue-in-repair-panel" className="mt-1">
            <a href="/ide-repair/" target="_blank" rel="noreferrer" className="underline">
              Continue in Repair Panel
            </a>{" "}
            for the patch plan, temp verification, and human approval flow.
          </div>
        )}
        {!resp && <div>loading workflow definition…</div>}
      </footer>
    </section>
  );
}
