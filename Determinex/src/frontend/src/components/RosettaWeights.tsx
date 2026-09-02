"use client";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Loader2, Network, RefreshCw } from "lucide-react";
import { invokeSafe, isTauri } from "@/lib/api";

/**
 * Latent-bridge projection weights: what is on this machine, and fetching what is
 * not.
 *
 * The Rosetta bridge maps one model's hidden state into another's, so the Monitor's
 * evaluation of a failed step can be handed to the Builder as semantic context
 * rather than re-serialised prose. It needs per-architecture weights, and those are
 * a 1.68 GB torch checkpoint that cannot travel in git (`*.pt` is correctly
 * gitignored) or in an installer.
 *
 * So they are exported to numpy `.npz` shards -- 92-134 MB per architecture, no
 * torch at runtime -- and fetched on demand. This panel exists because a feature
 * whose weights are missing should SAY so and offer the fix, rather than silently
 * disabling itself. That silent disable is exactly how the bridge came to look
 * "never finished" when in fact a rename had orphaned its checkpoint.
 */

interface ShardStatus {
  arch: string;
  file: string;
  bytes: number;
  dim: number | null;
  ready: boolean;
  corrupt: boolean;
}

interface RosettaStatus {
  manifest_present: boolean;
  dir: string;
  repo: string;
  d_rosetta: number | null;
  storage_dtype: string | null;
  shards: ShardStatus[];
  ready_count: number;
  source_checkpoint_present: boolean;
  note: string;
}

interface FetchResult {
  fetched: string[];
  skipped: string[];
  failed: string[];
  bytes: number;
}

const MB = (n: number) => `${Math.round(n / 1_000_000)} MB`;

/** The architectures Determinex's own bundled models use. */
const RECOMMENDED = ["qwen2_1b5", "qwen2_3b"];

export function RosettaWeights() {
  const [status, setStatus] = useState<RosettaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isTauri()) {
      setLoading(false);
      return;
    }
    const res = await invokeSafe<RosettaStatus>("rosetta_status", {});
    if (res) setStatus(res);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const fetchArches = async (arches: string[], label: string) => {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      // rosetta_fetch returns a value, so invokeSafe would be fine -- but a failed
      // fetch must be visible, and invokeSafe swallows a rejection into null.
      const res = (await invokeSafe<FetchResult>("rosetta_fetch", { arches })) ?? null;
      if (!res) {
        setError("The fetch did not return a result. Check the app log.");
        return;
      }
      const parts: string[] = [];
      if (res.fetched.length) parts.push(`downloaded ${res.fetched.join(", ")} (${MB(res.bytes)})`);
      if (res.skipped.length) parts.push(`already present: ${res.skipped.join(", ")}`);
      setMessage(parts.join(" · ") || "Nothing to do.");
      // Failures are reported alongside successes rather than replacing them: a
      // partial fetch is the common case and hiding either half is misleading.
      if (res.failed.length) setError(res.failed.join(" · "));
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  if (!isTauri()) {
    return <p className="text-label text-gray-600">Projection weights need the desktop runtime.</p>;
  }

  if (loading) {
    return <Loader2 size={14} className="animate-spin text-gray-600" />;
  }

  const missingRecommended = RECOMMENDED.filter(
    (a) => !status?.shards.find((s) => s.arch === a)?.ready
  );

  return (
    <div className="space-y-2.5" data-testid="rosetta-weights">
      <div className="flex items-start gap-2">
        <Network size={13} className="mt-0.5 shrink-0 text-cyan-400" />
        <div className="min-w-0 flex-1">
          <div className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
            Latent bridge weights
          </div>
          <p className="mt-1 text-label leading-relaxed text-gray-500">
            Projects one model&apos;s hidden state into another&apos;s, so the Monitor can hand the
            Builder semantic context instead of prose. Runs on numpy — no torch needed.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          aria-label="Re-check downloaded weights"
          title="Re-check"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-600 hover:bg-white/5 hover:text-gray-300"
        >
          <RefreshCw size={11} />
        </button>
      </div>

      {!status?.manifest_present ? (
        <div className="rounded-lg border border-white/8 bg-white/[0.02] p-3">
          <p className="text-label leading-relaxed text-gray-500">
            No weights yet. Downloading the two architectures Determinex&apos;s own models use is
            about 193 MB; the bridge stays off until then and everything else works normally.
          </p>
          <button
            type="button"
            onClick={() => void fetchArches(RECOMMENDED, "recommended")}
            disabled={busy !== null}
            data-testid="rosetta-fetch-recommended"
            className="mt-2 flex items-center gap-1.5 rounded-md border border-cyan-500/40 bg-cyan-950/30 px-2.5 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-cyan-300 hover:bg-cyan-950/60 disabled:opacity-50"
          >
            {busy ? <Loader2 size={10} className="animate-spin" /> : <Download size={10} />}
            Get recommended (193 MB)
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between text-eyebrow text-gray-600">
            <span>
              {status.ready_count}/{status.shards.length} architectures ·{" "}
              {status.d_rosetta ? `${status.d_rosetta}-dim shared space` : ""}
            </span>
            <span className="font-mono">{status.storage_dtype}</span>
          </div>

          <div className="space-y-1">
            {status.shards.map((s) => (
              <div
                key={s.arch}
                className="flex items-center gap-2 rounded-md border border-white/8 bg-white/[0.02] px-2.5 py-1.5"
              >
                {s.ready ? (
                  <CheckCircle2 size={11} className="shrink-0 text-emerald-400" />
                ) : s.corrupt ? (
                  <AlertTriangle size={11} className="shrink-0 text-amber-400" />
                ) : (
                  <Download size={11} className="shrink-0 text-gray-700" />
                )}
                <span className="flex-1 truncate font-mono text-label text-gray-300">{s.arch}</span>
                {s.dim && <span className="text-eyebrow text-gray-600">{s.dim}d</span>}
                <span className="w-16 text-right text-eyebrow text-gray-600">{MB(s.bytes)}</span>
                {!s.ready && (
                  <button
                    type="button"
                    onClick={() => void fetchArches([s.arch], s.arch)}
                    disabled={busy !== null}
                    aria-label={`Download ${s.arch} weights`}
                    className="rounded border border-white/10 px-2 py-0.5 text-eyebrow font-bold uppercase tracking-widest text-gray-400 hover:bg-white/5 hover:text-white disabled:opacity-50"
                  >
                    {busy === s.arch ? "..." : s.corrupt ? "Redo" : "Get"}
                  </button>
                )}
              </div>
            ))}
          </div>

          {missingRecommended.length > 0 && (
            <button
              type="button"
              onClick={() => void fetchArches(missingRecommended, "recommended")}
              disabled={busy !== null}
              data-testid="rosetta-fetch-recommended"
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-cyan-500/30 bg-cyan-950/20 px-2 py-1.5 text-eyebrow font-bold uppercase tracking-widest text-cyan-300 hover:bg-cyan-950/50 disabled:opacity-50"
            >
              <Download size={10} /> Get the {missingRecommended.length} Determinex model
              {missingRecommended.length === 1 ? "" : "s"}
            </button>
          )}
        </>
      )}

      {status?.source_checkpoint_present && (
        <p className="text-eyebrow leading-relaxed text-gray-600">
          A 1.68 GB source checkpoint is also present. The shards above are preferred: they are the
          only path that works in the packaged app, which excludes torch.
        </p>
      )}

      {message && (
        <p className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1.5 text-eyebrow text-emerald-300">
          {message}
        </p>
      )}
      {error && (
        <p className="rounded border border-red-400/30 bg-red-950/20 px-2 py-1.5 text-eyebrow text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
