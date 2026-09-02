/**
 * The nine-group surface taxonomy.
 *
 * Ryan, live 2026-07-27: "the side bar is really cluttered again, i want real
 * breakdown and real organization not a whole list of things that do nothing.
 * lets put like 9 icons on the left bar, lets take the subs to those nine in an
 * expandable side window."
 *
 * Determinex has 34 surfaces (10 primary sidebars + 24 addon panels). Before
 * this they were exposed through four overlapping, inconsistent lists -- an
 * 18-icon rail, a 20-item dropdown, a 17-item Quick Attach popover, and the
 * Tools hub. Some panels were reachable three ways, others (Review, Merge) zero
 * ways without scrolling a menu whose scrollbar was hidden.
 *
 * Invariants this file exists to hold, enforced by surfaceGroups.test.ts:
 *   1. EVERY surface belongs to exactly one group -- no orphans, no duplicates.
 *   2. Exactly nine groups.
 *   3. Every member carries `what` (what it is) and `does` (what it does), so
 *      the drawer can explain a panel before you commit screen space to it.
 *      Ryan: "when you click on them, it brings out what they are, what they
 *      do, etc."
 *
 * `kind` decides how a member opens: "sidebar" swaps the left workspace,
 * "addon" opens a dockable panel. The drawer lets the user choose the
 * destination rather than the entry point hard-coding it.
 */

/**
 * How a member opens.
 *
 * "modal" exists because three members (Settings, Skin, Guide) open a modal or
 * overlay, not a panel -- and before this they were declared "addon" and cast
 * with `as WorkspaceAddon` at the call site. That cast was a lie: none of the
 * three is in the addon union, so the drawer advertised them, the user clicked,
 * and nothing opened. Precisely the "list of things that do nothing" this
 * taxonomy was built to eliminate, hiding inside the taxonomy itself.
 */
export type SurfaceKind = "sidebar" | "addon" | "modal";

export interface SurfaceMember {
  /** PrimaryWorkspace id (kind "sidebar") or WorkspaceAddon id (kind "addon"). */
  id: string;
  label: string;
  kind: SurfaceKind;
  /** One line: what this surface IS. */
  what: string;
  /** One line: what it DOES for you. */
  does: string;
  /**
   * Optional heading this member sits under inside its group's drawer.
   *
   * Exists because folding the tool-introspection surfaces into `system` made that one
   * group ten members long, and the "keep groups scannable" guard correctly failed it: a
   * single flat list of ten is the clutter moved, not removed. Sections let one rail icon
   * hold a structured drawer, so the count guard applies per SECTION rather than being
   * relaxed away.
   */
  section?: string;
  /**
   * For `kind: "modal"`, which modal to open. Kept as a named union rather than
   * reusing `id` so the shell's handler cannot silently fall through.
   */
  modal?: "settings" | "skin" | "guide";
  /** Determinex's own release tooling -- hidden from shipped end-user builds. */
  internalOnly?: boolean;
}

export interface SurfaceGroup {
  id: string;
  label: string;
  /** lucide-react icon name, resolved by the rail so this file stays UI-free. */
  icon: string;
  /** Tailwind text colour for the active/hover state. */
  tone: string;
  /** One line explaining the group itself, shown at the top of the drawer. */
  blurb: string;
  members: SurfaceMember[];
}

