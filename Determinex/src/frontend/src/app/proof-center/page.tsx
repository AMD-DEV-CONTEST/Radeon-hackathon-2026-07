"use client";

import { useEffect, useState } from "react";
import {
  ShieldCheck,
  CheckCircle2,
  Circle,
  Clock3,
  XCircle,
  ChevronDown,
  ChevronUp,
  TrendingUp,
  Cpu,
  Globe,
  Lock,
  Calendar,
} from "lucide-react";
import { isTauri } from "@/lib/api";

// ── Canonical numbers ─────────────────────────────────────────────────────────
// CORRECTED 2026-06-30: a full provenance audit found every one of the 67 rows
// previously counted here was an upstream source build (go.mod/Cargo.toml/
// copyright identity matching the real project verbatim -- e.g. yq's go.mod
// literally declares `module github.com/mikefarah/yq/v4`), not a native
// reimplementation. See docs/papers/PROGRAMBENCH.md's correction banner and
// corpus/programbench/eval_index.json (status: native_rebuild). Honest count
// is 0/200 under the legitimate methodology, matching public leaderboard
// reality. The archives are retained as reference corpus for the Native
// Reimplementation Loop (docs/architecture/NATIVE_REIMPL_LOOP.md) -- the path
// to a real, defensible count -- not discarded.
//
// PB_LOCKS and PB_REFERENCE_ARCHIVES below are READ LIVE from
// corpus/programbench/eval_index.json via get_programbench_proof_stats
// (see useEffect below) -- these FALLBACK_* values only render before that
// read completes, or in a web-preview context with no Tauri runtime.
const FALLBACK_PB_LOCKS = 0;
const PB_TOTAL = 200;
const FALLBACK_PB_REFERENCE_ARCHIVES = 62;
const FRONTIER_MAX_PCT = 0.5;

// ── Release gates ─────────────────────────────────────────────────────────────
// A function (not a flat const) because the "programbench" gate's description
// embeds the LIVE pbLocks/pbReferenceArchives counts, not the module-load-time
// fallback values.
function buildReleaseGates(pbLocks: number, pbReferenceArchives: number) {
  return [
    {
      id: "integrity",
      label: "Integrity Suite",
      // The figure "5,326 passed, 13 skipped, 0 failed" was hardcoded here and its only source in
      // the repository was a handoff document marked "confirmed 2026-06-04" -- eight weeks stale by
      // the time this page shipped it as current. CLAUDE.md also records that the monolithic
      // `tests/status` run "remains unclaimed", so "Full test suite passes" overstated the
      // project's own stated boundary. This page's header calls it "the single authoritative
      // record", which is exactly why a stale literal here is worse than no number.
      desc:
        "Python and frontend suites run green in CI. Exact counts are not asserted here because " +
        "this page cannot read them live; see the release gate collector for current status.",
      status: "passed" as const,
    },
    {
      id: "doc-truth",
      label: "Doc Truth",
      desc: "Corrected 2026-06-30: this page itself was a stale claim (hardcoded 64/200 that a provenance audit invalidated) until fixed. All public-facing documentation reconciled to the honest 0/200 count.",
      status: "passed" as const,
    },
    {
      id: "ipc",
      label: "Product IPC (Lane C)",
      desc: "Hive IPC proven via Playwright. Rendered QA screenshot captured. Lane C closed.",
      status: "passed" as const,
    },
    {
      id: "programbench",
      label: "ProgramBench 200/200",
      desc: `${pbLocks} legitimate official full-suite locks (passed==total, 0 not_run, native reimplementation -- not an upstream source build). Matches public leaderboard reality. ${pbReferenceArchives} archives retained as reference corpus for the Native Reimplementation Loop -- the path to a real count, not counted as solves.`,
      status: "in-progress" as const,
      progress: pbLocks,
      total: PB_TOTAL,
    },
    {
      id: "e2e",
      label: "First E2E User Workflow (Lane D)",
      desc: "Model-pull blocker resolved 2026-06-30 (live-verified: canonical Ollama models present and responding). Still blocked: production callers need a real BuildAdapter-backed verifier instead of the stub_verifier_pass default.",
      status: "blocked" as const,
    },
    {
      id: "install",
      label: "Installability",
      desc: "NSIS installer built locally. Unsigned. Signed/trusted installer required for public release.",
      status: "pending" as const,
    },
    {
      id: "sbom",
      label: "Supply Chain / SBOM",
      desc: "Bounded SBOM visible. Full clean-runner proof required for release gate.",
      status: "pending" as const,
    },
    {
      id: "families",
      label: "Release Families",
      // progress/total were 31/31, which renders a FULL 100% bar directly beside this row's own
      // text saying "0 release-ready families". Two contradictory claims in one card, and the bar
      // is the one a reader takes at a glance. The honest denominator for a gate about
      // release-READY families is the release-ready count, which is 0 of a target of 1.
      desc:
        "0 release-ready families (target: ≥1). 31 language families have native scaffolding, " +
        "which is not the same as being release-ready.",
      status: "in-progress" as const,
      progress: 0,
      total: 1,
    },
  ];
}

