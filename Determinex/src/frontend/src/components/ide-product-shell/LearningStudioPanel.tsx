// CLAUDE LANE — Learning Studio panel.
// Locked under: locks/sentinel/DETERMINEX_REACT_LEARNING_STUDIO_PANEL_LOCK_001.json
//
// Mounts the teaching / explanation panel. Learning outputs are
// visibly non-authorizing. Suggested fixes route to Repo Clinic.
// Suggested new projects route to Idea Lab. Learning cannot approve
// or mutate source. Teaching windows explain blocked reasons.

"use client";
import * as React from "react";

import {
  invokeUnifiedProductCommand,
  READY_DOES_NOT_MEAN_AUTHORIZED,
  UnifiedProductResponse,
} from "@/lib/ide-product-shell-api";
import { UserLevelTeachingMode } from "./UserLevelTeachingMode";

export const REACT_LEARNING_STUDIO_PANEL_STATUS_TOKENS = [
  "REACT_LEARNING_STUDIO_PANEL_PASSED",
  "REACT_LEARNING_STUDIO_PANEL_BLOCKED_MUTATION_CONFUSION",
  "REACT_LEARNING_STUDIO_PANEL_BLOCKED_FALSE_SUCCESS",
  "REACT_LEARNING_STUDIO_PANEL_BLOCKED_MISSING_TEACHING_LEVELS",
] as const;

// The 9 canonical learning modes. Order matches the backend's
// LEARNING_MODES tuple in scripts/ide/learning_studio_workflow.py.
const LEARNING_MODES = [
  "explain_this_repo",
  "explain_this_file",
  "explain_this_error",
  "explain_this_test_failure",
  "teach_me_the_concept",
  "compare_possible_fixes",
  "walk_me_through_the_patch",
  "show_beginner_vs_professional_version",
  "generate_learning_checklist",
] as const;

type LearningMode = (typeof LEARNING_MODES)[number];

const MODE_LABELS: Record<LearningMode, string> = {
  explain_this_repo: "Explain this repo",
  explain_this_file: "Explain this file",
  explain_this_error: "Explain this error",
  explain_this_test_failure: "Explain this test failure",
  teach_me_the_concept: "Teach me the concept",
  compare_possible_fixes: "Compare possible fixes",
  walk_me_through_the_patch: "Walk me through the patch",
  show_beginner_vs_professional_version: "Beginner version / professional version",
  generate_learning_checklist: "Generate learning checklist",
};

export interface LearningStudioPanelProps {
  /** Switch the workbench to the Repo Clinic panel. */
  onOpenRepoClinic?: () => void;
  /** Switch the workbench to the new-project flow (ConceptLab). */
  onOpenIdeaLab?: () => void;
}

