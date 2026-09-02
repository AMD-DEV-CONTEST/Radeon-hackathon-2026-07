// CLAUDE LANE — Unified product navigation panel.
// Locked under:
//   locks/sentinel/DETERMINEX_REACT_UNIFIED_NAVIGATION_PANEL_LOCK_001.json
//
// Live frontend navigation shell for the five product surfaces:
//   - Idea Lab
//   - Repo Clinic
//   - Maintenance Bay
//   - Learning Studio
//   - Proof / Operator Center
//
// Reads the locked backend view-model via
//   invokeUnifiedProductCommand("get_unified_product_navigation_model")
// and renders one tab per surface. Every surface shows: purpose,
// current status, blocked states, what is allowed, what is NOT
// authorized. No green/success state without negative authority text.

"use client";
import * as React from "react";

import {
  invokeUnifiedProductCommand,
  READY_DOES_NOT_MEAN_AUTHORIZED,
  SHARED_AUTHORITY_VOCABULARY,
  UnifiedProductResponse,
  UNIFIED_PRODUCT_SURFACES,
  UnifiedProductSurfaceKey,
} from "@/lib/ide-product-shell-api";

export const REACT_UNIFIED_NAVIGATION_PANEL_STATUS_TOKENS = [
  "REACT_UNIFIED_NAVIGATION_PANEL_PASSED",
  "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_MISSING_SURFACE",
  "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_AUTHORITY_CONFUSION",
  "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_HIDDEN_BLOCKED_STATE",
] as const;

interface ProductSurfaceVm {
  key: string;
  title: string;
  purpose: string;
  blocked_states: string[];
  source_mutation_boundary: string;
  training_eligibility_boundary: string;
  claim_caveats: string[];
}

const SURFACE_LABELS: Record<UnifiedProductSurfaceKey, string> = {
  idea_lab: "Idea Lab",
  repo_clinic: "Repo Clinic",
  maintenance_bay: "Maintenance Bay",
  learning_studio: "Learning Studio",
  proof_operator_center: "Proof / Operator Center",
};

export function UnifiedNavigationPanel() {
  const [resp, setResp] = React.useState<UnifiedProductResponse | null>(null);
  const [active, setActive] = React.useState<UnifiedProductSurfaceKey>("idea_lab");
  const [loading, setLoading] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await invokeUnifiedProductCommand("get_unified_product_navigation_model");
      setResp(r);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const payload = (resp?.payload ?? {}) as Record<string, unknown>;
  const surfaces = (payload.surfaces ?? []) as ProductSurfaceVm[];
  const byKey = new Map(surfaces.map((s) => [s.key, s]));
  const activeSurface = byKey.get(active);

  // All five surfaces must be present; if any is missing we surface
  // a BLOCKED_MISSING_SURFACE banner rather than silently skipping.
  const missingSurfaces = UNIFIED_PRODUCT_SURFACES.filter((k) => !byKey.has(k));
  const allPresent = missingSurfaces.length === 0;

  const renderStatus = !resp
    ? "loading"
    : !allPresent
      ? "REACT_UNIFIED_NAVIGATION_PANEL_BLOCKED_MISSING_SURFACE"
      : "REACT_UNIFIED_NAVIGATION_PANEL_PASSED";

  return (
    <section
      data-testid="unified-navigation-panel"
      data-status={renderStatus}
      className="rounded border p-3 text-sm"
    >
      <header className="flex items-center justify-between">
        <h2 className="font-medium">Determinex — Unified Product Shell</h2>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="text-xs underline opacity-80 hover:opacity-100"
          data-testid="unified-navigation-refresh"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <nav
        role="tablist"
        className="mt-2 flex gap-2 border-b"
        data-testid="unified-navigation-tabs"
      >
        {UNIFIED_PRODUCT_SURFACES.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={active === k}
            data-testid={`unified-navigation-tab-${k}`}
            data-surface={k}
            onClick={() => setActive(k)}
            className={
              "px-3 py-1 text-xs " + (active === k ? "font-semibold underline" : "opacity-70")
            }
          >
            {SURFACE_LABELS[k]}
          </button>
        ))}
      </nav>

      {!allPresent && (
        <div
          data-testid="unified-navigation-missing-surface-banner"
          className="mt-2 text-amber-600"
        >
          Missing surfaces: {missingSurfaces.join(", ")}
        </div>
      )}

      {activeSurface && (
        <div
          data-testid={`unified-navigation-content-${activeSurface.key}`}
          className="mt-3 space-y-2"
        >
          <div data-testid="unified-navigation-purpose">
            <strong>Purpose:</strong> {activeSurface.purpose}
          </div>

          <div data-testid="unified-navigation-blocked-states">
            <strong>Blocked / unsupported states:</strong>
            <ul className="ml-4 list-disc">
              {activeSurface.blocked_states.map((b) => (
                <li key={b} className="font-mono text-xs">
                  {b}
                </li>
              ))}
            </ul>
          </div>

          <div data-testid="unified-navigation-what-is-allowed">
            <strong>What this surface does:</strong> {activeSurface.purpose}
          </div>

          <div data-testid="unified-navigation-what-is-not-authorized">
            <strong>What is NOT authorized here:</strong> source mutation boundary:{" "}
            {activeSurface.source_mutation_boundary}. Training:{" "}
            {activeSurface.training_eligibility_boundary}.
          </div>

          <div
            data-testid="unified-navigation-ready-does-not-mean-authorized"
            className="text-xs opacity-80"
          >
            {READY_DOES_NOT_MEAN_AUTHORIZED}
          </div>

          <div data-testid="unified-navigation-claim-caveats">
            <strong>Caveats:</strong>
            <ul className="ml-4 list-disc">
              {activeSurface.claim_caveats.map((c) => (
                <li key={c} className="text-xs">
                  {c}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <footer
        data-testid="unified-navigation-authority-vocabulary"
        className="mt-3 border-t pt-2 text-xs opacity-70"
      >
        Shared authority vocabulary:{" "}
        <span className="font-mono">{SHARED_AUTHORITY_VOCABULARY.join(" / ")}</span>
      </footer>
    </section>
  );
}