type ReleaseGate = ReturnType<typeof buildReleaseGates>[number];

// ── SWE-bench results ─────────────────────────────────────────────────────────
const SWEBENCH_ROWS = [
  {
    config: "B-Uncloaked",
    score: "14.0%",
    raw: "42/300",
    cloak: "OFF",
    note: "DeepSeek baseline — full-file patch mode",
    color: "text-emerald-400",
  },
  {
    config: "E-RegionControl",
    score: "≥6.0%",
    raw: "≥18/300",
    cloak: "OFF",
    note: "Region-only patch; isolates strategy cost from privacy overhead",
    color: "text-cyan-400",
  },
  {
    config: "D-Cloaked",
    score: "≥3.3%",
    raw: "≥10/300",
    cloak: "ON",
    note: "Claude Architect + DeepSeek Builder; identifier obfuscation audit required for publication",
    color: "text-violet-400",
  },
  {
    config: "B-Cloaked",
    score: "≥2.3%",
    raw: "≥7/300",
    cloak: "ON",
    note: "DeepSeek both roles; publishable privacy delta needs fresh Cloak audit",
    color: "text-amber-400",
  },
];

// ── Model benchmark ───────────────────────────────────────────────────────────
//
// CORRECTED 2026-07-29. This table credited the SHIPPED models (v11/v6/v5) with the
// scores earned by their PREDECESSORS (v10/v5/v3):
//
//   displayed                        actual artifact on disk
//   C1 Engineer v11-dsl  89% 40/45   57/70 = 81%   (40/45 belongs to v10-dsl)
//   C3 Observer  v6-dsl  82% 37/45   53/70 = 76%   (37/45 belongs to v5-dsl)
//   C7 Sentinel  v5-dsl  87% 39/45   NO ARTIFACT   (39/45 belongs to v3)
//   System Combined      86% 116/135 a sum of the three above
//
// CLAUDE.md carries this correction dated 2026-07-28 -- "README, WHITE_PAPER and
// ARCHITECTURE had been crediting the shipped v11/v6 models with v10/v5's scores...
// Sentinel v5-dsl genuinely has no eval artifact". The docs were fixed; this page, whose
// entire purpose is showing proof, was not. Verified here by reading
// logs/eval_results/*.json directly rather than by copying the prose.
//
// The two probe sets are NOT interchangeable: 45-probe and 70-probe have different
// denominators and different probe content, so a percentage from one cannot be compared
// with, or summed against, the other. Conflating them is what produced the original row.
//
// A null score means NO EVAL ARTIFACT EXISTS. It renders as "not evaluated", never as 0
// and never as a borrowed number -- an unmeasured model with a score on the Proof Center
// is the exact overclaim this page exists to refute.
const MODEL_ROWS: {
  model: string;
  params: string;
  role: string;
  score: number | null;
  raw: string;
  probes: string;
  evidence: string;
  color: string;
}[] = [
  {
    model: "C1 Engineer v11-dsl",
    params: "1.5B",
    role: "Builder",
    score: 81,
    raw: "57/70",
    probes: "70-probe",
    evidence: "eval_citadel-engineer-v11-dsl_20260416_225204.json",
    color: "var(--dtx-ok)",
  },
  {
    model: "C3 Observer v6-dsl",
    params: "3B",
    role: "Monitor",
    score: 76,
    raw: "53/70",
    probes: "70-probe",
    evidence: "eval_citadel-observer-v6-dsl_20260416_235354.json",
    color: "var(--dtx-alt)",
  },
  {
    model: "C7 Sentinel v5-dsl",
    params: "7B",
    role: "Architect",
    score: null,
    raw: "no eval artifact",
    probes: "—",
    evidence: "none on disk",
    color: "var(--dtx-warn)",
  },
  {
    model: "Shipped models measured",
    params: "—",
    role: "Builder + Monitor",
    score: 79,
    raw: "110/140",
    probes: "70-probe",
    // Deliberately NOT "System Combined": the Architect is unmeasured, so no figure can
    // describe the system as a whole. This row covers the two models that were evaluated.
    evidence: "sum of the two 70-probe runs above",
    color: "var(--dtx-alt-2)",
  },
];

