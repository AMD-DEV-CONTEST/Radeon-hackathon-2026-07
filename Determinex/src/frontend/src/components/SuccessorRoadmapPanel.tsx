"use client";

import { useEffect, useState } from "react";
import { Blocks, CheckCircle2, GitBranch, Milestone, ShieldCheck } from "lucide-react";

import {
  DETERMINEX_SUCCESSOR_BRAND_BOUNDARY,
  DETERMINEX_SUCCESSOR_NEXT_LOCKS,
  DETERMINEX_SUCCESSOR_PILLARS,
  successorStatusLabel,
  type SuccessorPillarStatus,
} from "@/lib/successorRoadmap";
import {
  DETERMINEX_RELEASE_GATES,
  fetchLiveReleaseGateStatus,
  releaseGateStatusLabel,
  type ReleaseGateSnapshot,
  type ReleaseGateStatus,
} from "@/lib/releaseGateStatus";
import {
  DETERMINEX_INDUSTRY_BACKLOG_CATEGORIES,
  getIndustryIdeBacklogSummary,
  getIndustryIdeCategorySummary,
  getTopIndustryIdeNextActions,
  industryBacklogStatusLabel,
  type IndustryBacklogStatus,
} from "@/lib/industryIdeBacklog";

const STATUS_CLASS: Record<SuccessorPillarStatus, string> = {
  live: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  partial: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  planned: "border-blue-400/40 bg-blue-500/10 text-blue-200",
  blocked: "border-rose-400/40 bg-rose-500/10 text-rose-200",
};

const GATE_STATUS_CLASS: Record<ReleaseGateStatus, string> = {
  passed: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  partial: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  deferred: "border-sky-400/40 bg-sky-500/10 text-sky-200",
  planned: "border-blue-400/40 bg-blue-500/10 text-blue-200",
  blocked: "border-rose-400/40 bg-rose-500/10 text-rose-200",
};

const CHECKLIST_STATUS_CLASS: Record<IndustryBacklogStatus, string> = {
  done: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  partial: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  planned: "border-blue-400/40 bg-blue-500/10 text-blue-200",
  blocked: "border-rose-400/40 bg-rose-500/10 text-rose-200",
};

