"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  ClipboardList,
  FileText,
  GraduationCap,
  PlayCircle,
  ShieldAlert,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";

import {
  DETERMINEX_MISSION_CONTROL_MISSIONS,
  MISSION_CONTROL_CLAIM_BOUNDARY,
  getMissionControlCompletionLabel,
  resolveMissionControlMission,
  type MissionControlMissionId,
} from "@/lib/missionControl";
import {
  DETERMINEX_RELEASE_GATES,
  fetchLiveReleaseGateStatus,
  releaseGateStatusLabel,
  type ReleaseGateSnapshot,
  type ReleaseGateStatus,
} from "@/lib/releaseGateStatus";
import { successorStatusLabel } from "@/lib/successorRoadmap";

const GATE_STATUS_CLASS: Record<ReleaseGateStatus, string> = {
  passed: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
  partial: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  deferred: "border-sky-400/40 bg-sky-500/10 text-sky-200",
  planned: "border-blue-400/40 bg-blue-500/10 text-blue-200",
  blocked: "border-rose-400/40 bg-rose-500/10 text-rose-200",
};

const GATE_STATUS_DOT: Record<ReleaseGateStatus, string> = {
  passed: "bg-emerald-300",
  partial: "bg-amber-300",
  deferred: "bg-sky-300",
  planned: "bg-blue-300",
  blocked: "bg-rose-300",
};

