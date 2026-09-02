"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Brain,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Code2,
  FolderGit2,
  FolderOpen,
  FolderPlus,
  GitBranch,
  Play,
  Plus,
  ShieldCheck,
  Terminal,
  Zap,
} from "lucide-react";

import { useIterationTheme } from "@/contexts/IterationThemeContext";
import { cloneRepo } from "@/lib/gitService";
import { invokeSafe, pickFolder } from "@/lib/api";

export type ProjectHubDestination = "work" | "workspace" | "source" | "runs" | "brain" | "proof";

export interface ProjectHubProject {
  id: string;
  name: string;
  localPath: string;
  remote: string;
  provider: string;
  branch: string;
  status: "clean" | "dirty" | "running" | "needs-proof";
  stack: string[];
  defaultView: "last" | "work" | "workspace" | "proof" | "brain";
  lastOpened: string;
  lastRun: string;
  proof: string;
  bgImage?: string;
}

interface ProjectHubProps {
  selectedProjectName?: string;
  onSelectProject: (project: ProjectHubProject) => void;
  onNavigate: (destination: ProjectHubDestination) => void;
  onOpenLibrary?: () => void;
}

// SEEDED EXAMPLES, NOT FACTS.
//
// These are the development machine's own projects. `branch` and `status` are already overridden at
// runtime by a live `git_status` read with an honest "unknown" fallback (see the effect below) --
// but `lastOpened`, `lastRun` and `proof` were not, and they shipped as literals: "Today",
// "Frontend IA pass", "Proof gated". On a fresh install that meant a new user's project list
// described recent activity and proof state on drives they do not have (`T:\Dev\ProgramBench`).
//
// Corrected 2026-07-30: the activity fields say "—" / "not checked" instead of inventing a history.
// The cards themselves still appear on a machine that lacks these paths, which is a smaller lie
// than the one removed: selecting one runs `git_status`, which returns ok:false and shows "unknown",
// so the card degrades honestly on contact. Filtering the list by path existence would need a
// full `get_file_system_tree` read per seed on mount, which is not worth the cost -- if it matters
// later, add a cheap `path_exists` command rather than paying for a tree walk.
const SEEDED_PROJECTS: ProjectHubProject[] = [
  {
    id: "determinex",
    name: "Determinex",
    // localPath/remote are literal disk/GitHub references, not display prose --
    // must track the real checkout (this IDE's own repo). Verified 2026-07-26
    // against `git remote -v`, `gh repo list`, and the filesystem. NOTE: the
    // old value here was github.com/DarthCeltic/citadel, which a
    // mechanical rename turned into .../determinex -- a repo that does not
    // exist. That account only owns hf-hackathon; the real home is DarthCeltic.
    localPath: "C:\\Dev\\Determinex",
    remote: "github.com/DarthCeltic/Determinex",
    provider: "GitHub",
    branch: "clean-main",
    status: "dirty",
    stack: ["Next", "Tauri", "Rust", "Python"],
    defaultView: "work",
    lastOpened: "—",
    lastRun: "—",
    proof: "not checked",
  },
  {
    id: "programbench",
    name: "ProgramBench Workbench",
    localPath: "T:\\Dev\\ProgramBench",
    remote: "github.com/ProgramBench/ProgramBench",
    provider: "Git",
    branch: "local-eval",
    status: "running",
    stack: ["Python", "Docker", "CLI Eval"],
    defaultView: "brain",
    lastOpened: "—",
    lastRun: "—",
    proof: "not checked",
  },
  {
    id: "swebench",
    name: "SWE-bench Corpus",
    localPath: "T:\\determinex-swebench-work",
    remote: "local corpus mirror",
    provider: "Local",
    branch: "detached fixtures",
    status: "needs-proof",
    stack: ["Python", "Docker", "Cloak"],
    defaultView: "proof",
    lastOpened: "—",
    lastRun: "—",
    proof: "not checked",
  },
];

// Only user-added covers are persisted -- the 3 SEEDED_PROJECTS are re-derived from code every
// load, so they never go stale/duplicate if this file's seed list changes later.
const USER_PROJECTS_STORAGE_KEY = "determinex.userAddedProjects";

function loadPersistedUserProjects(): ProjectHubProject[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(USER_PROJECTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ProjectHubProject[]) : [];
  } catch {
    return [];
  }
}

