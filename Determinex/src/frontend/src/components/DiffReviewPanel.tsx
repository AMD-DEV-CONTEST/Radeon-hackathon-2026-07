import React, { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { invokeSafe, isTauri } from "../lib/api";
import { DiffEditor } from "@monaco-editor/react";
import { Check, X, GitCompare, Save, Trash2, Loader2, Columns2, Rows2 } from "lucide-react";

export function DiffReviewPanel() {
  const [stagedDiffs, setStagedDiffs] = useState<any[]>([]);
  const [selectedDiffId, setSelectedDiffId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionInProgress, setActionInProgress] = useState(false);
  const [sideBySide, setSideBySide] = useState(true);

  // invokeSafe returns null both when the backend is unreachable and never
  // when the list is genuinely empty -- so "no diffs" and "no backend" used to
  // render the identical "No pending changes to review." Same
  // empty-state-doubles-as-something-else bug class already fixed in the Space
  // panel and ToolsRegistry: the reassuring message was shown in cases where
  // nothing had actually been checked.
  const fetchDiffs = async () => {
    try {
      const diffs = await invokeSafe<any[]>("get_staged_diffs", {});
      if (diffs === null) {
        setUnreachable(true);
        setStagedDiffs([]);
        setSelectedDiffId(null);
        return;
      }
      setUnreachable(false);
      setStagedDiffs(diffs);
      if (diffs.length > 0 && !selectedDiffId) {
        setSelectedDiffId(diffs[0].id);
      } else if (diffs.length === 0) {
        setSelectedDiffId(null);
      }
    } catch (e) {
      console.error("Failed to load staged diffs", e);
      setUnreachable(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDiffs();
    const int = setInterval(fetchDiffs, 10000);
    return () => clearInterval(int);
  }, []);

  // Raw invoke, not invokeSafe. apply_staged_diff really can refuse -- it
  // rejects any path outside the workspace boundary, and the write itself can
  // fail -- but invokeSafe swallowed that into null and the catch below only
  // console.error'd. The result was an "Apply Change" click that did nothing,
  // left the row in place, and explained nothing, inviting the user to keep
  // clicking a button that could never work for that diff.
  const runDiffAction = async (cmd: string, id: string, verb: string) => {
    setActionInProgress(true);
    setActionError(null);
    try {
      await invoke(cmd, { id });
    } catch (e) {
      setActionError(
        `Could not ${verb} this change: ${e instanceof Error ? e.message : String(e)}`
      );
    } finally {
      // Refresh either way: on success the row is gone, on failure it must stay
      // visible rather than appearing to have been handled.
      await fetchDiffs();
      setActionInProgress(false);
    }
  };

  const handleApply = (id: string) => runDiffAction("apply_staged_diff", id, "apply");
  const handleReject = (id: string) => runDiffAction("reject_staged_diff", id, "reject");

  const selectedDiff = stagedDiffs.find((d) => d.id === selectedDiffId);

  if (loading && stagedDiffs.length === 0) {
    return (
      <div className="flex-1 bg-[var(--dtx-code-bg)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-full bg-[var(--dtx-code-bg)] text-[var(--dtx-code-text)]">
      <div className="w-64 border-r border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] flex flex-col">
        <div className="p-4 border-b border-[var(--dtx-code-border)] flex items-center gap-2">
          <GitCompare className="w-4 h-4 text-purple-400" />
          <h2 className="text-sm font-bold text-white">AI Proposed Changes</h2>
        </div>
        <div className="flex-1 overflow-y-auto">
          {unreachable ? (
            <div className="p-4 text-xs text-amber-300/80">
              {isTauri()
                ? "Could not reach the staged-diff backend, so nothing has been checked."
                : "Browser mode cannot read staged diffs — this needs the desktop runtime."}
            </div>
          ) : stagedDiffs.length === 0 ? (
            <div className="space-y-2 p-4">
              <p className="text-xs italic text-[var(--dtx-code-muted)]">
                No changes waiting for review. An agent stages a diff here whenever it proposes an
                edit — nothing touches your files until you approve it.
              </p>
              {/* Names the one producer that exists rather than implying every
                  agent feeds this queue. stage_diff_for_review is still the
                  staging store's only writer; Verified Search now calls it, but
                  the hive fix path does not -- it writes to your files directly
                  and reverts on failure, so git is its review surface. */}
              <p className="text-label leading-relaxed text-[#6e7681]">
                Verified Search queues oracle-verified programs here with{" "}
                <span className="text-[var(--dtx-code-muted)]">Stage for review</span>. Agent edits
                do not land here — for your own uncommitted work, open Source Control.
              </p>
            </div>
          ) : (
            stagedDiffs.map((diff) => (
              <div
                key={diff.id}
                onClick={() => setSelectedDiffId(diff.id)}
                className={
                  "p-3 border-b border-[var(--dtx-code-border)] cursor-pointer hover:bg-[var(--dtx-code-border-subtle)] transition-colors " +
                  (selectedDiffId === diff.id
                    ? "bg-[var(--dtx-code-border-subtle)] border-l-2 border-l-purple-500"
                    : "")
                }
              >
                <div className="text-sm font-mono truncate text-blue-400">
                  {diff.path.split(/[/\\]/).pop()}
                </div>
                <div className="text-xs text-[var(--dtx-code-muted)] truncate">{diff.path}</div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        {/* A refused apply/reject must say so. The row deliberately stays in
            the list on failure, so without this the button would just look
            inert. */}
        {actionError && (
          <div className="flex shrink-0 items-start gap-2 border-b border-red-500/30 bg-red-950/30 px-4 py-2">
            <X className="mt-0.5 h-3 w-3 shrink-0 text-red-400" />
            <p className="flex-1 font-mono text-label leading-relaxed text-red-300">
              {actionError}
            </p>
            <button
              onClick={() => setActionError(null)}
              className="shrink-0 text-red-400/60 transition-colors hover:text-red-300"
              title="Dismiss"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        {selectedDiff ? (
          <>
            <div className="h-14 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-4 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-mono text-[var(--dtx-code-muted)]">
                  {selectedDiff.path}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSideBySide((v) => !v)}
                  title={sideBySide ? "Switch to inline diff" : "Switch to side-by-side diff"}
                  className="px-2.5 py-1.5 flex items-center gap-1.5 text-xs font-medium text-[var(--dtx-code-muted)] hover:bg-white/5 border border-white/10 rounded transition-colors"
                >
                  {sideBySide ? (
                    <Rows2 className="w-3.5 h-3.5" />
                  ) : (
                    <Columns2 className="w-3.5 h-3.5" />
                  )}
                  {sideBySide ? "Inline" : "Side-by-side"}
                </button>
                <button
                  onClick={() => handleReject(selectedDiff.id)}
                  disabled={actionInProgress}
                  className="px-3 py-1.5 flex items-center gap-1.5 text-sm font-medium text-red-400 hover:bg-red-500/10 border border-red-500/20 rounded transition-colors disabled:opacity-50"
                >
                  <Trash2 className="w-4 h-4" /> Reject
                </button>
                <button
                  onClick={() => handleApply(selectedDiff.id)}
                  disabled={actionInProgress}
                  className="px-3 py-1.5 flex items-center gap-1.5 text-sm font-medium text-green-400 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 rounded transition-colors disabled:opacity-50"
                >
                  <Save className="w-4 h-4" /> Apply Change
                </button>
              </div>
            </div>
            <div className="flex-1 min-h-0">
              <DiffEditor
                theme="vs-dark"
                original={selectedDiff.originalContent}
                modified={selectedDiff.proposedContent}
                options={{
                  readOnly: true,
                  renderSideBySide: sideBySide,
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                }}
              />
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center opacity-50">
            <Check className="w-16 h-16 text-green-500 mb-4" />
            <p className="text-lg">All caught up!</p>
            <p className="text-sm text-[var(--dtx-code-muted)]">
              No AI changes pending your review.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