export function MissionControlPanel() {
  const [selectedMissionId, setSelectedMissionId] =
    useState<MissionControlMissionId>("release-readiness");
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
  const mission = useMemo(
    () => resolveMissionControlMission(selectedMissionId, gatesSnapshot),
    [selectedMissionId, gatesSnapshot]
  );
  const nextGate = mission.gates.find((gate) => gate.status !== "passed") ?? mission.gates[0];

  return (
    /* @container, and every breakpoint below is a CONTAINER query, because this panel is not
       laid out against the viewport. It is hosted in `zone1-hosted-addon`, which is ~618px
       wide while the window is 1600px — so viewport `lg:`/`xl:` breakpoints all fired at
       full strength inside a column less than half that wide. The result was a 280px rail
       plus a two-column split crammed into the ~330px that remained: "Clean-host install
       proof" broke to four lines, the blocker text ran one word per line, and the panel grew
       its own horizontal AND vertical scrollbars. Nothing was wrong with the values — they
       were measured against the wrong box. */
    <section
      className="@container flex h-full min-h-0 flex-col overflow-hidden bg-[#05070b] text-white"
      data-testid="mission-control-panel"
    >
      <div className="shrink-0 border-b border-white/10 bg-black/40 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
              <GraduationCap size={14} /> Interactive guide
            </div>
            <h2 className="mt-2 text-xl font-black tracking-tight text-white">
              Determinex Mission Control
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-gray-400">
              Pick a mission, read the exact blocker, run the current verifier, and keep every
              readiness claim tied to evidence.
            </p>
            <p
              data-testid="mission-control-gate-freshness"
              className="mt-2 text-eyebrow font-mono uppercase tracking-widest text-gray-600"
            >
              {liveGates
                ? `Live gate status · generated ${liveGates.generatedAtUtc}`
                : "Baked-in snapshot (desktop app not connected) · generated " +
                  DETERMINEX_RELEASE_GATES.generatedAtUtc}
            </p>
          </div>
          <div
            data-testid="mission-control-boundary"
            className="max-w-md rounded-lg border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-label leading-relaxed text-amber-100"
          >
            <div className="mb-1 flex items-center gap-2 text-eyebrow font-black uppercase tracking-widest text-amber-200">
              <ShieldAlert size={12} /> Proof boundary
            </div>
            {MISSION_CONTROL_CLAIM_BOUNDARY}
          </div>
        </div>
      </div>

      {/* Side-by-side only once the PANEL is wide enough to seat a 280px rail beside readable
          content — @3xl is 768px. Below that the rail stacks above, which is what the 618px
          hosted zone gets. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden @3xl:grid-cols-[280px_1fr]">
        <aside className="min-h-0 overflow-y-auto border-b border-white/10 bg-white/[0.025] p-4 lg:border-b-0 lg:border-r">
          <div className="mb-3 text-eyebrow font-black uppercase tracking-widest text-gray-500">
            Guided missions
          </div>
          <div className="space-y-2">
            {DETERMINEX_MISSION_CONTROL_MISSIONS.map((candidate) => {
              const resolved = resolveMissionControlMission(candidate.id, gatesSnapshot);
              const isSelected = candidate.id === selectedMissionId;
              return (
                <button
                  key={candidate.id}
                  type="button"
                  data-testid={`mission-tab-${candidate.id}`}
                  onClick={() => setSelectedMissionId(candidate.id)}
                  className={`w-full rounded-lg border p-3 text-left transition ${
                    isSelected
                      ? "border-[var(--determinex-accent)] bg-[var(--determinex-accent)]/10 shadow-[0_0_18px_rgba(53,255,138,0.14)]"
                      : "border-white/10 bg-black/25 hover:border-white/20 hover:bg-white/[0.04]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-label font-black text-white">{candidate.title}</span>
                    <ArrowRight
                      size={13}
                      className={isSelected ? "text-[var(--determinex-accent)]" : "text-gray-600"}
                    />
                  </div>
                  <p className="mt-1 text-meta leading-relaxed text-gray-500">
                    {candidate.audience}
                  </p>
                  <div className="mt-3 flex items-center justify-between gap-2 text-meta">
                    <span className="font-mono text-gray-500">
                      {getMissionControlCompletionLabel(resolved)}
                    </span>
                    <span className="flex items-center gap-1">
                      {(["blocked", "partial", "deferred", "planned", "passed"] as const).map(
                        (status) => (
                          <span
                            key={status}
                            title={`${releaseGateStatusLabel(status)}: ${resolved.counts[status]}`}
                            className={`h-1.5 w-1.5 rounded-full ${resolved.counts[status] ? GATE_STATUS_DOT[status] : "bg-white/10"}`}
                          />
                        )
                      )}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Its own container: the two card splits below must react to THIS column's width,
            not the panel's and not the window's. */}
        <div className="@container min-h-0 overflow-y-auto p-5">
          {/* The REAL root cause the @container fix below doesn't reach on its own: CSS Grid's
              default track sizing floors an `Nfr` column at its content's max-content width, not
              0 -- this grid's second column (mission-next-action-card) contains long
              `whitespace-nowrap` command strings meant to ellipsis-truncate, but text-overflow
              only engages once something ACTUALLY constrains the width. Without min-w-0 on the
              grid children, those commands' full intrinsic width (1076px, measured live) became
              the second track's floor, squeezing this card down to 130px regardless of the
              1.05fr/0.95fr split -- min-w-0 lets the tracks size to the fr ratio like intended,
              which is what makes the ellipsis/@container fixes on the first card meaningful at
              all. Found live 2026-07-27 by measuring getBoundingClientRect() down the ancestor
              chain after the @container-only fix still measured a 130px card. */}
          <div className="grid gap-4 @2xl:grid-cols-[1.05fr_0.95fr]">
            <article
              className="@container min-w-0 rounded-lg border border-white/10 bg-black/30 p-5"
              data-testid="mission-active-card"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                    <ClipboardList size={13} /> Active mission
                  </div>
                  <h3 className="text-2xl font-black tracking-tight text-white">{mission.title}</h3>
                </div>
                <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-right">
                  <div className="text-lg font-black text-white">
                    {mission.passedGates}/{mission.totalGates}
                  </div>
                  <div className="text-eyebrow font-black uppercase tracking-widest text-gray-500">
                    Gates passed
                  </div>
                </div>
              </div>

              {/* @container (on the article above) + @md:/@md: variants, not md: -- this card's
                  real rendered width depends on 4 nested viewport-breakpointed splits (the
                  280px missions rail, then xl:[1.05fr_0.95fr] for this card vs. Next Useful
                  Action), so at a perfectly ordinary 1600px window the viewport-relative md:
                  breakpoint activated 2 columns while the ACTUAL available width was under
                  300px -- "Objective"/"User outcome" rendered overlapping, body text wrapped to
                  one word per line. Found live 2026-07-27 driving the real running app, not
                  caught by any viewport-width-only test. Container queries measure this
                  article's own box, which is what actually constrains the grid, regardless of
                  how many ancestor splits are active. */}
              <dl className="mt-5 grid gap-3 text-label leading-relaxed @md:grid-cols-2">
                <div className="rounded-lg border border-white/8 bg-white/[0.025] p-3">
                  <dt className="font-black uppercase tracking-widest text-gray-500">Objective</dt>
                  <dd className="mt-1 text-gray-300">{mission.objective}</dd>
                </div>
                <div className="rounded-lg border border-white/8 bg-white/[0.025] p-3">
                  <dt className="font-black uppercase tracking-widest text-gray-500">
                    User outcome
                  </dt>
                  <dd className="mt-1 text-gray-300">{mission.userOutcome}</dd>
                </div>
                <div className="rounded-lg border border-white/8 bg-white/[0.025] p-3 @md:col-span-2">
                  <dt className="font-black uppercase tracking-widest text-gray-500">
                    Primary action
                  </dt>
                  <dd className="mt-1 text-gray-300">{mission.primaryAction}</dd>
                </div>
                <div className="rounded-lg border border-amber-400/15 bg-amber-500/10 p-3 @md:col-span-2">
                  <dt className="flex items-center gap-2 font-black uppercase tracking-widest text-amber-200">
                    <ShieldCheck size={13} /> Mission proof boundary
                  </dt>
                  <dd className="mt-1 text-amber-100">{mission.proofBoundary}</dd>
                </div>
              </dl>
            </article>

            <article
              className="min-w-0 rounded-lg border border-white/10 bg-black/30 p-5"
              data-testid="mission-next-action-card"
            >
              <div className="mb-3 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-rose-200">
                <PlayCircle size={13} /> Next useful action
              </div>
              {nextGate ? (
                <div data-testid="mission-next-action">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-lg font-black text-white">{nextGate.title}</h3>
                    <span
                      className={`rounded-md border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${GATE_STATUS_CLASS[nextGate.status]}`}
                    >
                      {releaseGateStatusLabel(nextGate.status)}
                    </span>
                  </div>
                  {nextGate.exactBlocker && (
                    <p className="mt-3 text-body leading-relaxed text-rose-100">
                      {nextGate.exactBlocker}
                    </p>
                  )}
                  <p className="mt-3 text-body leading-relaxed text-gray-300">
                    {nextGate.nextAction}
                  </p>
                  <div className="mt-4 space-y-2">
                    {nextGate.runbookCommands.map((command) => (
                      <code
                        key={command}
                        className="block overflow-hidden text-ellipsis whitespace-nowrap rounded border border-white/10 bg-black/45 px-3 py-2 text-label text-gray-300"
                        title={command}
                      >
                        {command}
                      </code>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-gray-500">No gate is bound to this mission.</p>
              )}
            </article>
          </div>

          {/* Same min-w-0 fix as the grid above -- defensive here even though this pair's
              content doesn't currently have unbreakable long strings, since the same
              Nfr-floors-at-max-content trap applies to any Nfr grid-cols split. */}
          <div className="mt-4 grid gap-4 @2xl:grid-cols-[1.15fr_0.85fr]">
            <section className="@container min-w-0 rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <div className="mb-3 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                <BookOpenCheck size={13} /> Gate checklist
              </div>
              {/* Same nested-viewport-breakpoint bug as the Objective/User outcome grid above --
                  @container query instead of md:, since this section's real width is likewise
                  determined by ancestor splits (280px missions rail, xl:[1.15fr_0.85fr] here),
                  not the raw viewport. */}
              <div className="grid gap-3 @md:grid-cols-2">
                {mission.gates.map((gate) => (
                  <article
                    key={gate.gateId}
                    className="rounded-lg border border-white/8 bg-black/25 p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 className="text-sm font-black text-white">{gate.title}</h4>
                      <span
                        className={`rounded-md border px-2 py-1 text-eyebrow font-black uppercase tracking-widest ${GATE_STATUS_CLASS[gate.status]}`}
                      >
                        {releaseGateStatusLabel(gate.status)}
                      </span>
                    </div>
                    <p className="mt-2 text-label leading-relaxed text-gray-400">
                      {gate.nextAction}
                    </p>
                    <div className="mt-3 space-y-1">
                      {gate.evidence.slice(0, 2).map((path) => (
                        <div
                          key={path}
                          className="flex min-w-0 items-center gap-2 rounded border border-white/8 bg-black/30 px-2 py-1 text-meta text-gray-500"
                          title={path}
                        >
                          <FileText size={11} className="shrink-0 text-gray-600" />
                          <span className="truncate font-mono">{path}</span>
                        </div>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="min-w-0 rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <div className="mb-3 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)]">
                <TerminalSquare size={13} /> Related successor locks
              </div>
              <div className="space-y-3">
                {mission.pillars.map((pillar) => (
                  <article
                    key={pillar.id}
                    className="rounded-lg border border-white/8 bg-black/25 p-3"
                  >
                    <div className="flex items-start gap-3">
                      <CheckCircle2
                        size={14}
                        className="mt-0.5 shrink-0 text-[var(--determinex-accent)]"
                      />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm font-black text-white">{pillar.title}</h4>
                          <span className="rounded border border-white/10 bg-white/[0.03] px-2 py-0.5 text-eyebrow font-black uppercase tracking-widest text-gray-500">
                            {successorStatusLabel(pillar.status)}
                          </span>
                        </div>
                        <p className="mt-2 text-label leading-relaxed text-gray-400">
                          {pillar.nextLock}
                        </p>
                        <p className="mt-2 text-label leading-relaxed text-gray-600">
                          {pillar.blocker}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </section>
  );
}