function persistUserProjects(projects: ProjectHubProject[]) {
  if (typeof window === "undefined") return;
  const seededIds = new Set(SEEDED_PROJECTS.map((p) => p.id));
  const userProjects = projects.filter((p) => !seededIds.has(p.id));
  window.localStorage.setItem(USER_PROJECTS_STORAGE_KEY, JSON.stringify(userProjects));
}

const DEFAULT_OPTIONS: Array<{ id: ProjectHubProject["defaultView"]; label: string }> = [
  { id: "last", label: "Last used" },
  { id: "work", label: "Work" },
  { id: "workspace", label: "Workspace" },
  { id: "proof", label: "Proof" },
  { id: "brain", label: "Brain" },
];

const STACK_PRIORITY: Array<[string, string]> = [
  ["rust", "var(--dtx-warn)"],
  ["tauri", "var(--dtx-warn)"],
  ["go", "#00bcd4"],
  ["kotlin", "#a855f7"],
  ["swift", "var(--dtx-warn)"],
  ["python", "var(--dtx-ok)"],
  ["typescript", "var(--dtx-alt)"],
  ["next", "var(--dtx-alt)"],
  ["react", "var(--dtx-info)"],
  ["docker", "#2196f3"],
  ["cloak", "var(--dtx-alt)"],
];

function getStackAccent(stack: string[]): string {
  for (const [key, color] of STACK_PRIORITY) {
    if (stack.some((s) => s.toLowerCase().includes(key))) return color;
  }
  return "var(--dtx-code-border)";
}

// Was `path.replace(/Citadel/gi, "Determinex")` -- a display-only cosmetic
// rewrite from the period when the brand had been renamed but the real paths
// on disk had not. A mechanical rename turned it into replace(Determinex ->
// Determinex), i.e. a confusing no-op. The paths themselves are now genuinely
// Determinex-named, so the whole rewrite is obsolete: show the real path.
function displayPath(path: string) {
  return path;
}

const statusStyle = {
  clean: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  dirty: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  running: "border-cyan-400/30 bg-cyan-400/10 text-cyan-300",
  "needs-proof": "border-rose-400/30 bg-rose-400/10 text-rose-300",
} satisfies Record<ProjectHubProject["status"], string>;

const statusDot = {
  clean: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]",
  dirty: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.7)]",
  running: "bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)] animate-pulse",
  "needs-proof": "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.7)]",
} satisfies Record<ProjectHubProject["status"], string>;