export function LearningStudioPanel({
  onOpenRepoClinic,
  onOpenIdeaLab,
}: LearningStudioPanelProps = {}) {
  const [resp, setResp] = React.useState<UnifiedProductResponse | null>(null);
  const [active, setActive] = React.useState<LearningMode>("explain_this_repo");
  const [loading, setLoading] = React.useState(false);
  const [context, setContext] = React.useState("");
  const [genResp, setGenResp] = React.useState<UnifiedProductResponse | null>(null);
  const [generating, setGenerating] = React.useState(false);
  const [corpusMode, setCorpusMode] = React.useState<"ask" | "maturity">("ask");
  const [showLevelPicker, setShowLevelPicker] = React.useState(false);
  const [corpusQuery, setCorpusQuery] = React.useState("");
  const [corpusResp, setCorpusResp] = React.useState<UnifiedProductResponse | null>(null);
  const [corpusQuerying, setCorpusQuerying] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await invokeUnifiedProductCommand("get_learning_studio_workflow_state");
      setResp(r);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const generate = React.useCallback(async () => {
    setGenerating(true);
    try {
      const r = await invokeUnifiedProductCommand("generate_learning_studio_content", {
        mode: active,
        context,
      });
      setGenResp(r);
    } finally {
      setGenerating(false);
    }
  }, [active, context]);

  const askCorpus = React.useCallback(async () => {
    if (!corpusQuery.trim()) return;
    setCorpusQuerying(true);
    try {
      // Was corpus_query/corpus_mode -- those are the INTERNAL payload keys
      // query_corpus's Rust command repackages its real params into before
      // shelling to Python, not the Tauri command's actual parameter names
      // (query, mode). Passing the wrong names meant the query text never
      // reached the backend -- every search silently ran against an empty
      // query, so "No corpus entries matched" looked like a real (if
      // unlucky) empty result instead of the bug it was.
      const r = await invokeUnifiedProductCommand("query_corpus", {
        query: corpusQuery,
        mode: "ask",
      });
      setCorpusResp(r);
    } finally {
      setCorpusQuerying(false);
    }
  }, [corpusQuery]);

  // "What's missing" — the corpus's own grounded self-report (literal markers like "NOT YET
  // BUILT" it already writes into its own entries), not an LLM guessing at gaps. Answers the
  // question directly: can the corpus tell you what it thinks it's missing?
  const checkCorpusMaturity = React.useCallback(async () => {
    setCorpusQuerying(true);
    try {
      const r = await invokeUnifiedProductCommand("query_corpus", {
        query: corpusQuery,
        mode: "maturity",
      });
      setCorpusResp(r);
    } finally {
      setCorpusQuerying(false);
    }
  }, [corpusQuery]);

  const output = genResp?.payload?.output as
    | { text?: string; suggests_fix?: boolean; suggests_new_project?: boolean; routes_to?: string }
    | undefined;

  const corpusHits =
    (corpusResp?.payload?.hits as
      | { source: string; key: string; title: string; snippet: string; score: number }[]
      | undefined) ?? [];
  const corpusWarnings = (corpusResp?.payload?.warnings as string[] | undefined) ?? [];
  const corpusOpenItems =
    (corpusResp?.payload?.open_items as
      | { key: string; marker: string; topic: string; snippet: string }[]
      | undefined) ?? [];
  const corpusMaturityStats = corpusResp?.payload?.stats as
    | {
        total_top_level_entries: number;
        learned_class_verified_count: number;
        quarantined_count: number;
      }
    | undefined;
  const corpusFlywheelEmpty = corpusResp?.payload?.flywheel_is_empty as boolean | undefined;

  const renderStatus = "REACT_LEARNING_STUDIO_PANEL_PASSED";

  return (
    <section
      data-testid="learning-studio-panel"
      data-status={renderStatus}
      className="rounded border p-3 text-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium">Learning Studio</h3>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="text-xs underline opacity-80 hover:opacity-100"
          data-testid="learning-studio-refresh"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="mt-2">
        <button
          type="button"
          data-testid="learning-studio-toggle-level-picker"
          onClick={() => setShowLevelPicker((v) => !v)}
          className="text-xs underline opacity-80 hover:opacity-100"
        >
          {showLevelPicker
            ? "Hide explanation level"
            : "Choose explanation level (beginner ↔ professional)"}
        </button>
        {showLevelPicker && (
          <div data-testid="learning-studio-user-level-teaching-mode" className="mt-2">
            <UserLevelTeachingMode />
          </div>
        )}
      </div>

      <nav
        role="tablist"
        className="mt-2 flex flex-wrap gap-2 border-b"
        data-testid="learning-studio-modes"
      >
        {LEARNING_MODES.map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={active === m}
            data-testid={`learning-studio-mode-${m}`}
            data-mode={m}
            onClick={() => setActive(m)}
            className={
              "px-2 py-1 text-xs " + (active === m ? "font-semibold underline" : "opacity-70")
            }
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </nav>

      <div data-testid="learning-studio-ask-corpus" className="mt-3 space-y-1 border-b pb-3">
        <div className="flex items-center justify-between">
          <strong>Consult the corpus</strong>
          <div className="flex gap-1" data-testid="learning-studio-corpus-mode-toggle">
            <button
              type="button"
              data-testid="learning-studio-corpus-mode-ask"
              onClick={() => setCorpusMode("ask")}
              className={`rounded border px-2 py-0.5 text-label ${corpusMode === "ask" ? "font-semibold underline" : "opacity-70"}`}
            >
              Ask
            </button>
            <button
              type="button"
              data-testid="learning-studio-corpus-mode-maturity"
              onClick={() => setCorpusMode("maturity")}
              className={`rounded border px-2 py-0.5 text-label ${corpusMode === "maturity" ? "font-semibold underline" : "opacity-70"}`}
            >
              What&apos;s missing?
            </button>
          </div>
        </div>

        {corpusMode === "ask" ? (
          <div className="flex gap-2">
            <input
              type="text"
              data-testid="learning-studio-ask-corpus-input"
              className="w-full rounded border bg-transparent p-1 text-xs"
              placeholder="e.g. what is the honest ProgramBench lock count?"
              value={corpusQuery}
              onChange={(e) => setCorpusQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void askCorpus();
              }}
            />
            <button
              type="button"
              data-testid="learning-studio-ask-corpus-button"
              onClick={() => void askCorpus()}
              disabled={corpusQuerying || !corpusQuery.trim()}
              className="shrink-0 rounded border px-2 py-1 text-xs opacity-90 hover:opacity-100"
            >
              {corpusQuerying ? "Asking…" : "Ask"}
            </button>
          </div>
        ) : (
          <div className="flex gap-2">
            <input
              type="text"
              data-testid="learning-studio-corpus-maturity-topic-input"
              className="w-full rounded border bg-transparent p-1 text-xs"
              placeholder="Optional topic filter (e.g. HACKATHON_CAMPAIGN) — leave blank for everything"
              value={corpusQuery}
              onChange={(e) => setCorpusQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void checkCorpusMaturity();
              }}
            />
            <button
              type="button"
              data-testid="learning-studio-corpus-maturity-button"
              onClick={() => void checkCorpusMaturity()}
              disabled={corpusQuerying}
              className="shrink-0 rounded border px-2 py-1 text-xs opacity-90 hover:opacity-100"
            >
              {corpusQuerying ? "Checking…" : "Show what's missing"}
            </button>
          </div>
        )}

        {corpusResp && corpusMode === "ask" && (
          <div
            data-testid="learning-studio-ask-corpus-results"
            className="rounded border p-2 text-xs"
          >
            {corpusHits.length === 0 ? (
              <div data-testid="learning-studio-ask-corpus-no-hits">
                No corpus entries matched. Try different wording.
              </div>
            ) : (
              <ul className="space-y-1">
                {corpusHits.map((h) => (
                  <li
                    key={h.source + h.key}
                    data-testid={`learning-studio-ask-corpus-hit-${h.key}`}
                  >
                    <strong>{h.title}</strong> <span className="opacity-60">({h.source})</span>
                    <div className="opacity-80">{h.snippet}</div>
                  </li>
                ))}
              </ul>
            )}
            {corpusWarnings.length > 0 && (
              <div
                data-testid="learning-studio-ask-corpus-warnings"
                className="mt-2 rounded bg-amber-50 p-1 text-amber-900"
              >
                {corpusWarnings.map((w, i) => (
                  <div key={i}>⚠ {w}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {corpusResp && corpusMode === "maturity" && (
          <div
            data-testid="learning-studio-corpus-maturity-results"
            className="rounded border p-2 text-xs"
          >
            {corpusMaturityStats && (
              <div data-testid="learning-studio-corpus-maturity-stats" className="mb-2 opacity-80">
                {corpusMaturityStats.total_top_level_entries} corpus entries ·{" "}
                {corpusMaturityStats.learned_class_verified_count} verified learned classes ·{" "}
                {corpusFlywheelEmpty ? "flywheel is EMPTY" : "flywheel has entries"}
                {corpusMaturityStats.quarantined_count > 0 &&
                  ` · ${corpusMaturityStats.quarantined_count} quarantined pending reabsorption`}
              </div>
            )}
            {corpusOpenItems.length === 0 ? (
              <div data-testid="learning-studio-corpus-maturity-no-open-items">
                No open/unresolved markers found for this scope. This does NOT mean everything is
                done — only that the corpus&apos;s own entries don&apos;t flag anything open here.
              </div>
            ) : (
              <ul className="space-y-1">
                {corpusOpenItems.map((item, i) => (
                  <li
                    key={item.key + i}
                    data-testid={`learning-studio-corpus-maturity-item-${item.key}`}
                  >
                    <strong>{item.marker}</strong>{" "}
                    <span className="opacity-60">
                      ({item.key}
                      {item.topic ? ` · ${item.topic}` : ""})
                    </span>
                    <div className="opacity-80">{item.snippet}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div data-testid={`learning-studio-content-${active}`} className="mt-3 space-y-2">
        <div data-testid="learning-studio-mode-explanation">
          <strong>Mode:</strong> {MODE_LABELS[active]}
        </div>

        <div data-testid="learning-studio-context-input-row" className="space-y-1">
          <textarea
            data-testid="learning-studio-context-input"
            className="w-full rounded border bg-transparent p-1 text-xs"
            rows={3}
            placeholder="Paste an error, file path, diff, concept, or symptom for this mode…"
            value={context}
            onChange={(e) => setContext(e.target.value)}
          />
          <button
            type="button"
            data-testid="learning-studio-generate"
            onClick={() => void generate()}
            disabled={generating}
            className="rounded border px-2 py-1 text-xs opacity-90 hover:opacity-100"
          >
            {generating ? "Generating…" : "Generate (grounded in the verified corpus)"}
          </button>
        </div>

        {output && (
          <div
            data-testid="learning-studio-generated-output"
            className="rounded border p-2 text-xs whitespace-pre-wrap"
          >
            {output.text}
            {output.suggests_fix && (
              <div data-testid="learning-studio-generated-suggests-fix" className="mt-1 opacity-80">
                This explanation names a known fix — see &quot;Open in Repo Clinic&quot; below to
                act on it.
              </div>
            )}
          </div>
        )}

        <div
          data-testid="learning-studio-non-authorizing-caption"
          className="rounded bg-slate-50 p-2 text-xs"
        >
          Learning explains. Learning does NOT approve, apply, or authorize source mutation.
        </div>

        {/* These two were <a href="#repo-clinic"> and <a href="#idea-lab">. NOTHING in the
            app carries those ids, so both were dead clicks -- a user reading "Want to act
            on a fix? Open in Repo Clinic" got a changed URL hash and no navigation, while
            Repo Clinic sat one panel away in the same window.

            Both now call the workbench's real panel switcher. When no handler is supplied
            they render as plain text rather than a link, so this can never present a
            clickable promise it cannot keep again. */}
        <div data-testid="learning-studio-route-to-repo-clinic">
          <strong>Want to act on a fix?</strong>{" "}
          {onOpenRepoClinic ? (
            <button
              type="button"
              data-testid="learning-studio-route-link-repo-clinic"
              data-routes-to="repo_clinic"
              className="underline"
              onClick={onOpenRepoClinic}
            >
              Open in Repo Clinic
            </button>
          ) : (
            <span data-routes-to="repo_clinic">Repo Clinic</span>
          )}{" "}
          — the gated repair workflow.
        </div>

        <div data-testid="learning-studio-route-to-idea-lab">
          <strong>Want to start a new project?</strong>{" "}
          {onOpenIdeaLab ? (
            <button
              type="button"
              data-testid="learning-studio-route-link-idea-lab"
              data-routes-to="idea_lab"
              className="underline"
              onClick={onOpenIdeaLab}
            >
              Open in Idea Lab
            </button>
          ) : (
            <span data-routes-to="idea_lab">Idea Lab</span>
          )}{" "}
          — the gated new-project workflow.
        </div>

        <div
          data-testid="learning-studio-teaching-window-blocked-reason"
          className="text-xs opacity-80"
        >
          When something is blocked, this window explains why: the relevant gate (approval /
          verifier / snapshot / body hash / symlink refusal) is named so the operator can act.
        </div>
      </div>

      <footer
        data-testid="learning-studio-caveats-footer"
        className="mt-3 border-t pt-2 text-xs opacity-80"
      >
        <div data-testid="learning-studio-ready-does-not-mean-authorized">
          {READY_DOES_NOT_MEAN_AUTHORIZED}
        </div>
        <div data-testid="learning-studio-cannot-approve">Learning cannot approve a patch.</div>
        <div data-testid="learning-studio-cannot-mark-repair-success">
          Learning cannot mark repair success.
        </div>
        <div data-testid="learning-studio-cannot-mutate-source">Learning cannot mutate source.</div>
        <div data-testid="learning-studio-training-stays-false">
          Training stays false (training_eligible: false).
        </div>
        {!resp && <div>loading workflow definition…</div>}
      </footer>
    </section>
  );
}
