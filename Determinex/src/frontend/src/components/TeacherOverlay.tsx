"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import type { PointerEvent } from "react";
import {
  X,
  ChevronLeft,
  ChevronRight,
  GraduationCap,
  Zap,
  Code2,
  ShieldCheck,
  Activity,
  Search,
  Package,
  Terminal,
  BookOpen,
  Lightbulb,
  CheckCircle2,
  KeyRound,
  Folder,
  Database,
  Eye,
  GitPullRequest,
  Bot,
} from "lucide-react";

type Step = {
  id: string;
  title: string;
  subtitle: string;
  icon: typeof Zap;
  color: string;
  panel: string;
  tips: string[];
  checklist?: string[];
  shortcut?: string;
  action?: string;
};

const STEPS: Step[] = [
  {
    id: "welcome",
    title: "Welcome to Determinex IDE",
    subtitle: "A local-first, self-improving AI coding system with verified correctness.",
    icon: GraduationCap,
    color: "text-[var(--determinex-accent)]",
    panel: "none",
    tips: [
      "Every code change passes a real compiler oracle before it is accepted.",
      "Determinex never returns a 'passing' result from a hallucination — the compiler is the only judge.",
      "Local models keep code on your machine; Cloak sends obfuscated payloads through explicit privacy gates.",
    ],
    action: "Use this guide any time you want the current screen explained.",
  },
  {
    id: "setup",
    title: "First-Run Setup",
    subtitle:
      "Setup should configure privacy policy, provider keys, Ollama, local models, and startup checks in one place.",
    icon: KeyRound,
    color: "text-indigo-400",
    panel: "setup",
    tips: [
      "API keys are optional, but they belong in the Config Vault during setup so cloud roles do not fail later.",
      "Ollama and required local models are checked before the IDE claims the system is ready.",
      "If hardware probing fails, Determinex uses a conservative fallback and tells you it is a fallback.",
    ],
    checklist: [
      "Choose Offline, Cloaked, or Online policy",
      "Add provider keys or intentionally skip them",
      "Confirm Ollama and local model startup checks",
      "Launch only after setup reports System Ready",
    ],
    action: "Open setup if it appears, then move through API keys before hardware startup.",
  },
  {
    id: "local-cloak",
    title: "Local vs Cloak",
    subtitle:
      "Local means models run on this machine; Cloak means cloud calls are allowed only after privacy gates.",
    icon: ShieldCheck,
    color: "text-emerald-400",
    panel: "cloak",
    tips: [
      "Local keeps prompts, source, and model execution on your machine when the selected route is local.",
      "Cloak obfuscates identifiers before cloud-bound calls and keeps audit boundaries explicit.",
      "Cloak is a privacy gate, not a promise that every possible leak has been mathematically eliminated.",
    ],
    checklist: [
      "Use Local when you want no provider calls",
      "Use Cloak when local hardware is tight but privacy gates are required",
      "Check the Privacy Cockpit for Cloak audit evidence after a cloud-assisted run",
    ],
    action: "Use the rail lock button to switch policy and open the Privacy Cockpit.",
  },
  {
    id: "work",
    title: "Work",
    subtitle:
      "The universal entry point for a new idea, an existing project, or an imported app/codebase -- and where the compile-gate loop runs once you start.",
    icon: Zap,
    color: "text-emerald-400",
    // Was "ideation" -- a nav id from before the Work/Space/Brain/Proof/Repair/
    // Audit/Tools rail redesign. It matched nothing real, so this step could
    // only ever be reached manually (dots/Jump To), never by the "explains the
    // current screen" auto-sync the welcome step promises. The real Work rail
    // button sets activeSidebar to "hive" -- confirmed live 2026-07-19 by
    // reading the header title rendered for that value ("Work", not "Hive
    // Sessions"). The separate "Hive Sessions" step this used to defer to
    // described a screen ("click the hexagon icon") that no longer exists in
    // the current rail; folded its still-true tips into this one instead of
    // leaving it stranded and unreachable.
    panel: "hive",
    tips: [
      "Start with plain language; Determinex should ask clarifying questions before writing code.",
      "Choose the project direction before a spec is generated.",
      "Use the project picker when you want to continue an existing codebase.",
      "Each build attempt writes a WAL record: patch + compile error + correction prompt.",
      "Failed attempts automatically become training data for the flywheel.",
    ],
    shortcut: "Ctrl+2",
    action: "Click Work in the rail, then describe the outcome you want.",
  },
  // The five steps below (space, brain, proof-screen, repair-screen, audit)
  // did not exist before 2026-07-19 -- the other 5 primary rail screens had
  // ZERO guide coverage, so opening the guide on any of them silently fell
  // back to the generic "Welcome" step instead of explaining what was
  // actually on screen. Found live while checking Ryan's "space needs more
  // explanation" / "repair is odd" / "brain is wierd layout" / "guide is
  // wierd" feedback -- the guide's own promise ("explains the current
  // screen") was broken for most of the app. Content below was written from
  // the real live screens, not guessed.
  {
    id: "space",
    title: "Space",
    subtitle: "The open project's real git and file state -- not a mockup.",
    icon: Folder,
    color: "text-purple-400",
    panel: "explorer",
    tips: [
      "Source shows branch, upstream tracking, and a real uncommitted-change count; Open Source Control jumps to the Git panel.",
      "Files reports how many entries were scanned; Browse Tree and Find in Files dig in from here.",
      "Runs opens the session log, or jumps to Work if nothing has run yet.",
      "Quick Attach docks Terminal or Code beside this screen instead of navigating away from it.",
    ],
    action: "Click Space in the rail to see the open project's git and file state.",
  },
  {
    id: "brain-screen",
    title: "Brain",
    subtitle:
      "The ProgramBench Cockpit -- live scores from the corpus of locked, oracle-verified tool reimplementations.",
    icon: Database,
    color: "text-orange-400",
    panel: "benchmark",
    tips: [
      "AVG and Tests % are aggregate scores across the active lock set, not a claim about any single tool.",
      '"Perfect (Live)" counts tools re-verified at 100% in the most recent run, not the historical best.',
      'Top Family names the most common failure class across recent evals; Advisor\'s "expected lift" is what fixing it should be worth.',
      "Locked Tools lists real archived evals: pass count / total tests, and the workspace path each was built from.",
    ],
    action: "Click Brain in the rail to see the live lock board, not a static score.",
  },
  {
    id: "proof-screen",
    title: "Proof",
    subtitle:
      "Project-scoped run history, build output, trace logs, diffs, and verifier results -- empty states explain exactly what's missing.",
    icon: Eye,
    color: "text-cyan-400",
    panel: "proof",
    tips: [
      "Oracle Verdict and Pipeline State are empty until a hive session actually runs -- that's a real empty state, not a broken panel.",
      "Session Library, Builds, Trace, Diffs, and Gates are separate lenses on the same run history.",
      '"Go to Work" is the fastest way to produce something for this screen to show.',
    ],
    action: "Run something from Work, then check Proof for the oracle verdict.",
  },
  {
    id: "repair-screen",
    title: "Repair",
    subtitle:
      "Diagnose this repo, review a patch plan, and gate human approval -- read-only until you explicitly approve.",
    icon: GitPullRequest,
    color: "text-cyan-400",
    panel: "repair",
    tips: [
      'Workspace shows the real detected adapter (Python/Rust/Go/Node/...) for the open project -- "Unknown" briefly on first open just means the check hasn\'t resolved yet, not that detection failed.',
      "Diagnosis is advisory; the verifier (the real compiler/test oracle) is the only source of truth, not the model.",
      "Source mutation is BLOCKED until a human approves a verified diff -- nothing here writes to your files by itself.",
    ],
    action: "Click Repair in the rail to see this repo's real adapter, verifier, and gate state.",
  },
  {
    id: "audit",
    title: "Audit",
    subtitle:
      "Shippable Project Audit -- scans code, dependencies, security, and release blockers for this workspace.",
    icon: ShieldCheck,
    color: "text-red-400",
    panel: "audit",
    tips: [
      "Run Audit Scan triggers a real security, compile, and release-readiness pass -- it is not pre-computed or cosmetic.",
      "The scorecard is scoped to the current workspace, not a generic checklist.",
    ],
    action: "Click Audit in the rail, then Run Audit Scan.",
  },
  {
    id: "terminal",
    title: "Tools Dock",
    subtitle: "Terminal, Code, Build, Trace, Search, and Health attach to the active screen.",
    icon: Terminal,
    color: "text-cyan-400",
    panel: "terminal",
    tips: [
      "Tools are add-ons, not separate primary pages.",
      "Use Bottom or Right dock placement based on the task.",
      "Terminal should sit beside Work, Space, Brain, or Proof when you need it.",
    ],
    shortcut: "Ctrl+`",
    action: "Open Tools, or use an Attach button inside the active screen.",
  },
  {
    id: "editor",
    title: "Monaco Editor",
    subtitle: "Full IDE editor with syntax highlighting for all Determinex target languages.",
    icon: Code2,
    color: "text-blue-400",
    panel: "editor",
    tips: [
      "Tabs show a dot when the file is modified (unsaved).",
      "Ctrl+S writes the file directly -- it does not run an oracle compile-check.",
      "Syntax highlighting for Rust, Go, Python, TypeScript, C/C++, and more.",
    ],
    shortcut: "Ctrl+Shift+P -> Attach Code Editor",
    action: "Click the code icon in the lower rail.",
  },
  {
    id: "search",
    title: "Verified Search",
    subtitle: "Oracle-verified code generation -- any weak model becomes correct under sampling.",
    icon: Search,
    color: "text-amber-400",
    panel: "search",
    tips: [
      "A model correct 20% of the time hits 200/200 tasks with K=15 samples.",
      "Every candidate is tested against the oracle before being shown to you.",
      "The winner is the first candidate that PASSES -- not just the highest confidence.",
    ],
    action: "Click the search icon and try a natural language query.",
  },
  {
    id: "health",
    title: "Health Map",
    subtitle: "Color-coded oracle status for every file in your workspace.",
    icon: Activity,
    color: "text-green-400",
    panel: "health",
    tips: [
      "Green = pass, Yellow = warning, Red = compile error, Gray = not yet scanned.",
      "Click 'Re-scan Workspace' to trigger a fresh oracle pass on all files.",
      "Errors link directly to the line in the Monaco editor.",
    ],
    action: "Click the Activity icon to see your project health at a glance.",
  },
  {
    id: "privacy",
    title: "Privacy Cockpit",
    subtitle: "Project Cloak obfuscates every identifier before any cloud API call.",
    icon: ShieldCheck,
    color: "text-cyan-400",
    panel: "cloak",
    tips: [
      "Cloak audit evidence records which identifiers were mapped to opaque x_NNNN tokens.",
      "Cloud-bound errors can be re-obfuscated before they are sent back into a model.",
      "Patches are de-obfuscated locally before being applied to your source.",
    ],
    action: "Click the shield icon to see the Cloak obfuscation map.",
  },
  {
    id: "market",
    title: "Tools Panel",
    subtitle: "Manage providers, extensions, integrations, and attachable IDE tools.",
    icon: Package,
    color: "text-pink-400",
    panel: "extensions",
    tips: [
      "AI providers are slotable: local, API, or hybrid.",
      "Installed tools expose capabilities to Work, Space, Brain, and Proof.",
      "Runtime panes attach to screens instead of becoming disconnected buttons.",
    ],
    checklist: [
      "Use LLM Providers for API-backed model routes",
      "Use Privacy for Cloak and sandbox controls",
      "Use Integrations for GitHub, Docker, and external workflow add-ons",
      "Open Browse Community Hub for the local add-on manager panel",
    ],
    action: "Click Tools in the rail to review providers and add-ons.",
  },
  {
    id: "flywheel",
    title: "Flywheel Feed",
    subtitle: "Every failure becomes training data. The system gets smarter automatically.",
    icon: Zap,
    color: "text-orange-400",
    panel: "flywheel",
    tips: [
      "Each compiler error + fix pair is a perfect labeled training sample.",
      "The corpus grows automatically -- no human labeling required.",
      "LoRA fine-tunes run on RunPod when the corpus hits a new checkpoint.",
    ],
    action: "Click the Flywheel icon and watch the live corpus counter.",
  },
];