function statusLabel(status: ProjectHubProject["status"]) {
  if (status === "needs-proof") return "Needs proof";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function viewToDestination(view: ProjectHubProject["defaultView"]): ProjectHubDestination {
  if (view === "workspace") return "workspace";
  if (view === "proof") return "proof";
  if (view === "brain") return "brain";
  return "work";
}

function ProjectCard({
  project,
  selected,
  onSelect,
  onNavigate,
}: {
  project: ProjectHubProject;
  selected: boolean;
  onSelect: () => void;
  onNavigate: (destination: ProjectHubDestination) => void;
}) {
  const stackAccent = getStackAccent(project.stack);
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid={`project-hub-card-${project.id}`}
      className={`group relative w-full rounded-xl border p-4 pl-5 text-left transition-all duration-300 ease-out hover:-translate-y-0.5 overflow-hidden ${
        selected
          ? "border-[var(--determinex-accent)] bg-gradient-to-br from-[var(--determinex-accent)]/10 to-transparent shadow-[0_8px_32px_var(--determinex-accent-glow)] scale-[1.01]"
          : "border-white/5 bg-black/30 hover:border-[var(--determinex-border)] hover:shadow-[0_4px_20px_rgba(255,255,255,0.04)]"
      }`}
    >
      {/* Stack accent stripe */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-xl transition-all duration-300"
        style={{
          background: stackAccent,
          boxShadow: selected ? `0 0 12px ${stackAccent}` : `0 0 6px ${stackAccent}60`,
          opacity: selected ? 1 : 0.6,
        }}
      />
      {project.bgImage && (
        <div
          className="absolute inset-0 z-0 opacity-20 transition-opacity duration-500 group-hover:opacity-40"
          style={{
            backgroundImage: `url(${project.bgImage})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
            maskImage: "linear-gradient(to top, transparent, black 100%)",
            WebkitMaskImage: "linear-gradient(to right, transparent, black 100%)",
            borderTopLeftRadius: "0.75rem",
            borderBottomLeftRadius: "0.75rem",
          }}
        />
      )}
      <div className="relative z-10 flex items-start gap-3">
        <div
          className={`relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border transition-colors ${selected ? "border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/15" : "border-white/10 bg-white/5"}`}
        >
          <FolderGit2
            size={18}
            className={
              selected ? "text-[var(--determinex-accent)]" : "text-[var(--determinex-muted)]"
            }
          />
          <span
            className={`absolute -bottom-1 -right-1 h-2.5 w-2.5 rounded-full border-2 border-[var(--determinex-bg)] ${statusDot[project.status]}`}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3
              className="truncate text-sm font-semibold tracking-wide text-[var(--determinex-text)]"
              style={{ fontFamily: "var(--determinex-font-display)" }}
            >
              {project.name}
            </h3>
            {selected && (
              <CheckCircle2
                size={15}
                className="shrink-0 text-[var(--determinex-accent)] animate-in zoom-in"
              />
            )}
          </div>
          <p className="mt-0.5 truncate font-mono text-label text-[var(--determinex-muted)] opacity-70">
            {displayPath(project.localPath)}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {project.stack.slice(0, 3).map((s) => (
              <span
                key={s}
                className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-meta text-gray-500"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>

      {selected && (
        <div className="mt-4 grid grid-cols-2 gap-2 animate-in slide-in-from-top-2 fade-in duration-300">
          {[
            ["Work", "work", Play],
            ["Space", "workspace", Terminal],
            ["Code", "source", Code2],
            ["Runs", "runs", Activity],
            ["Brain", "brain", Brain],
            ["Proof", "proof", ShieldCheck],
          ].map(([label, destination, Icon]) => {
            const ActionIcon = Icon as typeof Play;
            return (
              <span
                key={label as string}
                role="button"
                tabIndex={0}
                onClick={(event) => {
                  event.stopPropagation();
                  onNavigate(destination as ProjectHubDestination);
                }}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-[var(--determinex-border)]/30 bg-[var(--determinex-accent)]/10 px-2 py-2 text-eyebrow font-bold uppercase tracking-widest text-[var(--determinex-text)] transition-all hover:bg-[var(--determinex-accent)] hover:text-black hover:shadow-[0_0_15px_var(--determinex-accent)]"
              >
                <ActionIcon size={11} /> {label as string}
              </span>
            );
          })}
        </div>
      )}
    </button>
  );
}

export function ProjectHub({
  selectedProjectName,
  onSelectProject,
  onNavigate,
  onOpenLibrary,
}: ProjectHubProps) {
  const { themePack } = useIterationTheme();
  const [projects, setProjects] = useState<ProjectHubProject[]>(SEEDED_PROJECTS);
  const [selectedId, setSelectedId] = useState("determinex");
  const [defaultView, setDefaultView] = useState<ProjectHubProject["defaultView"]>("last");
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectRemote, setNewProjectRemote] = useState("");
  const [newProjectDestination, setNewProjectDestination] = useState("");
  const [addMode, setAddMode] = useState<"folder" | "clone">("folder");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("determinex.defaultView");
    if (stored && DEFAULT_OPTIONS.some((option) => option.id === stored)) {
      setDefaultView(stored as ProjectHubProject["defaultView"]);
    }
  }, []);

  // Restore user-added project covers from a prior session -- previously every addProject()
  // call was lost on reload since it only ever touched in-memory React state.
  useEffect(() => {
    const persisted = loadPersistedUserProjects();
    if (persisted.length > 0) {
      setProjects((current) => [...persisted, ...current]);
    }
  }, []);

  useEffect(() => {
    if (!selectedProjectName) return;
    const match = projects.find((project) => project.name === selectedProjectName);
    if (match) setSelectedId(match.id);
  }, [projects, selectedProjectName]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedId) ?? projects[0],
    [projects, selectedId]
  );

  // Live git state for the selected project's checkout.
  //
  // WHY (added 2026-07-29). `branch` and `status` were seeded literals rendered as
  // present tense: the Determinex card read "clean-main" / "dirty" while the checkout was
  // actually on `mojibake-and-count-fix`. These are the operator's REAL projects with
  // verified paths, which makes a stale branch worse than obviously-fake demo data --
  // it looks exactly like a reading of the repo, and it is not.
  //
  // The `git_status` command already existed (src-tauri/src/git.rs) and nothing here
  // called it. When it fails -- no git, path absent, not a repo -- the seeded literal is
  // NOT shown as a fallback: a stale branch presented confidently is the bug. The badge
  // says "unknown" instead.
  const [liveGit, setLiveGit] = useState<{
    branch: string;
    dirty: boolean;
    ok: boolean;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const path = selectedProject?.localPath;
    if (!path) {
      setLiveGit(null);
      return;
    }
    setLiveGit(null); // never show the previous project's branch while loading
    void (async () => {
      const result = await invokeSafe<{ branch: string; files: { path: string }[] }>("git_status", {
        cwd: path,
      });
      if (cancelled) return;
      setLiveGit(
        result
          ? { branch: result.branch, dirty: (result.files?.length ?? 0) > 0, ok: true }
          : { branch: "unknown", dirty: false, ok: false }
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedProject?.localPath]);

  const projectCoverRows = useMemo(
    () => [
      {
        label: "Project.md",
        value:
          selectedProject.id === "determinex" ? "Bound to repo contract" : "Draft needed from scan",
        detail:
          "Defines what this codebase is, how it should be handled, and what the worker can trust.",
      },
      {
        label: "Plan Source",
        value: selectedProject.lastRun,
        detail:
          "The active plan can come from a prompt, imported docs, README, open issues, or a prior run.",
      },
      {
        label: "Next Safe Action",
        value:
          selectedProject.status === "needs-proof" ? "Scan before building" : "Resume or open Work",
        detail:
          "Determinex should explain the next action before it writes code or starts a verifier.",
      },
      {
        label: "Evidence Boundary",
        value: selectedProject.proof,
        detail:
          "Proof screens own builds, logs, verifier output, and release blockers for this project.",
      },
    ],
    [selectedProject]
  );

  const addProject = async () => {
    const typedValue = newProjectRemote.trim();
    const destination = newProjectDestination.trim();
    setAddError(null);

    if (addMode === "clone") {
      if (!typedValue) {
        setAddError("Enter a git remote URL to clone.");
        return;
      }
      if (!destination) {
        setAddError("Enter a local destination folder to clone into.");
        return;
      }
      setAdding(true);
      try {
        await cloneRepo(typedValue, destination);
      } catch (err) {
        setAdding(false);
        setAddError(err instanceof Error ? err.message : String(err));
        return;
      }
      setAdding(false);
    } else if (!typedValue) {
      setAddError("Enter a local folder path to bind.");
      return;
    }

    const name =
      newProjectName.trim() || (addMode === "clone" ? "Cloned Codebase" : "Local Codebase");
    const id = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${Date.now()}`;
    // "folder" mode: the typed value IS the local path to bind (no clone step).
    // "clone" mode: cloneRepo() above already cloned the remote into `destination` --
    // localPath is the real checkout, not a placeholder.
    const project: ProjectHubProject = {
      id,
      name,
      localPath: addMode === "clone" ? destination : typedValue,
      remote: addMode === "clone" ? typedValue : "local folder",
      provider: addMode === "clone" ? "Git" : "Local",
      branch: addMode === "clone" ? "main" : "unscanned",
      status: "needs-proof",
      stack: ["Unscanned", "Read-only"],
      defaultView: "workspace",
      lastOpened: "Just added",
      lastRun: addMode === "clone" ? "Cloned, workspace scan pending" : "Workspace scan pending",
      proof: "No verifier run",
    };
    setProjects((current) => {
      const next = [project, ...current];
      persistUserProjects(next);
      return next;
    });
    setSelectedId(id);
    onSelectProject(project);
    setNewProjectName("");
    setNewProjectRemote("");
    setNewProjectDestination("");
  };

  const chooseProject = (project: ProjectHubProject) => {
    setSelectedId(project.id);
    onSelectProject(project);
  };

  const applyDefault = (view: ProjectHubProject["defaultView"]) => {
    setDefaultView(view);
    localStorage.setItem("determinex.defaultView", view);
  };

  return (
    <section
      data-testid="project-hub"
      className="relative h-full min-h-0 overflow-hidden bg-transparent"
      style={{ fontFamily: "var(--determinex-font-sans)" }}
    >
      {/* Ambient backdrop */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        {/* Orbital ring */}
        <div
          className="absolute -right-32 top-4 h-[700px] w-[700px] rounded-full border opacity-10"
          style={{
            borderColor: themePack.colors.accent,
            boxShadow: `0 0 120px ${themePack.colors.accentGlow}`,
            animation: "determinex-hub-orbit 28s linear infinite",
          }}
        />
        {/* Secondary inner ring */}
        <div
          className="absolute -right-10 top-24 h-[500px] w-[500px] rounded-full border opacity-[0.06]"
          style={{
            borderColor: themePack.colors.accent2,
            animation: "determinex-hub-orbit 18s linear infinite reverse",
          }}
        />
        {/* Sweep beam */}
        <div
          className="absolute left-0 top-16 h-32 w-[70rem] rotate-[-6deg] rounded-full opacity-10 blur-[90px]"
          style={{
            background: `linear-gradient(90deg, transparent, ${themePack.colors.accent}, ${themePack.colors.accent2}, transparent)`,
            animation: "determinex-hub-drift 14s ease-in-out infinite",
          }}
        />
        {/* Deep radial glow bottom-left */}
        <div
          className="absolute -bottom-24 -left-24 h-[400px] w-[400px] rounded-full opacity-10 blur-[80px]"
          style={{ background: themePack.colors.accent2 }}
        />
      </div>

      <div className="relative z-10 flex h-full min-h-0 flex-col px-8 py-6 max-w-[1920px] mx-auto">
        {/* Header */}
        <header className="shrink-0 mb-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {/* Project logo */}
              <div
                className="relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl border-2 transition-all"
                style={{
                  borderColor: themePack.colors.border,
                  boxShadow: `0 0 30px ${themePack.colors.accentGlow}, inset 0 0 20px rgba(0,0,0,0.4)`,
                }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/determinex-icon.jpg"
                  alt="Determinex"
                  className="h-full w-full object-cover mix-blend-screen"
                />
              </div>
              <div>
                <h1
                  className="text-3xl font-black tracking-tight text-[var(--determinex-text)] drop-shadow-md"
                  style={{ fontFamily: "var(--determinex-font-display)" }}
                >
                  Determinex
                </h1>
                <p className="text-sm text-[var(--determinex-muted)] opacity-80 mt-0.5">
                  Project covers, work runs, model slots, proof ledger, and attached tools
                </p>
              </div>
            </div>
            <div />
          </div>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-8 overflow-y-auto pb-8 lg:grid-cols-[380px_1fr] no-scrollbar">
          {/* Left Column: Projects + Add Source */}
          <div className="flex flex-col gap-5">
            <section className="flex-1 rounded-2xl border border-white/5 bg-black/25 p-5 backdrop-blur-md shadow-xl">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--determinex-text)] opacity-90">
                  Codebases
                </h2>
                <span className="rounded-full bg-white/10 px-2 py-0.5 font-mono text-label text-white/70">
                  {projects.length}
                </span>
              </div>
              <div className="space-y-3 overflow-y-auto pr-1 max-h-[42vh] no-scrollbar">
                {projects.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    selected={project.id === selectedProject.id}
                    onSelect={() => chooseProject(project)}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-white/5 bg-black/25 p-5 backdrop-blur-md shadow-xl">
              <div className="flex items-center gap-2 mb-4">
                <FolderPlus size={15} className="text-[var(--determinex-accent)]" />
                <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--determinex-text)] opacity-90">
                  Add Project Cover
                </h2>
              </div>
              <div className="grid grid-cols-2 gap-2 mb-4">
                {[
                  ["folder", "Local Path"],
                  ["clone", "Git Clone"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setAddMode(id as typeof addMode)}
                    className={`rounded-xl border px-3 py-2 text-meta font-bold uppercase tracking-wider transition-all ${
                      addMode === id
                        ? "border-[var(--determinex-accent)] bg-[var(--determinex-accent)]/15 text-[var(--determinex-text)] shadow-[0_0_15px_var(--determinex-accent-glow)]"
                        : "border-white/5 bg-white/5 text-[var(--determinex-muted)] hover:bg-white/10"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="space-y-3">
                <p className="text-label leading-relaxed text-[var(--determinex-muted)]">
                  Start from a local folder or a Git remote. Determinex should scan it, explain the
                  stack, and draft the project contract before building.
                </p>
                <input
                  value={newProjectName}
                  onChange={(event) => setNewProjectName(event.target.value)}
                  placeholder="Project Name"
                  className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-xs text-[var(--determinex-text)] outline-none transition-all placeholder:text-[var(--determinex-muted)] focus:border-[var(--determinex-border)] focus:shadow-[0_0_15px_var(--determinex-accent-glow)]"
                />
                <div className="flex gap-2">
                  <input
                    data-testid="project-hub-add-remote-input"
                    value={newProjectRemote}
                    onChange={(event) => setNewProjectRemote(event.target.value)}
                    placeholder={
                      addMode === "clone" ? "https://github.com/..." : "C:\\Path\\To\\Code"
                    }
                    className="flex-1 min-w-0 rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-xs text-[var(--determinex-text)] font-mono outline-none transition-all placeholder:text-[var(--determinex-muted)] focus:border-[var(--determinex-border)] focus:shadow-[0_0_15px_var(--determinex-accent-glow)]"
                  />
                  {addMode === "folder" && (
                    <button
                      type="button"
                      title="Browse for a folder"
                      onClick={async () => {
                        const picked = await pickFolder("Choose a project folder");
                        if (picked) setNewProjectRemote(picked);
                      }}
                      className="shrink-0 rounded-xl border border-white/10 bg-white/5 px-3 text-[var(--determinex-muted)] transition-all hover:bg-white/10 hover:text-[var(--determinex-text)]"
                    >
                      <FolderOpen size={15} />
                    </button>
                  )}
                </div>
                {addMode === "clone" && (
                  <div className="flex gap-2">
                    <input
                      data-testid="project-hub-add-destination-input"
                      value={newProjectDestination}
                      onChange={(event) => setNewProjectDestination(event.target.value)}
                      placeholder="C:\Path\To\Clone\Into (must not exist yet)"
                      className="flex-1 min-w-0 rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-xs text-[var(--determinex-text)] font-mono outline-none transition-all placeholder:text-[var(--determinex-muted)] focus:border-[var(--determinex-border)] focus:shadow-[0_0_15px_var(--determinex-accent-glow)]"
                    />
                    <button
                      type="button"
                      title="Browse for a destination folder"
                      onClick={async () => {
                        const picked = await pickFolder("Choose a destination folder");
                        if (picked) setNewProjectDestination(picked);
                      }}
                      className="shrink-0 rounded-xl border border-white/10 bg-white/5 px-3 text-[var(--determinex-muted)] transition-all hover:bg-white/10 hover:text-[var(--determinex-text)]"
                    >
                      <FolderOpen size={15} />
                    </button>
                  </div>
                )}
                {addError && (
                  <p
                    data-testid="project-hub-add-error"
                    className="text-label leading-relaxed text-rose-400"
                  >
                    {addError}
                  </p>
                )}
                <button
                  type="button"
                  data-testid="project-hub-add-submit"
                  onClick={() => void addProject()}
                  disabled={adding}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-[var(--determinex-border)] bg-[var(--determinex-accent)]/15 px-4 py-3 text-xs font-black uppercase tracking-widest text-[var(--determinex-text)] transition-all hover:bg-[var(--determinex-accent)] hover:text-black hover:shadow-[0_0_20px_var(--determinex-accent)] disabled:opacity-50"
                >
                  <Plus size={15} /> {adding ? "Cloning…" : "Create Cover"}
                </button>
              </div>
            </section>
          </div>

          {/* Right Column: Hero + Actions + Recent Sessions */}
          <main className="flex flex-col gap-6 min-h-0">
            {/* Hero Card */}
            <section className="relative flex-1 overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.04] to-black/40 p-8 shadow-2xl backdrop-blur-xl">
              {/* Hero glow */}
              <div
                className="absolute right-0 top-0 h-80 w-80 -translate-y-1/3 translate-x-1/4 rounded-full opacity-10 blur-[80px]"
                style={{ background: themePack.colors.accent }}
              />
              <div
                className="absolute bottom-0 left-12 h-64 w-64 translate-y-1/3 rounded-full opacity-8 blur-[70px]"
                style={{ background: themePack.colors.accent2 }}
              />

              <div className="relative h-full flex flex-col">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="inline-flex items-center gap-2 rounded-full border border-[var(--determinex-accent)]/30 bg-[var(--determinex-accent)]/10 px-3 py-1 text-meta font-bold uppercase tracking-widest text-[var(--determinex-accent)] mb-4 shadow-[0_0_15px_var(--determinex-accent-glow)]">
                      <Zap size={11} className="animate-pulse" /> Project Cover
                    </div>
                    <h2
                      className="text-5xl font-black tracking-tight text-[var(--determinex-text)] drop-shadow-lg"
                      style={{ fontFamily: "var(--determinex-font-display)" }}
                    >
                      {selectedProject.name}
                    </h2>

                    <div className="mt-5 flex flex-wrap gap-2.5">
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/40 px-3 py-1.5 text-xs text-[var(--determinex-muted)]">
                        <FolderGit2 size={13} /> {selectedProject.provider}
                      </span>
                      <span
                        className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/40 px-3 py-1.5 text-xs text-[var(--determinex-muted)] font-mono"
                        title={
                          liveGit === null
                            ? "Reading git state…"
                            : liveGit.ok
                              ? `Live from git status in ${selectedProject.localPath}${liveGit.dirty ? " — uncommitted changes present" : " — clean"}`
                              : `Could not read git state in ${selectedProject.localPath}`
                        }
                      >
                        <GitBranch size={13} /> {liveGit === null ? "…" : liveGit.branch}
                        {liveGit?.ok && liveGit.dirty && (
                          <span className="text-amber-400" title="uncommitted changes">
                            *
                          </span>
                        )}
                      </span>
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-black uppercase tracking-widest ${statusStyle[selectedProject.status]}`}
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${statusDot[selectedProject.status]}`}
                        />
                        {statusLabel(selectedProject.status)}
                      </span>
                    </div>
                  </div>

                  <div className="hidden lg:flex flex-col gap-2 text-right shrink-0 ml-4">
                    <div className="rounded-xl border border-white/5 bg-black/30 px-4 py-3 backdrop-blur-md">
                      <div className="text-eyebrow uppercase tracking-widest text-[var(--determinex-muted)] font-bold mb-1">
                        Last Open
                      </div>
                      <div className="text-sm font-black text-[var(--determinex-text)]">
                        {selectedProject.lastOpened}
                      </div>
                    </div>
                    <div className="rounded-xl border border-white/5 bg-black/30 px-4 py-3 backdrop-blur-md">
                      <div className="text-eyebrow uppercase tracking-widest text-[var(--determinex-muted)] font-bold mb-1">
                        Proof Status
                      </div>
                      <div className="text-sm font-black text-[var(--determinex-text)]">
                        {selectedProject.proof}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-7 grid gap-3 lg:grid-cols-4">
                  {projectCoverRows.map((row) => (
                    <div
                      key={row.label}
                      className="rounded-2xl border border-white/8 bg-black/35 p-4"
                    >
                      <div className="mb-2 flex items-center gap-2 text-eyebrow font-black uppercase tracking-widest text-[var(--determinex-muted)]">
                        <CheckCircle2 size={12} className="text-[var(--determinex-accent)]" />{" "}
                        {row.label}
                      </div>
                      <div className="min-h-[2rem] text-body font-black leading-tight text-[var(--determinex-text)]">
                        {row.value}
                      </div>
                      <p className="mt-2 text-label leading-relaxed text-[var(--determinex-muted)] opacity-75">
                        {row.detail}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Nav cards */}
                <div className="mt-6 flex-1 flex items-center justify-center">
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 w-full max-w-4xl">
                    {[
                      ["Work", "work", Play, "Ask, plan, build, and continue active sessions"],
                      [
                        "Space",
                        "workspace",
                        Terminal,
                        "Files, source state, runs, and project map",
                      ],
                      ["Brain", "brain", Brain, "Model slots, routing, health, and evals"],
                      [
                        "Proof",
                        "proof",
                        ShieldCheck,
                        "Build verdicts, logs, outputs, and evidence",
                      ],
                    ].map(([label, destination, Icon, desc]) => {
                      const ActionIcon = Icon as typeof Play;
                      return (
                        <button
                          key={label as string}
                          type="button"
                          onClick={() => onNavigate(destination as ProjectHubDestination)}
                          className="group relative overflow-hidden rounded-2xl border border-white/10 bg-black/40 p-6 text-left transition-all duration-300 hover:-translate-y-1 hover:border-[var(--determinex-accent)] hover:shadow-[0_10px_40px_var(--determinex-accent-glow)]"
                        >
                          <div className="absolute inset-0 bg-gradient-to-br from-[var(--determinex-accent)]/5 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
                          <div className="relative z-10 flex h-12 w-12 items-center justify-center rounded-xl border border-white/10 bg-white/5 transition-all duration-300 group-hover:scale-110 group-hover:border-[var(--determinex-accent)]/50 group-hover:bg-[var(--determinex-accent)]/20">
                            <ActionIcon
                              size={22}
                              className="text-[var(--determinex-muted)] transition-colors duration-300 group-hover:text-[var(--determinex-accent)]"
                            />
                          </div>
                          <h3
                            className="relative z-10 mt-4 text-lg font-bold tracking-wide text-[var(--determinex-text)]"
                            style={{ fontFamily: "var(--determinex-font-display)" }}
                          >
                            {label as string}
                          </h3>
                          <p className="relative z-10 mt-1 text-xs text-[var(--determinex-muted)] opacity-75">
                            {desc as string}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </section>

            {/* Bottom Row: Recent Sessions + Default Entry */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              {/* Recent Sessions */}
              <section className="rounded-2xl border border-white/5 bg-black/25 p-5 backdrop-blur-md shadow-xl">
                <div className="flex items-center gap-2 mb-4">
                  <Activity size={15} className="text-violet-400" />
                  <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--determinex-text)] opacity-90">
                    Continue Work
                  </h2>
                </div>
                <div className="flex flex-col gap-3">
                  <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-label font-black text-[var(--determinex-text)]">
                          {selectedProject.lastRun}
                        </div>
                        <div className="mt-1 font-mono text-meta text-gray-600">
                          {selectedProject.lastOpened} - {selectedProject.proof}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => onNavigate("runs")}
                        className="shrink-0 rounded-lg border border-violet-400/25 bg-violet-950/20 px-3 py-1.5 text-eyebrow font-black uppercase tracking-widest text-violet-300 transition-all hover:bg-violet-900/30"
                      >
                        Runs
                      </button>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={onOpenLibrary}
                    className="flex items-center justify-center gap-2 rounded-xl border border-[var(--determinex-border)]/40 bg-[var(--determinex-accent)]/10 px-3 py-2.5 text-meta font-black uppercase tracking-widest text-[var(--determinex-text)] transition-all hover:bg-[var(--determinex-accent)] hover:text-black"
                  >
                    <BookOpen size={13} /> Open Session Library
                  </button>
                </div>
              </section>

              {/* Default Entry */}
              <section className="rounded-2xl border border-white/5 bg-black/25 p-5 backdrop-blur-md shadow-xl flex flex-col">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xs font-bold uppercase tracking-widest text-[var(--determinex-text)] opacity-90">
                    Default Entry
                  </h2>
                  <button
                    type="button"
                    onClick={() => onNavigate(viewToDestination(defaultView))}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--determinex-accent)] px-3 py-1.5 text-meta font-black uppercase tracking-widest text-black transition-all hover:bg-white hover:shadow-[0_0_15px_var(--determinex-accent)]"
                  >
                    Launch <ChevronRight size={13} />
                  </button>
                </div>
                <div className="flex-1 flex items-center justify-center gap-2">
                  {DEFAULT_OPTIONS.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => applyDefault(option.id)}
                      className={`flex-1 rounded-xl border px-2 py-3 text-meta font-bold uppercase tracking-widest transition-all duration-300 ${
                        defaultView === option.id
                          ? "border-[var(--determinex-accent)] bg-gradient-to-b from-[var(--determinex-accent)]/20 to-[var(--determinex-accent)]/5 text-[var(--determinex-text)] shadow-[0_0_15px_var(--determinex-accent-glow)] scale-105"
                          : "border-white/5 bg-white/5 text-[var(--determinex-muted)] hover:border-white/15 hover:bg-white/10"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </section>
            </div>
          </main>
        </div>
      </div>
    </section>
  );
}
