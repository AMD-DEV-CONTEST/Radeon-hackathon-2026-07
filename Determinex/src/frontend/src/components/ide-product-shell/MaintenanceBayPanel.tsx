// CLAUDE LANE — Maintenance Bay panel.
// Locked under: locks/sentinel/DETERMINEX_REACT_MAINTENANCE_BAY_PANEL_LOCK_001.json
//
// Mounts the maintenance / update panel. No "updated" or
// "maintained" label without compatibility verifier pass.
// Dependency/security changes show risk. Advisory/scanner status
// is caveated if not run. Proposed update cannot look applied or
// verified.

"use client";
import * as React from "react";

import {
  invokeUnifiedProductCommand,
  READY_DOES_NOT_MEAN_AUTHORIZED,
  UnifiedProductResponse,
} from "@/lib/ide-product-shell-api";

export const REACT_MAINTENANCE_BAY_PANEL_STATUS_TOKENS = [
  "REACT_MAINTENANCE_BAY_PANEL_PASSED",
  "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_FALSE_UPDATED_LABEL",
  "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_MISSING_COMPATIBILITY_VERIFIER",
  "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_RISK_HIDDEN",
] as const;

interface SecurityGateResult {
  gate: string;
  passed: boolean;
  detail: string;
}

interface SecurityGateReport {
  schema?: string;
  generated_at?: string;
  overall_passed: boolean | null;
  gates: SecurityGateResult[];
  scan_error?: string;
}

interface Props {
  maintenanceType?: string;
  // Later-stage flags (update application / approval) have no session-state
  // source yet -- honestly default to false rather than fabricated, same as
  // RepoClinicPanel's later stages.
  riskClassification?: string;
  compatibilityVerifierPresent?: boolean;
  compatibilityVerifierPassed?: boolean;
  advisoryStatusCaveated?: boolean;
  approvalPresent?: boolean;
  postApplyVerifierPassed?: boolean;
  rollbackPlanPresent?: boolean;
}

