"use client";
import { useCallback, useEffect, useState } from "react";
import { RefreshCcw, CheckCircle2, XCircle, Zap, TrendingUp, Loader2 } from "lucide-react";
import { isTauri, invokeSafe } from "@/lib/api";

type FlywheelPair = {
  tool: string;
  lang: string;
  test_id: string;
  verdict: "PASS" | "FAIL" | string;
  captured_at: string;
  error_preview: string | null;
};

type FlywheelSummary = {
  total_pairs: number;
  added_today: number;
  pairs: FlywheelPair[];
  // The corpus is 8.44 GB on the author's machine. An exact line count means reading all
  // of it, so above a size threshold the backend estimates the total from the average
  // record length it actually observed in the tail. Rendering an estimate as a count
  // would be an overclaim, so these flags exist to be shown, not swallowed.
  // Records in the scanned window whose metadata is empty. They are real training pairs
  // and are counted in the totals, but they name no tool or test, so showing them as rows
  // produced a feed of "unknown / unknown" that drowned the real ones. Omitted from
  // `pairs` and reported here instead -- stated, not swallowed.
  unidentified_in_window?: number;
  total_is_estimate?: boolean;
  added_today_is_partial?: boolean;
  corpus_bytes?: number;
};

const EMPTY_SUMMARY: FlywheelSummary = {
  total_pairs: 0,
  added_today: 0,
  pairs: [],
  total_is_estimate: false,
  added_today_is_partial: false,
  corpus_bytes: 0,
};

function formatCount(n: number, isEstimate?: boolean): string {
  const s = n.toLocaleString();
  return isEstimate ? `~${s}` : s;
}

