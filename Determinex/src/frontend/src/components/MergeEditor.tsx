import React, { useEffect, useState, useCallback } from "react";
import Editor, { DiffEditor } from "@monaco-editor/react";
import { GitMerge, Check, Loader2, AlertTriangle, Columns2, Rows2 } from "lucide-react";
import { getGitStatus, type GitFile } from "../lib/gitService";
import { getConflictSides, resolveConflict, type ConflictSides } from "../lib/gitService";
import { isTauri } from "../lib/api";

// A merge conflict has THREE pre-merge sides (base/ours/theirs) plus the raw
// conflict-marked working-tree text. VS Code's own merge editor shows ours/theirs/result
// panes with per-conflict accept controls; this is a pragmatic real v1 of the same idea
// built on the Monaco editor already wired into DiffReviewPanel -- two read-only diff
// panes (base-vs-ours, base-vs-theirs) for context, plus one editable result pane
// pre-seeded with the real conflict markers, with quick "Use Ours/Theirs/Both" actions
// that replace the result content programmatically. "Mark Resolved" writes the file and
// `git add`s it, exactly mirroring what a human resolving the conflict by hand would do.
interface MergeEditorProps {
  workspacePath: string;
}

export function MergeEditor({ workspacePath }: MergeEditorProps) {
  const [conflicted, setConflicted] = useState<GitFile[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [sides, setSides] = useState<ConflictSides | null>(null);
  const [resultText, setResultText] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [loadingSides, setLoadingSides] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sideBySide, setSideBySide] = useState(false);

  const refreshConflicts = useCallback(async () => {
    if (!workspacePath) return;
    try {
      const status = await getGitStatus(workspacePath);
      const files = status.files.filter((f) => f.status === "conflicted");
      setConflicted(files);
      setSelectedPath((prev) => {
        if (prev && files.some((f) => f.path === prev)) return prev;
        return files.length > 0 ? files[0].path : null;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    if (!isTauri()) {
      setLoading(false);
      return;
    }
    void refreshConflicts();
    const id = setInterval(refreshConflicts, 10000);
    return () => clearInterval(id);
  }, [refreshConflicts]);

  useEffect(() => {
    if (!selectedPath || !workspacePath) {
      setSides(null);
      return;
    }
    setLoadingSides(true);
    setError(null);
    getConflictSides(workspacePath, selectedPath)
      .then((s) => {
        setSides(s);
        setResultText(s.current ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingSides(false));
  }, [selectedPath, workspacePath]);

  const useOurs = () => setResultText(sides?.ours ?? "");
  const useTheirs = () => setResultText(sides?.theirs ?? "");
  const useBoth = () => setResultText(`${sides?.ours ?? ""}\n${sides?.theirs ?? ""}`);

  const markResolved = async () => {
    if (!selectedPath || !workspacePath) return;
    setBusy(true);
    setError(null);
    try {
      await resolveConflict(workspacePath, selectedPath, resultText);
      await refreshConflicts();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 bg-[var(--dtx-code-bg)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  if (!isTauri()) {
    return (
      <div className="flex-1 bg-[var(--dtx-code-bg)] flex flex-col items-center justify-center gap-2 text-center opacity-40">
        <p className="text-label text-gray-500">Browser mode cannot read real git merge state</p>
        <p className="text-label text-gray-600">Open the Tauri desktop app to resolve conflicts.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full bg-[var(--dtx-code-bg)] text-[var(--dtx-code-text)]">
      <div className="w-64 border-r border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] flex flex-col shrink-0">
        <div className="p-4 border-b border-[var(--dtx-code-border)] flex items-center gap-2">
          <GitMerge className="w-4 h-4 text-orange-400" />
          <h2 className="text-sm font-bold text-white">Merge Conflicts</h2>
        </div>
        <div className="flex-1 overflow-y-auto">
          {conflicted.length === 0 ? (
            <div className="p-4 text-xs text-[var(--dtx-code-muted)] italic">
              No unresolved conflicts.
            </div>
          ) : (
            conflicted.map((f) => (
              <div
                key={f.path}
                onClick={() => setSelectedPath(f.path)}
                className={
                  "p-3 border-b border-[var(--dtx-code-border)] cursor-pointer hover:bg-[var(--dtx-code-border-subtle)] transition-colors " +
                  (selectedPath === f.path
                    ? "bg-[var(--dtx-code-border-subtle)] border-l-2 border-l-orange-500"
                    : "")
                }
              >
                <div className="flex items-center gap-1.5 text-sm font-mono truncate text-orange-400">
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  {f.path.split(/[/\\]/).pop()}
                </div>
                <div className="text-xs text-[var(--dtx-code-muted)] truncate">{f.path}</div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0">
        {error && (
          <div className="shrink-0 px-4 py-2 text-xs text-red-400 bg-red-500/10 border-b border-red-500/20">
            {error}
          </div>
        )}
        {!selectedPath ? (
          <div className="flex-1 flex flex-col items-center justify-center opacity-50">
            <Check className="w-16 h-16 text-green-500 mb-4" />
            <p className="text-lg">No conflicts to resolve.</p>
          </div>
        ) : loadingSides || !sides ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-6 h-6 text-blue-500 animate-spin" />
          </div>
        ) : (
          <>
            <div className="h-14 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-4 flex items-center justify-between shrink-0">
              <span className="text-sm font-mono text-[var(--dtx-code-muted)]">{selectedPath}</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSideBySide((v) => !v)}
                  title={
                    sideBySide
                      ? "Switch context diffs to inline"
                      : "Switch context diffs to side-by-side"
                  }
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
                  onClick={useOurs}
                  disabled={busy}
                  className="px-2.5 py-1.5 text-xs font-medium text-blue-400 hover:bg-blue-500/10 border border-blue-500/20 rounded transition-colors disabled:opacity-50"
                >
                  Use Ours
                </button>
                <button
                  onClick={useTheirs}
                  disabled={busy}
                  className="px-2.5 py-1.5 text-xs font-medium text-purple-400 hover:bg-purple-500/10 border border-purple-500/20 rounded transition-colors disabled:opacity-50"
                >
                  Use Theirs
                </button>
                <button
                  onClick={useBoth}
                  disabled={busy}
                  className="px-2.5 py-1.5 text-xs font-medium text-gray-400 hover:bg-white/5 border border-white/10 rounded transition-colors disabled:opacity-50"
                >
                  Use Both
                </button>
                <button
                  onClick={() => void markResolved()}
                  disabled={busy}
                  className="px-3 py-1.5 flex items-center gap-1.5 text-sm font-medium text-green-400 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 rounded transition-colors disabled:opacity-50"
                >
                  <Check className="w-4 h-4" /> Mark Resolved
                </button>
              </div>
            </div>

            <div className="flex-1 min-h-0 grid grid-rows-2">
              <div className="grid grid-cols-2 divide-x divide-[var(--dtx-code-border)] min-h-0">
                <div className="flex flex-col min-h-0">
                  <div className="shrink-0 px-3 py-1 text-meta uppercase font-bold tracking-wide text-blue-400 bg-black/20 border-b border-[var(--dtx-code-border)]">
                    Ours (base &rarr; ours)
                  </div>
                  <div className="flex-1 min-h-0">
                    <DiffEditor
                      theme="vs-dark"
                      original={sides.base ?? ""}
                      modified={sides.ours ?? ""}
                      options={{
                        readOnly: true,
                        renderSideBySide: sideBySide,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                      }}
                    />
                  </div>
                </div>
                <div className="flex flex-col min-h-0">
                  <div className="shrink-0 px-3 py-1 text-meta uppercase font-bold tracking-wide text-purple-400 bg-black/20 border-b border-[var(--dtx-code-border)]">
                    Theirs (base &rarr; theirs)
                  </div>
                  <div className="flex-1 min-h-0">
                    <DiffEditor
                      theme="vs-dark"
                      original={sides.base ?? ""}
                      modified={sides.theirs ?? ""}
                      options={{
                        readOnly: true,
                        renderSideBySide: sideBySide,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                      }}
                    />
                  </div>
                </div>
              </div>
              <div className="flex flex-col min-h-0 border-t-2 border-orange-500/30">
                <div className="shrink-0 px-3 py-1 text-meta uppercase font-bold tracking-wide text-orange-400 bg-black/20 border-b border-[var(--dtx-code-border)]">
                  Result (edit directly, then Mark Resolved)
                </div>
                <div className="flex-1 min-h-0">
                  <Editor
                    theme="vs-dark"
                    language="plaintext"
                    value={resultText}
                    onChange={(v) => setResultText(v ?? "")}
                    options={{ minimap: { enabled: false }, scrollBeyondLastLine: false }}
                  />
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