type Props = {
  open: boolean;
  onClose: () => void;
  activeSidebar?: string;
  activeAddon?: string | null;
  onAskAgent?: (task: string) => void;
};

/**
 * Same panel-matching rule the overlay itself uses (addon takes priority over
 * the primary tab behind it) -- exposed so the collapsed teaser bubble can show
 * a real, per-screen line instead of one static sentence on every screen.
 */
export function getGuideStepFor(activeSidebar?: string, activeAddon?: string | null): Step {
  const idx = activeAddon
    ? STEPS.findIndex((s) => s.panel === activeAddon)
    : STEPS.findIndex((s) => s.panel === activeSidebar);
  return idx >= 0 ? STEPS[idx] : STEPS[0];
}

const COMPLETED_ACTIONS_STORAGE_KEY = "determinex.guide.completedActions";

function loadCompletedActions(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(COMPLETED_ACTIONS_STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

export function TeacherOverlay({ open, onClose, activeSidebar, activeAddon, onAskAgent }: Props) {
  const [step, setStep] = useState(0);
  const [position, setPosition] = useState({ x: 24, y: 24, height: 560 });
  const [completedActions, setCompletedActions] = useState<Set<string>>(loadCompletedActions);
  const dragState = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);

  useEffect(() => {
    if (!open) return;
    // Steps map to either a primary rail selection (activeSidebar, e.g.
    // "ideation"/"hive") or an attached addon (activeAddon, e.g.
    // "terminal"/"editor"/"cloak") -- checking only one of these used to
    // mean addon-mapped steps could never sync, even though their panel
    // ids were valid addon ids. When an addon is open it's what's actually
    // visible, so it takes priority over whatever primary tab sits behind it
    // (matching activeAddon and activeSidebar independently, rather than one
    // findIndex over both, avoids the addon dock's own match losing to an
    // earlier, coincidental activeSidebar match in the STEPS array order).
    const idx = activeAddon
      ? STEPS.findIndex((s) => s.panel === activeAddon)
      : STEPS.findIndex((s) => s.panel === activeSidebar);
    if (idx >= 0) setStep(idx);
  }, [open, activeSidebar, activeAddon]);

  useEffect(() => {
    if (!open) return;
    setPosition((current) => {
      const width = 380;
      const height = Math.min(560, window.innerHeight - 48);
      // `height` here MUST be the same number the card is actually allowed to
      // grow to (its rendered maxHeight), not just a guess used for placement.
      // It used to be: this effect picked a placement assuming <=560px tall,
      // but the card's own style separately allowed it to grow up to
      // `calc(100vh - 48px)` (often 800px+) -- so any step with enough
      // content (a checklist, 4+ tips) grew taller than the gap this left
      // below it and its footer (Prev/Next, page dots) rendered off the
      // bottom of the window entirely, with no way to scroll to it. Ryan: "on
      // some of its pages you cant see all of it." Now both the placement AND
      // the rendered maxHeight (see the style prop below) come from this same
      // `height` value, so the card can never be taller than the room this
      // math actually left for it.
      if (current.x !== 24 || current.y !== 24) {
        return {
          x: Math.min(Math.max(16, current.x), Math.max(16, window.innerWidth - width - 16)),
          y: Math.min(Math.max(16, current.y), Math.max(16, window.innerHeight - height - 16)),
          height,
        };
      }
      return {
        x: Math.max(16, window.innerWidth - width - 24),
        y: Math.max(16, window.innerHeight - height - 72),
        height,
      };
    });
  }, [open]);

  const prev = useCallback(() => setStep((s) => Math.max(0, s - 1)), []);
  const next = useCallback(() => setStep((s) => Math.min(STEPS.length - 1, s + 1)), []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, next, prev, onClose]);

  if (!open) return null;

  const s = STEPS[step];
  const StepIcon = s.icon;
  const progress = (step / (STEPS.length - 1)) * 100;
  const focusSteps = ["setup", "local-cloak", "work", "space", "market", "privacy"];
  const toggleAction = (label: string) => {
    setCompletedActions((current) => {
      const next = new Set(current);
      const key = `${s.id}:${label}`;
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try {
        window.localStorage.setItem(COMPLETED_ACTIONS_STORAGE_KEY, JSON.stringify([...next]));
      } catch {
        /* localStorage unavailable -- checklist just won't persist this session */
      }
      return next;
    });
  };

  const beginDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragState.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: position.x,
      originY: position.y,
    };
  };

  const drag = (event: PointerEvent<HTMLDivElement>) => {
    const state = dragState.current;
    if (!state || state.pointerId !== event.pointerId) return;
    const width = 380;
    const maxX = Math.max(16, window.innerWidth - width - 16);
    const maxY = Math.max(16, window.innerHeight - 160);
    setPosition((current) => ({
      x: Math.min(Math.max(16, state.originX + event.clientX - state.startX), maxX),
      y: Math.min(Math.max(16, state.originY + event.clientY - state.startY), maxY),
      height: current.height,
    }));
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (dragState.current?.pointerId === event.pointerId) {
      dragState.current = null;
    }
  };

  return (
    <div data-testid="guide-overlay" className="fixed inset-0 z-[200] pointer-events-none">
      <div
        data-testid="guide-window"
        className="pointer-events-auto absolute flex flex-col rounded-2xl border shadow-2xl overflow-hidden"
        style={{
          left: position.x,
          top: position.y,
          width: 380,
          maxHeight: position.height,
          background: "rgba(8,8,16,0.97)",
          borderColor: "var(--determinex-border)",
          boxShadow: "0 0 0 1px rgba(255,255,255,0.04), 0 32px 80px -12px rgba(0,0,0,0.8)",
        }}
      >
        {/* Progress bar */}
        <div
          className="h-0.5 w-full transition-all duration-300"
          style={{
            background: `linear-gradient(90deg, var(--determinex-accent) ${progress}%, rgba(255,255,255,0.05) ${progress}%)`,
          }}
        />

        {/* Header */}
        <div
          data-testid="guide-drag-handle"
          className="flex cursor-move touch-none select-none items-center gap-3 px-5 py-4 border-b"
          style={{ borderColor: "var(--determinex-border)" }}
          onPointerDown={beginDrag}
          onPointerMove={drag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <div
            className="h-8 w-8 rounded-xl flex items-center justify-center border border-white/8 shrink-0"
            style={{ background: "rgba(255,255,255,0.04)" }}
          >
            <StepIcon size={16} className={s.color} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-eyebrow uppercase font-black tracking-widest text-gray-600 mb-0.5">
              Determinex Guide &middot; {step + 1} of {STEPS.length}
            </div>
            <div className="text-label font-bold text-white/85 leading-tight truncate">
              {s.title}
            </div>
          </div>
          <button
            onClick={onClose}
            onPointerDown={(event) => event.stopPropagation()}
            className="shrink-0 text-gray-600 hover:text-gray-300 transition-colors"
          >
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        {/* min-h-0 is load-bearing: a flex child defaults to min-height:auto,
            which lets it grow to fit its content instead of respecting the
            parent's maxHeight -- so overflow-y-auto never kicked in and the
            footer (Prev/Next, page dots) got pushed below the window edge
            entirely instead of the body scrolling internally. Only visible on
            steps with enough content to overflow (checklists, 4+ tips) --
            Ryan: "on some of its pages you cant see all of it." */}
        <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar px-5 py-4 space-y-4">
          <p className="text-label leading-relaxed text-gray-400">{s.subtitle}</p>

          <div className="space-y-2">
            <div className="flex items-center gap-2 text-eyebrow uppercase font-black tracking-widest text-gray-600">
              <GraduationCap size={9} />
              Jump To
            </div>
            <div className="grid grid-cols-2 gap-2">
              {focusSteps.map((id) => {
                const idx = STEPS.findIndex((candidate) => candidate.id === id);
                const target = STEPS[idx];
                if (!target) return null;
                const TargetIcon = target.icon;
                return (
                  <button
                    key={id}
                    onClick={() => setStep(idx)}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-left transition-all ${
                      idx === step
                        ? "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/8"
                        : "border-white/5 bg-white/[0.02] hover:bg-white/[0.05]"
                    }`}
                  >
                    <TargetIcon size={11} className={target.color} />
                    <span className="text-label font-semibold text-gray-400">{target.title}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2 text-eyebrow uppercase font-black tracking-widest text-gray-600">
              <Lightbulb size={9} />
              Key Concepts
            </div>
            {s.tips.map((tip, i) => (
              <div
                key={i}
                className="flex gap-2.5 rounded-xl border border-white/5 bg-white/[0.02] px-3.5 py-2.5"
              >
                <div className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-current ${s.color}`} />
                <p className="text-label leading-relaxed text-gray-400">{tip}</p>
              </div>
            ))}
          </div>

          {s.shortcut && (
            <div className="flex items-center gap-2.5 rounded-xl border border-white/5 bg-black/30 px-3.5 py-2.5">
              <span className="text-meta text-gray-600">Keyboard shortcut</span>
              <kbd className="ml-auto rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 text-meta font-mono text-gray-300">
                {s.shortcut}
              </kbd>
            </div>
          )}

          {s.action && (
            <div className="flex items-start gap-2.5 rounded-xl border border-[var(--determinex-accent)]/15 bg-[var(--determinex-accent)]/5 px-3.5 py-2.5">
              <BookOpen size={11} className="text-[var(--determinex-accent)] mt-0.5 shrink-0" />
              <p className="text-label leading-relaxed text-[var(--determinex-accent)]/80">
                {s.action}
              </p>
            </div>
          )}

          {onAskAgent && s.id !== "welcome" && (
            <button
              type="button"
              onClick={() =>
                onAskAgent(
                  `I'm looking at the "${s.title}" screen in Determinex and have a question about it: ${s.subtitle}\n\nMy question: `
                )
              }
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-violet-400/25 bg-violet-950/15 px-3.5 py-2.5 text-meta font-black uppercase tracking-widest text-violet-300 transition hover:bg-violet-900/25"
            >
              <Bot size={12} /> Ask an Agent about this screen
            </button>
          )}

          {s.checklist && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-eyebrow uppercase font-black tracking-widest text-gray-600">
                <CheckCircle2 size={9} />
                Walkthrough
              </div>
              {s.checklist.map((item) => {
                const done = completedActions.has(`${s.id}:${item}`);
                return (
                  <button
                    key={item}
                    onClick={() => toggleAction(item)}
                    className={`flex w-full items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-left transition-all ${
                      done
                        ? "border-emerald-500/20 bg-emerald-500/8"
                        : "border-white/5 bg-white/[0.02] hover:bg-white/[0.05]"
                    }`}
                  >
                    <CheckCircle2
                      size={12}
                      className={done ? "text-emerald-400" : "text-gray-700"}
                    />
                    <span
                      className={`text-label leading-relaxed ${done ? "text-emerald-300/80" : "text-gray-400"}`}
                    >
                      {item}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Step dots */}
        <div className="flex justify-center gap-1 py-3">
          {STEPS.map((_, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              className={`rounded-full transition-all ${
                i === step
                  ? "w-5 h-1.5 bg-[var(--determinex-accent)]"
                  : "w-1.5 h-1.5 bg-white/10 hover:bg-white/20"
              }`}
            />
          ))}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-3 border-t px-5 py-3.5"
          style={{ borderColor: "var(--determinex-border)" }}
        >
          <button
            onClick={prev}
            disabled={step === 0}
            className="flex items-center gap-1.5 rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2 text-label font-semibold text-gray-500 disabled:opacity-30 hover:enabled:bg-white/[0.06] hover:enabled:text-gray-300 transition-all"
          >
            <ChevronLeft size={11} /> Prev
          </button>
          <div className="flex-1 text-center text-meta text-gray-700 font-mono">
            {step + 1} / {STEPS.length}
          </div>
          {step < STEPS.length - 1 ? (
            <button
              onClick={next}
              className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-label font-bold text-black transition-all hover:opacity-90"
              style={{ background: "var(--determinex-accent)" }}
            >
              Next <ChevronRight size={11} />
            </button>
          ) : (
            <button
              onClick={onClose}
              className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-label font-bold text-black transition-all hover:opacity-90"
              style={{ background: "var(--determinex-accent)" }}
            >
              Done <X size={11} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// TeacherButton was removed 2026-07-29. It rendered a GraduationCap trigger for this
// overlay and was imported by nothing: page.tsx builds its own trigger inline
// (search "Open Guide"), and that one is strictly better -- its tooltip names the current
// guide step via getGuideStepFor(), which this generic version could not do.
//
// Deleted rather than wired, because wiring it would have replaced a context-aware
// control with a context-free one. Unused code that duplicates a live feature is worth
// removing precisely because it reads as the real thing to the next person looking.