function formatGB(bytes?: number): string | null {
  if (!bytes) return null;
  const gb = bytes / 1024 / 1024 / 1024;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(bytes / 1024 / 1024).toFixed(0)} MB`;
}

export function FlywheelFeed() {
  const [summary, setSummary] = useState<FlywheelSummary | null>(null);
  const [loading, setLoading] = useState(true);
  // Whether the last read FAILED, as opposed to succeeding with nothing to report. Without this the
  // two are identical on screen: `result ?? EMPTY_SUMMARY` substituted all-zeros, and the UI renders
  // "0" Total Pairs under a tooltip reading "Exact line count." plus "+0" Today under "Every record
  // captured today." A failed IPC read was being presented as a measurement.
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    const result = await invokeSafe<FlywheelSummary>("get_flywheel_feed", { limit: 30 });
    setUnavailable(result === null);
    setSummary(result ?? EMPTY_SUMMARY);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [refresh]);

  const pairs = summary?.pairs ?? [];
  const corpusSize = summary?.total_pairs ?? 0;
  const todayAdded = summary?.added_today ?? 0;
  const isEstimate = summary?.total_is_estimate === true;
  const todayIsPartial = summary?.added_today_is_partial === true;
  const corpusLabel = formatGB(summary?.corpus_bytes);

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="pointer-events-none absolute inset-0 opacity-10">
        <div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full"
          style={{ background: "var(--dtx-warn)", filter: "blur(140px)" }}
        />
      </div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-4">
        <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
          <div>
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-amber-400 mb-2">
              <RefreshCcw size={13} /> Flywheel
            </div>
            <h2
              className="text-hero font-black leading-tight text-[var(--determinex-text)]"
              style={{ fontFamily: "var(--determinex-font-display)" }}
            >
              Training Feed
            </h2>
          </div>
          <button
            onClick={() => void refresh()}
            className={`flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-1.5 text-meta font-bold uppercase tracking-widest text-gray-500 hover:text-gray-300 transition-all ${loading ? "animate-spin" : ""}`}
          >
            <RefreshCcw size={11} />
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2 shrink-0">
          <div
            className="rounded-xl border border-white/8 bg-black/30 p-3 text-center"
            title={
              unavailable
                ? "Could not read the flywheel corpus. This is not a count of zero — the read failed."
                : isEstimate
                  ? `Estimated from ${corpusLabel ?? "corpus size"} and the average record length observed in the tail. An exact count would mean reading the whole file.`
                  : "Exact line count."
            }
          >
            <div className="font-mono text-display font-black text-amber-400">
              {unavailable ? "—" : formatCount(corpusSize, isEstimate)}
            </div>
            <div className="text-eyebrow uppercase tracking-widest text-gray-600 mt-0.5">
              {unavailable ? "Unavailable" : isEstimate ? "Total Pairs (est.)" : "Total Pairs"}
            </div>
          </div>
          <div
            className="rounded-xl border border-white/8 bg-black/30 p-3 text-center"
            title={
              unavailable
                ? "Could not read the flywheel corpus. This is not zero records today — the read failed."
                : todayIsPartial
                  ? "At least this many — the tail scan reached its byte cap before passing midnight, so the real number may be higher."
                  : "Every record captured today."
            }
          >
            <div className="flex items-center justify-center gap-1">
              <TrendingUp size={12} className="text-emerald-400" />
              <span className="font-mono text-display font-black text-emerald-400">
                {unavailable ? "—" : `${todayIsPartial ? "≥" : "+"}${todayAdded}`}
              </span>
            </div>
            <div className="text-eyebrow uppercase tracking-widest text-gray-600 mt-0.5">Today</div>
          </div>
          <div className="rounded-xl border border-white/8 bg-black/30 p-3 text-center">
            <div className="flex items-center justify-center">
              <Zap size={14} className={corpusSize > 0 ? "text-amber-400" : "text-gray-700"} />
            </div>
            <div
              className={`text-eyebrow uppercase tracking-widest mt-0.5 ${corpusSize > 0 ? "text-amber-400" : "text-gray-700"}`}
            >
              {corpusSize > 0 ? "CORPUS FOUND" : "NO CORPUS"}
            </div>
            {corpusLabel && (
              <div className="text-meta font-mono text-gray-700 mt-0.5">{corpusLabel}</div>
            )}
          </div>
        </div>

        {/* Records omitted from the list, said out loud. They are counted in the totals above,
            so silently dropping them would make the list and the count disagree with no
            explanation on screen -- the same class of quiet mismatch the estimate flags exist
            to prevent. */}
        {(summary?.unidentified_in_window ?? 0) > 0 && (
          <p className="mb-2 text-meta font-mono text-gray-600">
            {summary?.unidentified_in_window} record
            {summary?.unidentified_in_window === 1 ? "" : "s"} in this window carry no metadata —
            counted in the totals, omitted here because they name no tool or test.
          </p>
        )}

        <div className="flex-1 overflow-y-auto no-scrollbar space-y-2">
          {loading && summary === null ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 size={18} className="animate-spin text-gray-600" />
            </div>
          ) : (
            pairs.map((pair, i) => (
              <div
                key={`${pair.tool}-${pair.test_id}-${pair.captured_at}-${i}`}
                className="rounded-xl border border-white/8 overflow-hidden transition-all"
              >
                <div className="flex items-center gap-2 px-3 py-2 bg-black/20 border-b border-white/5">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${pair.verdict === "PASS" ? "bg-emerald-400" : "bg-red-400"}`}
                  />
                  <span className="text-label font-black text-white/70">{pair.tool}</span>
                  <span className="text-meta font-mono text-gray-600">{pair.lang}</span>
                  <div className="flex-1" />
                  <span
                    className={`flex items-center gap-1 text-meta font-bold ${pair.verdict === "PASS" ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {pair.verdict === "PASS" ? <CheckCircle2 size={9} /> : <XCircle size={9} />}
                    {pair.verdict}
                  </span>
                  <span className="text-meta font-mono text-gray-700">{pair.captured_at}</span>
                </div>
                <div className="px-3 py-2">
                  <div className="text-eyebrow uppercase font-bold tracking-widest text-gray-600 mb-1">
                    {pair.test_id}
                  </div>
                  {pair.error_preview && (
                    <div className="text-meta font-mono text-red-300/70 leading-relaxed">
                      {pair.error_preview}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          {!loading && pairs.length === 0 && (
            <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-1 opacity-40">
              <p className="text-label text-gray-500">No training pairs found on this machine</p>
              <p className="max-w-[320px] text-center text-meta text-gray-700">
                Reads corpus/programbench/training_corpus/pb_verdict_corpus.jsonl. That file only
                exists after a real ProgramBench gate run ingests results — none has on this box
                yet.
              </p>
            </div>
          )}
        </div>

        {!isTauri() && (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2 text-meta text-gray-700 font-mono text-center shrink-0">
            Browser mode cannot read native training feed evidence.
          </div>
        )}
      </div>
    </div>
  );
}
