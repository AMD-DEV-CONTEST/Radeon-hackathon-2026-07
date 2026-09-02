"use client";
import { useState } from "react";
import {
  Search,
  CheckCircle2,
  XCircle,
  Zap,
  Clock,
  ArrowRight,
  ShieldCheck,
  FlaskConical,
  GitCompare,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { isTauri, invokeSafe, readFileContent } from "@/lib/api";
import { resolveLocalModelTag } from "@/lib/work-readiness";

/**
 * Verified Search = the Correctness Amplifier, driven from the IDE.
 *
 * History worth keeping: this panel used to call a Tauri command named
 * "verified_search" that was never implemented on the Rust side -- 152
 * registered commands and none by that name. Every search therefore fell
 * straight into invokeSafe's null path and printed "backend is not
 * registered." It was the only broken invoke in the whole frontend.
 *
 * The fix is deliberately NOT a new parallel backend. CLAUDE.md's
 * audit-before-build rule says wire the canonical module instead of shipping
 * a duplicate, and the canonical idea -> sound-oracle -> amplified-solve path
 * already ships as two governed commands used by the Work cockpit's Quick
 * Verify (ConceptLab):
 *
 *   preview_idea_oracle  -> synthesize_oracle_preview  (deterministic, no model)
 *   build_idea           -> build_from_idea_opt_in     (opt-in, runs the local model)
 *
 * What is rendered below is exactly what those commands return -- oracle check
 * count, soundness, the generated test bodies, sample count, proof, and the
 * verified program. The old UI showed a per-candidate PASS/FAIL list with
 * source for every attempt; the backend does not expose per-candidate results
 * (only how many samples the amplifier drew), so that list is gone rather than
 * reconstructed from guesses. Fabricating it would be exactly the kind of
 * unearned claim the oracle exists to prevent.
 */

type PreviewPayload = {
  n_checks?: number;
  oracle_sound?: boolean;
  oracle_tests?: string;
  note?: string;
};

type BuildPayload = {
  solved?: boolean;
  n_checks?: number;
  samples?: number;
  proof?: string;
  program?: string;
  oracle_tests?: string;
  next_moves?: string[];
};

type Envelope<T> = {
  status?: string;
  payload?: T;
  notes?: string[];
};

const DEMO_QUERIES = [
  "find all files that match a shell glob pattern",
  "count lines in a file, skipping blank lines",
  "parse a JSON array and sum a numeric field",
];

function StatusNote({ status, notes }: { status?: string; notes?: string[] }) {
  if (!status) return null;
  const blocked = status.includes("BLOCKED");
  // Keyed on the suffix, not the whole string: _tauri_driver.py rewrites every
  // inner IDE_COMMAND_* status to TAURI_COMMAND_* on the way out, so matching
  // the IDE_ names (as this did at first) silently matched nothing and the user
  // got a bare status code with no explanation. Verified live -- a real run
  // returned TAURI_COMMAND_BLOCKED_NO_MODEL.
  const human: Record<string, string> = {
    BLOCKED_NO_MODEL:
      "No local model is configured, so the amplifier has nothing to sample from. Open the Repair panel and set one up under Local Model Settings — the oracle step above still works without it.",
    BLOCKED_NOT_OPTED_IN: "The build step needs an explicit opt-in before it will run a model.",
    BLOCKED_UNKNOWN:
      "The desktop backend did not recognize this command. This build may be out of date.",
  };
  const suffix = status.replace(/^(TAURI|IDE)_COMMAND_/, "");
  const msg = human[suffix];
  if (!blocked && !msg) return null;
  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-950/10 px-4 py-3 text-label font-mono text-amber-200/80 shrink-0">
      <div className="mb-1 flex items-center gap-2 text-eyebrow font-black uppercase tracking-widest text-amber-300">
        <XCircle size={11} /> {status}
      </div>
      {msg ?? notes?.join(" ") ?? "The backend declined this request."}
    </div>
  );
}

