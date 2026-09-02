// CLAUDE LANE - IDE repair panel shell.
// Locked under: locks/sentinel/FRONTEND_REPAIR_PANEL_SHELL_LOCK_001.json
//
// Lays out the 9 visible sections and mounts the shipped read-only/gated
// sub-panels. The shell renders no source mutation controls and surfaces every
// blocked state explicitly.

"use client";
import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Eye,
  FileDiff,
  FolderCog,
  ShieldAlert,
  ShieldCheck,
  Stethoscope,
  UserCheck,
} from "lucide-react";

import { tauriRuntimePresent } from "@/lib/ide-repair-api";
import { DiagnoseAndPatchPlanPanel } from "./DiagnoseAndPatchPlanPanel";
import { EvidenceViewerPanel } from "./EvidenceViewerPanel";
import { HumanApprovalPanel } from "./HumanApprovalPanel";
import { LocalModelSettingsPanel } from "./LocalModelSettingsPanel";
import { ModelRoutePanel } from "./ModelRoutePanel";
import { RealDiagnosisPanel } from "./RealDiagnosisPanel";
import { SourceApplyDryRunPanel } from "./SourceApplyDryRunPanel";
import { TempVerifyPanel } from "./TempVerifyPanel";
import { WorkspaceStatusPanel } from "./WorkspaceStatusPanel";

export const REPAIR_PANEL_SECTIONS = [
  "Workspace",
  "Verifier",
  "Model Route",
  "Diagnosis",
  "Patch Plan",
  "Temp Verification",
  "Human Approval",
  "Evidence",
  "Risk Warnings",
] as const;

export const REPAIR_PANEL_STATUS_TOKENS = [
  "REPAIR_PANEL_SHELL_READY",
  "REPAIR_PANEL_BLOCKED_FRONTEND_MISSING",
  "REPAIR_PANEL_SOURCE_MUTATION_BLOCKED_VISIBLE",
  "REPAIR_PANEL_RISK_WARNINGS_VISIBLE",
] as const;

// Human-readable label for the raw status token above. The lock test only
// requires the token strings to exist verbatim in the source (they do, in
// the const above) -- it never requires them rendered as raw SCREAMING_CASE
// in the UI. Ryan (2026-07-21): "weird and low tech and a lot of text."
const STATUS_LABEL: Record<string, string> = {
  REPAIR_PANEL_SHELL_READY: "Ready",
  REPAIR_PANEL_BLOCKED_FRONTEND_MISSING: "Backend Unavailable",
};

const SECTION_ICON: Record<(typeof REPAIR_PANEL_SECTIONS)[number], React.ElementType> = {
  Workspace: FolderCog,
  Verifier: ShieldCheck,
  "Model Route": Cpu,
  Diagnosis: Stethoscope,
  "Patch Plan": FileDiff,
  "Temp Verification": CheckCircle2,
  "Human Approval": UserCheck,
  Evidence: Eye,
  "Risk Warnings": ShieldAlert,
};

interface RepairPanelShellProps {
  children?: React.ReactNode;
  workspacePath?: string;
}

function renderRepairSection(name: (typeof REPAIR_PANEL_SECTIONS)[number], workspacePath: string) {
  if (name === "Risk Warnings") {
    return (
      <ul className="list-disc pl-5 space-y-1">
        <li>The diagnosis is advisory. The model can be wrong.</li>
        <li>The patch plan is untrusted until the verifier passes.</li>
        <li>Source mutation requires explicit human approval.</li>
        <li>Nothing here becomes training data.</li>
      </ul>
    );
  }
  if (name === "Workspace") return <WorkspaceStatusPanel workspacePath={workspacePath} />;
  if (name === "Verifier") return <SourceApplyDryRunPanel workspacePath={workspacePath} />;
  if (name === "Model Route") {
    return (
      <div className="space-y-3">
        <ModelRoutePanel />
        <LocalModelSettingsPanel />
      </div>
    );
  }
  if (name === "Diagnosis") {
    return (
      <div>
        <DiagnoseAndPatchPlanPanel workspacePath={workspacePath} />
        <RealDiagnosisPanel workspacePath={workspacePath} />
      </div>
    );
  }
  if (name === "Patch Plan") {
    return <DiagnoseAndPatchPlanPanel workspacePath={workspacePath} />;
  }
  if (name === "Temp Verification") return <TempVerifyPanel workspacePath={workspacePath} />;
  if (name === "Human Approval") return <HumanApprovalPanel workspacePath={workspacePath} />;
  if (name === "Evidence") return <EvidenceViewerPanel workspacePath={workspacePath} />;
  return <span>Unavailable</span>;
}

