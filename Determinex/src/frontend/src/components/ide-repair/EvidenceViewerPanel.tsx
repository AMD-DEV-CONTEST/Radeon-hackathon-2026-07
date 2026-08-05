// CLAUDE LANE — Evidence viewer panel.
// Locked under: locks/sentinel/FRONTEND_EVIDENCE_VIEWER_LOCK_001.json

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
export const EVIDENCE_VIEWER_STATUS_TOKENS = [
  "EVIDENCE_VIEWER_READY",
  "EVIDENCE_VIEWER_READ_ONLY",
  "EVIDENCE_HEALTH_VISIBLE",
] as const;

interface Props {
  workspacePath: string;
}

export function EvidenceViewerPanel({ workspacePath }: Props) {
  const [resp, setResp] = React.useState<IdeRepairResponse | null>(null);

  const refresh = React.useCallback(async () => {
    const r = await invokeIdeCommand("get_repair_flow_state", { workspace: workspacePath });
    setResp(r);
  }, [workspacePath]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const payload = (resp?.payload ?? {}) as Record<string, unknown>;
  const trainingEligible = Boolean(payload.training_eligible ?? false);
  const sourceMutation = String(payload.source_mutation ?? "BLOCKED_PENDING_HUMAN_APPROVAL");
  const locks = (payload.locks as string[] | undefined) ?? [];
  const evidenceFiles = (payload.evidence_files as string[] | undefined) ?? [];

  return (
    <section data-testid="evidence-viewer-panel" className="rounded border p-3 text-sm space-y-2">
      <header className="flex items-center justify-between">
        <h3 className="font-medium">Evidence</h3>
        <span
          className="text-xs uppercase opacity-70"
          data-testid="evidence-viewer-read-only-badge"
        >
          Read-only
        </span>
      </header>

      <dl className="grid grid-cols-2 gap-1 text-xs">
        <dt className="opacity-70">Source mutation</dt>
        <dd className="font-mono" data-testid="evidence-viewer-source-mutation">
          {sourceMutation}
        </dd>

        <dt className="opacity-70">Training eligible</dt>
        <dd className="font-mono" data-testid="evidence-viewer-training-eligible">
          {String(trainingEligible)}
        </dd>
      </dl>

      <div data-testid="evidence-viewer-locks">
        <h4 className="text-xs font-medium opacity-70">Lock IDs</h4>
        {locks.length === 0 ? (
          <p className="text-xs opacity-60">(no locks loaded for this flow yet)</p>
        ) : (
          <ul className="mt-1 list-disc pl-5 text-xs font-mono">
            {locks.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
      </div>

      <div data-testid="evidence-viewer-files">
        <h4 className="text-xs font-medium opacity-70">Evidence files</h4>
        {evidenceFiles.length === 0 ? (
          <p className="text-xs opacity-60">(no evidence files referenced yet)</p>
        ) : (
          <ul className="mt-1 list-disc pl-5 text-xs font-mono">
            {evidenceFiles.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="text-xs opacity-80" data-testid="evidence-viewer-health">
        Each lock manifest under <code>locks/sentinel/</code> describes what the step proves and
        what it does NOT prove. Validate with <code>determinex evidence validate</code> from the
        CLI.
      </div>
    </section>
  );
}
