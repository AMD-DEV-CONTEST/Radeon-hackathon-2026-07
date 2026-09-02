// CLAUDE LANE — Workspace status panel.
// Locked under: locks/sentinel/FRONTEND_WORKSPACE_STATUS_PANEL_LOCK_001.json

"use client";
import * as React from "react";

import { IdeRepairResponse, invokeIdeCommand, isBlocked } from "@/lib/ide-repair-api";

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set matches the Rust side.
 * knip cannot see that, so without this tag it reports the export as unused --
 * and deleting it would break the lock while the type-checker stayed green.
 * @public
 */
export const WORKSPACE_STATUS_PANEL_STATUS_TOKENS = [
  "WORKSPACE_STATUS_PANEL_READY",
  "WORKSPACE_STATUS_UNSUPPORTED_VISIBLE",
  "WORKSPACE_STATUS_VERIFIER_MISSING_VISIBLE",
  "WORKSPACE_STATUS_SOURCE_UNCHANGED",
] as const;

interface Props {
  workspacePath: string;
  initial?: IdeRepairResponse | null;
}

export function WorkspaceStatusPanel({ workspacePath, initial = null }: Props) {
  const [resp, setResp] = React.useState<IdeRepairResponse | null>(initial);
  const [loading, setLoading] = React.useState<boolean>(false);

  const refresh = React.useCallback(async () => {
    if (!workspacePath) return;
    setLoading(true);
    try {
      const r = await invokeIdeCommand("get_workspace_status", { workspace: workspacePath });
      setResp(r);
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const payload = (resp?.payload ?? {}) as Record<string, unknown>;
  // While the first request is still in flight (resp === null), payload.adapter
  // is genuinely absent -- but showing that as "Unknown"/"no"/"MISSING" reads as
  // a real negative detection result, not a loading placeholder. Found live
  // 2026-07-19 (Ryan: "repair is odd") while confirming this repo itself
  // detects correctly: it does (Python/pip, supported=yes) once the request
  // resolves, but the misleading interim values were visible for the ~1-3s a
  // cold python subprocess spin-up takes. Model Route (ModelRoutePanel) already
  // shows a literal "loading..." for this same window; match that pattern here.
  const stillLoading = !resp;
  const adapter = stillLoading ? "…" : String(payload.adapter ?? "Unknown");
  const supported = Boolean(payload.supported);
  const verifierMissing = !supported;
  const blocked = !!resp && isBlocked(resp);
  const evidenceRefs = Array.isArray(payload.evidence_refs)
    ? payload.evidence_refs.filter((ref): ref is string => typeof ref === "string")
    : [];

  const status = !resp
    ? "loading"
    : !supported
      ? "WORKSPACE_STATUS_UNSUPPORTED_VISIBLE"
      : verifierMissing
        ? "WORKSPACE_STATUS_VERIFIER_MISSING_VISIBLE"
        : "WORKSPACE_STATUS_PANEL_READY";

  return (
    <section
      data-testid="workspace-status-panel"
      data-status={status}
      className="rounded border p-3 text-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium">Workspace</h3>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="text-xs underline opacity-80 hover:opacity-100"
          data-testid="workspace-status-refresh"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <dl className="mt-2 grid grid-cols-2 gap-1">
        <dt className="opacity-70">Path</dt>
        <dd className="font-mono text-xs" data-testid="workspace-status-path">
          {workspacePath || "(none)"}
        </dd>

        <dt className="opacity-70">Adapter</dt>
        <dd data-testid="workspace-status-adapter">{adapter}</dd>

        <dt className="opacity-70">Supported</dt>
        <dd data-testid="workspace-status-supported">
          {stillLoading ? "…" : supported ? "yes" : "no"}
        </dd>

        <dt className="opacity-70">Verifier</dt>
        <dd data-testid="workspace-status-verifier">
          {stillLoading ? "…" : verifierMissing ? "MISSING" : "available"}
        </dd>
      </dl>

      <footer className="mt-3 text-xs opacity-80">
        <div data-testid="workspace-source-unchanged-note">
          Inspection is read-only. Your files were not modified.
        </div>
        {blocked && (
          <div className="mt-1 text-amber-600" data-testid="workspace-status-blocked-note">
            Status: {resp?.status}
          </div>
        )}
        {evidenceRefs.length > 0 && (
          <ul className="mt-2 list-disc pl-5" data-testid="workspace-status-evidence-refs">
            {evidenceRefs.map((r) => (
              <li key={r} className="font-mono">
                {r}
              </li>
            ))}
          </ul>
        )}
      </footer>
    </section>
  );
}