export const SURFACE_GROUPS: SurfaceGroup[] = [
  {
    id: "work",
    label: "Work",
    icon: "Zap",
    tone: "emerald",
    blurb: "Describe what you want built, and start it.",
    members: [
      {
        id: "hive",
        label: "Work Cockpit",
        kind: "sidebar",
        what: "The Ask / Plan / Build / Prove entry point.",
        does: "Turns a plain-language request into a spec, a plan, and a compiler-verified build.",
      },
      // "idea" / "Idea Lab" was removed 2026-07-29. It had no entry in page.tsx's
      // addonItems, so `selectedAddon` resolved to null and the dock render -- guarded by
      // `addonDockOpen && selectedAddon` -- produced NOTHING. A user clicking "Idea Lab"
      // watched the menu close and nothing happen.
      //
      // It was also a duplicate: the feature it described ("synthesizes a sound oracle
      // from your idea, then samples a model until something passes it") is exactly the
      // "search" member below, whose panel (VerifiedSearch) calls preview_idea_oracle and
      // build_idea and whose own docstring opens "Verified Search = the Correctness
      // Amplifier, driven from the IDE." So the capability is still offered -- once,
      // through the entry that actually opens.
      {
        id: "hub",
        label: "Project Hub",
        kind: "sidebar",
        what: "Your projects and codebases.",
        does: "Opens, clones, or binds a workspace so every other panel has something to point at.",
      },
    ],
  },
  {
    id: "code",
    label: "Code",
    icon: "FileCode",
    tone: "sky",
    blurb: "Read and edit the files themselves.",
    members: [
      {
        id: "editor",
        label: "Editor",
        kind: "addon",
        what: "A real code editor with its own file tree.",
        does: "Opens, edits, and saves workspace files. A failed save keeps the tab dirty and says why.",
      },
      {
        id: "explorer",
        label: "Space",
        kind: "sidebar",
        what: "Workspace overview and file tree.",
        does: "Browses the project and pushes files into the editor.",
      },
      {
        id: "findfiles",
        label: "Find in Files",
        kind: "addon",
        what: "Literal, gitignore-aware text search.",
        does: "Finds an exact string across the workspace with real file/line hits.",
      },
      {
        id: "search",
        label: "Verified Search",
        kind: "addon",
        what: "The Correctness Amplifier, driven from the IDE.",
        does: "Synthesizes an oracle, samples until a candidate passes it, and can stage the result for review.",
      },
    ],
  },
  {
    id: "source",
    label: "Source",
    icon: "GitBranch",
    tone: "amber",
    blurb: "Your changes, and changes proposed to you.",
    members: [
      {
        id: "git",
        label: "Source Control",
        kind: "sidebar",
        what: "Live git status, diffs, and branches.",
        does: "Stages, commits, pushes, and switches branches. Failures now surface instead of being swallowed.",
      },
      {
        id: "review",
        label: "Review",
        kind: "addon",
        what: "A queue of changes proposed to you.",
        does: "Shows an oracle-verified program as a diff so you can apply or reject it. Nothing is written until you approve.",
      },
      {
        id: "merge",
        label: "Merge",
        kind: "addon",
        what: "Three-way conflict resolution.",
        does: "Shows ours/theirs/base for a conflicted file and marks it resolved.",
      },
    ],
  },
  {
    id: "run",
    label: "Run",
    icon: "TerminalIcon",
    tone: "lime",
    blurb: "Execute things and watch them execute.",
    members: [
      {
        id: "terminal",
        label: "Terminal",
        kind: "addon",
        what: "A real PTY beside your work.",
        does: "Runs shell commands in the workspace without leaving the IDE.",
      },
      {
        id: "build",
        label: "Build",
        kind: "addon",
        what: "Tasks, tests, output, artifacts, env, CI.",
        does: "Groups the build-time tools. Some sub-tools are honestly unwired — see the audit.",
      },
      {
        id: "execution",
        label: "Runtime",
        kind: "addon",
        what: "Live hive sessions and local service status.",
        does: "Shows what is actually running, plus Ollama and Docker health.",
      },
      {
        id: "pipeline",
        label: "Pipeline",
        kind: "sidebar",
        what: "The orchestrated multi-step run.",
        does: "Drives a DAG of build steps through the compiler oracle.",
      },
    ],
  },
  {
    id: "prove",
    label: "Prove",
    icon: "Eye",
    tone: "cyan",
    blurb: "Evidence that it actually worked — not the model's opinion.",
    members: [
      {
        id: "proof",
        label: "Proof Center",
        kind: "sidebar",
        what: "Run history, verdicts, diffs, and release gates.",
        does: "Collects the evidence for a change. Empty states say exactly which proof is missing.",
      },
      {
        id: "trace",
        label: "Trace",
        kind: "addon",
        what: "Worker events and session history.",
        does: "Lists past sessions and opens their output folder.",
      },
      {
        id: "health",
        label: "Health",
        kind: "addon",
        what: "Oracle and file readiness.",
        does: "Scans whether the workspace is in a state the oracle can judge.",
      },
    ],
  },
  {
    id: "agents",
    label: "Agents",
    icon: "Bot",
    tone: "fuchsia",
    blurb: "The models and CLIs doing the work.",
    members: [
      {
        id: "repair",
        label: "Repair",
        kind: "addon",
        what: "Brownfield diagnosis through the canonical repair engine.",
        does: "Runs your workspace's own oracle and assigns blame to CODE, ENVIRONMENT, or TEST.",
      },
      {
        id: "agents",
        label: "Coding Agents",
        kind: "addon",
        what: "Installed agent CLIs (Claude Code, Codex, Gemini).",
        does: "Runs a real agent against the workspace and verifies its output through the oracle.",
      },
      {
        id: "agent-chat",
        label: "Agent Chat Room",
        kind: "addon",
        what: "Several agents in one shared conversation.",
        does: "Turn-taking chat where every edit is oracle-checked before the next agent goes.",
      },
    ],
  },
  {
    id: "trust",
    label: "Trust",
    icon: "ShieldCheck",
    tone: "orange",
    blurb: "What leaves this machine, and what is wrong with the repo.",
    members: [
      {
        id: "cloak",
        label: "Privacy Cockpit",
        kind: "addon",
        what: "Network policy and Project Cloak status.",
        does: "Controls whether anything may leave the machine. A policy the backend refuses is now rolled back, not displayed.",
      },
      {
        id: "audit",
        label: "Audit",
        kind: "sidebar",
        what: "Project audit findings.",
        does: "Reports structural problems found in the open workspace.",
      },
      {
        id: "repoclinic",
        label: "Repo Clinic",
        kind: "addon",
        what: "Live oracle-backed diagnosis of the workspace.",
        does: "Read-only: explains what is broken and what it would take, without changing anything.",
      },
      {
        id: "maintenancebay",
        label: "Maintenance Bay",
        kind: "addon",
        what: "Dependency, secret, license, and container scans.",
        does: "Composes the five security scanners into one advisory result. Never applies an update itself.",
      },
    ],
  },
  {
    id: "system",
    label: "System",
    icon: "Settings",
    tone: "slate",
    blurb: "Determinex itself — what it has learned, how it is doing, and its settings.",
    members: [

      {
        id: "learning",
        section: "About Determinex",
        label: "Learning Studio",
        kind: "addon",
        what: "Teaching explanations grounded in the verified corpus.",
        does: "Explains code and concepts from real evidence. Non-authorizing: it never approves anything.",
      },
      {
        id: "benchmark",
        section: "About Determinex",
        label: "Brain",
        kind: "sidebar",
        what: "Corpus, benchmarks, and accumulated knowledge.",
        does: "Queries what Determinex has learned and scored.",
      },
      {
        id: "guide",
        section: "Setup",
        label: "Guide",
        kind: "modal",
        modal: "guide",
        what: "The context-aware walkthrough.",
        does: "Explains the screen you are on and what to do next.",
      },
      {
        id: "passport",
        section: "Setup",
        label: "Passport",
        kind: "addon",
        what: "CLI logins, connected profiles, and spend.",
        does: "Shows which agent accounts are authenticated and what they are costing.",
      },

      {
        id: "extensions",
        section: "Setup",
        label: "Tools",
        kind: "sidebar",
        what: "Providers, oracles, benchmarks, integrations, skins.",
        does: "Installs and configures everything pluggable.",
      },
      {
        id: "skin",
        section: "Setup",
        label: "Skin",
        kind: "modal",
        modal: "skin",
        what: "The visual theme picker -- 27 skins, each a full palette.",
        does: "Switches the whole shell's colours. Every skin meets WCAG AA contrast on body text.",
      },
      {
        id: "settings",
        section: "Setup",
        label: "Settings",
        kind: "modal",
        modal: "settings",
        what: "Keys, hive roles, diagnostics, network.",
        does: "The main configuration surface.",
      },
      {
        id: "flywheel",
        section: "About Determinex",
        label: "Flywheel",
        kind: "addon",
        what: "Training corpus and feedback feed.",
        does: "Shows what the closed loop has captured from real runs.",
      },
      {
        id: "mission",
        section: "About Determinex",
        label: "Mission Control",
        kind: "addon",
        what: "Determinex's own release readiness.",
        does: "Tracks this product's shipping state, not your project's.",
        internalOnly: true,
      },
      {
        id: "roadmap",
        section: "About Determinex",
        label: "Determinex Roadmap",
        kind: "addon",
        what: "Successor direction and exact blockers.",
        does: "Tracks what is next for Determinex itself.",
        internalOnly: true,
      },
    ],
  },
];

/** Flat lookup: surface id -> the group that owns it. */
export const GROUP_BY_SURFACE: Record<string, SurfaceGroup> = Object.fromEntries(
  SURFACE_GROUPS.flatMap((g) => g.members.map((m) => [m.id, g]))
);

/** Every surface id, in group order. */
export function allSurfaceIds(): string[] {
  return SURFACE_GROUPS.flatMap((g) => g.members.map((m) => m.id));
}