export function SuccessorRoadmapPanel() {
  const [liveGates, setLiveGates] = useState<ReleaseGateSnapshot | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchLiveReleaseGateStatus().then((snapshot) => {
      if (!cancelled) setLiveGates(snapshot);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const gatesSnapshot = liveGates ?? DETERMINEX_RELEASE_GATES;

  const totals = DETERMINEX_SUCCESSOR_PILLARS.reduce(
    (acc, pillar) => {
      acc[pillar.status] += 1;
      return acc;
    },
    { live: 0, partial: 0, planned: 0, blocked: 0 } as Record<SuccessorPillarStatus, number>
  );
  const checklistSummary = getIndustryIdeBacklogSummary();
  const nextIndustryActions = getTopIndustryIdeNextActions(10);

  return (
    <section
      className="flex h-full min-h-0 flex-col overflow-hidden bg-[#06090f] text-white"
      data-testid="successor-roadmap-panel"
    >
      <div className="shrink-0 border-b border-white/10 bg-black/35 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
              <ShieldCheck size={14} /> Determinex product truth
            </div>
            <h2 className="mt-2 text-xl font-black tracking-tight text-white">
              Determinex IDE Roadmap
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-gray-400">
              Natural successor direction for a proof-native IDE. This is the current contract for
              what exists, what is partial, and what still needs release evidence.
            </p>
          </div>
          <div className="grid grid-cols-4 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] text-center">
            {(["live", "partial", "planned", "blocked"] as const).map((status) => (
              <div
                key={status}
                className="min-w-16 border-r border-white/10 px-3 py-2 last:border-r-0"
              >
                <div className="text-base font-black text-white">{totals[status]}</div>
                <div className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
                  {successorStatusLabel(status)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div
          data-testid="successor-roadmap-boundary"
          className="mb-5 rounded-lg border border-white/10 bg-white/[0.03] p-4"
        >
          <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-amber-200">
            <Milestone size={13} /> Roadmap status, not release readiness
          </div>
          <p className="mt-2 text-sm leading-relaxed text-gray-400">
            Public product name is {DETERMINEX_SUCCESSOR_BRAND_BOUNDARY.publicName}.{" "}
            {DETERMINEX_SUCCESSOR_BRAND_BOUNDARY.legacyNamespace}
          </p>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          {DETERMINEX_SUCCESSOR_PILLARS.map((pillar) => (
            <article key={pillar.id} className="rounded-lg border border-white/10 bg-black/30 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <GitBranch size={15} className="shrink-0 text-[var(--determinex-accent)]" />
                  <h3 className="truncate text-sm font-black text-white">{pillar.title}</h3>
                </div>
                <span
                  className={`rounded-md border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${STATUS_CLASS[pillar.status]}`}
                >
                  {successorStatusLabel(pillar.status)}
                </span>
              </div>
              <dl className="mt-3 space-y-3 text-label leading-relaxed">
                <div>
                  <dt className="font-black uppercase tracking-widest text-gray-500">Current</dt>
                  <dd className="mt-1 text-gray-300">{pillar.current}</dd>
                </div>
                <div>
                  <dt className="font-black uppercase tracking-widest text-gray-500">Next lock</dt>
                  <dd className="mt-1 text-gray-300">{pillar.nextLock}</dd>
                </div>
                <div>
                  <dt className="font-black uppercase tracking-widest text-gray-500">Blocker</dt>
                  <dd className="mt-1 text-gray-400">{pillar.blocker}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>

        <div className="mt-5 rounded-lg border border-white/10 bg-white/[0.03] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
              <ShieldCheck size={13} /> Release gate collector
            </div>
            <div className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
              {gatesSnapshot.collector}
            </div>
          </div>
          <p
            data-testid="release-gate-freshness"
            className="mt-2 text-label leading-relaxed text-gray-500"
          >
            {liveGates
              ? `Live gate status · generated ${liveGates.generatedAtUtc}`
              : `Baked-in snapshot (desktop app not connected) · generated ${gatesSnapshot.generatedAtUtc}`}
            . Overall release-ready remains {gatesSnapshot.releaseReady ? "true" : "false"}; this
            panel displays evidence and blockers only.
          </p>
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            {gatesSnapshot.gates.map((gate) => (
              <article
                key={gate.gateId}
                className="rounded-lg border border-white/8 bg-black/25 p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-black text-white">{gate.title}</h3>
                  <span
                    className={`rounded-md border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${GATE_STATUS_CLASS[gate.status]}`}
                  >
                    {releaseGateStatusLabel(gate.status)}
                  </span>
                </div>
                {gate.exactBlocker && (
                  <p className="mt-2 text-label leading-relaxed text-rose-200">
                    {gate.exactBlocker}
                  </p>
                )}
                <p className="mt-2 text-label leading-relaxed text-gray-400">{gate.nextAction}</p>
                <div className="mt-2 space-y-1">
                  {gate.runbookCommands.slice(0, 2).map((command) => (
                    <code
                      key={command}
                      className="block overflow-hidden text-ellipsis whitespace-nowrap rounded border border-white/8 bg-black/35 px-2 py-1 text-meta text-gray-300"
                      title={command}
                    >
                      {command}
                    </code>
                  ))}
                </div>
                <div
                  className="mt-2 truncate text-meta font-mono text-gray-600"
                  title={gate.evidence.join(" | ")}
                >
                  {gate.evidence[0] ?? "no evidence path"}
                </div>
              </article>
            ))}
          </div>
        </div>

        <div className="mt-5 rounded-lg border border-white/10 bg-white/[0.03] p-4">
          <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
            <Blocks size={13} /> Successor locks
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {DETERMINEX_SUCCESSOR_NEXT_LOCKS.map((lock) => (
              <div
                key={lock}
                className="flex items-start gap-2 rounded-md border border-white/8 bg-black/25 px-3 py-2"
              >
                <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-300" />
                <span className="text-label leading-relaxed text-gray-300">{lock}</span>
              </div>
            ))}
          </div>
        </div>

        <div
          className="mt-5 rounded-lg border border-white/10 bg-white/[0.03] p-4"
          data-testid="industry-ide-checklist"
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                <CheckCircle2 size={13} /> Industry IDE checklist
              </div>
              <p className="mt-2 max-w-3xl text-label leading-relaxed text-gray-500">
                Audited checklist for making Determinex a top-tier proof-governed IDE. Checked means
                current repo evidence supports completion; partial, blocked, and planned items
                remain work.
              </p>
            </div>
            <div className="grid grid-cols-4 overflow-hidden rounded-lg border border-white/10 bg-black/30 text-center">
              {(["done", "partial", "blocked", "planned"] as const).map((status) => (
                <div
                  key={status}
                  className="min-w-16 border-r border-white/10 px-3 py-2 last:border-r-0"
                >
                  <div className="text-base font-black text-white">{checklistSummary[status]}</div>
                  <div className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
                    {industryBacklogStatusLabel(status)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
            {DETERMINEX_INDUSTRY_BACKLOG_CATEGORIES.map((category) => {
              const categorySummary = getIndustryIdeCategorySummary(category.id);
              return (
                <article
                  key={category.id}
                  className="rounded-lg border border-white/8 bg-black/25 p-3"
                >
                  <div className="text-label font-black text-white">{category.title}</div>
                  <div className="mt-1 text-meta font-mono text-gray-500">
                    {categorySummary.checked}/{categorySummary.total} checked
                  </div>
                  <p className="mt-2 text-label leading-relaxed text-gray-500">
                    {category.objective}
                  </p>
                </article>
              );
            })}
          </div>

          <div className="mt-4">
            <div className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
              Next highest-priority unfinished actions
            </div>
            <div className="mt-2 grid gap-2 xl:grid-cols-2">
              {nextIndustryActions.map((item) => (
                <article key={item.id} className="rounded-lg border border-white/8 bg-black/25 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                        {item.priority} - {item.category}
                      </div>
                      <h3 className="mt-1 text-body font-black text-white">{item.title}</h3>
                    </div>
                    <span
                      className={`rounded-md border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${CHECKLIST_STATUS_CLASS[item.status]}`}
                    >
                      {industryBacklogStatusLabel(item.status)}
                    </span>
                  </div>
                  {item.blocker && (
                    <p className="mt-2 text-label leading-relaxed text-rose-200">{item.blocker}</p>
                  )}
                  <p className="mt-2 text-label leading-relaxed text-gray-400">{item.nextAction}</p>
                  <div
                    className="mt-2 truncate text-meta font-mono text-gray-600"
                    title={item.evidence.join(" | ")}
                  >
                    {item.evidence[0] ?? "no evidence path"}
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