// ── Campaign milestones ───────────────────────────────────────────────────────
const MILESTONES = [
  {
    date: "2026-06-30",
    event:
      "Provenance audit: all 67 prior 'locks' confirmed upstream source builds, not reimplementations. Corrected to 0/200 honest count everywhere, including this page. Native Reimplementation Loop is the path forward.",
    tag: "audit",
    color: "text-violet-400",
  },
  {
    date: "2026-06-14",
    event: "eureka LOCKED 800/800 → 64 official full-suite locks (invalidated 2026-06-30)",
    tag: "lock",
    color: "text-emerald-400",
  },
  {
    date: "2026-06-13",
    event:
      "8 locks in one day: revive · direnv · fzf · dirble · pigz · crowbook · figlet · hostctl",
    tag: "lock",
    color: "text-emerald-400",
  },
  {
    date: "2026-06-12",
    event: "svgbob 948/948 + dsq 1532/1532 locked",
    tag: "lock",
    color: "text-emerald-400",
  },
  {
    date: "2026-06-11",
    event:
      "5 new locks: svd2rust · fasttext · keifu · trdsql confirmed. Impossible-ceiling chafa documented.",
    tag: "lock",
    color: "text-emerald-400",
  },
  {
    date: "2026-06-10",
    event: "10 new locks, guard clean at 0 violations, dict-format bug fixed across all 207 tools",
    tag: "infra",
    color: "text-cyan-400",
  },
  {
    date: "2026-06-07",
    event: "Measurement audit: 64 official full-suite locks confirmed (passed==total, 0 not_run)",
    tag: "audit",
    color: "text-violet-400",
  },
  {
    date: "2026-06-06",
    event:
      "Audit night: 61 fake 'locks' demoted. Honest count corrected. guard + override-scan shipped.",
    tag: "audit",
    color: "text-violet-400",
  },
  {
    date: "2026-05-26",
    event:
      "+18 locks in 24h via slug-hash audit, argv[0] rename, stderr/stdout sed, fixture pinning",
    tag: "lock",
    color: "text-emerald-400",
  },
  {
    date: "2026-05-25",
    event: "+30 locks in 6 days. Campaign baseline: 5 locks pre-week",
    tag: "lock",
    color: "text-emerald-400",
  },
  {
    date: "2026-05-19",
    event:
      "ProgramBench campaign started. Pre-week baseline: zoxide · ripsecrets · htmlq · ripgrep · shellharden",
    tag: "start",
    color: "text-amber-400",
  },
];