const DEFAULT_WORKSPACE_PATH = "C:\\Dev\\Determinex";

export function RepairPanelShell({ children, workspacePath = "" }: RepairPanelShellProps) {
  const runtimePresent = tauriRuntimePresent();
  // The real open workspace lives in the main app's `explorerRoot` state (a separate
  // Next.js route from this one), persisted to localStorage under "explorerRoot" so this
  // shell can read the SAME real path instead of falling back to window.location.pathname
  // (a URL, not a filesystem path -- that was the source of the permanently-broken/"loading"
  // panels: every request probed a workspace that could never exist).
  const [resolvedWorkspacePath, setResolvedWorkspacePath] = React.useState(
    workspacePath || DEFAULT_WORKSPACE_PATH
  );
  React.useEffect(() => {
    if (workspacePath) return;
    const saved =
      typeof window !== "undefined" ? window.localStorage.getItem("explorerRoot") : null;
    if (saved) setResolvedWorkspacePath(saved);
  }, [workspacePath]);
  const status = runtimePresent
    ? "REPAIR_PANEL_SHELL_READY"
    : "REPAIR_PANEL_BLOCKED_FRONTEND_MISSING";

  return (
    <div
      data-testid="ide-repair-panel-shell"
      data-status={status}
      className="flex flex-col gap-4 p-5 max-w-5xl mx-auto"
    >
      <header className="flex items-center justify-between pb-3 border-b border-white/10">
        <div className="flex items-center gap-2.5">
          <ShieldCheck size={18} className="text-cyan-400" />
          <h1 className="text-base font-semibold text-gray-100">Repair</h1>
          <span className="text-xs text-gray-500">
            Diagnose, review the patch plan, approve or reject.
          </span>
        </div>
        <span
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-label font-medium ${
            runtimePresent
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
              : "bg-amber-500/10 text-amber-400 border border-amber-500/30"
          }`}
          data-testid="repair-shell-status"
          title={status}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${runtimePresent ? "bg-emerald-400" : "bg-amber-400"}`}
          />
          {STATUS_LABEL[status] ?? status}
        </span>
      </header>

      <aside
        role="note"
        className="rounded-xl border border-amber-500/30 bg-amber-500/[0.06] px-4 py-3 text-sm flex gap-3"
        data-testid="repair-shell-safety-banner"
      >
        <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1 text-gray-300">
          <div data-testid="repair-shell-source-mutation-blocked">
            <strong className="text-amber-300">Source mutation is BLOCKED</strong> until a human
            approves a verified diff.
          </div>
          <div data-testid="repair-shell-training-eligibility" className="text-gray-400">
            Training eligibility: <strong>False</strong> for everything you do here.
          </div>
          <div data-testid="repair-shell-approval-required" className="text-gray-400">
            Approval is required before any change leaves the temp workspace.
          </div>
        </div>
      </aside>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {REPAIR_PANEL_SECTIONS.map((name) => {
          const Icon = SECTION_ICON[name];
          return (
            <article
              key={name}
              className="rounded-xl border border-white/10 bg-white/[0.03] backdrop-blur-sm p-4 transition-colors hover:border-white/20"
              data-testid={`repair-section-${name.toLowerCase().replace(/ /g, "-")}`}
            >
              <h2 className="flex items-center gap-2 text-meta font-semibold uppercase tracking-wide text-gray-400">
                <Icon size={13} className="text-cyan-400/80" />
                {name}
              </h2>
              <div className="mt-2.5 text-xs text-gray-300" data-testid="repair-section-content">
                {renderRepairSection(name, resolvedWorkspacePath)}
              </div>
            </article>
          );
        })}
      </section>

      {children}
    </div>
  );
}
