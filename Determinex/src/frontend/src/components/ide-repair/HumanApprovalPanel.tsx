// CLAUDE LANE — Human approval panel.
// Locked under: locks/sentinel/FRONTEND_HUMAN_APPROVAL_PANEL_LOCK_001.json
//
// Renders the approval packet built by the backend + the locked UX
// copy. Approve/reject buttons exist, but source mutation remains
// gated — the buttons only record a fixture-mode decision.

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
export const HUMAN_APPROVAL_PANEL_STATUS_TOKENS = [
  "HUMAN_APPROVAL_PANEL_READY",
  "HUMAN_APPROVAL_RISK_COPY_VISIBLE",
  "HUMAN_APPROVAL_REJECT_AVAILABLE",
  "HUMAN_APPROVAL_SOURCE_MUTATION_STILL_GATED",
  "HUMAN_APPROVAL_BLOCKERS_VISIBLE",
] as const;

// Mirrors the locked APPROVAL_UX_COPY from
// scripts/ide/approval_ux_copy.py — frontend copy lives here so the
// build does not need Python at render time.
export const APPROVAL_UX_COPY = {
  diagnosis_advisory:
    "The diagnosis above is a suggestion from a model. The model can be wrong. The verifier result, not the model, is the source of truth.",
  patch_plan_untrusted:
    "This patch plan was produced by a model and has not been verified. Treat it as a draft. Read every change before approving.",
  verifier_result_explanation:
    "The verifier ran on a temporary copy of your workspace. A pass means the patched code compiled and the configured tests passed in that temp copy. It does not mean the change is correct for your use case.",
  temp_workspace_explanation:
    "The patch was applied only to a temporary workspace. Your original files were not modified. You can dismiss the patch at any time before approval.",
  source_mutation_warning:
    "Approving here records the decision only. The patch plan stages its proposed files into the Review panel, and applying them there is the single path that writes to your source — with the same workspace-boundary check every other write uses.",
  approval_consequences:
    "Approving records your operator identity and a signature over the diff. Approvals can be revoked, but not retroactively: any later audit will see that you approved this packet at this time.",
  reject_option:
    "You can reject this packet. Rejection records the reason and discards the temp workspace. Nothing is changed in your repo.",
  evidence_trail_explanation:
    "Every step in this flow is recorded under assurance/evidence/. Each lock manifest under locks/sentinel/ describes what the step proves and what it does NOT prove.",
  training_eligibility_notice:
    "Nothing from this flow becomes training data. The corpus eligibility guard refuses to admit any output produced by a mocked, advisory, fixture, or temp-only step.",
  live_model_disclaimer:
    "Even when a live local model is admitted, its output is treated as untrusted. The model can hallucinate code, misread your repo, or produce plausible-looking patches that fail the verifier.",
  no_blind_approval:
    "Read the diff. Read the verifier output. If anything is unclear, reject the packet.",
} as const;

interface Props {
  workspacePath: string;
  unifiedDiff?: string;
}

export function HumanApprovalPanel({ workspacePath, unifiedDiff = "" }: Props) {
  const [packet, setPacket] = React.useState<IdeRepairResponse | null>(null);
  const [operator, setOperator] = React.useState<string>("");
  const [decision, setDecision] = React.useState<"" | "approved-fixture" | "rejected">("");

  const fetchPacket = React.useCallback(async () => {
    const r = await invokeIdeCommand("get_human_approval_packet", {
      workspace: workspacePath,
      unifiedDiff,
    });
    setPacket(r);
  }, [workspacePath, unifiedDiff]);

  React.useEffect(() => {
    void fetchPacket();
  }, [fetchPacket]);

  const payload = (packet?.payload ?? {}) as Record<string, unknown>;
  const filesChanged = (payload.files_changed as string[] | undefined) ?? [];
  const verifierResult = String(payload.verifier_result ?? "");
  const diffSummary = String(payload.diff_summary ?? "");
  const traceId = String(payload.trace_id ?? "");
  const staleAfter = String(payload.stale_after ?? "");

  const canApprove = operator.trim().length > 0;

  return (
    <section data-testid="human-approval-panel" className="rounded border p-3 text-sm space-y-3">
      <header>
        <h3 className="font-medium">Human Approval</h3>
        <p className="text-xs opacity-80" data-testid="human-approval-source-mutation-still-gated">
          Source mutation is still gated. This panel records your decision; it does not write to
          your repo.
        </p>
      </header>

      <ul
        className="rounded bg-amber-500/5 border border-amber-500/30 p-3 text-xs space-y-1"
        data-testid="human-approval-risk-copy"
      >
        <li>{APPROVAL_UX_COPY.diagnosis_advisory}</li>
        <li>{APPROVAL_UX_COPY.patch_plan_untrusted}</li>
        <li>{APPROVAL_UX_COPY.verifier_result_explanation}</li>
        <li>{APPROVAL_UX_COPY.temp_workspace_explanation}</li>
        <li>{APPROVAL_UX_COPY.source_mutation_warning}</li>
        <li>{APPROVAL_UX_COPY.training_eligibility_notice}</li>
        <li>{APPROVAL_UX_COPY.no_blind_approval}</li>
      </ul>

      <dl className="grid grid-cols-2 gap-1 text-xs">
        <dt className="opacity-70">Trace</dt>
        <dd className="font-mono" data-testid="human-approval-trace-id">
          {traceId || "—"}
        </dd>

        <dt className="opacity-70">Files</dt>
        <dd data-testid="human-approval-files-changed">
          {filesChanged.length ? filesChanged.join(", ") : "—"}
        </dd>

        <dt className="opacity-70">Verifier</dt>
        <dd className="font-mono" data-testid="human-approval-verifier-result">
          {verifierResult || "—"}
        </dd>

        <dt className="opacity-70">Stale after</dt>
        <dd className="font-mono text-xs" data-testid="human-approval-stale-after">
          {staleAfter || "—"}
        </dd>
      </dl>

      {diffSummary && (
        <pre
          className="overflow-auto rounded bg-muted/50 p-2 text-xs"
          data-testid="human-approval-diff-summary"
        >
          {diffSummary}
        </pre>
      )}

      <div className="flex items-center gap-2">
        <label className="text-xs">
          Operator id
          <input
            type="text"
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="your id"
            className="ml-1 rounded border bg-transparent px-1 text-xs"
            data-testid="human-approval-operator-input"
          />
        </label>

        <button
          type="button"
          disabled={!canApprove || decision !== ""}
          onClick={() => setDecision("approved-fixture")}
          className="rounded border px-2 py-1 text-xs disabled:opacity-50"
          data-testid="human-approval-approve-button"
        >
          Approve (fixture only)
        </button>

        <button
          type="button"
          disabled={decision !== ""}
          onClick={() => setDecision("rejected")}
          className="rounded border px-2 py-1 text-xs disabled:opacity-50"
          data-testid="human-approval-reject-button"
        >
          Reject
        </button>
      </div>

      {decision === "approved-fixture" && (
        <div
          className="rounded border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs"
          data-testid="human-approval-fixture-recorded"
        >
          Recorded as FIXTURE approval. Source mutation remains BLOCKED.
        </div>
      )}
      {decision === "rejected" && (
        <div
          className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs"
          data-testid="human-approval-rejected-recorded"
        >
          Recorded as REJECTED. Temp workspace will be discarded by the backend.
        </div>
      )}
    </section>
  );
}