export function MaintenanceBayPanel({
  maintenanceType = "dependency_update",
  riskClassification: riskClassificationProp,
  compatibilityVerifierPresent: compatibilityVerifierPresentProp,
  compatibilityVerifierPassed: compatibilityVerifierPassedProp,
  advisoryStatusCaveated: advisoryStatusCaveatedProp,
  approvalPresent = false,
  postApplyVerifierPassed = false,
  rollbackPlanPresent = false,
}: Props) {
  const [resp, setResp] = React.useState<UnifiedProductResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [scanResult, setScanResult] = React.useState<SecurityGateReport | null>(null);
  const [scanning, setScanning] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await invokeUnifiedProductCommand("get_maintenance_bay_workflow_state");
      setResp(r);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  // Explicit opt-in only -- composes 5 real scanners (pip-audit et al.) and can take
  // several seconds, so it is never auto-fetched on mount like refresh() above.
  const runScan = React.useCallback(async () => {
    setScanning(true);
    try {
      const r = await invokeUnifiedProductCommand("run_maintenance_bay_scan");
      setScanResult((r.payload as unknown as SecurityGateReport) ?? null);
    } finally {
      setScanning(false);
    }
  }, []);

  // A crashed/blocked invoke (e.g. Tauri IPC not ready yet) resolves to a
  // payload of {} rather than throwing -- scanResult would be truthy with
  // no scan_error but also no real `gates` array, and `.filter()` on
  // undefined threw a full white-screen-style crash caught by the app's
  // error boundary. Require gates to actually be an array before treating
  // the scan as having run.
  const scanRan = scanResult != null && !scanResult.scan_error && Array.isArray(scanResult.gates);
  const failedGates = scanRan ? scanResult!.gates.filter((g) => !g.passed) : [];

  // A SECURITY scan is not a compatibility verifier. These used to default to `scanRan` and
  // `scanResult.overall_passed`, where scanRan means the pip-audit/secret/licence/container scan
  // ran -- so after a green security scan the row "Compatibility verifier required" reported
  // "passed", asserting that a dependency update had been checked for compatibility when nothing of
  // the kind had happened. There is no compatibility verifier in this product yet, so absent it
  // reports absent, and only an explicit prop can claim otherwise.
  const compatibilityVerifierPresent = compatibilityVerifierPresentProp ?? false;
  const compatibilityVerifierPassed = compatibilityVerifierPassedProp ?? false;
  const riskClassification =
    riskClassificationProp ??
    (scanRan
      ? failedGates.length > 0
        ? failedGates.map((g) => g.gate).join(", ")
        : "none_found"
      : "unknown");
  const advisoryStatusCaveated = advisoryStatusCaveatedProp ?? !scanRan;

  // Hard rule: "UPDATED" label requires compatibility verifier AND
  // approval AND post-apply verifier ALL passed.
  const updatedLabelEnabled =
    compatibilityVerifierPresent &&
    compatibilityVerifierPassed &&
    approvalPresent &&
    postApplyVerifierPassed;

  const riskRequiredForType =
    maintenanceType === "dependency_update" || maintenanceType === "security_fix";
  const riskVisible = riskClassification !== "" && riskClassification !== "unknown";

  const renderStatus =
    riskRequiredForType && !riskVisible
      ? "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_RISK_HIDDEN"
      : !compatibilityVerifierPresent
        ? "REACT_MAINTENANCE_BAY_PANEL_BLOCKED_MISSING_COMPATIBILITY_VERIFIER"
        : "REACT_MAINTENANCE_BAY_PANEL_PASSED";

  return (
    <section
      data-testid="maintenance-bay-panel"
      data-status={renderStatus}
      className="rounded border p-3 text-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium">Maintenance Bay</h3>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void runScan()}
            disabled={scanning}
            className="text-xs underline opacity-80 hover:opacity-100"
            data-testid="maintenance-bay-run-scan"
          >
            {scanning ? "Scanning… (pip-audit, secrets, licenses, containers)" : "Run Live Scan"}
          </button>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="text-xs underline opacity-80 hover:opacity-100"
            data-testid="maintenance-bay-refresh"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      {scanResult && (
        <div data-testid="maintenance-bay-scan-results" className="mt-2 rounded border p-2 text-xs">
          {!Array.isArray(scanResult.gates) ? (
            <div data-testid="maintenance-bay-scan-error">
              Scan did not run: {scanResult.scan_error ?? "backend returned no result"}
            </div>
          ) : (
            <ul className="space-y-0.5">
              {scanResult.gates.map((g) => (
                <li key={g.gate} data-testid={`maintenance-bay-gate-${g.gate}`}>
                  [{g.passed ? "PASS" : "BLOCKED"}] {g.gate}: {g.detail}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <dl className="mt-2 grid grid-cols-2 gap-1">
        <dt data-testid="maintenance-bay-request-type">Maintenance request type</dt>
        <dd className="font-mono text-xs">{maintenanceType}</dd>

        <dt data-testid="maintenance-bay-risk-classification">Risk classification</dt>
        <dd data-testid="maintenance-bay-risk-visible">
          {riskVisible ? riskClassification : "UNDISCLOSED — must be set for dependency/security"}
        </dd>

        <dt data-testid="maintenance-bay-impact-plan">
          Dependency / security / doc / test impact plan
        </dt>
        <dd>
          {/* Was `riskVisible ? "impact plan present" : ...`, and riskVisible is only
              `riskClassification !== "unknown"` -- which becomes "none_found" after any clean scan.
              So a clean SECURITY scan asserted that a dependency/doc/test impact plan existed. No
              impact plan is produced anywhere in this component or its backend payload. */}
          {riskVisible
            ? "risk classified — impact plan not produced yet"
            : "impact plan pending — risk must be visible first"}
        </dd>

        <dt data-testid="maintenance-bay-quarantined-changes">Proposed changes quarantined</dt>
        <dd>
          {/* Was the bare literal "UPDATE_PROPOSED_QUARANTINED", rendered unconditionally -- so on a
              fresh mount with nothing proposed the panel stated that a change set had been proposed
              and quarantined. Nothing in this component or the workflow payload tracks a proposal,
              so the honest rendering is the POLICY that would apply, labelled as such. */}
          {resp?.payload
            ? "UPDATE_PROPOSED_QUARANTINED"
            : "policy: any proposed update is quarantined (none proposed)"}
        </dd>

        <dt data-testid="maintenance-bay-compatibility-verifier-required">
          Compatibility verifier required
        </dt>
        <dd>
          {compatibilityVerifierPresent
            ? compatibilityVerifierPassed
              ? "passed"
              : "available — not yet passed"
            : "MISSING — UPDATED label disabled"}
        </dd>

        <dt data-testid="maintenance-bay-approval-requirement">Approval requirement</dt>
        <dd>{approvalPresent ? "granted" : "APPROVAL_REQUIRED — pending operator"}</dd>

        <dt data-testid="maintenance-bay-post-apply-verifier">Post-apply verifier</dt>
        <dd>{postApplyVerifierPassed ? "passed" : "not yet run"}</dd>

        <dt data-testid="maintenance-bay-rollback-evidence">Rollback plan / evidence</dt>
        <dd>{rollbackPlanPresent ? "rollback plan present" : "no rollback plan"}</dd>

        <dt data-testid="maintenance-bay-training-eligibility">Training eligibility</dt>
        <dd>training_eligible: false (remains false)</dd>
      </dl>

      <div className="mt-3 flex items-center gap-2">
        <span
          data-testid="maintenance-bay-updated-label"
          data-enabled={updatedLabelEnabled}
          className={
            "rounded px-2 py-0.5 text-xs " +
            (updatedLabelEnabled
              ? "bg-emerald-100 text-emerald-900"
              : "bg-slate-100 text-slate-500")
          }
        >
          {updatedLabelEnabled
            ? "UPDATE_APPLIED_AFTER_APPROVAL"
            : "UPDATED_LABEL_DISABLED_NO_VERIFIER"}
        </span>
        <span data-testid="maintenance-bay-updated-meaning" className="text-xs opacity-70">
          &quot;Updated&quot; requires compatibility verifier + approval + post-apply verifier.
        </span>
      </div>

      <footer
        data-testid="maintenance-bay-caveats-footer"
        className="mt-3 border-t pt-2 text-xs opacity-80"
      >
        <div data-testid="maintenance-bay-ready-does-not-mean-authorized">
          {READY_DOES_NOT_MEAN_AUTHORIZED}
        </div>
        <div data-testid="maintenance-bay-proposed-is-not-applied">
          Proposed is NOT applied; quarantined is NOT verified.
        </div>
        <div data-testid="maintenance-bay-advisory-caveat">
          {advisoryStatusCaveated
            ? "Advisory / scanner status caveated when not independently run."
            : "ADVISORY_UNCAVEATED — operator must mark advisory source."}
        </div>
        {!resp && <div>loading workflow definition…</div>}
      </footer>
    </section>
  );
}
