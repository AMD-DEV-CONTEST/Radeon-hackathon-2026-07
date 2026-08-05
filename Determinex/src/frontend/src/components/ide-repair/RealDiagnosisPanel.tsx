// Runs the real Repo Clinic engine (compiler/test oracle + Impossibility
// Adjudicator + Test Validator + Failure Explainer) against the workspace.
// Read-only: no model call, no source mutation. Distinct from the advisory
// dry-run/live-opt-in flow above it, which is model-output-based and gated.
"use client";
import * as React from "react";

import {
  getGovernanceStatus,
  repairDiagnose,
  type GovernanceStatus,
  type RepairDiagnosis,
} from "@/lib/api";

const RESPONSIBLE_LABEL: Record<string, string> = {
  CODE: "Fix the code",
  TEST: "The test is wrong (proven)",
  ENVIRONMENT: "Match the environment",
};

interface Props {
  workspacePath: string;
}

export function RealDiagnosisPanel({ workspacePath }: Props) {
  const [result, setResult] = React.useState<RepairDiagnosis | null>(null);
  const [running, setRunning] = React.useState(false);
  const [governance, setGovernance] = React.useState<GovernanceStatus | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getGovernanceStatus().then((g) => {
      if (!cancelled) setGovernance(g);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const run = React.useCallback(async () => {
    setRunning(true);
    const r = await repairDiagnose(workspacePath);
    setResult(r);
    setRunning(false);
  }, [workspacePath]);

  return (
    <div className="mt-3 rounded border p-3 text-sm space-y-2" data-testid="real-diagnosis-panel">
      {governance && (
        <div data-testid="real-diagnosis-governance" className="text-xs opacity-70">
          Governance:{" "}
          {governance.all_closed
            ? "no open overclaim anchors"
            : `${(governance.violations ?? []).length} open anchor(s)`}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void run()}
          disabled={running}
          className="rounded border px-2 py-1 text-xs disabled:opacity-50"
          data-testid="real-diagnosis-run-button"
        >
          {running ? "Running oracle…" : "Run real diagnosis (oracle-verified)"}
        </button>
        <span className="text-xs opacity-70">
          runs the workspace&apos;s own compiler/tests; no model call
        </span>
      </div>

      {result && (
        <div data-testid="real-diagnosis-result" className="space-y-2">
          {result.note ? (
            <p className="text-xs opacity-70">{result.note}</p>
          ) : result.healthy ? (
            <p className="text-xs text-emerald-500">Oracle passes — nothing to diagnose.</p>
          ) : (
            <>
              <p className="text-xs opacity-80">
                {result.language} · {result.oracle} · {result.n_failures} failing check
                {result.n_failures === 1 ? "" : "s"}
              </p>
              <ul className="space-y-2">
                {result.explanations.map((e) => (
                  <li key={e.test_id} className="rounded border p-2 text-xs">
                    <div className="font-medium">
                      [{e.responsible}] {RESPONSIBLE_LABEL[e.responsible] ?? e.responsible} (
                      {e.test_id})
                    </div>
                    <div className="opacity-80">why: {e.why}</div>
                    {e.expected !== null && (
                      <div className="opacity-80">expected: {e.expected}</div>
                    )}
                    {e.actual !== null && <div className="opacity-80">actual: {e.actual}</div>}
                    <div className="opacity-80">delta: {e.delta}</div>
                    {e.proof && <div className="opacity-80">proof: {e.proof}</div>}
                    <div className="opacity-60">confidence: {e.confidence.toFixed(2)}</div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