function OracleCard({
  nChecks,
  sound,
  tests,
}: {
  nChecks?: number;
  sound?: boolean;
  tests?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-white/8 bg-black/30 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <ShieldCheck
          size={13}
          className={sound ? "text-emerald-400 shrink-0" : "text-amber-400 shrink-0"}
        />
        <div className="flex-1 min-w-0">
          <div className="text-label font-bold text-white/70">
            {nChecks ?? 0} oracle check{nChecks === 1 ? "" : "s"} synthesized
          </div>
          <div className="text-meta font-mono text-gray-600">
            {sound
              ? "Sound — every check is type-safe and assertable."
              : "Not proven sound — treat any result as unverified."}
          </div>
        </div>
        <span className="text-eyebrow uppercase font-bold tracking-widest text-gray-600 shrink-0">
          {open ? "Hide" : "Show tests"}
        </span>
      </button>
      {open && tests && (
        <pre className="max-h-64 overflow-auto no-scrollbar border-t border-white/5 bg-black/40 p-3 text-label leading-relaxed text-emerald-300/80 whitespace-pre-wrap">
          {tests}
        </pre>
      )}
    </div>
  );
}

export function VerifiedSearch({
  selectedModel,
  workspacePath,
}: {
  selectedModel?: string;
  workspacePath?: string;
}) {
  const [query, setQuery] = useState("");
  // A verified program is deliberately TEMP-ONLY -- build_from_idea_opt_in never
  // writes into the workspace. That left it as a dead end: oracle-verified code
  // you could only copy out by hand. Staging it into the Review queue is the
  // missing step, and it is the one honest producer for that queue -- unlike the
  // hive fix pipeline, which writes to your real files and then reverts on
  // failure, so git (Source Control) is already its review surface.
  // `solution` is not arbitrary: the synthesized oracle emits
  // `from solution import *`, so that module name is what the tests import.
  const [savePath, setSavePath] = useState("solution.py");
  const [staging, setStaging] = useState(false);
  const [stageMsg, setStageMsg] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "preview" | "build">("idle");
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [build, setBuild] = useState<BuildPayload | null>(null);
  const [status, setStatus] = useState<string | undefined>();
  const [notes, setNotes] = useState<string[] | undefined>();
  const [error, setError] = useState<string | null>(null);
  const tauriMode = isTauri();

  const reset = () => {
    setPreview(null);
    setBuild(null);
    setStatus(undefined);
    setNotes(undefined);
    setError(null);
  };

  // Step 1: deterministic, no model, no mutation. Shows the oracle the answer
  // will have to satisfy BEFORE anything is generated -- the soundness
  // contract the amplifier depends on.
  const runPreview = async () => {
    if (!query.trim() || phase !== "idle") return;
    reset();
    setPhase("preview");
    try {
      const res = await invokeSafe<Envelope<PreviewPayload>>("preview_idea_oracle", {
        ideaText: query,
        modelId: resolveLocalModelTag(selectedModel),
      });
      if (!res) {
        setError(
          tauriMode
            ? "The desktop backend did not respond to preview_idea_oracle."
            : "Verified Search needs the Tauri desktop runtime or the local IDE HTTP bridge."
        );
        return;
      }
      setStatus(res.status);
      setNotes(res.notes);
      setPreview(res.payload ?? {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Oracle preview failed.");
    } finally {
      setPhase("idle");
    }
  };

  // Step 2: opt-in, runs the local model, TEMP-ONLY (never mutates your source).
  const runBuild = async () => {
    if (!query.trim() || phase !== "idle") return;
    setBuild(null);
    setError(null);
    setPhase("build");
    try {
      const res = await invokeSafe<Envelope<BuildPayload>>("build_idea", {
        ideaText: query,
        optIn: true,
        modelId: resolveLocalModelTag(selectedModel),
      });
      if (!res) {
        setError(
          tauriMode
            ? "The desktop backend did not respond to build_idea."
            : "Verified Search needs the Tauri desktop runtime or the local IDE HTTP bridge."
        );
        return;
      }
      setStatus(res.status);
      setNotes(res.notes);
      setBuild(res.payload ?? {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verified build failed.");
    } finally {
      setPhase("idle");
    }
  };

  const stageForReview = async (program: string) => {
    if (!workspacePath) {
      setStageMsg("Open a workspace first — a staged diff must land inside one.");
      return;
    }
    const rel = savePath.trim().replace(/^[\\/]+/, "");
    if (!rel) {
      setStageMsg("Give the file a name first.");
      return;
    }
    const sep = workspacePath.includes("\\") ? "\\" : "/";
    const target = `${workspacePath.replace(/[\\/]+$/, "")}${sep}${rel}`;

    setStaging(true);
    setStageMsg(null);
    try {
      // A brand-new file has no original; read_file_content throws for a
      // missing path, which is the normal case here rather than an error.
      let original = "";
      try {
        const existing = await readFileContent(target);
        if (existing) original = existing.content;
      } catch {
        original = "";
      }
      if (original === program) {
        setStageMsg(`${rel} already contains exactly this program — nothing to review.`);
        return;
      }
      // Raw invoke, deliberately, and NOT invokeSafe.
      //
      // stage_diff_for_review returns Result<(), String>, so a success resolves
      // to null -- exactly what invokeSafe also returns on failure. Treating
      // null as failure reported "the backend refused" for a stage that had in
      // fact just been queued; caught live when Review then showed two entries
      // after one "failed" and one "successful" click. A false negative on a
      // write action is worse than a raw error: it invites the user to retry
      // and silently duplicates the work.
      //
      // invoke() rejects on a real error and resolves on success, which is the
      // only way to tell those apart for a void command. It also surfaces the
      // actual message, where invokeSafe only console.warn's it and the dev
      // overlay forwards nothing but console.error.
      if (!isTauri()) {
        setStageMsg("Staging a diff needs the desktop runtime.");
        return;
      }
      await invoke("stage_diff_for_review", {
        diff: {
          id: `verified-${Date.now()}`,
          path: target,
          originalContent: original,
          proposedContent: program,
        },
      });
      setStageMsg(
        `Staged ${rel} for review. Open the Review panel to inspect the diff and apply it.`
      );
    } catch (e) {
      setStageMsg(`Could not stage: ${e}`);
    } finally {
      setStaging(false);
    }
  };

  const busy = phase !== "idle";

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="pointer-events-none absolute inset-0 opacity-8">
        <div
          className="absolute right-0 bottom-0 h-[400px] w-[400px] translate-x-1/3 translate-y-1/3 rounded-full"
          style={{ background: "var(--dtx-info)", filter: "blur(100px)" }}
        />
      </div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-4">
        {/* Header */}
        <div className="border-b border-white/10 pb-4 shrink-0">
          <div className="mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-blue-400">
            <Search size={13} /> Verified Search
          </div>
          <h2
            className="text-hero font-black leading-tight text-[var(--determinex-text)]"
            style={{ fontFamily: "var(--determinex-font-display)" }}
          >
            Oracle Search
          </h2>
          <p className="mt-1 text-label font-mono text-gray-600">
            Synthesize a sound oracle first, then sample until something passes it.
          </p>
        </div>

        {/* Query */}
        <div className="flex gap-2 shrink-0">
          <div className="relative flex-1">
            <Search
              size={13}
              className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-600"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runPreview()}
              placeholder="Describe a single function you need..."
              className="w-full rounded-xl border border-white/10 bg-black/40 py-3 pl-10 pr-4 text-body text-white/80 outline-none transition-colors placeholder:text-gray-700 focus:border-[var(--determinex-accent)]/40"
            />
          </div>
          <button
            onClick={runPreview}
            disabled={busy || !query.trim()}
            title="Deterministic. Synthesizes the oracle only — no model runs."
            className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/[0.03] px-4 py-3 text-meta font-black uppercase tracking-widest text-gray-300 transition-all hover:bg-white/[0.07] disabled:opacity-40"
          >
            {phase === "preview" ? (
              <Clock size={14} className="animate-spin" />
            ) : (
              <FlaskConical size={14} />
            )}
            Oracle
          </button>
          <button
            onClick={runBuild}
            disabled={busy || !query.trim()}
            title="Runs the local model, sampling until a candidate passes the oracle. Never writes to your source."
            className="flex items-center gap-2 rounded-xl border border-[var(--determinex-accent)]/40 bg-[var(--determinex-accent)]/10 px-4 py-3 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)] transition-all hover:bg-[var(--determinex-accent)]/20 disabled:opacity-40"
          >
            {phase === "build" ? <Clock size={14} className="animate-spin" /> : <Zap size={14} />}
            Verify
          </button>
        </div>

        {/* Demo queries */}
        {!preview && !build && !busy && !error && (
          <div className="space-y-1.5 shrink-0">
            <div className="mb-2 text-eyebrow font-bold uppercase tracking-widest text-gray-700">
              Try a query
            </div>
            {DEMO_QUERIES.map((q) => (
              <button
                key={q}
                onClick={() => setQuery(q)}
                className="group flex w-full items-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2.5 text-left transition-all hover:border-white/10 hover:bg-white/[0.04]"
              >
                <ArrowRight
                  size={11}
                  className="shrink-0 text-gray-700 transition-colors group-hover:text-[var(--determinex-accent)]"
                />
                <span className="text-label font-mono text-gray-500 transition-colors group-hover:text-gray-300">
                  {q}
                </span>
              </button>
            ))}
          </div>
        )}

        {error && !busy && (
          <div className="shrink-0 rounded-xl border border-amber-500/20 bg-amber-950/10 px-4 py-3 font-mono text-label text-amber-200/80">
            <div className="mb-1 flex items-center gap-2 text-eyebrow font-black uppercase tracking-widest text-amber-300">
              <XCircle size={11} /> Backend unavailable
            </div>
            {error}
          </div>
        )}

        {!error && <StatusNote status={status} notes={notes} />}

        {busy && (
          <div className="flex flex-1 flex-col items-center justify-center gap-4">
            <div className="relative h-20 w-20">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div
                  key={i}
                  className="absolute inset-0 animate-ping rounded-full border border-[var(--determinex-accent)]/30"
                  style={{ animationDelay: `${i * 0.2}s`, animationDuration: "1.5s" }}
                />
              ))}
              <div className="absolute inset-0 flex items-center justify-center">
                <Zap size={24} className="animate-pulse text-[var(--determinex-accent)]" />
              </div>
            </div>
            <div className="text-center">
              <div className="text-body font-bold text-white/60">
                {phase === "preview" ? "Synthesizing oracle…" : "Sampling until one passes…"}
              </div>
              <div className="mt-1 font-mono text-label text-gray-700">
                {phase === "preview"
                  ? "Deterministic — no model is running."
                  : "Each candidate is checked against the oracle before you see it."}
              </div>
            </div>
          </div>
        )}

        {/* Results */}
        {!busy && (preview || build) && (
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto no-scrollbar">
            <OracleCard
              nChecks={build?.n_checks ?? preview?.n_checks}
              sound={preview?.oracle_sound ?? (build ? true : undefined)}
              tests={build?.oracle_tests ?? preview?.oracle_tests}
            />

            {preview?.note && !build && (
              <p className="px-1 font-mono text-label leading-relaxed text-gray-500">
                {preview.note}
              </p>
            )}

            {preview && !build && (
              <p className="px-1 text-label leading-relaxed text-gray-600">
                This is the contract only — nothing has been generated yet. Press{" "}
                <span className="font-bold text-[var(--determinex-accent)]">Verify</span> to sample
                the local model until a candidate satisfies every check above.
              </p>
            )}

            {build && (
              <>
                <div className="flex items-center justify-between rounded-xl border border-white/8 bg-black/30 px-4 py-3">
                  <div className="flex items-center gap-2">
                    {build.solved ? (
                      <CheckCircle2 size={13} className="text-emerald-400" />
                    ) : (
                      <XCircle size={13} className="text-red-400" />
                    )}
                    <span
                      className={`text-meta font-black uppercase tracking-widest ${build.solved ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {build.solved ? "Oracle-verified" : "Not solved"}
                    </span>
                  </div>
                  <div className="font-mono text-label text-gray-600">
                    {build.samples ?? 0} sample{build.samples === 1 ? "" : "s"} drawn
                  </div>
                </div>

                {build.proof && (
                  <div className="rounded-xl border border-emerald-500/15 bg-emerald-950/10 px-4 py-3">
                    <div className="mb-1 text-eyebrow font-black uppercase tracking-widest text-emerald-400">
                      Proof
                    </div>
                    <pre className="whitespace-pre-wrap font-mono text-label leading-relaxed text-emerald-200/70">
                      {build.proof}
                    </pre>
                  </div>
                )}

                {build.solved && build.program && (
                  <div className="overflow-hidden rounded-xl border border-emerald-500/25 bg-black/40">
                    <div className="border-b border-white/5 px-3 py-2 text-eyebrow font-black uppercase tracking-widest text-emerald-400">
                      Verified program
                    </div>
                    <pre className="max-h-80 overflow-auto no-scrollbar p-3 font-mono text-label leading-relaxed text-emerald-300/85 whitespace-pre-wrap">
                      {build.program}
                    </pre>
                  </div>
                )}

                {!build.solved && !!build.next_moves?.length && (
                  <div className="rounded-xl border border-white/8 bg-black/30 px-4 py-3">
                    <div className="mb-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-500">
                      Next moves
                    </div>
                    <ul className="space-y-1">
                      {build.next_moves.map((m, i) => (
                        <li key={i} className="font-mono text-label leading-relaxed text-gray-400">
                          — {m}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {build.solved && build.program && (
                  <div className="rounded-xl border border-white/8 bg-black/30 p-3">
                    <div className="mb-2 text-eyebrow font-black uppercase tracking-widest text-gray-500">
                      Send to your workspace
                    </div>
                    <div className="flex gap-2">
                      <input
                        value={savePath}
                        onChange={(e) => setSavePath(e.target.value)}
                        spellCheck={false}
                        placeholder="solution.py"
                        className="flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 font-mono text-label text-white/80 outline-none transition-colors placeholder:text-gray-700 focus:border-[var(--determinex-accent)]/40"
                      />
                      <button
                        onClick={() => stageForReview(build.program!)}
                        disabled={staging || !workspacePath}
                        title={
                          workspacePath
                            ? "Queue this as a diff in the Review panel — nothing is written until you approve it there."
                            : "Open a workspace first."
                        }
                        className="flex items-center gap-1.5 rounded-lg border border-purple-400/40 bg-purple-400/10 px-3 py-2 text-meta font-black uppercase tracking-widest text-purple-300 transition-all hover:bg-purple-400/20 disabled:opacity-40"
                      >
                        <GitCompare size={12} />
                        {staging ? "Staging…" : "Stage for review"}
                      </button>
                    </div>
                    {stageMsg && (
                      <p className="mt-2 font-mono text-label leading-relaxed text-gray-400">
                        {stageMsg}
                      </p>
                    )}
                  </div>
                )}

                <p className="px-1 font-mono text-meta text-gray-700">
                  Nothing is written to your workspace until you approve the staged diff in Review.
                </p>
              </>
            )}
          </div>
        )}

        {!tauriMode && (
          <div className="shrink-0 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2 text-center font-mono text-meta text-gray-700">
            Browser mode: results appear only when the local IDE HTTP bridge returns a real verifier
            response.
          </div>
        )}
      </div>
    </div>
  );
}