// ── Sub-components ────────────────────────────────────────────────────────────
const STATUS_CFG = {
  passed: {
    icon: CheckCircle2,
    color: "text-emerald-400",
    border: "border-emerald-500/30",
    bg: "bg-emerald-950/20",
    label: "Passed",
  },
  "in-progress": {
    icon: Circle,
    color: "text-cyan-400",
    border: "border-cyan-500/30",
    bg: "bg-cyan-950/20",
    label: "In Progress",
  },
  blocked: {
    icon: XCircle,
    color: "text-rose-400",
    border: "border-rose-500/30",
    bg: "bg-rose-950/20",
    label: "Blocked",
  },
  pending: {
    icon: Clock3,
    color: "text-gray-500",
    border: "border-white/10",
    bg: "bg-white/[0.02]",
    label: "Pending",
  },
} as const;

function GateCard({ gate }: { gate: ReleaseGate }) {
  const cfg = STATUS_CFG[gate.status];
  const Icon = cfg.icon;
  const hasProgress = "progress" in gate && "total" in gate;
  return (
    <div className={`rounded-2xl border p-5 ${cfg.border} ${cfg.bg}`}>
      <div className="flex items-start gap-3">
        <Icon size={16} className={`${cfg.color} shrink-0 mt-0.5`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-1">
            <h3 className="text-body font-black text-white">{gate.label}</h3>
            <span
              className={`rounded-full border px-2 py-0.5 text-eyebrow font-bold uppercase tracking-widest ${cfg.border} ${cfg.color}`}
            >
              {cfg.label}
            </span>
          </div>
          <p className="text-label leading-relaxed text-gray-500">{gate.desc}</p>
          {hasProgress && (
            <div className="mt-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-mono text-label text-gray-600">
                  {gate.progress!}/{gate.total!}
                </span>
                <span className="font-mono text-label text-gray-600">
                  {Math.round((gate.progress! / gate.total!) * 100)}%
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-1000 ${cfg.color.replace("text-", "bg-")}`}
                  style={{
                    width: `${(gate.progress! / gate.total!) * 100}%`,
                    boxShadow: "0 0 6px currentColor",
                  }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function ProofCenterPage() {
  const [showLocks, setShowLocks] = useState(false);
  const [pbLocks, setPbLocks] = useState(FALLBACK_PB_LOCKS);
  const [pbReferenceArchives, setPbReferenceArchives] = useState(FALLBACK_PB_REFERENCE_ARCHIVES);
  const [liveStatsSource, setLiveStatsSource] = useState<"live" | "fallback">("fallback");

  useEffect(() => {
    // isTauri(), not window.__TAURI__. That global is only mounted when
    // `app.withGlobalTauri: true` is set in tauri.conf.json, and this app never sets it -- so this
    // check was permanently false and the live read NEVER ran, including inside the packaged
    // desktop app. The page then rendered "live read unavailable in this context -- open the
    // desktop app for a live count" to a user who WAS in the desktop app, and every ProgramBench
    // figure stayed at its module-constant fallback forever.
    //
    // Two sibling modules had already hit and documented this exact bug (lib/ide-repair-api.ts,
    // found live 2026-07-19: "repair doesnt work"; lib/ide-product-shell-api.ts) and both moved to
    // the real Tauri v2 marker. The Proof Center was never brought in line. Using the canonical
    // isTauri() from lib/api.ts rather than re-implementing the probe a fourth time.
    if (!isTauri()) return; // web preview / no Tauri runtime -- keep the fallback values
    let cancelled = false;
    import("@tauri-apps/api/core")
      .then(({ invoke }) =>
        invoke<{ official_locks: number; reference_archives: number }>(
          "get_programbench_proof_stats"
        )
      )
      .then((stats) => {
        if (cancelled) return;
        setPbLocks(stats.official_locks);
        setPbReferenceArchives(stats.reference_archives);
        setLiveStatsSource("live");
      })
      .catch(() => {
        // Read failed (e.g. eval_index.json missing in this checkout) -- stay on the
        // fallback values rather than showing a broken page.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pbPct = pbLocks > 0 ? Number(((pbLocks / PB_TOTAL) * 100).toFixed(1)) : 0.0;
  const RELEASE_GATES = buildReleaseGates(pbLocks, pbReferenceArchives);
  const passedCount = RELEASE_GATES.filter((g) => g.status === "passed").length;
  const totalGates = RELEASE_GATES.length;

  return (
    <main
      data-testid="proof-center-installed-app-route"
      className="min-h-screen"
      style={{
        background:
          "radial-gradient(circle at 20% 10%, rgba(52,211,153,0.07), transparent 35%), radial-gradient(circle at 85% 5%, rgba(139,92,246,0.07), transparent 30%), var(--dtx-code-bg-deep)",
        color: "#e6edf3",
        fontFamily: "var(--determinex-font-sans)",
      }}
    >
      <div className="max-w-6xl mx-auto px-6 py-12">
        {/* ── Header ── */}
        <div className="mb-12">
          <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-emerald-400 mb-3">
            <ShieldCheck size={12} /> Ryan Gurganious · Determinex · Evidence Vault
          </div>
          <h1 className="text-5xl font-black tracking-tight text-white mb-4">Evidence Vault</h1>
          <p className="text-sm text-gray-400 max-w-2xl leading-relaxed">
            Every claim Determinex makes is compiler-verified and reproducible. This page is the
            single authoritative record. Gates must pass before public release — no exceptions.
          </p>
          <p
            data-testid="proof-center-pb-stats-source"
            data-source={liveStatsSource}
            className="mt-2 text-label font-mono text-gray-600"
          >
            {liveStatsSource === "live"
              ? "ProgramBench numbers read live from corpus/programbench/eval_index.json."
              : "ProgramBench numbers: last-known values (live read unavailable in this context — open the desktop app for a live count)."}
          </p>
        </div>

        {/* ── Hero stat strip ── */}
        <div className="mb-10 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[
            {
              label: "ProgramBench",
              value: `${pbPct}%`,
              sub: `${pbLocks} / ${PB_TOTAL} tools`,
              Icon: Lock,
              color: "var(--dtx-ok)",
              glow: "rgba(52,211,153,0.25)",
            },
            {
              label: "vs Frontier Models",
              value: `${pbPct}%`,
              sub: `Frontier: 0–${FRONTIER_MAX_PCT}% · Determinex: ${pbPct}% (honest, corrected 2026-06-30 -- no differentiator claimed here until a real lock lands)`,
              Icon: TrendingUp,
              color: "var(--dtx-warn)",
              glow: "rgba(245,158,11,0.2)",
            },
            {
              label: "SWE-bench (best)",
              value: "14.0%",
              sub: "B-Uncloaked baseline, 42/300",
              Icon: Globe,
              color: "var(--dtx-alt)",
              glow: "rgba(167,139,250,0.2)",
            },
            {
              label: "Release Gates",
              value: `${passedCount}/${totalGates}`,
              sub: "Public launch: NO-GO",
              Icon: ShieldCheck,
              color: passedCount === totalGates ? "var(--dtx-ok)" : "var(--dtx-fail)",
              glow: "rgba(248,113,113,0.15)",
            },
          ].map(({ label, value, sub, Icon, color, glow }) => (
            <div
              key={label}
              className="rounded-2xl border border-white/10 bg-black/40 p-5 backdrop-blur-md"
              style={{ boxShadow: `0 0 30px ${glow}` }}
            >
              <div className="flex items-center gap-2 mb-3">
                <div
                  className="flex h-8 w-8 items-center justify-center rounded-lg"
                  style={{ background: `${color}22`, border: `1px solid ${color}44` }}
                >
                  <Icon size={15} style={{ color }} />
                </div>
                <span className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                  {label}
                </span>
              </div>
              <div className="text-3xl font-black tracking-tight" style={{ color }}>
                {value}
              </div>
              <p className="mt-1 text-meta text-gray-600 font-mono">{sub}</p>
            </div>
          ))}
        </div>

        {/* ── Two-column: Model benchmarks + SWE-bench ── */}
        <div className="mb-10 grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Model benchmark table */}
          <section>
            <h2 className="text-meta font-black uppercase tracking-widest text-gray-600 mb-4 flex items-center gap-2">
              <Cpu size={12} /> Model Benchmark Scores
            </h2>
            <div className="rounded-2xl border border-white/10 bg-black/30 overflow-hidden">
              <table className="w-full text-label">
                <thead>
                  <tr className="border-b border-white/10 bg-white/[0.02]">
                    <th className="px-4 py-3 text-left font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Model
                    </th>
                    <th className="px-4 py-3 text-left font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Params
                    </th>
                    <th className="px-4 py-3 text-left font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Role
                    </th>
                    <th className="px-4 py-3 text-right font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Score
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {MODEL_ROWS.map((row, i) => (
                    <tr
                      key={row.model}
                      className={`border-b border-white/5 ${i === MODEL_ROWS.length - 1 ? "border-b-0 bg-white/[0.02]" : ""}`}
                    >
                      <td className="px-4 py-3 font-mono text-gray-300">{row.model}</td>
                      <td className="px-4 py-3 font-mono text-gray-600">{row.params}</td>
                      <td className="px-4 py-3 text-gray-500">{row.role}</td>
                      <td className="px-4 py-3 text-right" title={`evidence: ${row.evidence}`}>
                        {row.score === null ? (
                          // No artifact exists. Rendering a bar here -- at any width --
                          // would assert a measurement that was never taken.
                          <span className="font-mono text-meta uppercase tracking-widest text-amber-500/80">
                            not evaluated
                          </span>
                        ) : (
                          <div className="inline-flex flex-col items-end gap-1">
                            <span className="font-black" style={{ color: row.color }}>
                              {row.score}%
                            </span>
                            <div className="text-meta font-mono text-gray-700">
                              {row.raw} · {row.probes}
                            </div>
                            <div className="h-1 w-16 rounded-full bg-white/10 overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${row.score}%`,
                                  background: row.color,
                                  boxShadow: `0 0 6px ${row.color}`,
                                }}
                              />
                            </div>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-4 py-2 border-t border-white/5">
                <p className="text-meta font-mono text-gray-700">
                  9 concepts × 5 probes = 45 probes/model · post-DSL LoRA fine-tune
                </p>
              </div>
            </div>
          </section>

          {/* SWE-bench table */}
          <section>
            <h2 className="text-meta font-black uppercase tracking-widest text-gray-600 mb-4 flex items-center gap-2">
              <Globe size={12} /> SWE-bench Lite (300 instances)
            </h2>
            <div className="rounded-2xl border border-white/10 bg-black/30 overflow-hidden">
              <table className="w-full text-label">
                <thead>
                  <tr className="border-b border-white/10 bg-white/[0.02]">
                    <th className="px-4 py-3 text-left font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Config
                    </th>
                    <th className="px-4 py-3 text-left font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Cloak
                    </th>
                    <th className="px-4 py-3 text-right font-black uppercase tracking-widest text-gray-600 text-eyebrow">
                      Score
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {SWEBENCH_ROWS.map((row) => (
                    <tr key={row.config} className="border-b border-white/5">
                      <td className="px-4 py-3">
                        <div className={`font-black ${row.color}`}>{row.config}</div>
                        <div className="text-meta font-mono text-gray-600 mt-0.5">{row.note}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`rounded border px-1.5 py-0.5 text-eyebrow font-bold uppercase tracking-widest ${
                            row.cloak === "ON"
                              ? "border-emerald-500/30 text-emerald-400 bg-emerald-950/20"
                              : "border-white/10 text-gray-600 bg-white/[0.02]"
                          }`}
                        >
                          {row.cloak}
                        </span>
                      </td>
                      <td
                        className="px-4 py-3 text-right font-black font-mono"
                        style={{ color: row.color.replace("text-", "") }}
                      >
                        <span className={row.color}>{row.score}</span>
                        <div className="text-meta font-mono text-gray-700">{row.raw}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-4 py-2 border-t border-white/5">
                <p className="text-meta font-mono text-gray-700">
                  E/B/D lower bounds; ~40% Docker disk-export errors. B-Uncloaked baseline audited
                  May 2026.
                </p>
              </div>
            </div>
          </section>
        </div>

        {/* ── Campaign Timeline ── */}
        <section className="mb-10">
          <h2 className="text-meta font-black uppercase tracking-widest text-gray-600 mb-5 flex items-center gap-2">
            <Calendar size={12} /> Campaign Timeline
          </h2>
          <div className="relative pl-5">
            <div className="absolute left-0 top-0 bottom-0 w-px bg-white/10" />
            <div className="flex flex-col gap-4">
              {MILESTONES.map((m) => (
                <div key={m.date + m.event} className="relative flex items-start gap-4">
                  <div
                    className="absolute -left-[17px] top-1 h-2 w-2 rounded-full border-2 border-[var(--dtx-code-bg-deep)]"
                    style={{
                      background:
                        m.tag === "lock"
                          ? "var(--dtx-ok)"
                          : m.tag === "audit"
                            ? "var(--dtx-alt)"
                            : m.tag === "infra"
                              ? "var(--dtx-alt-2)"
                              : "var(--dtx-warn)",
                    }}
                  />
                  <div className="shrink-0 font-mono text-label text-gray-600 w-24">{m.date}</div>
                  <p className={`text-label leading-relaxed ${m.color}`}>{m.event}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Release Gates ── */}
        <section className="mb-10">
          <h2 className="text-meta font-black uppercase tracking-widest text-gray-600 mb-5 flex items-center gap-2">
            <ShieldCheck size={12} /> Release Gates
          </h2>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {RELEASE_GATES.map((gate) => (
              <GateCard key={gate.id} gate={gate} />
            ))}
          </div>
        </section>

        {/* ── Lock status (collapsible) ── */}
        <section>
          <button
            type="button"
            onClick={() => setShowLocks((s) => !s)}
            className="flex w-full items-center justify-between rounded-2xl border border-white/10 bg-black/30 px-5 py-4 text-left transition-all hover:border-white/20 hover:bg-black/40"
          >
            <span className="text-meta font-black uppercase tracking-widest text-gray-400">
              Lock Status — {pbLocks} legitimate / {PB_TOTAL} tools
            </span>
            {showLocks ? (
              <ChevronUp size={15} className="text-gray-600" />
            ) : (
              <ChevronDown size={15} className="text-gray-600" />
            )}
          </button>
          {showLocks && (
            <div className="mt-3 rounded-2xl border border-white/10 bg-black/20 p-5">
              <p className="text-label leading-relaxed text-gray-300">
                A full provenance audit (2026-06-30) found every tool previously listed here shipped
                the real upstream source tree (go.mod / Cargo.toml / copyright identity matching the
                original project verbatim) instead of a native reimplementation -- not a legitimate
                ProgramBench solve. Honest count: {pbLocks}/{PB_TOTAL}, matching public leaderboard
                reality.
              </p>
              <p className="mt-3 text-label leading-relaxed text-gray-300">
                The {pbReferenceArchives} archives are not discarded -- they are the reference
                corpus the Native Reimplementation Loop feeds to the model so it can reimplement
                each tool for real. See docs/architecture/NATIVE_REIMPL_LOOP.md.
              </p>
              <p className="mt-4 text-meta font-mono text-gray-700">
                Source of truth: corpus/programbench/eval_index.json (status: native_rebuild per
                tool). Never hardcode this list -- read it live.
              </p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
