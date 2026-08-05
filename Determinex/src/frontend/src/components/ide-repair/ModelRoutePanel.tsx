// CLAUDE LANE — Model route panel.
// Locked under: locks/sentinel/FRONTEND_MODEL_ROUTE_PANEL_LOCK_001.json

"use client";
import * as React from "react";
import { AlertTriangle, CheckCircle2, Loader2, WifiOff } from "lucide-react";

import { IdeRepairResponse, invokeIdeCommand } from "@/lib/ide-repair-api";

// Backend task-class/route tokens are SCREAMING_SNAKE_CASE; humanize for
// display only, raw value still drives all the branching logic below.
function humanize(token: string): string {
  return token
    .split("_")
    .map((w) => (w ? w.charAt(0) + w.slice(1).toLowerCase() : w))
    .join(" ");
}

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set matches the Rust side.
 * knip cannot see that, so without this tag it reports the export as unused --
 * and deleting it would break the lock while the type-checker stayed green.
 * @public
 */
export const FRONTEND_MODEL_ROUTE_PANEL_STATUS_TOKENS = [
  "MODEL_ROUTE_PANEL_READY",
  "MODEL_ROUTE_DRY_RUN_VISIBLE",
  "MODEL_ROUTE_LIVE_OPT_IN_VISIBLE",
  "MODEL_ROUTE_BLOCKED_NO_MODEL_VISIBLE",
  "MODEL_ROUTE_NETWORK_BLOCKED_VISIBLE",
] as const;

interface Props {
  taskClass?: string;
  initial?: IdeRepairResponse | null;
}

export function ModelRoutePanel({ taskClass = "BUILD_DIAGNOSIS", initial = null }: Props) {
  const [resp, setResp] = React.useState<IdeRepairResponse | null>(initial);
  // Distinct from "resp is null" -- a response can come back with an empty
  // payload (backend_missing fallback, malformed JSON from the driver, etc.),
  // which previously looked identical to "still fetching" and left the
  // Decision field stuck on a literal "loading…" forever with no way to tell
  // the two apart.
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      // Was `{ task_class: taskClass }` -- Tauri converts camelCase JS keys
      // to the Rust command's snake_case parameter names, so the snake_case
      // key here meant Tauri never found a matching argument and this call
      // failed 100% of the time. That's the actual root cause of the
      // "Decision: loading forever" bug this panel already works around
      // below (backendUnavailable) -- the workaround stays because a
      // legitimately slow or failing backend should still degrade
      // gracefully, but this is the real fix.
      const r = await invokeIdeCommand("get_model_route_status", { taskClass });
      setResp(r);
    } finally {
      setLoading(false);
    }
  }, [taskClass]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const payload = (resp?.payload ?? {}) as Record<string, unknown>;
  const decision = String(payload.decision ?? "");
  const selectedRoute = String(payload.selected_route ?? "");
  const selectedModelId = String(payload.selected_model_id ?? "");
  const backendUnavailable = !loading && !decision && resp !== null;
  const decisionText = loading
    ? "loading…"
    : decision || (backendUnavailable ? "unavailable" : "—");

  const dryRunDefault = decision === "" || decision === "ROUTE_DRY_RUN_SELECTED";
  const liveOptInAvailable =
    decision === "ROUTE_SELECTED" || decision === "ROUTE_FALLBACK_SELECTED";
  const noModel = decision.startsWith("ROUTE_BLOCKED_") || decision === "ROUTE_NO_MODEL_REQUIRED";

  const status = noModel
    ? "MODEL_ROUTE_BLOCKED_NO_MODEL_VISIBLE"
    : liveOptInAvailable
      ? "MODEL_ROUTE_LIVE_OPT_IN_VISIBLE"
      : "MODEL_ROUTE_DRY_RUN_VISIBLE";

  return (
    <section
      data-testid="model-route-panel"
      data-status={status}
      className="rounded-xl border border-white/10 bg-white/[0.02] p-3.5 text-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium text-gray-200 text-body">Model Route</h3>
        <span
          className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-meta uppercase tracking-wide text-gray-400"
          data-testid="model-route-mode"
        >
          Dry-run default
        </span>
      </header>

      <dl className="mt-2.5 grid grid-cols-2 gap-y-1.5 text-xs">
        <dt className="text-gray-500">Task class</dt>
        <dd className="text-right text-gray-300" data-testid="model-route-task-class">
          {humanize(taskClass)}
        </dd>

        <dt className="text-gray-500">Decision</dt>
        <dd
          className="text-right text-gray-300 flex items-center justify-end gap-1"
          data-testid="model-route-decision"
        >
          {loading && <Loader2 size={11} className="animate-spin text-gray-500" />}
          {loading ? "Checking…" : decision ? humanize(decision) : decisionText}
        </dd>

        <dt className="text-gray-500">Route</dt>
        <dd className="text-right text-gray-300" data-testid="model-route-selected">
          {selectedRoute ? humanize(selectedRoute) : "—"}
        </dd>

        <dt className="text-gray-500">Model</dt>
        <dd
          className="text-right text-gray-400 text-label font-mono"
          data-testid="model-route-model-id"
        >
          {selectedModelId || "—"}
        </dd>
      </dl>

      <ul className="mt-3 space-y-1.5 text-xs">
        {backendUnavailable && (
          <li
            className="flex items-center gap-1.5 text-red-300"
            data-testid="model-route-backend-unavailable-note"
          >
            <WifiOff size={12} className="shrink-0" />
            Could not reach the model-route backend ({resp?.status ?? "unknown status"}). Retry, or
            check the app logs.
          </li>
        )}
        {dryRunDefault && !backendUnavailable && (
          <li
            className="flex items-center gap-1.5 text-gray-500"
            data-testid="model-route-dry-run-note"
          >
            <CheckCircle2 size={12} className="shrink-0 text-cyan-400/70" />
            Dry-run is the default. No live model call is made unless you opt in explicitly.
          </li>
        )}
        {liveOptInAvailable && (
          <li
            className="flex items-center gap-1.5 text-emerald-300"
            data-testid="model-route-live-opt-in-note"
          >
            <CheckCircle2 size={12} className="shrink-0" />
            Live opt-in is available for this task class. The model output remains advisory.
          </li>
        )}
        {noModel && (
          <li
            className="flex items-center gap-1.5 text-amber-300"
            data-testid="model-route-blocked-note"
          >
            <AlertTriangle size={12} className="shrink-0" />
            Live diagnose is blocked: no admitted local model.
          </li>
        )}
        <li
          className="flex items-center gap-1.5 text-gray-500"
          data-testid="model-route-network-blocked-note"
        >
          <WifiOff size={12} className="shrink-0" />
          Network/cloud providers are blocked by default.
        </li>
      </ul>
    </section>
  );
}
