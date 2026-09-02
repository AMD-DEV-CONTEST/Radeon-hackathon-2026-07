"use client";
import { useEffect, useState, useCallback } from "react";
import { Check, X, ChevronDown, GitBranch, FileCode, Loader2 } from "lucide-react";
import { invokeSafe, invokeWrite } from "@/lib/api";

type StagedDiff = { id: string; path: string; originalContent: string; proposedContent: string };

function diffLineCounts(original: string, proposed: string): { adds: number; removes: number } {
  const o = original.split("\n");
  const p = proposed.split("\n");
  const oSet = new Set(o);
  const pSet = new Set(p);
  const adds = p.filter((l) => !oSet.has(l)).length;
  const removes = o.filter((l) => !pSet.has(l)).length;
  return { adds, removes };
}

export function DiffViewer() {
  const [diffs, setDiffs] = useState<StagedDiff[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await invokeSafe<StagedDiff[]>("get_staged_diffs", {});
      setDiffs(result || []);
      setSelected((prev) => {
        if (prev && (result || []).some((d) => d.id === prev)) return prev;
        return result && result.length > 0 ? result[0].id : null;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  const diff = diffs.find((d) => d.id === selected);

  // apply_staged_diff / reject_staged_diff return Result<(), String> and DO
  // refuse: apply enforces the workspace boundary and rejects a write outside
  // it. Under invokeSafe that refusal resolved to null, the queue refreshed with
  // the diff still in it, and the button looked inert -- so the natural response
  // was to click Apply again on a write the backend had already denied. This is
  // the same defect that was fixed in DiffReviewPanel; this component was
  // missed by that hand-audit and caught by
  // determinex/no-invokesafe-on-void-command.
  const act = async (cmd: "apply_staged_diff" | "reject_staged_diff", verb: string) => {
    if (!diff) return;
    setBusy(true);
    setActionError(null);
    try {
      await invokeWrite(cmd, { id: diff.id });
      await refresh();
    } catch (e) {
      setActionError(`Could not ${verb} ${diff.path}: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const approve = () => act("apply_staged_diff", "apply");
  const reject = () => act("reject_staged_diff", "reject");

  const { adds, removes } = diff
    ? diffLineCounts(diff.originalContent, diff.proposedContent)
    : { adds: 0, removes: 0 };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={18} className="animate-spin text-gray-600" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {actionError && (
        <div className="flex shrink-0 items-start gap-2 border-b border-red-400/30 bg-red-950/20 px-4 py-2 text-label leading-relaxed text-red-300">
          <span className="flex-1">{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="shrink-0 text-red-400/70 hover:text-red-300"
          >
            Dismiss
          </button>
        </div>
      )}
      {/* Patch selector */}
      <div
        className="shrink-0 border-b px-4 py-2"
        style={{ borderColor: "var(--determinex-border)", background: "rgba(0,0,0,0.2)" }}
      >
        <div className="flex items-center gap-2 text-eyebrow uppercase font-black tracking-widest text-gray-600 mb-2">
          <GitBranch size={10} /> Staged Changes
        </div>
        {diffs.length === 0 ? (
          <p className="text-label italic px-1 py-1 text-gray-500">
            No changes staged. Run a build or a repair and proposed edits land here for approval.
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {diffs.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelected(d.id)}
                className={`flex items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition-all ${selected === d.id ? "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/5" : "border-white/5 hover:bg-white/[0.02]"}`}
              >
                <FileCode size={11} className="text-gray-600 shrink-0" />
                <span className="text-label font-semibold text-white/70 flex-1 truncate font-mono">
                  {d.path.split(/[/\\]/).pop()}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {diff ? (
        <>
          {/* Diff header */}
          <div
            className="shrink-0 flex items-center gap-3 border-b px-4 py-2.5"
            style={{ borderColor: "var(--determinex-border)" }}
          >
            <span className="text-label font-mono text-gray-500 flex-1 truncate">{diff.path}</span>
            <span className="text-meta text-emerald-400 font-mono">+{adds}</span>
            <span className="text-meta text-red-400 font-mono">-{removes}</span>
            <div className="flex gap-2 ml-2">
              <button
                onClick={() => void reject()}
                disabled={busy}
                className="flex items-center gap-1 rounded-lg border px-2.5 py-1 text-meta font-bold transition-all border-white/8 text-gray-600 hover:border-red-500/30 hover:text-red-400 disabled:opacity-50"
              >
                <X size={10} /> Reject
              </button>
              <button
                onClick={() => void approve()}
                disabled={busy}
                className="flex items-center gap-1 rounded-lg border px-2.5 py-1 text-meta font-bold transition-all border-white/8 text-gray-600 hover:border-emerald-500/30 hover:text-emerald-400 disabled:opacity-50"
              >
                <Check size={10} /> Apply
              </button>
            </div>
          </div>

          {/* Diff body -- plain before/after text, not a full Monaco diff editor (BuildCenter's
              tab is a lightweight preview; the full side-by-side Monaco diff lives in the
              dedicated Review addon / DiffReviewPanel). */}
          <div className="flex-1 overflow-y-auto no-scrollbar grid grid-cols-2 divide-x divide-white/[0.03]">
            <div>
              <div className="text-eyebrow text-gray-600 uppercase font-black tracking-widest px-4 py-2 border-b border-white/[0.03] bg-black/10">
                Original
              </div>
              <pre className="px-4 py-2 text-label font-mono text-gray-500 whitespace-pre-wrap">
                {diff.originalContent}
              </pre>
            </div>
            <div>
              <div className="text-eyebrow text-gray-600 uppercase font-black tracking-widest px-4 py-2 border-b border-white/[0.03] bg-black/10">
                Proposed
              </div>
              <pre className="px-4 py-2 text-label font-mono text-emerald-300/80 whitespace-pre-wrap">
                {diff.proposedContent}
              </pre>
            </div>
          </div>
        </>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 opacity-50">
          <Check size={28} className="text-emerald-500" />
          <p className="text-label text-gray-500">No AI changes pending review.</p>
        </div>
      )}
    </div>
  );
}
