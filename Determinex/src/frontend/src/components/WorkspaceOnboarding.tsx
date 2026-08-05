import React, { useEffect, useState } from "react";
import { invokeSafe } from "../lib/api";
import { ShieldCheck, ArrowRight, Server, Terminal, Settings, Loader2, Wrench } from "lucide-react";

type Props = {
  workspacePath: string;
  onClose: () => void;
};

// Maps analyze_workspace's display-string inferredStack entries to the toolchain-installer's
// oracle language keys. Deliberately narrow: inferredStack is about THIS repo's build tooling
// (npm/cargo for Execute Action), not the full oracle registry, and Node.js isn't something
// determinex_toolchain_installer.py manages per-project (it's a prerequisite for the app
// itself, already required before this dialog could even be showing).
const STACK_TO_TOOLCHAIN: Record<string, { key: string; label: string }> = {
  "Rust (Tauri)": { key: "rust", label: "Rust" },
  Python: { key: "python", label: "Python" },
};

type ToolchainInstallResult = {
  language: string;
  alreadyAvailable: boolean;
  attempted: boolean;
  installer: string;
  command: string;
  succeeded: boolean;
  output: string;
  notes: string[];
};

export function WorkspaceOnboarding({ workspacePath, onClose }: Props) {
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<string | null>(null);
  const didSucceed = executionResult?.startsWith("Done:") ?? false;
  const [missingToolchain, setMissingToolchain] = useState<{ key: string; label: string } | null>(
    null
  );
  const [installingToolchain, setInstallingToolchain] = useState(false);
  const [toolchainNote, setToolchainNote] = useState<string | null>(null);

  useEffect(() => {
    async function analyze() {
      try {
        const result = await invokeSafe<any>("analyze_workspace", { workspace: workspacePath });
        setAnalysis(result);

        // "As needed during a project they open" -- check whether THIS project's detected
        // stack actually has its toolchain available, and if not, offer the same one-click
        // install the Setup Wizard offers up front. Best-effort: a failed probe just means no
        // banner shows, never blocks the rest of this dialog.
        const stackEntries: { key: string; label: string }[] = (result?.inferredStack ?? [])
          .map((s: string) => STACK_TO_TOOLCHAIN[s])
          .filter(Boolean);
        if (stackEntries.length > 0) {
          const toolchains = await invokeSafe<Record<string, boolean>>("list_toolchains", {});
          const firstMissing = stackEntries.find((e) => toolchains && !toolchains[e.key]);
          if (firstMissing) setMissingToolchain(firstMissing);
        }
      } catch (e) {
        console.error("Failed to analyze workspace", e);
      } finally {
        setLoading(false);
      }
    }
    analyze();
  }, [workspacePath]);

  const installMissingToolchain = async () => {
    if (!missingToolchain) return;
    setInstallingToolchain(true);
    setToolchainNote(null);
    try {
      const res = await invokeSafe<ToolchainInstallResult>("install_toolchain", {
        language: missingToolchain.key,
      });
      if (res?.succeeded) {
        setMissingToolchain(null);
        setToolchainNote(`${missingToolchain.label} installed and verified.`);
      } else {
        setToolchainNote(res?.notes?.[0] ?? "Install did not complete.");
      }
    } catch (e) {
      setToolchainNote(String(e));
    } finally {
      setInstallingToolchain(false);
    }
  };

  const executeAction = async () => {
    if (!analysis?.actionCommand) {
      onClose();
      return;
    }
    setExecuting(true);
    setExecutionResult(null);
    try {
      const result = await invokeSafe<{ stdout: string; stderr: string; exit_code: number | null }>(
        "run_terminal_command",
        { command: analysis.actionCommand, cwd: analysis.actionCwd || workspacePath }
      );
      setExecutionResult(
        result && result.exit_code === 0
          ? `Done: ${analysis.actionCommand}`
          : `Failed (exit ${result?.exit_code}): ${result?.stderr || result?.stdout || "unknown error"}`
      );
    } catch (e) {
      setExecutionResult(`Failed to run: ${e}`);
    } finally {
      setExecuting(false);
    }
  };

  // A spinner is never worth blocking the application for. This used to be
  // `fixed inset-0 z-50` -- a full-bleed blocker whose entire content was a
  // spinner, rendered BEFORE the dismiss button existed, so there was a window in
  // which the app was unusable and offered no way out. It also broke two attempts
  // at automating this app, because every click landed on an invisible overlay.
  if (loading) {
    return (
      <div
        data-testid="workspace-onboarding"
        role="status"
        aria-live="polite"
        className="fixed bottom-10 right-4 z-40 flex items-center gap-2.5 rounded-xl border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] px-4 py-3 shadow-2xl"
      >
        <div className="h-4 w-4 animate-spin rounded-full border-b-2 border-t-2 border-blue-500" />
        <p className="text-label text-[var(--dtx-code-muted)]">Scanning workspace stack...</p>
      </div>
    );
  }

  return (
    <div
      data-testid="workspace-onboarding"
      role="dialog"
      aria-label="Workspace detected"
      /* Was a centred full-screen modal with a backdrop. A workspace scan reports
         a FINDING; it does not need a decision before the app can be used, and
         gating the whole IDE behind it is the single worst piece of first-run
         friction measured in the UI review. Now an anchored sheet: dismissible,
         non-blocking, and it cannot swallow clicks meant for the shell. */
      className="fixed bottom-10 right-4 z-40 flex max-h-[80vh] w-full max-w-xl flex-col"
    >
      <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] shadow-2xl">
        <div className="bg-[var(--dtx-code-border-subtle)] border-b border-[var(--dtx-code-border)] px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Server className="w-5 h-5 text-blue-400" /> Workspace Detected
          </h2>
        </div>

        <div className="p-6 space-y-6">
          <div className="bg-[var(--dtx-code-bg)] border border-[var(--dtx-code-border)] rounded-lg p-4 space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sm text-[var(--dtx-code-muted)]">Inferred Stack</span>
              <div className="flex gap-2">
                {analysis?.inferredStack?.map((stack: string) => (
                  <span
                    key={stack}
                    className="px-2 py-1 bg-[var(--dtx-ok)]/20 text-[var(--dtx-ok)] border border-[var(--dtx-ok)]/50 rounded text-xs font-mono"
                  >
                    {stack}
                  </span>
                ))}
              </div>
            </div>

            {analysis?.buildCommand && (
              <div className="flex justify-between items-center">
                <span className="text-sm text-[var(--dtx-code-muted)]">Build Command</span>
                <span className="px-2 py-1 bg-gray-800 text-gray-300 rounded text-xs font-mono flex items-center gap-2">
                  <Terminal className="w-3 h-3" /> {analysis.buildCommand}
                </span>
              </div>
            )}
          </div>

          {missingToolchain && (
            <div className="p-4 border border-amber-500/30 bg-amber-500/10 rounded-lg flex items-start gap-4">
              <div className="mt-1 bg-amber-500/20 p-2 rounded-md">
                <Wrench className="w-5 h-5 text-amber-400" />
              </div>
              <div className="flex-1">
                <h4 className="text-sm font-bold text-amber-300">
                  {missingToolchain.label} toolchain not detected
                </h4>
                <p className="text-xs text-[var(--dtx-code-muted)] mt-1">
                  This project&apos;s detected stack needs {missingToolchain.label}, but it
                  wasn&apos;t found on this machine. Determinex&apos;s compiler oracle verifies
                  every change against a real build/test run -- without this toolchain, that
                  verification can&apos;t run for this project.
                </p>
                {toolchainNote && (
                  <p className="text-xs text-amber-200/90 mt-2 font-mono">{toolchainNote}</p>
                )}
              </div>
              <button
                onClick={installMissingToolchain}
                disabled={installingToolchain}
                className="shrink-0 px-3 py-1.5 bg-amber-600/80 hover:bg-amber-600 disabled:opacity-60 text-white text-xs font-medium rounded-md shadow-sm flex items-center gap-1.5 transition-colors"
              >
                {installingToolchain ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Wrench className="w-3.5 h-3.5" />
                )}
                Install
              </button>
            </div>
          )}

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-white">Recommended Next Action</h3>
            <div className="p-4 border border-blue-500/30 bg-blue-500/10 rounded-lg flex items-start gap-4">
              <div className="mt-1 bg-blue-500/20 p-2 rounded-md">
                <ShieldCheck className="w-5 h-5 text-blue-400" />
              </div>
              <div className="flex-1">
                <h4 className="text-sm font-bold text-blue-300">{analysis?.recommendedAction}</h4>
                <p className="text-xs text-[var(--dtx-code-muted)] mt-1">
                  Based on the detected stack, this is the safest first step to ensure your
                  workspace is ready for AI ideation.
                </p>
              </div>
            </div>
          </div>

          {executionResult && (
            <div className="text-xs font-mono text-[var(--dtx-code-muted)] bg-[var(--dtx-code-bg)] border border-[var(--dtx-code-border)] rounded p-2 whitespace-pre-wrap">
              {executionResult}
            </div>
          )}

          {/* The command really did run (confirmed live: a real `npm run
              build` produced fresh frontend/out/ + .next/ output) -- but
              rebuilding static output has no visible effect on this
              already-running instance, and the dialog gave no indication of
              what to do next, which read as "nothing happened" even on a
              genuine success. */}
          {didSucceed && (
            <p className="text-xs text-[var(--dtx-ok)] leading-relaxed">
              This ran for real and finished cleanly. It won&apos;t change anything visible in this
              window -- rebuilding static output doesn&apos;t hot-reload a running instance.
              You&apos;re clear to continue.
            </p>
          )}
        </div>

        <div className="bg-[var(--dtx-code-bg)] border-t border-[var(--dtx-code-border)] px-6 py-4 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--dtx-code-muted)] hover:text-white transition-colors"
          >
            Dismiss
          </button>
          {didSucceed ? (
            <button
              onClick={onClose}
              className="px-4 py-2 bg-[var(--dtx-ok)] hover:bg-[var(--dtx-ok)] text-white text-sm font-medium rounded-md shadow-sm flex items-center gap-2 transition-colors"
            >
              Continue <ArrowRight className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={executeAction}
              disabled={executing}
              className="px-4 py-2 bg-[var(--dtx-ok)] hover:bg-[var(--dtx-ok)] disabled:opacity-60 text-white text-sm font-medium rounded-md shadow-sm flex items-center gap-2 transition-colors"
            >
              {executing ? (
                <>
                  Running <Loader2 className="w-4 h-4 animate-spin" />
                </>
              ) : (
                <>
                  Execute Action <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
