"use client";
import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, Eye, EyeOff, Search, Loader2 } from "lucide-react";
import { isTauri, invokeSafe } from "@/lib/api";
import { useSettings } from "@/contexts/SettingsContext";
import { NETWORK_POLICY_COPY } from "@/lib/networkPolicy";

type CloakIdentifier = { real: string; token: string };

type CloakAuditSummary = {
  run_dir: string;
  verdict: "clean" | "leaked" | "unverified" | string;
  total_private_identifiers: number;
  restoration_failures: number;
  leaks_found: number;
  api_audit_present: boolean;
  keep_list_preserved: string[];
  identifiers: CloakIdentifier[];
  // A real audit dir holds 299 cloak_map_*.json files totalling 621 MB. The panel needs a
  // 200-identifier sample, so the backend opens a bounded few. Displaying a sample as if
  // it were the whole audit would misstate what the evidence covers.
  maps_sampled?: number;
  maps_total?: number;
};

const VERDICT_COLOR: Record<string, string> = {
  clean: "var(--dtx-ok)",
  leaked: "var(--dtx-fail)",
  unverified: "var(--dtx-warn)",
};

export function PrivacyCockpit() {
  const [reveal, setReveal] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [summary, setSummary] = useState<CloakAuditSummary | null | undefined>(undefined);
  const { networkPolicy, setSettingsTab, setShowSettings } = useSettings();
  const networkCopy = NETWORK_POLICY_COPY[networkPolicy];

  const refresh = useCallback(async () => {
    const result = await invokeSafe<CloakAuditSummary | null>("get_cloak_audit_summary", {});
    setSummary(result ?? null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggleReveal = (token: string) => {
    setReveal((prev) => {
      const next = new Set(prev);
      if (next.has(token)) next.delete(token);
      else next.add(token);
      return next;
    });
  };

  const identifiers = summary?.identifiers ?? [];
  // True when the backend read fewer instance maps than the run contains, which makes the
  // keep-list a union over a sample rather than over the whole run.
  const mapsPartial =
    !!summary?.maps_total && !!summary?.maps_sampled && summary.maps_sampled < summary.maps_total;
  const filtered = identifiers.filter(
    (e) =>
      !search ||
      e.real.toLowerCase().includes(search.toLowerCase()) ||
      e.token.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="pointer-events-none absolute inset-0 opacity-8">
        <div
          className="absolute inset-0"
          style={{
            background:
              "repeating-linear-gradient(0deg, transparent, transparent 30px, rgba(52,211,153,0.02) 30px, rgba(52,211,153,0.02) 31px)",
          }}
        />
      </div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-4">
        {/* Header */}
        <div className="border-b border-white/10 pb-4">
          <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-emerald-400 mb-2">
            <ShieldCheck size={13} /> Project Cloak
          </div>
          <h2
            className="text-hero font-black leading-tight text-[var(--determinex-text)]"
            style={{ fontFamily: "var(--determinex-font-display)" }}
          >
            Privacy Cockpit
          </h2>
          <p className="text-label text-gray-600 mt-1 font-mono">
            Reads the newest logs/swebench/*/cloak_audit/verify_report.json on this machine.
          </p>
        </div>

        <button
          type="button"
          onClick={() => {
            setSettingsTab("network");
            setShowSettings(true);
          }}
          className="rounded-full border border-white/10 bg-black/30 px-3 py-1.5 text-left text-eyebrow font-black uppercase tracking-widest text-gray-500 transition hover:border-emerald-500/40 hover:text-emerald-400"
          title="Open Network Policy settings"
        >
          Network: {networkCopy.shortLabel}
        </button>

        {summary === undefined ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 size={18} className="animate-spin text-gray-600" />
          </div>
        ) : summary === null ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 opacity-40">
            <p className="text-label text-gray-500">No Cloak audit loaded on this machine</p>
            <p className="max-w-[320px] text-center text-meta text-gray-700 leading-relaxed">
              Cloak only does something during a cloud-routed run (e.g. a SWE-bench config with
              Claude/GPT as architect) -- a normal local-only Hive build never calls it, so
              there&apos;s nothing to show yet. Run with DETERMINEX_CLOAK_AUDIT=1 to write the real
              evidence file this panel reads.
            </p>
          </div>
        ) : (
          <>
            {/* Stats */}
            <div className="grid grid-cols-3 gap-2 shrink-0">
              <div className="rounded-xl border border-white/8 bg-black/30 p-3 text-center">
                <div className="font-mono text-display font-black text-emerald-400">
                  {summary.total_private_identifiers}
                </div>
                <div className="text-eyebrow uppercase tracking-widest text-gray-600 mt-0.5">
                  Cloaked Identifiers
                </div>
              </div>
              <div
                className="rounded-xl border border-white/8 bg-black/30 p-3 text-center"
                title={
                  mapsPartial
                    ? `Union of the keep-lists in ${summary.maps_sampled} of ${summary.maps_total} instance maps in this run. Reading all of them means parsing hundreds of MB per refresh.`
                    : "Union of the keep-lists across every instance map in this run."
                }
              >
                <div className="font-mono text-display font-black text-violet-400">
                  {mapsPartial ? "≥" : ""}
                  {summary.keep_list_preserved.length}
                </div>
                <div className="text-eyebrow uppercase tracking-widest text-gray-600 mt-0.5">
                  Sent Verbatim (Keep-list)
                </div>
              </div>
              <div className="rounded-xl border border-white/8 bg-black/30 p-3 text-center">
                <div
                  className="font-mono text-display font-black"
                  style={{ color: VERDICT_COLOR[summary.verdict] ?? "var(--dtx-code-muted)" }}
                >
                  {summary.leaks_found}
                </div>
                <div className="text-eyebrow uppercase tracking-widest text-gray-600 mt-0.5">
                  Leaks Found
                </div>
              </div>
            </div>

            {/* Search */}
            <div className="relative shrink-0">
              <Search
                size={11}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600"
              />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter identifiers…"
                className="w-full rounded-xl border border-white/8 bg-black/30 py-2 pl-8 pr-3 text-label text-white/70 placeholder:text-gray-700 outline-none focus:border-[var(--determinex-accent)]/40"
              />
            </div>

            {/* Identifier table — every entry here was replaced with an opaque token before
                leaving the machine; the cloud side never saw the real name. */}
            <div className="flex-1 overflow-y-auto no-scrollbar space-y-1">
              {filtered.map((entry) => {
                const shown = reveal.has(entry.token);
                return (
                  <div
                    key={entry.token}
                    className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.01] px-3 py-2.5 hover:border-white/10 transition-colors"
                  >
                    <span className="font-mono text-label text-emerald-400/80 shrink-0 w-20 truncate">
                      {entry.token}
                    </span>
                    <span className="text-gray-700 text-label shrink-0">→</span>
                    <span
                      className={`font-mono text-label flex-1 min-w-0 truncate transition-all ${shown ? "text-white/70" : "blur-[3px] select-none text-white/40"}`}
                    >
                      {entry.real}
                    </span>
                    <button
                      onClick={() => toggleReveal(entry.token)}
                      className="shrink-0 text-gray-700 hover:text-gray-400 transition-colors"
                    >
                      {shown ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                  </div>
                );
              })}
              {filtered.length === 0 && (
                <p className="text-center text-label text-gray-700 py-6">
                  No identifiers match &quot;{search}&quot;.
                </p>
              )}
            </div>

            {/* Proof banner */}
            <div className="rounded-xl border border-white/10 bg-black/30 px-4 py-3 flex items-center gap-3 shrink-0">
              <ShieldCheck
                size={16}
                style={{ color: VERDICT_COLOR[summary.verdict] ?? "var(--dtx-code-muted)" }}
                className="shrink-0"
              />
              <div className="min-w-0">
                <div className="text-meta font-black text-gray-400 uppercase">
                  verdict: {summary.verdict}
                </div>
                <div
                  className="text-meta text-gray-700 mt-0.5 font-mono truncate"
                  title={summary.run_dir}
                >
                  {summary.run_dir}
                </div>
              </div>
            </div>
          </>
        )}

        {!isTauri() && (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2 text-meta text-gray-700 font-mono text-center shrink-0">
            Browser mode cannot read native Cloak audit evidence.
          </div>
        )}
      </div>
    </div>
  );
}
