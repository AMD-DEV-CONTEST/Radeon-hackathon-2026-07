"use client";

import { useState, useEffect, useMemo, useRef, type ReactNode, useCallback } from "react";
import { listen } from "@tauri-apps/api/event";
import Editor, { DiffEditor } from "@monaco-editor/react";
import {
  Folder,
  FolderOpen,
  Zap,
  Plus,
  Settings,
  AlertTriangle,
  Check,
  Activity,
  Cpu,
  XOctagon,
  HelpCircle,
  Terminal as TerminalIcon,
  GitPullRequest,
  GitMerge,
  ChevronRight,
  Gauge,
  Files,
  Database,
  Globe,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  Code2,
  Eye,
  Brain,
  LayoutGrid,
  GitBranch,
  RefreshCcw,
  Search,
  FileSearch,
  Lock,
  FileCode,
  Package,
  GraduationCap,
  Key,
  Palette,
  X,
  Maximize2,
  Minimize2,
  GripHorizontal,
  GripVertical,
  ChevronDown,
  Circle,
  Bot,
  MessageSquare,
  BadgeCheck,
  type LucideIcon,
  PanelRight,
  Sparkles,
} from "lucide-react";
import {
  injectSandboxContext,
  abortOrchestration,
  promoteToGarden,
  unleashThePack,
  getModelsRegistry,
  getFileSystemTree,
  readFileContent,
  getWorkspaceFiles,
  fetchTodos,
  getThreads,
  nativeOrchestratePlan,
  nativeOrchestrateCodegen,
  nativeOrchestrateAudit,
  invokeSafe,
  isTauri,
  isInternalBuild,
  openInternalWindow,
} from "@/lib/api";
// Raw invoke for commands returning Result<(), _> -- see the set_project_root call below.
import { invoke } from "@tauri-apps/api/core";
import type { WorkReadiness } from "@/lib/work-readiness";
import { useSettings } from "@/contexts/SettingsContext";
import { useAiRouter } from "@/contexts/AiRouterContext";
import { useIterationTheme } from "@/contexts/IterationThemeContext";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import "@xterm/xterm/css/xterm.css";

import { FileSystemNode, FileNode } from "@/components/FileSystemNode";
import { PipelineDashboard } from "@/components/PipelineDashboard";
import { MatrixExecutionDisplay, type AgentStatus } from "@/components/MatrixExecutionDisplay";
import { SetupWizard } from "@/components/SetupWizard";
import { UpdateNotice } from "@/components/UpdateNotice";
import dynamic from "next/dynamic";
import type { PathInfo } from "@/components/ConceptLab";

import { AnimatePresence, motion } from "framer-motion";

const ConceptLab = dynamic(() => import("@/components/ConceptLab").then((m) => m.ConceptLab), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg-deep)]" />,
});
const OracleArena = dynamic(() => import("@/components/OracleArena").then((m) => m.OracleArena), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const HealthMap = dynamic(() => import("@/components/HealthMap").then((m) => m.HealthMap), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const AgentTrace = dynamic(() => import("@/components/AgentTrace").then((m) => m.AgentTrace), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const PrivacyCockpit = dynamic(
  () => import("@/components/PrivacyCockpit").then((m) => m.PrivacyCockpit),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const FlywheelFeed = dynamic(
  () => import("@/components/FlywheelFeed").then((m) => m.FlywheelFeed),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const TerminalPanel = dynamic(
  () => import("@/components/TerminalPanel").then((m) => m.TerminalPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const EditorPanel = dynamic(() => import("@/components/EditorPanel").then((m) => m.EditorPanel), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const VerifiedSearch = dynamic(
  () => import("@/components/VerifiedSearch").then((m) => m.VerifiedSearch),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const TeacherOverlay = dynamic(
  () => import("@/components/TeacherOverlay").then((m) => m.TeacherOverlay),
  { ssr: false }
);
import { getGuideStepFor } from "@/components/TeacherOverlay";
const ToolsHub = dynamic(() => import("@/components/ToolsHub").then((m) => m.ToolsHub), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const BuildCenter = dynamic(() => import("@/components/BuildCenter").then((m) => m.BuildCenter), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const ExecutionWorkspace = dynamic(
  () => import("@/components/ExecutionWorkspace").then((m) => m.ExecutionWorkspace),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const SuccessorRoadmapPanel = dynamic(
  () => import("@/components/SuccessorRoadmapPanel").then((m) => m.SuccessorRoadmapPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const MissionControlPanel = dynamic(
  () => import("@/components/MissionControlPanel").then((m) => m.MissionControlPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const LearningStudioPanel = dynamic(
  () =>
    import("@/components/ide-product-shell/LearningStudioPanel").then((m) => m.LearningStudioPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const RepoClinicPanel = dynamic(
  () => import("@/components/ide-product-shell/RepoClinicPanel").then((m) => m.RepoClinicPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const MaintenanceBayPanel = dynamic(
  () =>
    import("@/components/ide-product-shell/MaintenanceBayPanel").then((m) => m.MaintenanceBayPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const UnifiedNavigationPanel = dynamic(
  () =>
    import("@/components/ide-product-shell/UnifiedNavigationPanel").then(
      (m) => m.UnifiedNavigationPanel
    ),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const RepairPanelShell = dynamic(
  () => import("@/components/ide-repair/RepairPanelShell").then((m) => m.RepairPanelShell),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const AgentsPanel = dynamic(() => import("@/components/AgentsPanel").then((m) => m.AgentsPanel), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const AgentChatPanel = dynamic(
  () => import("@/components/AgentChatPanel").then((m) => m.AgentChatPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const PassportPanel = dynamic(
  () => import("@/components/PassportPanel").then((m) => m.PassportPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const StatusBar = dynamic(() => import("@/components/StatusBar").then((m) => m.StatusBar), {
  ssr: false,
});
import type { QuickAttachItem } from "@/components/StatusBar";
const CommandPalette = dynamic(
  () => import("@/components/CommandPalette").then((m) => m.CommandPalette),
  { ssr: false }
);
const GitPanel = dynamic(() => import("@/components/GitPanel"), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const ProjectAuditPanel = dynamic(
  () => import("@/components/ProjectAuditPanel").then((m) => m.ProjectAuditPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const WorkspaceOnboarding = dynamic(
  () => import("@/components/WorkspaceOnboarding").then((m) => m.WorkspaceOnboarding),
  { ssr: false }
);
const ProblemsPanel = dynamic(
  // Was importing an orphaned duplicate (components/ProblemsPanel.tsx, no
  // other importer) that still had the fixed run_project_audit-on-every-
  // mount-and-60s-poll bug -- BuildCenter.tsx's internal Problems tab
  // already used this canonical, fixed copy. Consolidated to one module
  // instead of patching two.
  () => import("@/components/buildtools/ProblemsPanel").then((m) => m.ProblemsPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const DiffReviewPanel = dynamic(
  () => import("@/components/DiffReviewPanel").then((m) => m.DiffReviewPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
const MergeEditor = dynamic(() => import("@/components/MergeEditor").then((m) => m.MergeEditor), {
  ssr: false,
  loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" />,
});
const FileSearchPanel = dynamic(
  () => import("@/components/FileSearchPanel").then((m) => m.FileSearchPanel),
  { ssr: false, loading: () => <div className="flex-1 bg-[var(--dtx-code-bg)]" /> }
);
import type { PaletteCommand } from "@/components/CommandPalette";
import { HiveBuildLoop, type HiveBuildCompletionResult } from "@/components/HiveBuildLoop";
import { BenchmarkRunner } from "@/components/BenchmarkRunner";
import { PathDetailPanel } from "@/components/PathDetailPanel";
import { DiscoveryProgressView } from "@/components/DiscoveryProgressView";
import { SpecBreakdownView } from "@/components/SpecBreakdownView";
import { ToolsRegistry } from "@/components/ToolsRegistry";
import { MatrixRain } from "@/components/MatrixRain";
import { SkinBackdrop } from "@/components/SkinBackdrop";
import { ProjectLibrary } from "@/components/ProjectLibrary";
import { BrainStage } from "@/components/BrainStage";
import {
  ProjectHub,
  type ProjectHubDestination,
  type ProjectHubProject,
} from "@/components/ProjectHub";
import { ADDONS } from "@/lib/addons";
import { getGitStatus, type GitFile } from "@/lib/gitService";
import { ADDONS_UPDATED_EVENT, readInstalledAddonIds } from "@/lib/addonStorage";
import { NETWORK_POLICY_COPY, hasCompletedSetup, SETUP_COMPLETED_EVENT } from "@/lib/networkPolicy";
import {
  hasDismissedOnboarding,
  markOnboardingDismissed,
  resolveWorkspaceRoot,
} from "@/lib/workspaceOnboarding";
import { AiRouteSelect, AiRouteSummary } from "@/components/AiRouteSelect";
import { routeKeyReady, type ApiKeyStatus } from "@/lib/aiRouting";
import { BootOverlay } from "@/components/modals/BootOverlay";
import { HelpModal } from "@/components/modals/HelpModal";
import { ServiceLoginModal } from "@/components/modals/ServiceLoginModal";
import { SettingsModal } from "@/components/modals/SettingsModal";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useMoaTelemetry } from "@/hooks/useMoaTelemetry";
import { useErrorToast } from "@/components/ErrorToast";
import { getSkinPackStyle } from "@/theme/skinPacks";
import { SURFACE_GROUPS, type SurfaceMember } from "@/lib/surfaceGroups";
import { SurfaceDrawer, type SurfaceDestination } from "@/components/SurfaceDrawer";
import { usePanelWidth } from "@/lib/usePanelWidth";
import { usePanelSplit } from "@/lib/useSplitRatio";

// surfaceGroups.ts names its icons as strings so the taxonomy stays testable
// without importing React. This is the one place those names become components.
const GROUP_ICONS: Record<string, LucideIcon> = {
  Zap,
  FileCode,
  GitBranch,
  TerminalIcon,
  Eye,
  Bot,
  ShieldCheck,
  GraduationCap,
  Settings,
};

export type PrimaryWorkspace =
  | "pipeline"
  | "explorer"
  | "git"
  | "hive"
  | "benchmark"
  | "proof"
  | "extensions"
  | "hub"
  | "audit"
  | "none";

type WorkspaceAddon =
  | "terminal"
  | "editor"
  | "health"
  | "search"
  | "trace"
  | "cloak"
  | "flywheel"
  | "build"
  | "execution"
  | "mission"
  | "roadmap"
  | "review"
  | "merge"
  // NOTE: no double-quoted words in comments inside this block. surfaceGroups.test.ts
  // parses this union by pulling every double-quoted token out of the declaration, so any
  // such word in a comment is read as a union member. Documenting the removal below put
  // the removed name straight back into the parsed list; the rewrite then did it again
  // with the word it used to describe the hazard.
  //
  // The idea addon was removed 2026-07-29: a declared member with no addonItems entry, so
  // the taxonomy advertised Idea Lab and clicking it rendered nothing. That capability is
  // served by the search member (VerifiedSearch = the Correctness Amplifier).
  | "learning"
  | "repoclinic"
  | "maintenancebay"
  | "findfiles"
  | "repair"
  | "agents"
  | "agent-chat"
  | "passport";

type AddonItem = {
  id: WorkspaceAddon;
  label: string;
  description: string;
  icon: typeof TerminalIcon;
  tone: string;
  panel: ReactNode;
};

type DeterminexUiSnapshot = {
  app: "Determinex";
  activeWorkspace: PrimaryWorkspace;
  activeAddon: WorkspaceAddon | null;
  addonDockOpen: boolean;
  addonDockMaximized: boolean;
  selectedProjectName: string;
  workspacePath: string;
  hiveSessionId: string | null;
  selectedModel: string;
  networkPolicy: string;
  panels: {
    projectLibrary: boolean;
    settings: boolean;
    help: boolean;
  };
  viewport: {
    width: number;
    height: number;
  };
  timestamp: string;
};

declare global {
  interface Window {
    __DETERMINEX_UI_SNAPSHOT__?: () => DeterminexUiSnapshot;
  }
}

function displayPath(path: string) {
  return path.replace(/Determinex/gi, "Determinex");
}

function displayModelName(name: string) {
  return name.replace(/determinex/gi, "determinex");
}

// Compact model-route chip for surfaces embedded in a screen header (Work's
// request box today) -- a scaled-down sibling of StatusBar's own chip+popover
// pattern, not a full-size AiRouteSummary card dropped inline (that read as
// a bolted-on afterthought, not part of the design). Ryan: "thats not premier."
export function WorkModelPicker({
  selectedModel,
  keyStatus,
  onChange,
  onOpenSettings,
}: {
  selectedModel: string;
  keyStatus: ApiKeyStatus;
  onChange: (value: string) => void;
  onOpenSettings: () => void;
}) {
  const router = useAiRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const ready = routeKeyReady(selectedModel, keyStatus) && router.routeWarnings.length === 0;
  const option = router.allowedOptions.find((candidate) => candidate.id === selectedModel);
  const label = option?.label ?? (selectedModel === "auto" ? "Auto" : selectedModel);

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="work-model-picker"
        title="Model route for this request"
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-eyebrow font-black uppercase tracking-widest transition-all ${
          open
            ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-200"
            : "border-white/10 bg-white/[0.03] text-gray-400 hover:border-cyan-400/30 hover:bg-white/[0.06] hover:text-gray-200"
        }`}
      >
        <Circle
          size={6}
          className={`shrink-0 fill-current ${ready ? "text-emerald-400" : "text-amber-400"}`}
        />
        <Cpu size={11} className="shrink-0 text-cyan-300" />
        <span className="max-w-[100px] truncate font-mono normal-case tracking-normal">
          {label}
        </span>
        <ChevronDown
          size={10}
          className={`shrink-0 text-gray-600 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {/* Opens upward, not downward -- this chip sits right above the Consult
          Oracle submit button, near the bottom of the panel, so a downward
          popover routinely got clipped by the window edge. Found live
          2026-07-19 (Ryan screenshotted it cut off mid-dropdown). */}
      {open && (
        <div className="absolute right-0 bottom-[calc(100%+8px)] z-[200] w-[290px] animate-fade-in">
          <AiRouteSummary
            value={selectedModel}
            keyStatus={keyStatus}
            onChange={(v) => {
              onChange(v);
              setOpen(false);
            }}
            onOpenSettings={() => {
              setOpen(false);
              onOpenSettings();
            }}
          />
        </div>
      )}
    </div>
  );
}

// Was an 18-icon-wide horizontal strip with no visible labels (only a
// screen-reader-only <span> + hover tooltip) -- "a gob of tools on it, with
// no telling what they are, just that their icons people are supposed to
// randomly know." Same compact chip+popover pattern as WorkModelPicker, but
// with real text labels in the list instead of guessing icons.
function AddonSwitcher({
  items,
  activeId,
  activeLabel,
  onSelect,
}: {
  items: {
    id: string;
    label: string;
    icon: React.ComponentType<{ size?: number; className?: string }>;
    tone: string;
  }[];
  activeId: string;
  activeLabel: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-eyebrow font-black uppercase tracking-widest transition ${
          open
            ? "border-[var(--determinex-accent)]/50 bg-[var(--determinex-accent)]/10 text-white"
            : "border-white/8 bg-white/[0.03] text-gray-500 hover:bg-white/10 hover:text-white"
        }`}
        title="Switch attached tool"
      >
        <span className="max-w-[100px] truncate normal-case tracking-normal">{activeLabel}</span>
        <ChevronDown
          size={10}
          className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {/* The menu was max-h-[360px] + no-scrollbar, which silently truncated
          it: 20 runtime addons need roughly 540px, so Review, Merge, Repair,
          Coding Agents, Agent Chat Room and Passport were all cut off with no
          scrollbar and no other hint they existed. Found live 2026-07-27 while
          trying to open Review from this very menu -- it looked like the panel
          simply did not exist. Same overflow-y-auto-plus-no-scrollbar trap as
          the left rail. A menu is the one place a visible scrollbar is
          unambiguous, so it stays scrollable but now says so, with a taller cap
          to reduce the need. */}
      {open && (
        <div className="absolute right-0 top-[calc(100%+8px)] z-[200] max-h-[70vh] w-[220px] overflow-y-auto rounded-xl border border-white/10 bg-[var(--dtx-code-bg)] p-1.5 shadow-2xl animate-fade-in">
          {items.map((item) => {
            const ItemIcon = item.icon;
            const isActive = item.id === activeId;
            return (
              <button
                key={item.id}
                type="button"
                data-testid={`addon-switch-${item.id}`}
                onClick={() => {
                  onSelect(item.id);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-label transition-colors ${
                  isActive
                    ? "bg-[var(--determinex-accent)]/15 text-white"
                    : "text-gray-400 hover:bg-white/[0.06] hover:text-gray-200"
                }`}
              >
                <ItemIcon size={12} className={isActive ? item.tone : "text-gray-600"} />
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function DeterminexIDE() {
  const showError = useErrorToast();
  const { theme, themePack } = useIterationTheme();
  const skinPackStyle = getSkinPackStyle(themePack);
  const {
    showSettings,
    setShowSettings,
    settingsTab,
    setSettingsTab,
    keyStatus,
    apiKeys,
    setApiKeys,
    toolCatalog,
    toolCoverage,
    showServiceLogin,
    setShowServiceLogin,
    serviceKeyInput,
    setServiceKeyInput,
    diagnosticResult,
    isDiagnosing,
    runDiagnostics,
    networkPolicy,
    setNetworkPolicy,
    networkPolicyError,
    dismissNetworkPolicyError,
  } = useSettings();
  const networkPolicyCopy = NETWORK_POLICY_COPY[networkPolicy];
  const nextPrivacyPolicy = networkPolicy === "offline" ? "cloaked" : "offline";

  const [inputVal, setInputVal] = useState("");
  const [activeContexts, setActiveContexts] = useState<string[]>([]);
  const { selectedModel, changeModel: setSelectedModel } = useAiRouter();
  const [modelTiers, setModelTiers] = useState<any[]>([]);
  const [tandemPresets, setTandemPresets] = useState<any[]>([]);

  // Tactical Guidance State
  const [helpModal, setHelpModal] = useState<{ title: string; desc: string } | null>(null);
  const [lastPrompt, setLastPrompt] = useState("");
  // Seeded from the Guide's "Ask an Agent about this screen" button -- handed
  // to AgentsPanel as its initial task so a real installed agent CLI can
  // actually answer, instead of the Guide either faking an answer itself or
  // staying purely static. See TeacherOverlay's onAskAgent prop.
  const [guideAskTask, setGuideAskTask] = useState<string | undefined>(undefined);

  // File System State
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [explorerRoot, setExplorerRoot] = useState<string>("C:\\Dev\\Determinex");
  const [gitBranch, setGitBranch] = useState<string>("");
  // Whether the last git_status read FAILED, as opposed to succeeding with no changes. Without
  // this the two are indistinguishable: the catch below resets files to [] and the banner keys on
  // `explorerGitFiles.length > 0`, so a repo with uncommitted work whose git_status errored (git
  // not on PATH, a locked index, a timeout) rendered an emerald tick reading "Working tree clean"
  // on the landing screen.
  const [explorerGitUnavailable, setExplorerGitUnavailable] = useState(false);
  // Local-model coverage for the configured roles. Undefined until probed; ConceptLab treats
  // undefined as "no opinion", so this must actually be fetched or its gate stays dead.
  const [workReadiness, setWorkReadiness] = useState<WorkReadiness | undefined>(undefined);
  const [explorerGitFiles, setExplorerGitFiles] = useState<GitFile[]>([]);
  const [explorerGitMeta, setExplorerGitMeta] = useState<{
    upstream: string | null;
    ahead: number;
    behind: number;
  }>({
    upstream: null,
    ahead: 0,
    behind: 0,
  });

  useEffect(() => {
    if (!explorerRoot) return;
    let cancelled = false;
    // Announce the project BEFORE reading it. `set_project_root` is what grants the file
    // browser access to a project outside the base boundary -- on Windows that boundary is the
    // system drive, so a project on any other drive is refused until this call lands. These
    // were two independent effects with no ordering between them, so the tree read raced the
    // grant and lost about as often as it won; the visible symptom was an empty explorer and
    // "outside workspace boundary 'C:\'" that came back on reload but not on a re-render.
    (async () => {
      if (isTauri()) {
        try {
          await invoke("set_project_root", { path: explorerRoot });
        } catch (err) {
          console.error("set_project_root failed; the file tree may be refused:", err);
        }
      }
      if (cancelled) return;
      try {
        const res = await getFileSystemTree(explorerRoot);
        if (!cancelled && res && res.tree) setFileTree(res.tree);
      } catch (err) {
        if (!cancelled) showError(`Could not load file tree: ${err}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [explorerRoot]);

  useEffect(() => {
    if (!explorerRoot) {
      setGitBranch("");
      setExplorerGitFiles([]);
      return;
    }
    // `set_project_root` used to be called here too. It now lives in the file-tree effect
    // above, which must AWAIT it -- the call both scopes credential reads (env_manager) and
    // grants the file browser access to a project outside the base boundary, so the tree read
    // has to happen after it, and two independent effects gave no such ordering.
    //
    // Raw `invoke` there, not invokeSafe: set_project_root returns Result<(), _>, so it
    // resolves to null on SUCCESS -- and invokeSafe resolves to null on FAILURE. The two are
    // indistinguishable, which made the catch unreachable and the failure silent. Guarded on
    // isTauri because the raw `invoke` reads `window.__TAURI_INTERNALS__`, absent in the
    // browser preview, where there is no Env Manager to refuse anything and the alarming
    // message was pure noise. Crying wolf is how a genuine occurrence gets ignored.

    // Probe model coverage alongside the git read. A failure resolves to an explicit "unknown"
    // rather than being left undefined, so the difference between "not checked yet" and "checked,
    // could not tell" stays visible instead of silently reading as "fine".
    invokeSafe("get_work_readiness")
      .then((res) => {
        if (res) setWorkReadiness(res as WorkReadiness);
      })
      .catch(() => {
        setWorkReadiness({
          status: "unknown",
          ready: false,
          label: "Model coverage unknown",
          summary: "Could not determine local model coverage for the configured roles.",
          details: [],
          missingRoles: [],
        });
      });

    getGitStatus(explorerRoot)
      .then((res) => {
        setExplorerGitUnavailable(false);
        setGitBranch(res.branch);
        setExplorerGitFiles(res.files);
        setExplorerGitMeta({ upstream: res.upstream, ahead: res.ahead, behind: res.behind });
      })
      .catch(() => {
        // Record that the read FAILED. Clearing the state alone made a failure look identical to
        // a clean tree, and the banner then asserted "Working tree clean" about a repo it had not
        // been able to read.
        setExplorerGitUnavailable(true);
        setGitBranch("");
        setExplorerGitFiles([]);
        setExplorerGitMeta({ upstream: null, ahead: 0, behind: 0 });
      });
  }, [explorerRoot]);

  // Absolute-path -> status map for the file explorer tree. git_status returns
  // paths relative to explorerRoot (repo-relative porcelain output); FileNode.path
  // is always absolute (built server-side via to_string_lossy()), so normalize
  // both to forward slashes and join against explorerRoot to key the map the
  // same way FileSystemNode will look it up.
  const explorerGitStatusMap = useMemo(() => {
    const map: Record<string, { status: string; code: string }> = {};
    const rootNorm = explorerRoot.replace(/\\/g, "/").replace(/\/+$/, "");
    for (const file of explorerGitFiles) {
      const relNorm = file.path.replace(/\\/g, "/").replace(/^\/+/, "");
      map[`${rootNorm}/${relNorm}`] = { status: file.status, code: file.code };
    }
    return map;
  }, [explorerGitFiles, explorerRoot]);

  const toggleContext = (filename: string) => {
    setActiveContexts((prev) => {
      if (prev.includes(filename)) return prev.filter((c) => c !== filename);
      return [...prev, filename];
    });
  };

  // Viewport Engine
  const [isMobile, setIsMobile] = useState(false);

  // Workspace States
  // The Code addon (EditorPanel) is a self-contained component with its own tab state;
  // pendingEditorFile is how a file-tree click actually reaches it and becomes visible.
  const [pendingEditorFile, setPendingEditorFile] = useState<{
    path: string;
    content: string;
    requestId: number;
  } | null>(null);
  const pendingEditorRequestId = useRef(0);

  // The left rail scrolls but deliberately hides its scrollbar (`no-scrollbar`),
  // so overflow was completely invisible: promoting 4 icons to the rail silently
  // pushed Learn/Surfaces AND the pre-existing Tools button off the bottom with
  // zero indication anything was down there. Caught live 2026-07-27 on a 939px
  // window. Track whether more rail content exists below the fold so we can
  // render an affordance instead of just losing the buttons.
  // Which of the nine groups has its drawer open (null = closed).
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const railScrollRef = useRef<HTMLDivElement | null>(null);
  const [railHasMore, setRailHasMore] = useState(false);

  useEffect(() => {
    const el = railScrollRef.current;
    if (!el) return;
    const update = () => {
      // 4px slack: sub-pixel layout rounding otherwise reports a phantom 1-2px
      // of "more content" on a rail that actually fits exactly.
      setRailHasMore(el.scrollHeight - el.scrollTop - el.clientHeight > 4);
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      ro.disconnect();
    };
  }, []);

  const handleOpenFile = async (filePath: string) => {
    const fileName = filePath.split("\\").pop()?.split("/").pop() || filePath;
    try {
      const res = await readFileContent(filePath);
      if (res) {
        pendingEditorRequestId.current += 1;
        setPendingEditorFile({
          path: filePath,
          content: res.content,
          requestId: pendingEditorRequestId.current,
        });
        handleAddonLaunch("editor");
      }
    } catch (err) {
      setMatrixLogs((prev) => [...prev, `[ERROR] Could not read file ${fileName}: ${err}`]);
    }
  };

  // Pipeline State
  const [isExecutingPack, setIsExecutingPack] = useState(false);
  const [readinessScore, setReadinessScore] = useState(0);
  const [todos, setTodos] = useState<{ id: number; text: string; done: boolean }[]>([]);

  // Hardware Bootstrap
  const { isBootstrapping, bootTier, bootError, bootProgress, dismissBootError } = useBootstrap();

  // Pipeline output
  const [retryCount, setRetryCount] = useState(0);
  const [generatedFile, setGeneratedFile] = useState<string | null>(null);
  const [compilerWarning, setCompilerWarning] = useState<string | null>(null);

  // MoA Agent Telemetry
  const [agentStatus, setAgentStatus] = useState<AgentStatus>({
    currentAgent: null,
    isExecuting: false,
    verdict: null,
    confidence: null,
    accepted: null,
    error: null,
  });

  const [showWarRoom, setShowWarRoom] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState("");
  const [threadHistory, setThreadHistory] = useState<
    { id: string; title: string; updated: string }[]
  >([]);
  // Defaults closed; a mount effect below opens it only if this workspace has
  // never had it dismissed. Previously defaulted to `true` with no persistence
  // at all, so ANY reload (including one triggered by running a real terminal
  // command from inside the modal itself) brought back a full-screen blocking
  // overlay mid-task -- found live 2026-07-19.
  const [showOnboarding, setShowOnboarding] = useState(false);
  // A dockable surface hosted in the LEFT PANEL rather than the floating dock.
  // The drawer offers PANEL and DOCK as two destinations; before this existed,
  // both branches called handleAddonLaunch, so PANEL silently gave you the dock
  // -- the button was decoration. Ryan, live: "the multiagent popout drawer is
  // still super wierd."
  const [panelAddon, setPanelAddon] = useState<WorkspaceAddon | null>(null);

  // Re-read models_registry.json after the user adds a model, so it appears in
  // the picker immediately. Reuses the ADDONS_UPDATED_EVENT the mount effect
  // already listens on rather than hoisting that fetch out of the effect --
  // one refresh path, not two.
  const refreshModelsRegistry = useCallback(() => {
    window.dispatchEvent(new Event(ADDONS_UPDATED_EVENT));
  }, []);
  // Tracks whether SetupWizard is still showing -- it manages its own open/closed
  // state internally and never told the rest of the app. Needed so full-screen
  // takeovers (SetupWizard, and the other blocking modals below) can suppress
  // ConceptLab's floating "Open multi-agent chat" rail button, which portals to
  // document.body at z-[999] and otherwise renders on top of literally
  // everything -- found live: it was still visible floating over the Setup
  // Wizard's "System Ready" screen on a brand-new install.
  const [setupWizardOpen, setSetupWizardOpen] = useState(() => !hasCompletedSetup());
  // Home/Command Center removed as a separate screen (2026-07-19) -- it was
  // three redundant status readouts (model route, audit score, git state)
  // that already live elsewhere (StatusBar, Audit, Work's own git-aware
  // banner) plus one contextual CTA, folded into Work's dashboard instead.
  // Work is now the landing screen.
  const [activeSidebar, setActiveSidebar] = useState<PrimaryWorkspace>("hive");
  const [lastWorkbenchSidebar, setLastWorkbenchSidebar] = useState<PrimaryWorkspace>("hive");
  const [activeAddon, setActiveAddon] = useState<WorkspaceAddon | null>(null);
  const [addonDockOpen, setAddonDockOpen] = useState(false);
  // Free-floating window model (2026-07-19) -- replaced the bottom/right docked
  // strip. Ryan: "still really buggy and no way to move it or position it, and
  // no memory of how user wants it." The dock is now a real draggable/resizable
  // window (drag by header, resize from any edge/corner) positioned absolutely
  // over the whole app canvas instead of squeezing the flex layout, and its
  // layout (x/y/w/h/maximized) is remembered PER ADDON via addonLayoutMemoryRef
  // + localStorage, restored every time that specific tool is reattached.
  const [addonDockX, setAddonDockX] = useState(90);
  const [addonDockY, setAddonDockY] = useState(64);
  const [addonDockHeight, setAddonDockHeight] = useState(600);
  const [addonDockWidth, setAddonDockWidth] = useState(920);
  const [addonDockMaximized, setAddonDockMaximized] = useState(true);
  // Mirrors the geometry state during an active drag/resize gesture so the
  // pointerup handler can commit the true final values -- reading React state
  // directly in that closure would see the value from gesture-start, not the
  // live value updated across intermediate pointermove events.
  const addonDockLiveRef = useRef({ x: 90, y: 64, w: 920, h: 600 });
  // Per-addon-id remembered window layout. Loaded from localStorage on mount,
  // written back whenever a drag/resize/maximize gesture completes.
  const addonLayoutMemoryRef = useRef<
    Record<string, { x: number; y: number; w: number; h: number; maximized: boolean }>
  >({});
  const [showTeacher, setShowTeacher] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [hiveSessionId, setHiveSessionId] = useState<string | null>(null);
  const [hiveAutoRun, setHiveAutoRun] = useState(false);
  const [hiveSpec, setHiveSpec] = useState<string>("");
  const [hiveProjectName, setHiveProjectName] = useState<string>("");
  const [previewedPath, setPreviewedPath] = useState<PathInfo | null>(null);
  const [confirmedPath, setConfirmedPath] = useState<PathInfo | null>(null);
  const [oracleAnsweredCount, setOracleAnsweredCount] = useState(0);
  const [isOracleConsulting, setIsOracleConsulting] = useState(false);

  /**
   * Which of Ask / Plan / Build / Prove the operator is actually on (0-3).
   *
   * The cockpit's four cards used to be static prose: they restated the vocabulary while
   * the panel beside them did the work, and they read the same before a run and after a
   * verified one. Derived from real state they answer the question a new operator actually
   * has -- not "what are the stages called" but "which one am I in, and what do I do now".
   */
  const cockpitStep = agentStatus.verdict
    ? 3
    : hiveSessionId || agentStatus.isExecuting
      ? 2
      : isOracleConsulting || hiveSpec.trim()
        ? 1
        : 0;

  /**
   * The ONE thing to do next, in plain words. Three surfaces can start work -- the Work
   * panel, this cockpit, and the Agent Chat Room -- and nothing on screen said which to
   * use, so the honest fix is to name a single next action rather than leave the operator
   * to infer it from three competing affordances.
   */
  const cockpitNextAction = [
    "Type what you want in the box on the left, then press Consult Oracle. If it is one function and you can give examples, press Quick Verify instead — it is faster and ends in a proof.",
    "Answer the Oracle's questions on the left until it can write a spec. It is narrowing your idea to something a test can check.",
    "The builder is working. Attach Terminal or Trace on the right to watch it, or wait — the verdict lands here.",
    "Done. The verdict and its evidence are in Proof; open it from the rail to see the diff, logs and oracle output.",
  ][cockpitStep];
  const [externalIdea, setExternalIdea] = useState("");
  const [colorHints, setColorHints] = useState<string[]>([]);
  const [showProjectLibrary, setShowProjectLibrary] = useState(false);
  const [hiveAutoRetry, setHiveAutoRetry] = useState(false);
  const [selectedProjectName, setSelectedProjectName] = useState("Determinex");
  const [workspaceView, setWorkspaceView] = useState<"overview" | "files" | "source" | "runs">(
    "overview"
  );

  // The drawer decides nothing; the user does. `kind` says what the surface is
  // (a left-panel workspace vs a dockable addon) and `destination` says where
  // they asked for it, so the same surface can go either place instead of the
  // entry point hard-coding it the way the old rail did.
  const openSurface = (member: SurfaceMember, destination: SurfaceDestination) => {
    // Modal surfaces (Settings, Skin, Guide) are not panels and have no
    // destination to choose. They were previously declared as addons and cast
    // with `as WorkspaceAddon`, which type-checked and opened nothing.
    if (member.kind === "modal") {
      if (member.modal === "guide") {
        setShowTeacher(true);
      } else {
        setSettingsTab(member.modal === "skin" ? "skin" : "keys");
        setShowSettings(true);
      }
      setOpenGroupId(null);
      return;
    }
    if (destination === "dock") {
      if (panelAddon === member.id) setPanelAddon(null);
      handleAddonLaunch(member.id as WorkspaceAddon);
    } else if (member.kind === "sidebar") {
      // SET, never toggle. This used to call handleSidebarLaunch, which toggles --
      // so choosing a surface that was already active CLOSED it, and the drawer's
      // "open this" action rendered an empty panel. Work Cockpit is the default
      // sidebar, so the very first surface a user picks was the one that broke.
      //
      // Also clears any panel-hosted addon: without that, an addon opened into the
      // panel earlier keeps rendering and shadows the sidebar you just asked for
      // (picking Brain showed Agent Chat Room).
      setPanelAddon(null);
      setActiveSidebar(member.id as PrimaryWorkspace);
      setPreviewedPath(null);
    } else {
      // An addon asked for the panel slot, so put it IN the panel. This used to
      // call handleAddonLaunch -- identical to the "dock" branch above -- so
      // choosing PANEL opened the floating dock window instead, which then
      // rendered at whatever geometry that tool last remembered and got
      // occluded by Zone 2. Hosting it here means it is laid out by the same
      // resizable, persisted panel as every other left-hand surface.
      setPanelAddon(member.id as WorkspaceAddon);
      // Dropping the sidebar to "none" hands the panel over wholesale. Without
      // it, the active workspace's body would render underneath the hosted
      // surface and its header would keep the workspace's own name.
      setActiveSidebar("none");
      if (addonDockOpen && activeAddon === member.id) {
        // Do not leave the same surface open twice in two places.
        setActiveAddon(null);
        setAddonDockOpen(false);
      }
    }
    setOpenGroupId(null);
  };

  // Zone 1's width was a hard-coded className switch, so the only way to change
  // it was to edit the source. Same defaults as before -- now a starting point
  // the user can drag, persisted per surface.
  // A dockable surface hosted here was built for a ~920px dock window, so the
  // 380px sidebar default cut its content in half. It gets a width that fits and
  // a higher floor; still user-draggable and still remembered per surface.
  const zone1Default = panelAddon
    ? 620
    : activeSidebar === "git"
      ? 760
      : activeSidebar === "hive"
        ? 460
        : activeSidebar === "benchmark"
          ? 400
          : 380;
  const zone1Key = panelAddon ? `zone1.addon.${panelAddon}` : `zone1.${activeSidebar}`;
  // The Work Cockpit's internal split, persisted like Zone 1's width.
  const cockpitGridRef = useRef<HTMLDivElement>(null);
  const cockpitSplit = usePanelSplit("workCockpit", 0.55, {
    min: 0.3,
    max: 0.75,
    containerRef: cockpitGridRef,
  });
  const zone1 = usePanelWidth(zone1Key, zone1Default, {
    min: panelAddon ? 420 : 280,
    max: 1100,
  });

  const handleSidebarLaunch = (sidebar: PrimaryWorkspace) => {
    setActiveSidebar(activeSidebar === sidebar ? "none" : sidebar);
  };
  useEffect(() => {
    if (activeSidebar !== "none" && activeSidebar !== "extensions") {
      setLastWorkbenchSidebar(activeSidebar);
    }
  }, [activeSidebar]);
  // A maximized addon (z-40, covers everything but the rail) used to silently
  // keep covering whatever screen you switched TO -- rail highlighted "Brain"
  // but the whole visible surface was still whatever addon (Cloak, Terminal...)
  // was left open, with no indication why. Found live 2026-07-19 (Ryan:
  // "cloak still brings up the privacy cockpit" -- while trying to look at
  // Brain). Keyed on activeSidebar itself, not one handler -- there are 3+
  // separate code paths that change it (handleSidebarLaunch, openWorkspace,
  // handleProjectHubNavigate) and patching just one missed the rail's own
  // Brain button.
  const prevSidebarForAddonRef = useRef(activeSidebar);
  // handleAddonLaunch below also changes activeSidebar (bootstrapping out of
  // "none"/"extensions" so the attached tool has a screen to sit beside) --
  // that transition must NOT trigger the auto-close above, or attaching a
  // tool from Home/Tools would immediately undo itself. Set right before that
  // specific setActiveSidebar call, consumed (and cleared) by the effect.
  const skipNextAddonAutoCloseRef = useRef(false);
  useEffect(() => {
    if (prevSidebarForAddonRef.current !== activeSidebar) {
      prevSidebarForAddonRef.current = activeSidebar;
      if (skipNextAddonAutoCloseRef.current) {
        skipNextAddonAutoCloseRef.current = false;
      } else {
        setActiveAddon(null);
        setAddonDockOpen(false);
      }
    }
  }, [activeSidebar]);

  // Restores that specific tool's remembered window geometry (or a sane
  // default for a tool that's never been opened before).
  const applyAddonLayout = (addon: WorkspaceAddon) => {
    const saved = addonLayoutMemoryRef.current[addon];
    const layout = saved ?? { x: 90, y: 64, w: 920, h: 600, maximized: true };
    addonDockLiveRef.current = { x: layout.x, y: layout.y, w: layout.w, h: layout.h };
    setAddonDockX(layout.x);
    setAddonDockY(layout.y);
    setAddonDockWidth(layout.w);
    setAddonDockHeight(layout.h);
    setAddonDockMaximized(layout.maximized);
  };
  // Commits the CURRENT window geometry as that tool's remembered layout.
  // Reads geometry from addonDockLiveRef (always fresh) rather than the x/y/w/h
  // state variables (which would be stale-closure at the end of a drag/resize).
  const commitAddonLayout = (addon: WorkspaceAddon, maximizedOverride?: boolean) => {
    const g = addonDockLiveRef.current;
    const layout = {
      x: g.x,
      y: g.y,
      w: g.w,
      h: g.h,
      maximized: maximizedOverride ?? addonDockMaximized,
    };
    addonLayoutMemoryRef.current = { ...addonLayoutMemoryRef.current, [addon]: layout };
    try {
      localStorage.setItem("addonWindowLayouts", JSON.stringify(addonLayoutMemoryRef.current));
    } catch {
      // best-effort persistence only
    }
  };

  const handleAddonLaunch = (addon: WorkspaceAddon) => {
    if (addonDockOpen && activeAddon === addon && activeSidebar !== "extensions") {
      setActiveAddon(null);
      setAddonDockOpen(false);
      return;
    }
    if (activeSidebar === "none" || activeSidebar === "extensions") {
      skipNextAddonAutoCloseRef.current = true;
      setActiveSidebar(
        lastWorkbenchSidebar === "none" || lastWorkbenchSidebar === "extensions"
          ? "hub"
          : lastWorkbenchSidebar
      );
    }
    applyAddonLayout(addon);
    setActiveAddon(addon);
    setAddonDockOpen(true);
  };
  const closeAddon = () => {
    setActiveAddon(null);
    setAddonDockOpen(false);
  };
  const openProjectHub = () => {
    setActiveSidebar("hub");
    setPreviewedPath(null);
  };
  const openWorkspace = (view: "overview" | "files" | "source" | "runs" = "overview") => {
    setWorkspaceView(view);
    setActiveSidebar("explorer");
  };
  const handleProjectHubNavigate = (destination: ProjectHubDestination) => {
    if (destination === "work") {
      setActiveSidebar("hive");
      return;
    }
    if (destination === "workspace") {
      openWorkspace("overview");
      return;
    }
    if (destination === "source") {
      openWorkspace("source");
      return;
    }
    if (destination === "runs") {
      openWorkspace("runs");
      return;
    }
    if (destination === "brain") {
      setActiveSidebar("benchmark");
      return;
    }
    if (destination === "proof") {
      setActiveSidebar("proof");
    }
  };

  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (
        document.activeElement?.tagName === "INPUT" ||
        document.activeElement?.tagName === "TEXTAREA"
      ) {
        return;
      }

      if ((e.metaKey || e.ctrlKey) && e.key === "b") {
        e.preventDefault();
        setActiveSidebar((prev) => (prev === "none" ? "explorer" : "none"));
      } else if ((e.metaKey || e.ctrlKey) && (e.key === "j" || e.key === "`")) {
        e.preventDefault();
        handleAddonLaunch("terminal");
      } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === "F" || e.key === "f")) {
        e.preventDefault();
        handleAddonLaunch("findfiles");
      } else if ((e.metaKey || e.ctrlKey) && /^[1-9]$/.test(e.key)) {
        // Ctrl/Cmd+1..9 opens the matching rail group's drawer.
        //
        // This used to map only 1/2/3, and to three specific left-hand
        // workspaces (hub / hive / explorer) rather than to the rail -- a
        // leftover from before the nine-group rail existed. So six of nine groups
        // had no shortcut, and the three that did went somewhere the rail no
        // longer represents. One coherent mapping instead.
        e.preventDefault();
        const group = SURFACE_GROUPS[Number(e.key) - 1];
        if (group) setOpenGroupId((cur) => (cur === group.id ? null : group.id));
      } else if (e.key === "Escape") {
        // Escape closed nothing at the shell level. The drawer is the most
        // common thing a user wants out of, so it goes first.
        if (openGroupId) {
          e.preventDefault();
          setOpenGroupId(null);
        }
      }
    };
    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
    // openGroupId is read above, so an empty dep list would pin this handler to
    // its mount-time value and Escape would only ever see "nothing open".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openGroupId]);
  const handleProjectSelect = (project: ProjectHubProject) => {
    setSelectedProjectName(project.name);
    if (!project.localPath.startsWith("Choose")) {
      setExplorerRoot(project.localPath);
    }
  };
  const handleResumeProjectSession = (
    sessionId: string,
    projectName: string,
    shouldRetry: boolean
  ) => {
    setHiveSessionId(sessionId);
    setHiveProjectName(projectName || selectedProjectName);
    setHiveAutoRun(false);
    setHiveAutoRetry(shouldRetry);
    setShowProjectLibrary(false);
    setActiveSidebar("hive");
  };

  const [sandboxFiles, setSandboxFiles] = useState<
    { name: string; modified: string; type: string }[]
  >([]);
  const [isDiffMode, setIsDiffMode] = useState(false);
  const [diffData, setDiffData] = useState({
    old: "# Old Implementation",
    new: "# Proposed Agent Scaffold",
  });
  const [matrixLogs, setMatrixLogs] = useState<string[]>([]);
  const statusBarErrorCount = matrixLogs.filter((l) => l.includes("[ERROR]")).length;

  // Rust telemetry bridge —" via extracted hook
  useMoaTelemetry({
    setMatrixLogs,
    setCompilerWarning,
    setGeneratedFile,
    setRetryCount,
    setAgentStatus,
  });

  // Viewport Lock
  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 768);
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Command palette keyboard shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "P") {
        e.preventDefault();
        setShowPalette((v) => !v);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setShowPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Session Hydration
  useEffect(() => {
    const savedRoot = localStorage.getItem("explorerRoot");
    if (savedRoot) setExplorerRoot(savedRoot);

    // Show workspace onboarding only for a path that hasn't dismissed it before, AND only
    // once SetupWizard itself has actually finished -- on a genuinely fresh install both
    // used to mount at once (SetupWizard checks hasCompletedSetup() independently), landing
    // a brand-new user on two stacked dialogs, the top one rendering blank because its own
    // analyze_workspace call was still racing SetupWizard's hardware/toolchain probes.
    // SETUP_COMPLETED_EVENT (fired by markSetupCompleted) re-runs this same check the
    // moment the wizard actually completes, in the same session, no reload required.
    // Resolved the SAME way the Dismiss handler resolves it. These two used to
    // disagree -- the check keyed off `savedRoot` (null on every new install)
    // and the write keyed off `explorerRoot` (a hard-coded default), so the
    // dismissal landed on a key nothing read and this modal returned on every
    // launch, permanently. See lib/workspaceOnboarding.ts.
    const onboardingRoot = resolveWorkspaceRoot(savedRoot, explorerRoot);
    const maybeShowOnboarding = () => {
      if (hasCompletedSetup() && !hasDismissedOnboarding(onboardingRoot)) {
        setShowOnboarding(true);
      }
    };
    maybeShowOnboarding();
    window.addEventListener(SETUP_COMPLETED_EVENT, maybeShowOnboarding);

    const handleSetupCompleted = () => setSetupWizardOpen(false);
    window.addEventListener(SETUP_COMPLETED_EVENT, handleSetupCompleted);

    try {
      const savedLayouts = localStorage.getItem("addonWindowLayouts");
      if (savedLayouts) addonLayoutMemoryRef.current = JSON.parse(savedLayouts);
    } catch {
      addonLayoutMemoryRef.current = {};
    }

    const savedCtx = localStorage.getItem("activeContexts");
    if (savedCtx) setActiveContexts(JSON.parse(savedCtx));
    else setActiveContexts(["main.py"]);

    const refreshRegistry = () => {
      getModelsRegistry()
        .then((data) => {
          if (data && data.tiers) {
            let mergedTiers = data.tiers;
            try {
              const installedAddons = readInstalledAddonIds(localStorage);
              const installedLlms = ADDONS.filter(
                (a) => a.category === "llm" && (installedAddons.has(a.id) || a.status === "builtin")
              );

              if (installedLlms.length > 0) {
                const cloudTier = {
                  tier_id: "addons",
                  title: "Providers & Tools",
                  color: "text-violet-400",
                  models: installedLlms.map((a) => ({
                    id: a.id,
                    name: a.name,
                    desc: a.description,
                    context_window: 128000,
                  })),
                };
                mergedTiers = [cloudTier, ...mergedTiers];
              }
            } catch (e) {
              console.error("Failed to parse addons", e);
            }
            setModelTiers(mergedTiers);
            setTandemPresets(data.tandem_presets || []);
          }
        })
        .catch((e) => showError(`Failed to load model registry: ${e}`));

      if (isTauri()) {
        invokeSafe<
          {
            id: string;
            name: string;
            size_gb: number;
            param_size: string;
            quantization: string;
            is_determinex: boolean;
          }[]
        >("get_ollama_models")
          .then((models) => {
            if (!models) return;
            const determinexModels = models.filter((m) => m.is_determinex);
            const otherModels = models.filter((m) => !m.is_determinex);
            const tiers = [];
            if (determinexModels.length > 0) {
              tiers.push({
                tier_id: "determinex",
                title: "Determinex Fine-tuned",
                color: "text-emerald-400",
                models: determinexModels.map((m) => ({
                  id: `ollama/${m.id}`,
                  name: displayModelName(m.name),
                  desc: `${m.param_size} · ${m.quantization} · ${m.size_gb.toFixed(1)}GB`,
                  context_window: 4096,
                })),
              });
            }
            if (otherModels.length > 0) {
              tiers.push({
                tier_id: "local",
                title: "Local (Ollama)",
                color: "text-blue-400",
                models: otherModels.map((m) => ({
                  id: `ollama/${m.id}`,
                  name: displayModelName(m.name),
                  desc: `${m.param_size} · ${m.quantization} · ${m.size_gb.toFixed(1)}GB`,
                  context_window: 4096,
                })),
              });
            }
            if (tiers.length > 0) setModelTiers(tiers);
          })
          .catch((e) => showError(`Failed to load Ollama models: ${e}`));
      }

      getWorkspaceFiles()
        .then((data) => setSandboxFiles(data.files || []))
        .catch((e) => showError(`Failed to load workspace files: ${e}`));
      getThreads()
        .then((data) => {
          const fetched = data.threads || [];
          setThreadHistory(fetched);
          if (activeThreadId === "" && fetched.length > 0) setActiveThreadId(fetched[0].id);
        })
        .catch((e) => showError(`Failed to load threads: ${e}`));
      if (activeThreadId) {
        fetchTodos(activeThreadId)
          .then((data) => setTodos(data.todos || []))
          .catch((e) => showError(`Failed to load todos: ${e}`));
      }
    };

    refreshRegistry();

    const handleAddonsUpdated = () => refreshRegistry();
    window.addEventListener(ADDONS_UPDATED_EVENT, handleAddonsUpdated);

    return () => {
      window.removeEventListener(ADDONS_UPDATED_EVENT, handleAddonsUpdated);
      window.removeEventListener(SETUP_COMPLETED_EVENT, maybeShowOnboarding);
      window.removeEventListener(SETUP_COMPLETED_EVENT, handleSetupCompleted);
    };
  }, []);

  useEffect(() => {
    if (activeThreadId) {
      fetchTodos(activeThreadId)
        .then((data) => setTodos(data.todos || []))
        .catch((e) => showError(`Failed to load todos: ${e}`));
    } else {
      setTodos([]);
    }
  }, [activeThreadId]);

  useEffect(() => {
    if (activeContexts.length > 0)
      localStorage.setItem("activeContexts", JSON.stringify(activeContexts));
  }, [activeContexts]);

  useEffect(() => {
    if (explorerRoot) localStorage.setItem("explorerRoot", explorerRoot);
  }, [explorerRoot]);

  // Per-addon layout is committed to addonLayoutMemoryRef + localStorage at the
  // end of each drag/resize/maximize gesture (see commitAddonLayout), not on
  // every render -- see addonDockLiveRef above for why.

  const handleInject = async (text?: string) => {
    if (isExecutingPack) return;
    const content = text || inputVal.trim();
    if (!content) return;
    if (!text) setInputVal("");
    setMatrixLogs((prev) => [...prev, `[USER] ${content}`]);

    if (isTauri()) {
      const threadId = activeThreadId || `thread-${Date.now()}`;
      setIsExecutingPack(true);
      setRetryCount(0);
      setGeneratedFile(null);
      setCompilerWarning(null);
      setAgentStatus({
        currentAgent: null,
        isExecuting: true,
        verdict: null,
        confidence: null,
        accepted: null,
        error: null,
      });

      try {
        const result = await nativeOrchestratePlan(content, threadId, selectedModel);
        const verdict = result.audit.verdict ?? null;
        const confidence = result.audit.confidence ?? null;
        const accepted = result.accepted ?? false;
        const firstFile: string | null = accepted ? (result.code.files_affected[0] ?? null) : null;
        setGeneratedFile(firstFile);
        if (firstFile) {
          invokeSafe<string>("read_workspace_file", { relativePath: firstFile })
            .then((code) => {
              if (code) setDiffData((d) => ({ ...d, new: code }));
            })
            .catch((e) => showError(`Failed to read generated file: ${e}`));
        }
        setAgentStatus({
          currentAgent: null,
          isExecuting: false,
          verdict,
          confidence,
          accepted,
          error: null,
        });
        setMatrixLogs((prev) => [
          ...prev,
          `[OBSERVER] Verdict: ${verdict} (confidence: ${((confidence ?? 0) * 100).toFixed(0)}%)`,
          accepted
            ? `[DETERMINEX] PASS Pipeline ACCEPTED. Check the Output panel for the generated file.`
            : `[DETERMINEX] FAIL Pipeline REJECTED. Observer audit failed - see issues above.`,
        ]);
        setTimeout(() => {
          getThreads()
            .then((data) => {
              const fetched = data.threads || [];
              setThreadHistory(fetched);
              if (!activeThreadId && fetched.length > 0) setActiveThreadId(fetched[0].id);
            })
            .catch((e) => showError(`Failed to refresh threads: ${e}`));
        }, 1500);
      } catch (e: any) {
        const stage = e?.stage ?? "Unknown";
        const message = e?.message ?? String(e);
        setAgentStatus({
          currentAgent: null,
          isExecuting: false,
          verdict: null,
          confidence: null,
          accepted: null,
          error: { stage, message },
        });
        setMatrixLogs((prev) => [...prev, `[ERROR][${stage}] MoA pipeline aborted: ${message}`]);
      } finally {
        setIsExecutingPack(false);
      }
    } else {
      try {
        await injectSandboxContext(
          content,
          activeThreadId || "default",
          activeContexts,
          selectedModel
        );
        setTimeout(() => {
          getThreads()
            .then((data) => {
              const fetched = data.threads || [];
              setThreadHistory(fetched);
              if (!activeThreadId && fetched.length > 0) setActiveThreadId(fetched[0].id);
            })
            .catch((e) => showError(`Failed to refresh threads: ${e}`));
        }, 3000);
      } catch (e) {
        setMatrixLogs((prev) => [...prev, `[ERROR] Failed to hit backend: ${e}`]);
      }
    }
  };

  const executeAbort = async () => {
    try {
      await abortOrchestration();
      setIsExecutingPack(false);
      setAgentStatus({
        currentAgent: null,
        isExecuting: false,
        verdict: null,
        confidence: null,
        accepted: null,
        error: null,
      });
      setMatrixLogs((prev) => [...prev, `[SYSTEM] ABORT INTERRUPT FIRED. Actor loop draining.`]);
    } catch (e) {
      setMatrixLogs((prev) => [
        ...prev,
        `[SYSTEM] Abort signal sent (channel may already be closed).`,
      ]);
    }
  };

  const handlePromoteToGarden = async (threadId: string, history: string) => {
    try {
      setMatrixLogs((prev) => [
        ...prev,
        `[SYSTEM] Promoting Thread ${threadId} through native MoA pipeline...`,
      ]);
      if (isTauri()) {
        setIsExecutingPack(true);
        setAgentStatus({
          currentAgent: "sentinel",
          isExecuting: true,
          verdict: null,
          confidence: null,
          accepted: null,
          error: null,
        });
        const result = await nativeOrchestratePlan(history, threadId, selectedModel);
        setAgentStatus({
          currentAgent: null,
          isExecuting: false,
          verdict: result.audit.verdict ?? null,
          confidence: result.audit.confidence ?? null,
          accepted: result.accepted ?? false,
          error: null,
        });
        setIsExecutingPack(false);
      } else {
        await promoteToGarden(threadId, history, selectedModel);
      }
    } catch (e) {
      setMatrixLogs((prev) => [...prev, `[ERROR] Failed to promote: ${e}`]);
      setIsExecutingPack(false);
    }
  };

  const handleUnleash = async () => {
    const payload = inputVal.trim();
    if (!payload) return;
    setLastPrompt(payload);
    setInputVal("");
    await handleInject(payload);
  };

  const HelpBtn = ({ title, desc }: { title: string; desc: string }) => (
    <button
      onClick={(e) => {
        e.stopPropagation();
        setHelpModal({ title, desc });
      }}
      className="ml-2 text-cyan-500/50 hover:text-cyan-400 hover:scale-110 transition-all focus:outline-none"
    >
      <HelpCircle size={14} />
    </button>
  );

  // -------------------------------------------------------------
  // COMMAND PALETTE COMMANDS
  // -------------------------------------------------------------
  const paletteCommands: PaletteCommand[] = [
    {
      id: "go-home",
      label: "Go to Home",
      description: "Project hub and overview",
      category: "Navigation",
      icon: Globe,
      action: () => setActiveSidebar("hub"),
    },
    {
      id: "go-work",
      label: "Open Work",
      description: "Hive sessions and model routing",
      category: "Navigation",
      icon: Zap,
      shortcut: "Ctrl+5",
      action: () => handleSidebarLaunch("hive"),
    },
    {
      id: "go-pipeline",
      label: "Open Pipeline",
      description: "Build pipeline and architect",
      category: "Navigation",
      icon: Activity,
      action: () => handleSidebarLaunch("pipeline"),
    },
    {
      id: "go-explorer",
      label: "Open Workspace",
      description: "File explorer and project view",
      category: "Navigation",
      icon: FolderOpen,
      action: () => handleSidebarLaunch("explorer"),
    },
    {
      id: "go-brain",
      label: "Open Brain",
      description: "Benchmarks and model telemetry",
      category: "Navigation",
      icon: Brain,
      action: () => handleSidebarLaunch("benchmark"),
    },
    {
      id: "go-terminal",
      label: "Attach Terminal",
      description: "Attach terminal to the current workspace",
      category: "Add-ons",
      icon: TerminalIcon,
      shortcut: "Ctrl+`",
      action: () => handleAddonLaunch("terminal"),
    },
    {
      id: "go-editor",
      label: "Attach Code Editor",
      description: "Attach Monaco editor to the current workspace",
      category: "Add-ons",
      icon: Code2,
      action: () => handleAddonLaunch("editor"),
    },
    {
      id: "go-learning",
      label: "Attach Learning Studio",
      description: "Attach non-authorizing teaching explanations grounded in the verified corpus",
      category: "Add-ons",
      icon: Brain,
      action: () => handleAddonLaunch("learning"),
    },
    {
      id: "go-repoclinic",
      label: "Attach Repo Clinic",
      description: "Attach live oracle-backed diagnosis of the open workspace",
      category: "Add-ons",
      icon: Activity,
      action: () => handleAddonLaunch("repoclinic"),
    },
    {
      id: "go-maintbay",
      label: "Attach Maintenance Bay",
      description: "Attach live dependency/secret/license/container security scan",
      category: "Add-ons",
      icon: ShieldCheck,
      action: () => handleAddonLaunch("maintenancebay"),
    },
    {
      id: "go-health",
      label: "Attach Health Map",
      description: "Attach oracle health and file status",
      category: "Add-ons",
      icon: LayoutGrid,
      action: () => handleAddonLaunch("health"),
    },
    {
      id: "go-search",
      label: "Attach Verified Search",
      description: "Attach oracle-verified search",
      category: "Add-ons",
      icon: Search,
      action: () => handleAddonLaunch("search"),
    },
    {
      id: "go-findfiles",
      label: "Find in Files",
      description: "Literal, gitignore-aware text search across the workspace",
      category: "Add-ons",
      icon: FileSearch,
      shortcut: "Ctrl+Shift+F",
      action: () => handleAddonLaunch("findfiles"),
    },
    {
      id: "go-trace",
      label: "Attach Agent Trace",
      description: "Attach WAL replay and session history",
      category: "Add-ons",
      icon: GitBranch,
      action: () => handleAddonLaunch("trace"),
    },
    {
      id: "go-cloak",
      label: "Attach Privacy Cockpit",
      description: "Attach Project Cloak obfuscation map",
      category: "Add-ons",
      icon: Lock,
      action: () => handleAddonLaunch("cloak"),
    },
    {
      id: "go-flywheel",
      label: "Attach Flywheel",
      description: "Attach live training corpus feed",
      category: "Add-ons",
      icon: RefreshCcw,
      action: () => handleAddonLaunch("flywheel"),
    },
    // mission/roadmap are Determinex's own release-tracking, not a per-project
    // feature -- command-palette entries only in internal/dev builds, never
    // shipped to a real end user. See isInternalBuild().
    ...(isInternalBuild()
      ? [
          {
            id: "go-mission",
            label: "Attach Mission Control",
            description: "Attach interactive guide, release gates, runbooks, and proof boundaries",
            category: "Add-ons",
            icon: GraduationCap,
            action: () => handleAddonLaunch("mission"),
          },
          {
            id: "go-roadmap",
            label: "Attach IDE Roadmap",
            description: "Attach Determinex successor roadmap and release blockers",
            category: "Add-ons",
            icon: ShieldCheck,
            action: () => handleAddonLaunch("roadmap"),
          },
        ]
      : []),
    {
      id: "go-tools",
      label: "Open Tools",
      description: "Installed tools, model providers, connectors, and attached panes",
      category: "Navigation",
      icon: Package,
      action: () => setActiveSidebar("extensions"),
    },
    {
      id: "go-build",
      label: "Attach Build Center",
      description: "Attach tasks, tests, output, deps, env, CI/CD",
      category: "Add-ons",
      icon: Gauge,
      action: () => handleAddonLaunch("build"),
    },
    {
      id: "go-proof",
      label: "Open Proof",
      description: "Project verdicts, builds, logs, diffs, and release gates",
      category: "Navigation",
      icon: Eye,
      action: () => handleSidebarLaunch("proof"),
    },
    {
      id: "go-ide-repair",
      label: "Attach Repair Panel",
      description: "Diagnose this repo, review the patch plan, and manage human approval",
      category: "Add-ons",
      icon: GitPullRequest,
      action: () => handleAddonLaunch("repair"),
    },
    {
      id: "go-guide",
      label: "Open Guide",
      description: "Interactive IDE guided tour",
      category: "Navigation",
      icon: GraduationCap,
      action: () => setShowTeacher(true),
    },
    {
      id: "settings",
      label: "Open Settings",
      description: "All settings",
      category: "Settings",
      icon: Settings,
      action: () => {
        setSettingsTab("keys");
        setShowSettings(true);
      },
    },
    {
      id: "settings-keys",
      label: "API Keys",
      description: "Manage provider credentials",
      category: "Settings",
      icon: Key,
      action: () => {
        setSettingsTab("keys");
        setShowSettings(true);
      },
    },
    {
      id: "settings-skin",
      label: "Appearance",
      description: "Skin packs and accent color",
      category: "Settings",
      icon: Palette,
      action: () => {
        setSettingsTab("skin");
        setShowSettings(true);
      },
    },
  ];

  const addonItems: AddonItem[] = [
    {
      id: "terminal",
      label: "Terminal",
      description: "Run commands beside the active screen.",
      icon: TerminalIcon,
      tone: "text-emerald-400",
      panel: <TerminalPanel workspacePath={explorerRoot} />,
    },
    {
      id: "learning",
      label: "Learning Studio",
      description: "Non-authorizing teaching explanations grounded in the verified corpus.",
      icon: Brain,
      tone: "text-fuchsia-400",
      // Learning Studio's two calls-to-action used to be dead hash links (#repo-clinic,
      // #idea-lab) with no matching element anywhere. Wired to the real switchers: Repo
      // Clinic is an addon panel, and the new-project flow is ConceptLab on the "hive"
      // sidebar.
      panel: (
        <LearningStudioPanel
          onOpenRepoClinic={() => handleAddonLaunch("repoclinic")}
          onOpenIdeaLab={() => {
            closeAddon();
            setActiveSidebar("hive");
          }}
        />
      ),
    },
    {
      id: "repoclinic",
      label: "Repo Clinic",
      description: "Live oracle-backed diagnosis of the open workspace, non-authorizing.",
      icon: Activity,
      tone: "text-orange-400",
      panel: <RepoClinicPanel workspacePath={explorerRoot} />,
    },
    {
      id: "maintenancebay",
      label: "Maintenance Bay",
      description: "Live dependency/secret/license/container security scan, non-authorizing.",
      icon: ShieldCheck,
      tone: "text-amber-400",
      panel: <MaintenanceBayPanel />,
    },
    {
      id: "editor",
      label: "Code",
      description: "Inspect generated code and source files.",
      icon: Code2,
      tone: "text-blue-400",
      panel: <EditorPanel pendingFile={pendingEditorFile} workspacePath={explorerRoot} />,
    },
    {
      id: "search",
      label: "Verified Search",
      // Was "Find verified snippets and project context." -- which describes a retrieval
      // feature this panel is not, and sent anyone looking for text search here instead of
      // to "Find in Files" below. VerifiedSearch.tsx opens: "Verified Search = the
      // Correctness Amplifier, driven from the IDE", and calls preview_idea_oracle then
      // build_idea. The description now matches what the panel does, and matches the
      // wording surfaceGroups.ts already used for this same surface.
      description:
        "Turn an idea into a verified program: synthesize an oracle, then sample until a candidate passes.",
      icon: Search,
      tone: "text-blue-400",
      panel: <VerifiedSearch selectedModel={selectedModel} workspacePath={explorerRoot} />,
    },
    {
      id: "findfiles",
      label: "Find in Files",
      description: "Literal, gitignore-aware text search across the workspace.",
      icon: FileSearch,
      tone: "text-blue-400",
      panel: <FileSearchPanel workspacePath={explorerRoot} />,
    },
    {
      id: "build",
      label: "Build",
      description: "Tasks, tests, problems, output, deps, env, and artifacts.",
      icon: Gauge,
      tone: "text-orange-400",
      panel: <BuildCenter workspacePath={explorerRoot} />,
    },
    {
      id: "trace",
      label: "Trace",
      description: "Worker timeline, WAL replay, and session events.",
      icon: GitBranch,
      tone: "text-violet-400",
      panel: <AgentTrace />,
    },
    {
      id: "health",
      label: "Health",
      description: "Oracle health, file status, and system readiness.",
      icon: LayoutGrid,
      tone: "text-teal-400",
      panel: <HealthMap />,
    },
    {
      id: "cloak",
      label: "Privacy Cockpit",
      description: "Privacy and context-boundary map.",
      icon: Lock,
      tone: "text-emerald-400",
      panel: <PrivacyCockpit />,
    },
    {
      id: "flywheel",
      label: "Flywheel",
      description: "Training corpus and feedback feed.",
      icon: RefreshCcw,
      tone: "text-amber-400",
      panel: <FlywheelFeed />,
    },
    {
      id: "execution",
      label: "Runtime",
      description:
        "Active hive sessions and local service status (Ollama, Docker) for this workspace.",
      icon: Cpu,
      tone: "text-rose-400",
      panel: <ExecutionWorkspace />,
    },
    {
      id: "mission",
      label: "Mission Control",
      description:
        "Determinex's own release readiness, gates, and next actions -- not your project's.",
      icon: GraduationCap,
      tone: "text-emerald-400",
      panel: <MissionControlPanel />,
    },
    {
      id: "roadmap",
      label: "Determinex Roadmap",
      description: "Determinex successor direction, exact blockers, and release locks.",
      icon: ShieldCheck,
      tone: "text-cyan-400",
      panel: <SuccessorRoadmapPanel />,
    },
    {
      id: "review",
      label: "Review",
      description: "Review and apply AI-proposed diffs.",
      icon: GitPullRequest,
      tone: "text-purple-400",
      panel: <DiffReviewPanel />,
    },
    {
      id: "merge",
      label: "Merge",
      description:
        "Resolve git merge conflicts: ours/theirs diff context plus an editable result pane.",
      icon: GitMerge,
      tone: "text-orange-400",
      panel: <MergeEditor workspacePath={explorerRoot} />,
    },
    {
      id: "repair",
      label: "Repair",
      description: "Diagnose this repo, review the patch plan, and manage human approval.",
      icon: GitPullRequest,
      tone: "text-cyan-400",
      panel: <RepairPanelShell workspacePath={explorerRoot} />,
    },
    {
      id: "agents",
      label: "Coding Agents",
      description:
        "Run Claude Code, Codex, Gemini CLI, or aider against this workspace, oracle-verified.",
      icon: Bot,
      tone: "text-violet-400",
      panel: <AgentsPanel workspacePath={explorerRoot} initialTask={guideAskTask} />,
    },
    {
      id: "agent-chat",
      label: "Agent Chat Room",
      description:
        "Claude Code, Codex, Gemini CLI, and a local model collaborate in one session, oracle-verified after every turn.",
      icon: MessageSquare,
      tone: "text-fuchsia-400",
      panel: <AgentChatPanel workspacePath={explorerRoot} />,
    },
    {
      id: "passport",
      label: "Passport",
      description:
        "Native CLI login status, connected service profiles, and real usage/spend tracking.",
      icon: BadgeCheck,
      tone: "text-amber-400",
      panel: <PassportPanel />,
    },
  ];
  const selectedAddon = addonItems.find((item) => item.id === activeAddon) ?? null;
  // The same registry entry, resolved for the panel host rather than the dock,
  // so a hosted surface renders its real panel with its real label and icon.
  const panelHostedAddon = addonItems.find((item) => item.id === panelAddon) ?? null;
  const runtimeAddonIds: WorkspaceAddon[] = [
    "learning",
    "repoclinic",
    "maintenancebay",
    "terminal",
    "editor",
    "build",
    "execution",
    "trace",
    "search",
    "findfiles",
    "health",
    "review",
    "merge",
    "repair",
    "agents",
    "agent-chat",
    "passport",
    // Determinex's own internal release-tracking, not a per-project feature --
    // dev-only, see isInternalBuild().
    ...(isInternalBuild() ? (["mission", "roadmap"] as WorkspaceAddon[]) : []),
  ];
  const runtimeAddonItems = runtimeAddonIds
    .map((id) => addonItems.find((item) => item.id === id))
    .filter((item): item is AddonItem => Boolean(item));
  // Status bar "Quick Attach" — reachable from every screen, not just Work/Explorer's
  // inline grids or the separate Tools hub. Found live 2026-07-19 (Ryan: "tools are
  // the only way to add on? ... this should be integrated into the screens").
  const quickAttachIds: WorkspaceAddon[] = [
    "terminal",
    "editor",
    "build",
    "trace",
    "search",
    "findfiles",
    "health",
    "cloak",
    "repair",
    "agents",
    "agent-chat",
    "passport",
    // Same fix as the WORK COCKPIT grid above -- these had no visible entry
    // point outside the command palette despite being real, lock-verified
    // surfaces (DETERMINEX_REACT_{LEARNING_STUDIO,REPO_CLINIC,
    // MAINTENANCE_BAY}_PANEL_LOCK_001).
    "learning",
    "repoclinic",
    "maintenancebay",
    // Same fix, round 2 (2026-07-23): a systematic id-by-id reachability
    // sweep (grep every addon id's total reference count across this file)
    // found 5 more with EXACTLY the same "command palette / AddonSwitcher
    // dropdown only" shape -- flywheel wasn't even in the dropdown's own
    // runtimeAddonIds list, execution/merge weren't even in the command
    // palette. Ryan: "im tired of issues that keep surfacing... go through
    // and find all instances of those patterns."
    "flywheel",
    "execution",
    "merge",
    // mission/roadmap (2026-07-27 correction): these are Determinex's OWN
    // release-gate/successor-blocker trackers, not a per-project feature --
    // reachable here only in internal/dev builds (isInternalBuild()), never
    // in what ships to a real end user. Kept textually in this array (not a
    // separate list) so test_addon_reachability_lock.py's static parse still
    // sees them as "wired into the one true reachability surface," which
    // they genuinely are -- just build-gated, not buried.
    ...(isInternalBuild() ? (["mission", "roadmap"] as WorkspaceAddon[]) : []),
    // "review" already has its own button on the Proof screen, but that's
    // an addon-specific exception to track, not a rule -- the whole point
    // of this array (per the "Status bar 'Quick Attach' -- reachable from
    // every screen" comment above) is to be the ONE unconditional answer to
    // "is this addon reachable," so every addonItems id belongs here with
    // no case-by-case carve-outs. See test_addon_reachability_lock.py.
    "review",
  ];
  const quickAttachItems: QuickAttachItem[] = quickAttachIds
    .map((id) => addonItems.find((item) => item.id === id))
    .filter((item): item is AddonItem => Boolean(item))
    .map((item) => ({ id: item.id, label: item.label, icon: item.icon }));
  // Drag the floating addon window by its header to any position on screen.
  const startAddonDockDrag = (e: React.PointerEvent) => {
    if (addonDockMaximized || !activeAddon) return;
    e.preventDefault();
    const startX = e.clientX;
    const startY = e.clientY;
    const startLeft = addonDockLiveRef.current.x;
    const startTop = addonDockLiveRef.current.y;
    const onMove = (ev: PointerEvent) => {
      const nx = Math.min(
        Math.max(4, startLeft + (ev.clientX - startX)),
        Math.max(4, window.innerWidth - 160)
      );
      const ny = Math.min(
        Math.max(4, startTop + (ev.clientY - startY)),
        Math.max(4, window.innerHeight - 60)
      );
      addonDockLiveRef.current = { ...addonDockLiveRef.current, x: nx, y: ny };
      setAddonDockX(nx);
      setAddonDockY(ny);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (activeAddon) commitAddonLayout(activeAddon);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // Resize the floating addon window from any edge or corner. `edges` marks
  // which sides are being dragged (a corner handle sets two of them at once).
  const startAddonDockResize =
    (edges: { n?: boolean; s?: boolean; e?: boolean; w?: boolean }) =>
    (ev0: React.PointerEvent) => {
      if (addonDockMaximized || !activeAddon) return;
      ev0.preventDefault();
      ev0.stopPropagation();
      const startX = ev0.clientX;
      const startY = ev0.clientY;
      const start = { ...addonDockLiveRef.current };
      const MIN_W = 320;
      const MIN_H = 220;
      const onMove = (ev: PointerEvent) => {
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;
        let { x, y, w, h } = start;
        if (edges.e) w = Math.min(Math.max(MIN_W, start.w + dx), window.innerWidth - start.x - 4);
        if (edges.s) h = Math.min(Math.max(MIN_H, start.h + dy), window.innerHeight - start.y - 40);
        if (edges.w) {
          const proposedW = Math.max(MIN_W, start.w - dx);
          x = start.x + (start.w - proposedW);
          w = proposedW;
        }
        if (edges.n) {
          const proposedH = Math.max(MIN_H, start.h - dy);
          y = start.y + (start.h - proposedH);
          h = proposedH;
        }
        addonDockLiveRef.current = { x, y, w, h };
        setAddonDockX(x);
        setAddonDockY(y);
        setAddonDockWidth(w);
        setAddonDockHeight(h);
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        if (activeAddon) commitAddonLayout(activeAddon);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    };

  useEffect(() => {
    window.__DETERMINEX_UI_SNAPSHOT__ = () => ({
      app: "Determinex",
      activeWorkspace: activeSidebar,
      activeAddon: addonDockOpen ? activeAddon : null,
      addonDockOpen,
      addonDockMaximized,
      selectedProjectName,
      workspacePath: explorerRoot,
      hiveSessionId,
      selectedModel,
      networkPolicy,
      panels: {
        projectLibrary: showProjectLibrary,
        settings: showSettings,
        help: helpModal !== null,
      },
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
      },
      timestamp: new Date().toISOString(),
    });

    return () => {
      delete window.__DETERMINEX_UI_SNAPSHOT__;
    };
  }, [
    activeAddon,
    activeSidebar,
    addonDockOpen,
    addonDockMaximized,
    explorerRoot,
    hiveSessionId,
    selectedModel,
    networkPolicy,
    selectedProjectName,
    helpModal,
    showProjectLibrary,
    showSettings,
  ]);

  // -------------------------------------------------------------
  // DESKTOP LUXURY VIEW
  // -------------------------------------------------------------
  const renderDesktopView = () => (
    <div
      className="relative z-10 flex h-full w-full overflow-hidden p-4 pb-9 font-sans"
      style={{
        background: `radial-gradient(circle at 16% 12%, ${themePack.colors.accentGlow}, transparent 28%), radial-gradient(circle at 88% 10%, ${themePack.colors.border}, transparent 24%), var(--determinex-bg)`,
        color: "var(--determinex-text)",
      }}
    >
      <SkinBackdrop />

      <div className="flex h-full w-full gap-4 relative z-10 pt-1">
        {/* The document's only heading. Visually hidden -- this shell is a workbench, not a
            titled page -- but a screen reader arriving here previously found no h1 and no
            landmarks of any kind, so there was nothing to orient against.

            Found 2026-08-02 by attaching to the RUNNING app over CDP and asking the DOM:
            nav/main/h1/header/aside all returned 0. Nothing caught it because
            playwright-tests/shell.spec.ts asserts every control has an accessible NAME --
            which passes -- and no test asserted the page has STRUCTURE. */}
        <h1 className="sr-only">Determinex — proof-governed code workbench</h1>
        {/* Activity Bar */}
        <div
          role="navigation"
          aria-label="Primary"
          className="flex h-full w-[72px] shrink-0 flex-col items-center border-r pt-6 pb-4 backdrop-blur-3xl z-50 transition-all duration-500 ease-out"
          style={{
            background:
              "linear-gradient(180deg, var(--determinex-panel-glass) 0%, rgba(0,0,0,0.4) 100%)",
            borderColor: "var(--determinex-border)",
            boxShadow: "10px 0 40px rgba(0,0,0,0.6)",
            borderTopRightRadius: "var(--determinex-radius)",
            borderBottomRightRadius: "var(--determinex-radius)",
          }}
        >
          {/* Logo (fixed top) */}
          <button
            type="button"
            onClick={openProjectHub}
            data-testid="rail-project-hub"
            title="Project Hub (Cmd/Ctrl+1)"
            aria-label="Project Hub"
            className={`mb-4 h-12 w-12 shrink-0 overflow-hidden border-2 transition-all duration-500 ${
              activeSidebar === "hub"
                ? "scale-110 shadow-[0_0_25px_var(--determinex-accent)]"
                : "hover:scale-105 hover:shadow-[0_0_15px_var(--determinex-accent-glow)]"
            }`}
            style={{
              borderColor: "var(--determinex-border)",
              borderRadius: "var(--determinex-radius)",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/determinex-icon.jpg"
              alt="Determinex"
              className="h-full w-full object-cover mix-blend-screen"
            />
          </button>

          {/* Nine groups, not eighteen icons.
              Ryan: "the side bar is really cluttered again, i want real
              breakdown and real organization not a whole list of things that
              do nothing. lets put like 9 icons on the left bar, lets take the
              subs to those nine in an expandable side window."

              Every one of the 34 surfaces now lives in exactly one group (see
              lib/surfaceGroups.ts; surfaceGroups.test.ts fails the build if a
              new panel has no home). The rail shows only the nine; clicking one
              opens SurfaceDrawer, which names each member, explains what it is
              and does, and lets YOU pick whether it lands in the panel or the
              dock. No scroll affordance is needed here any more -- nine icons
              fit any window, which is why the old chevron is gone. */}
          <div className="flex flex-1 flex-col items-center gap-2.5 w-full py-1">
            {SURFACE_GROUPS.map((group, index) => {
              const GroupIcon = GROUP_ICONS[group.icon] ?? Package;
              const isOpen = openGroupId === group.id;
              const holdsActive = group.members.some(
                (m) => m.id === activeSidebar || (addonDockOpen && m.id === activeAddon)
              );
              return (
                <button
                  key={group.id}
                  type="button"
                  data-testid={`rail-group-${group.id}`}
                  onClick={() => setOpenGroupId(isOpen ? null : group.id)}
                  title={`${group.label} — ${group.blurb}  (Ctrl+${index + 1})`}
                  aria-expanded={isOpen}
                  className={`flex w-full cursor-pointer flex-col items-center gap-1 transition-all ${
                    isOpen || holdsActive
                      ? "scale-110 text-[var(--determinex-accent)] drop-shadow-[0_0_8px_var(--determinex-accent-glow)]"
                      : "text-gray-500 hover:text-gray-200"
                  }`}
                >
                  <GroupIcon size={19} strokeWidth={1.5} />
                  <span className="text-eyebrow font-bold uppercase leading-none">
                    {group.label}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Fixed bottom. gap-2.5 to match the scroller above and hand the
              reclaimed vertical space back to it -- this section never scrolls,
              so every pixel it saves is a pixel the rail can actually use. */}
          <div className="flex flex-col items-center gap-2.5 w-full pb-2 shrink-0">
            <div className="w-8 h-px bg-[var(--dtx-code-border)] flex-shrink-0" />
            <span className="text-eyebrow uppercase tracking-[0.15em] text-gray-600 font-bold -mb-2">
              Settings
            </span>
            {isExecutingPack && (
              <div
                onClick={executeAbort}
                className="cursor-pointer transition-all flex flex-col items-center gap-1 text-red-500 hover:text-red-400 animate-pulse drop-shadow-[0_0_8px_rgba(239,68,68,0.8)]"
                title="Abort Orchestration"
              >
                <XOctagon size={20} strokeWidth={1.5} />
                <span className="text-eyebrow uppercase font-bold tracking-normal leading-none">
                  Abort
                </span>
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                // Always shows the Privacy Cockpit now -- it used to only open
                // when switching specifically *to* "cloaked", so 2 of the 3
                // policy states produced zero visible feedback beyond a 7px
                // label change in the corner. Found live 2026-07-19 (Ryan:
                // "cloak does nothing").
                setNetworkPolicy(nextPrivacyPolicy);
                handleAddonLaunch("cloak");
              }}
              data-testid="rail-cloak-policy-toggle"
              title={`${networkPolicyCopy.label}: ${networkPolicyCopy.summary}. Click to switch to ${NETWORK_POLICY_COPY[nextPrivacyPolicy].shortLabel}.`}
              className={`flex flex-col items-center gap-1 transition-all ${
                networkPolicy === "offline"
                  ? "text-amber-400 hover:text-emerald-300"
                  : networkPolicy === "cloaked"
                    ? "text-emerald-400 hover:text-amber-300"
                    : "text-cyan-400 hover:text-emerald-300"
              }`}
            >
              <Lock size={20} strokeWidth={1.5} />
              <span className="text-eyebrow font-bold uppercase leading-none tracking-normal">
                {networkPolicy === "offline" ? "Local" : "Cloak"}
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                setSettingsTab("skin");
                setShowSettings(true);
              }}
              title={`Skin: ${themePack.label ?? "Switch skin"}`}
              aria-label={`Switch skin (current: ${themePack.label ?? "default"})`}
              className="group flex min-w-6 flex-col items-center gap-1"
            >
              <span
                className="h-4 w-4 rounded-full border-2 transition-all duration-300 group-hover:scale-125"
                style={{
                  background: themePack.colors.accent,
                  borderColor: themePack.colors.border,
                  boxShadow: `0 0 8px ${themePack.colors.accentGlow}`,
                }}
              />
              <span className="text-eyebrow font-bold uppercase leading-none tracking-normal text-gray-600 group-hover:text-gray-400">
                Skin
              </span>
            </button>
            <div
              data-testid="rail-guide"
              onClick={() => setShowTeacher(true)}
              className="cursor-pointer flex flex-col items-center gap-1 text-gray-600 hover:text-[var(--determinex-accent)] transition-colors"
              // Carries the context line that the removed floating advisor pill
              // used to display, so the per-screen hint survives on hover.
              title={`Open Guide — ${getGuideStepFor(activeSidebar, addonDockOpen ? activeAddon : null).subtitle}`}
            >
              <GraduationCap size={20} strokeWidth={1.5} />
              <span className="text-eyebrow uppercase font-bold tracking-normal leading-none">
                Guide
              </span>
            </div>
            {bootTier && (
              <div
                className="w-full px-1 py-1 rounded-lg border border-cyan-500/20 bg-cyan-950/20 flex flex-col items-center gap-0.5"
                title={bootTier}
              >
                <span className="text-eyebrow font-mono text-cyan-400/50 uppercase leading-none">
                  {bootTier.match(/engineer=([^\s|]+)/)?.[1]?.split(":")[0] ?? "OK"}
                </span>
              </div>
            )}
          </div>
        </div>
        {/* Everything that is not the rail is the main content region. `display:
            contents` makes this wrapper layout-neutral -- the flex row still lays out
            its children exactly as before -- while giving assistive technology the
            landmark it needs. The page previously rendered NO landmarks at all (found
            2026-08-02 by driving the running app over CDP), so a screen-reader user
            could not skip the navigation or jump to content. */}
        <main className="contents">

        {/* The nine-group drawer. Sits beside the rail, in-flow -- not a portal
            and not a floating overlay, so it can never cover another surface
            the way the advisor pill and the multichat popout did. */}
        {openGroupId && (
          <SurfaceDrawer
            group={SURFACE_GROUPS.find((g) => g.id === openGroupId)!}
            activeSurfaceId={addonDockOpen ? activeAddon : activeSidebar}
            showInternal={isInternalBuild()}
            onOpen={openSurface}
            onClose={() => setOpenGroupId(null)}
          />
        )}

        {/* Zone 1: Left Brain -- hidden whenever ANY addon is attached (not just
            while maximized). Used to key off !addonDockMaximized, but that's now
            per-tool remembered state -- switching from a tool that remembers
            "maximized" to one that remembers "restored, dragged to a corner"
            made this panel flicker in and out with no direct user action
            explaining why. Ryan: "which magically just reappeared?" A floating
            window now overlays this area regardless (z-40, absolutely
            positioned), so keeping Zone 1 "visible" behind/around a small
            floating tool never helped anyway -- just added clutter. Simple,
            predictable rule instead: attaching a tool hides this panel; closing
            the tool brings it back. */}
        <AnimatePresence mode="wait">
          {(panelAddon ||
            (activeSidebar !== "none" &&
              activeSidebar !== "hub" &&
              activeSidebar !== "extensions" &&
              !addonDockOpen)) && (
            <motion.div
              key={panelAddon ?? activeSidebar}
              initial={{ opacity: 0, x: -20, scale: 0.98 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: -20, scale: 0.98 }}
              transition={{ type: "spring", stiffness: 300, damping: 30, mass: 0.75 }}
              // willChange -- see the matching note on Zone 2's motion.div below;
              // same stale-compositing symptom reproduced on this panel too (Proof's
              // narrow left card mounted blank until a resize forced a repaint).
              // Deliberately NOT `transform-gpu`: that Tailwind class sets `transform`,
              // which framer-motion's own inline style (driving x/scale here) silently
              // overrides every frame.
              className="relative flex h-full shrink-0 flex-col border backdrop-blur-2xl"
              style={{
                width: zone1.width,
                background: "var(--determinex-panel-glass)",
                borderColor: "var(--determinex-border)",
                borderRadius: "var(--determinex-radius)",
                boxShadow: "0 0 30px rgba(0,0,0,0.6)",
                willChange: "transform, opacity",
              }}
            >
              {/* Resize handle. The panel is `relative` so this rides its right
                    edge; the hit area is wider than the visible line so it is
                    actually grabbable. Persisted per surface on pointer-up. */}
              <div
                onPointerDown={zone1.startResize}
                data-testid="zone1-resize"
                title="Drag to resize — width is remembered per panel"
                className={`absolute -right-1 top-0 z-30 h-full w-2 cursor-ew-resize transition-colors ${
                  zone1.resizing
                    ? "bg-[var(--determinex-accent)]/40"
                    : "hover:bg-[var(--determinex-accent)]/25"
                }`}
              />
              <div className="px-5 py-3 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]/50 rounded-t-2xl flex-shrink-0 flex items-center justify-between">
                <span className="text-meta uppercase text-gray-300 font-black tracking-widest flex items-center gap-2 drop-shadow-md">
                  {/* A panel-hosted surface names ITSELF. Without this the
                        header kept showing whatever left workspace happened to
                        be active -- so opening Agent Chat Room into the panel
                        produced a box labelled "Work" containing a chat room. */}
                  {panelAddon && panelHostedAddon && (
                    <>
                      <panelHostedAddon.icon size={13} className={panelHostedAddon.tone} />{" "}
                      {panelHostedAddon.label}
                    </>
                  )}
                  {!panelAddon && activeSidebar === "pipeline" && (
                    <>
                      <Activity size={13} className="text-amber-500" /> Build Pipeline
                    </>
                  )}
                  {activeSidebar === "explorer" && (
                    <>
                      <Folder size={13} className="text-purple-400" /> Workspace
                    </>
                  )}
                  {activeSidebar === "git" && (
                    <>
                      <GitPullRequest size={13} className="text-green-400" /> Source
                    </>
                  )}
                  {activeSidebar === "hive" && (
                    <>
                      <Zap size={13} className="text-emerald-400" /> Work
                    </>
                  )}
                  {activeSidebar === "benchmark" && (
                    <>
                      <Database size={13} className="text-orange-400" /> Brain
                    </>
                  )}
                  {activeSidebar === "proof" && (
                    <>
                      <Eye size={13} className="text-cyan-400" /> Proof
                    </>
                  )}
                  {activeSidebar === "audit" && (
                    <>
                      <ShieldCheck size={13} className="text-red-400" /> Audit
                    </>
                  )}
                </span>
                <div className="flex items-center gap-2">
                  {/* Moving a panel-hosted surface to the dock without going
                        back through the drawer -- the destination is meant to be
                        the user's, changeable, not a one-way trip. */}
                  {panelAddon && (
                    <button
                      onClick={() => {
                        const addon = panelAddon;
                        setPanelAddon(null);
                        handleAddonLaunch(addon);
                      }}
                      data-testid="zone1-move-to-dock"
                      aria-label="Move this panel to the floating dock"
                      className="flex h-6 w-6 items-center justify-center rounded text-gray-600 transition-colors hover:bg-white/5 hover:text-gray-300"
                      title="Move to the floating dock"
                    >
                      <PanelRight size={13} />
                    </button>
                  )}
                  <button
                    onClick={() => {
                      if (panelAddon) {
                        setPanelAddon(null);
                        // Give the panel back to whatever workspace was there
                        // before, rather than leaving an empty column.
                        setActiveSidebar(
                          lastWorkbenchSidebar === "none" || lastWorkbenchSidebar === "extensions"
                            ? "hub"
                            : lastWorkbenchSidebar
                        );
                        return;
                      }
                      setActiveSidebar("none");
                      setPreviewedPath(null);
                    }}
                    data-testid="zone1-close"
                    aria-label="Close panel"
                    className="flex h-6 w-6 items-center justify-center rounded text-gray-600 transition-colors hover:bg-white/5 hover:text-gray-300"
                    title="Close panel"
                  >
                    <span className="text-title leading-none">✕</span>
                  </button>
                </div>
              </div>

              {/* This whole panel (Zone 1) already only mounts when !addonDockOpen
                (see the AnimatePresence condition above) -- checking
                addonDockMaximized here too was dead/redundant logic from
                before that rule existed, and became actively harmful once
                addonDockMaximized started defaulting to true: it permanently
                hid this panel's entire body (including ConceptLab's textarea)
                from first load, even with no addon ever opened. Ryan: "the
                type in area is now gone on the work?" */}
              <div className="flex-1 overflow-y-auto no-scrollbar relative flex flex-col">
                {/* min-h-0 so a tall surface scrolls inside the panel instead of
                      pushing its own header off the top. */}
                {panelAddon && panelHostedAddon && (
                  <div className="flex min-h-0 flex-1 flex-col" data-testid="zone1-hosted-addon">
                    {panelHostedAddon.panel}
                  </div>
                )}
                {!panelAddon && activeSidebar === "pipeline" && (
                  <PipelineDashboard
                    showWarRoom={showWarRoom}
                    setShowWarRoom={setShowWarRoom}
                    lastPrompt={lastPrompt}
                    sessionId={hiveSessionId}
                  />
                )}

                {activeSidebar === "explorer" && (
                  <div className="flex flex-col h-full">
                    <div className="p-4 bg-purple-950/20 border-b border-[var(--dtx-code-border)] relative flex-shrink-0 flex justify-between items-start">
                      <div>
                        <h3 className="text-meta uppercase font-bold text-purple-400 mb-2 tracking-widest flex items-center gap-2">
                          Project Map
                        </h3>
                        <p className="text-label text-purple-300/60 leading-relaxed font-mono">
                          Bound files, source state, scan actions, and runs for this project.
                        </p>
                      </div>
                      <button
                        onClick={() => {
                          getFileSystemTree(explorerRoot)
                            .then((res) => {
                              if (res && res.tree) setFileTree(res.tree);
                            })
                            .catch((err) => showError(`Could not load file system: ${err}`));
                        }}
                        className="p-1.5 border border-purple-500/20 bg-purple-900/20 hover:bg-purple-900/60 text-purple-400 rounded-lg transition-colors cursor-pointer"
                        title="Refresh File System"
                      >
                        <RefreshCw size={14} />
                      </button>
                    </div>
                    <div className="grid grid-cols-4 gap-1.5 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg-deep)] p-2">
                      {[
                        ["overview", "Overview", Gauge],
                        ["files", "Files", Files],
                        ["source", "Source", GitPullRequest],
                        ["runs", "Runs", Activity],
                      ].map(([id, label, Icon]) => {
                        const TabIcon = Icon as typeof Gauge;
                        return (
                          <button
                            key={id as string}
                            type="button"
                            data-testid={`workspace-tab-${id as string}`}
                            onClick={() => setWorkspaceView(id as typeof workspaceView)}
                            className={`flex items-center justify-center gap-1 rounded-md border px-1.5 py-1.5 text-eyebrow font-black uppercase tracking-widest transition ${
                              workspaceView === id
                                ? "border-purple-400/50 bg-purple-500/15 text-purple-200"
                                : "border-white/10 bg-white/[0.025] text-gray-600 hover:text-gray-300"
                            }`}
                          >
                            <TabIcon size={10} /> {label as string}
                          </button>
                        );
                      })}
                    </div>
                    <div className="flex-1 overflow-y-auto w-full p-4 flex flex-col h-full bg-[var(--dtx-code-bg-deep)]">
                      {workspaceView === "overview" && (
                        <div className="space-y-3">
                          <div className="rounded-lg border border-purple-500/20 bg-purple-950/20 p-3">
                            <div className="text-meta font-black uppercase tracking-widest text-purple-300">
                              {selectedProjectName}
                            </div>
                            <div className="mt-2 font-mono text-label text-gray-500">
                              {displayPath(explorerRoot) || "No workspace path bound yet."}
                            </div>
                          </div>
                          {[
                            [
                              "Inspect files",
                              "Browse the project tree and generated output files.",
                              "files",
                            ],
                            [
                              "Review source",
                              "See Git remote, branch, dirty state, and staged intent.",
                              "source",
                            ],
                            [
                              "Check runs",
                              "Open a run log or jump to the Work tab to start a session.",
                              "runs",
                            ],
                          ].map(([title, text, target]) => (
                            <button
                              key={title}
                              type="button"
                              data-testid={`workspace-action-${target as string}`}
                              onClick={() => setWorkspaceView(target as typeof workspaceView)}
                              className="group w-full rounded-lg border border-white/10 bg-white/[0.03] p-3 text-left transition hover:border-purple-400/50 hover:bg-purple-500/10"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-meta font-black uppercase tracking-widest text-gray-200">
                                  {title}
                                </span>
                                <ChevronRight
                                  size={12}
                                  className="text-gray-600 group-hover:text-purple-300"
                                />
                              </div>
                              <p className="mt-1 text-label leading-relaxed text-gray-500">
                                {text}
                              </p>
                            </button>
                          ))}
                        </div>
                      )}

                      {workspaceView === "files" && (
                        <>
                          {explorerRoot !== "" && (
                            <div
                              onClick={() => setExplorerRoot("")}
                              className="flex items-center gap-1 text-label font-bold text-cyan-400 hover:bg-[var(--dtx-code-border)] p-1.5 mb-2 cursor-pointer bg-cyan-950/20 border border-cyan-500/20 rounded"
                            >
                              <span className="mr-1">&lt; Back</span>
                              <span className="text-gray-400 capitalize opacity-70">to Root</span>
                            </div>
                          )}
                          <div
                            onClick={() => setExplorerRoot("")}
                            className="flex items-center gap-1 text-label font-bold text-gray-300 hover:bg-[var(--dtx-code-border)] p-1 mb-1 cursor-pointer"
                          >
                            <ChevronRight size={14} className="rotate-90" />{" "}
                            {explorerRoot.split(/[\\/]/).pop() || "Explorer"}
                          </div>
                          {fileTree.length > 0 ? (
                            <div className="flex flex-col gap-1">
                              {fileTree.map((node, i) => (
                                <FileSystemNode
                                  key={i}
                                  node={node}
                                  activeContexts={activeContexts}
                                  toggleContext={toggleContext}
                                  setExplorerRoot={setExplorerRoot}
                                  handleOpenFile={handleOpenFile}
                                  gitStatusMap={explorerGitStatusMap}
                                  onFsError={(msg) => showError(msg)}
                                />
                              ))}
                            </div>
                          ) : (
                            <div className="text-label text-gray-600 font-mono italic">
                              {isTauri()
                                ? "Scanning system..."
                                : "Browser mode cannot scan the real file tree."}
                            </div>
                          )}
                          {sandboxFiles.length > 0 && (
                            <div className="mt-4 pt-4 border-t border-[var(--dtx-code-border)]">
                              <div className="text-eyebrow uppercase font-bold text-purple-400 tracking-widest mb-2 flex items-center gap-1.5">
                                <Code2 size={9} /> Workspace Output
                              </div>
                              {sandboxFiles.map((f, i) => (
                                <div
                                  key={i}
                                  onClick={() => {
                                    setGeneratedFile(f.name);
                                    setActiveSidebar("none");
                                  }}
                                  className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/5 cursor-pointer group"
                                >
                                  <span className="text-label font-mono text-gray-400 group-hover:text-gray-200 truncate">
                                    {f.name}
                                  </span>
                                  <span className="text-meta font-mono text-gray-700 shrink-0 ml-2">
                                    {f.modified}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </>
                      )}

                      {workspaceView === "source" && (
                        <div className="space-y-3">
                          {[
                            ["Provider", "GitHub or local Git"],
                            ["Remote", "Connected remote appears here after read-only scan."],
                            ["Branch", "Current branch and ahead/behind belong here."],
                            ["Mutation", "Source apply stays gated until verified approval."],
                          ].map(([label, text]) => (
                            <div
                              key={label}
                              className="rounded-lg border border-white/10 bg-white/[0.03] p-3"
                            >
                              <div className="text-eyebrow font-black uppercase tracking-widest text-green-300">
                                {label}
                              </div>
                              <p className="mt-1 text-label leading-relaxed text-gray-500">
                                {text}
                              </p>
                            </div>
                          ))}
                          <button
                            type="button"
                            data-testid="workspace-source-view-runs"
                            onClick={() => setWorkspaceView("runs")}
                            className="w-full rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-meta font-black uppercase tracking-widest text-green-300"
                          >
                            View runs for this source
                          </button>
                        </div>
                      )}

                      {workspaceView === "runs" && (
                        <div className="flex flex-col items-center justify-center h-full gap-3 text-center py-12">
                          <Activity size={24} className="text-gray-700" />
                          <p className="text-label font-mono text-gray-600 leading-relaxed">
                            Build run history lives in{" "}
                            <strong className="text-amber-400/70">Work</strong>.<br />
                            Open a hive session to see live output.
                          </p>
                          <button
                            type="button"
                            onClick={() => setActiveSidebar("hive")}
                            className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-950/20 px-4 py-2 text-meta font-black uppercase tracking-widest text-emerald-400 transition-all hover:bg-emerald-900/30"
                          >
                            Go to Work
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeSidebar === "git" && <GitPanel workspacePath={explorerRoot} />}

                {activeSidebar === "audit" && <ProjectAuditPanel workspacePath={explorerRoot} />}

                {activeSidebar === "benchmark" && <BenchmarkRunner />}

                {activeSidebar === "proof" && (
                  <div className="flex flex-col gap-3 p-4">
                    <div
                      className={`rounded-xl border p-3 ${
                        agentStatus.verdict && agentStatus.accepted
                          ? "border-emerald-500/25 bg-emerald-950/20"
                          : agentStatus.verdict && !agentStatus.accepted
                            ? "border-red-500/25 bg-red-950/20"
                            : "border-white/8 bg-white/[0.03]"
                      }`}
                    >
                      <div className="text-eyebrow uppercase font-bold tracking-widest text-gray-600 mb-1.5">
                        Last Verdict
                      </div>
                      <div
                        className={`text-xl font-black ${
                          agentStatus.verdict && agentStatus.accepted
                            ? "text-emerald-400"
                            : agentStatus.verdict && !agentStatus.accepted
                              ? "text-red-400"
                              : "text-gray-700"
                        }`}
                      >
                        {agentStatus.verdict ?? "No runs yet"}
                      </div>
                      {agentStatus.confidence !== null && agentStatus.confidence !== undefined && (
                        <div className="text-label text-gray-500 mt-0.5">
                          {(agentStatus.confidence * 100).toFixed(0)}% confidence ·{" "}
                          {retryCount > 0 ? `${retryCount} retries` : "first attempt"}
                        </div>
                      )}
                    </div>

                    {generatedFile && (
                      <div className="rounded-xl border border-purple-500/20 bg-purple-950/20 p-3">
                        <div className="text-eyebrow uppercase font-bold tracking-widest text-purple-400 mb-1.5">
                          Last File
                        </div>
                        <div className="text-label font-mono text-gray-300 break-all leading-relaxed">
                          {generatedFile}
                        </div>
                      </div>
                    )}

                    {threadHistory.length > 0 && (
                      <div>
                        <div className="text-eyebrow uppercase font-bold tracking-widest text-gray-600 mb-2 mt-1">
                          Session History
                        </div>
                        <div className="flex flex-col gap-1.5">
                          {threadHistory.slice(0, 8).map((t) => (
                            <div
                              key={t.id}
                              onClick={() => {
                                setActiveThreadId(t.id);
                                setActiveSidebar("hive");
                              }}
                              className={`rounded-lg border p-2.5 cursor-pointer transition-colors ${
                                activeThreadId === t.id
                                  ? "border-cyan-500/30 bg-cyan-950/20 text-cyan-300"
                                  : "border-white/5 bg-white/[0.02] text-gray-500 hover:border-white/10 hover:text-gray-300"
                              }`}
                            >
                              <div className="text-label font-bold truncate">
                                {t.title || "Untitled session"}
                              </div>
                              <div className="flex items-center justify-between mt-0.5">
                                <span className="text-meta text-gray-700">{t.updated}</span>
                                <span className="text-meta text-gray-600">open →</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {threadHistory.length === 0 && !agentStatus.verdict && (
                      <div className="text-center py-8">
                        <Eye size={24} className="text-gray-700 mx-auto mb-3" />
                        <p className="text-label text-gray-600 font-mono leading-relaxed">
                          Run a hive session to see proof, logs, diffs, and build output.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {activeSidebar === "hive" && (
                  // workReadiness is wired below as of 2026-07-30. ConceptLab has always gated
                  // spec generation on specGenerationBlockMessage(workReadiness), but the prop was
                  // never passed and that helper returns null for undefined -- so the branch was
                  // dead. The Work tab would generate a spec and launch a hive session on an
                  // install whose Builder and Monitor roles resolve to absent models, with no
                  // warning at all; "Missing local model coverage for N roles" could never appear.
                  <ConceptLab
                    selectedProjectName={selectedProjectName}
                    projectPath={displayPath(explorerRoot)}
                    selectedModel={selectedModel}
                    // A Quick Verify run is a real oracle-verified result, so record it as
                    // evidence. The Proof panel reads matrixLogs and agentStatus.verdict and
                    // nothing else; before this, only the hive path (handleInject) wrote
                    // them, so Proof showed "No runs yet / No evidence yet" straight after a
                    // successful verified build.
                    onVerified={({ solved, checks, proof, idea }) => {
                      const verdict = solved
                        ? `VERIFIED — ${checks ?? "?"} oracle checks passed`
                        : "REFUSED — no sound oracle could be synthesised";
                      setMatrixLogs((prev) => [
                        ...prev,
                        `[QUICK VERIFY] ${idea.slice(0, 90)}`,
                        `[ORACLE] ${verdict}`,
                        ...(proof ? [`[PROOF] ${proof.slice(0, 200)}`] : []),
                      ]);
                      setAgentStatus((prev) => ({
                        ...prev,
                        currentAgent: null,
                        isExecuting: false,
                        verdict,
                        accepted: solved,
                        confidence: null,
                        error: null,
                      }));
                    }}
                    onOpenProjectLibrary={() => setShowProjectLibrary(true)}
                    onSpecChange={(s) => {
                      setHiveSpec(s);
                      setHiveProjectName(s.match(/^#\s+(.+)/m)?.[1]?.trim() ?? "");
                    }}
                    onSessionLaunched={(id) => {
                      setHiveSessionId(id);
                      setHiveAutoRun(true);
                      setHiveSpec("");
                      setActiveSidebar("none");
                      setIsOracleConsulting(false);
                    }}
                    onPathPreview={(path) => {
                      setPreviewedPath(path);
                      if (!path) setConfirmedPath(null);
                    }}
                    confirmedPath={confirmedPath}
                    onAnsweredCountChange={setOracleAnsweredCount}
                    onConsultingChange={setIsOracleConsulting}
                    externalIdea={externalIdea}
                    onColorHintsChange={setColorHints}
                    workReadiness={workReadiness}
                    onOpenModelSettings={() => {
                      setSettingsTab("roles");
                      setShowSettings(true);
                    }}
                    modelPicker={
                      <WorkModelPicker
                        selectedModel={selectedModel}
                        keyStatus={keyStatus}
                        onChange={setSelectedModel}
                        onOpenSettings={() => {
                          setSettingsTab("roles");
                          setShowSettings(true);
                        }}
                      />
                    }
                  />
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Zone 2: Center Arena */}
        <AnimatePresence mode="wait">
          {activeSidebar !== "none" && (
            <motion.div
              key={
                activeSidebar +
                "-" +
                (hiveSessionId || "") +
                "-" +
                isOracleConsulting +
                "-" +
                (previewedPath ? "prev" : "") +
                (confirmedPath ? "conf" : "") +
                (hiveSpec ? "spec" : "")
              }
              initial={{ opacity: 0, scale: 0.98, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, y: -10 }}
              transition={{ type: "spring", stiffness: 260, damping: 28, mass: 0.85 }}
              // Without a GPU-layer hint, Proof and Brain would mount fully blank --
              // just the SkinBackdrop canvas showing through -- until something else
              // (any window resize) forced a repaint; the real content was always
              // there, never painted. Reproduced live 2026-07-19, isolated with a
              // plain OS window resize (no devtools) as the only variable: same
              // content appeared instantly once the browser was forced to
              // recomposite. Classic Chromium/WebView2 stale-compositing bug: an
              // element with backdrop-filter (backdrop-blur-3xl) that remounts via
              // animation (AnimatePresence's key changes on every tab switch) sits
              // above a canvas using mixBlendMode (SkinBackdrop) and sometimes never
              // gets its first real paint. First attempt used the `transform-gpu`
              // Tailwind class, but framer-motion sets its own inline `transform`
              // for x/y/scale on every frame, which silently overrides a
              // class-based transform -- content stayed a barely-visible ghost.
              // `willChange` is a separate CSS property framer-motion never
              // touches, so it survives.
              className="relative flex h-full flex-1 flex-col overflow-hidden border backdrop-blur-3xl group"
              style={{
                background: "var(--determinex-panel-glass)",
                borderColor: "var(--determinex-border)",
                borderRadius: "var(--determinex-radius)",
                boxShadow: "var(--determinex-shell-shadow)",
                willChange: "transform, opacity",
              }}
            >
              <button
                onClick={() => setActiveSidebar("none")}
                className="absolute top-4 right-4 z-[100] h-8 w-8 flex items-center justify-center rounded-full bg-black/20 border border-white/10 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/40 hover:text-white"
                title="Close panel to view background"
                aria-label="Close panel to view background"
              >
                <X size={16} />
              </button>

              <div
                data-testid="workbench-primary-surface"
                className="relative min-h-0 flex-1 overflow-hidden"
              >
                {hiveSessionId ? (
                  <HiveBuildLoop
                    sessionId={hiveSessionId}
                    projectName={hiveProjectName}
                    autoRun={hiveAutoRun}
                    autoRetry={hiveAutoRetry}
                    onBack={() => {
                      setHiveSessionId(null);
                      setHiveProjectName("");
                      setHiveAutoRun(false);
                      setHiveAutoRetry(false);
                      setActiveSidebar("hub");
                    }}
                    onComplete={(result: HiveBuildCompletionResult) => {
                      // Distinct verdict vocabulary from the MoA/Observer audit path
                      // (CLEAN/HALLUCINATION/PARTIAL) -- this is a DIFFERENT, ground-truth
                      // compiler-oracle verdict, not an LLM audit. Never conflate the two.
                      const accepted = result.phase === "done";
                      setAgentStatus({
                        currentAgent: null,
                        isExecuting: false,
                        verdict: accepted ? "COMPILER_VERIFIED_PASS" : "COMPILER_VERIFIED_FAIL",
                        confidence: accepted ? 1 : 0,
                        accepted,
                        error: accepted
                          ? null
                          : {
                              stage: "hive_build",
                              message: `${result.failedCount} of ${result.stepCount} step(s) failed compiler verification`,
                            },
                      });
                      setMatrixLogs((prev) => [
                        ...prev,
                        accepted
                          ? `[HIVE] PASS Build session ${result.sessionId} — all ${result.stepCount} step(s) compiler-verified.`
                          : `[HIVE] FAIL Build session ${result.sessionId} — ${result.failedCount} of ${result.stepCount} step(s) failed compiler verification.`,
                      ]);
                    }}
                  />
                ) : activeSidebar === "hive" && isOracleConsulting ? (
                  <OracleArena />
                ) : activeSidebar === "hive" && previewedPath ? (
                  <PathDetailPanel
                    path={previewedPath}
                    onChoose={(path) => {
                      setConfirmedPath(path);
                      setPreviewedPath(null);
                    }}
                    onBack={() => setPreviewedPath(null)}
                    colorOverride={colorHints[0]}
                  />
                ) : activeSidebar === "hive" && confirmedPath && !hiveSpec ? (
                  <DiscoveryProgressView
                    path={confirmedPath}
                    answeredCount={oracleAnsweredCount}
                    colorOverride={colorHints[0]}
                  />
                ) : activeSidebar === "hive" && hiveSpec ? (
                  <SpecBreakdownView spec={hiveSpec} path={confirmedPath} />
                ) : activeSidebar === "hive" ? (
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <div className="shrink-0 border-b border-white/10 p-6">
                      <div className="mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-emerald-300">
                        <Zap size={13} /> Work Cockpit
                      </div>
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div>
                          <h2
                            className="text-3xl font-black leading-tight text-[var(--determinex-text)]"
                            style={{ fontFamily: "var(--determinex-font-display)" }}
                          >
                            Ask. Plan. Build. Prove.
                          </h2>
                          <p className="mt-2 max-w-3xl text-body leading-relaxed text-[var(--determinex-muted)]">
                            The left panel captures the request. This screen shows what will happen
                            next, which tools are attached, and where proof will appear.
                          </p>
                        </div>
                        <div className="rounded-xl border border-white/10 bg-black/35 px-4 py-3 text-right">
                          <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                            Workspace
                          </div>
                          <div className="mt-1 max-w-[260px] truncate text-label font-bold text-gray-200">
                            {selectedProjectName}
                          </div>
                          <div className="mt-0.5 max-w-[260px] truncate font-mono text-meta text-gray-600">
                            {displayPath(explorerRoot) || "No workspace path bound."}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto p-6 pb-28 no-scrollbar">
                      {/* Release-readiness banner -- the one piece of real value Home/
                    Command Center had (a contextual "what should I do next")
                    that didn't already duplicate the StatusBar or Audit screen.
                    Home itself was cut (2026-07-19): its Model Route and Audit
                    Score readouts were exact duplicates living elsewhere; this
                    banner is what's left once the redundancy is gone, folded
                    into the screen that's now the app's landing point. */}
                      <div
                        className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border p-4 ${
                          explorerGitFiles.length > 0
                            ? "border-amber-500/25 bg-amber-950/10"
                            : "border-emerald-500/20 bg-emerald-950/10"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          {explorerGitUnavailable ? (
                            <AlertTriangle size={18} className="shrink-0 text-amber-400" />
                          ) : explorerGitFiles.length > 0 ? (
                            <FileCode size={18} className="shrink-0 text-amber-400" />
                          ) : (
                            <Check size={18} className="shrink-0 text-emerald-400" />
                          )}
                          <div>
                            <div className="text-label font-black text-white">
                              {explorerGitUnavailable
                                ? "Git status unavailable"
                                : explorerGitFiles.length > 0
                                  ? `${explorerGitFiles.length} uncommitted change${explorerGitFiles.length === 1 ? "" : "s"}`
                                  : "Working tree clean"}
                            </div>
                            <div className="font-mono text-meta text-gray-500">
                              {explorerGitUnavailable
                                ? "could not read this repository"
                                : gitBranch || "no repo"}
                              {explorerGitMeta.upstream ? ` · ${explorerGitMeta.upstream}` : ""}
                            </div>
                          </div>
                        </div>
                        {explorerGitFiles.length > 0 ? (
                          <button
                            type="button"
                            onClick={() => setActiveSidebar("git")}
                            className="rounded-lg border border-amber-400/30 bg-amber-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-amber-300 transition hover:bg-amber-900/30"
                          >
                            Open Source Control
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setActiveSidebar("audit")}
                            className="rounded-lg border border-emerald-400/25 bg-emerald-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-emerald-300 transition hover:bg-emerald-900/30"
                          >
                            Run Release Audit
                          </button>
                        )}
                      </div>

                      {/* The cockpit split. Was a hard-coded
                          `xl:grid-cols-[1.1fr_0.9fr]`, so the only way to change
                          it was to edit this file -- the last genuinely locked box
                          in the shell. Now a drag handle with a persisted ratio.
                          Ratio, not pixels: this grid sits inside Zone 2, which is
                          itself `flex-1` and grows as Zone 1 shrinks, so a stored
                          width would stop matching the moment either changed. */}
                      <div
                        ref={cockpitGridRef}
                        className="grid gap-4"
                        style={{
                          gridTemplateColumns: `minmax(0, ${cockpitSplit.ratio}fr) 6px minmax(0, ${
                            1 - cockpitSplit.ratio
                          }fr)`,
                        }}
                      >
                        <section className="rounded-2xl border border-white/8 bg-black/30 p-5">
                          {/* min-w-0 on the growing side, shrink-0 on the badge. Without
                              both, a narrow window squeezed the badge until "No verdict"
                              rendered on top of "Attach What You Need" -- the collision
                              visible in the 2026-08-03 screenshot. flex children default to
                              min-width:auto, so the left block refuses to shrink and pushes
                              the badge out of its own box instead. */}
                          <div className="mb-4 flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                                Run State
                              </div>
                              <div className="mt-1 truncate text-2xl font-black text-white">
                                {hiveSessionId ? "Running" : "Ready"}
                              </div>
                            </div>
                            <span className="shrink-0 whitespace-nowrap rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-eyebrow font-black uppercase tracking-widest text-gray-500">
                              {agentStatus.verdict ?? "No verdict"}
                            </span>
                          </div>

                          {/* ONE next action, in plain words. Three surfaces can start work --
                              this cockpit, the Work panel on the left, and the Agent Chat Room
                              on the AGENTS rail -- and until now nothing said which to use, so a
                              new operator faced two panels that both looked like the beginning,
                              two primary buttons with no stated difference between them, and
                              fourteen attachable tools. Naming a single next step is the whole
                              fix; the alternative is a tour, and a tour is what you write when
                              the screen will not say it itself. */}
                          <div
                            data-testid="cockpit-next-action"
                            className="mb-4 rounded-xl border border-emerald-400/25 bg-emerald-950/15 px-4 py-3"
                          >
                            <div className="mb-1 flex items-center gap-2 text-eyebrow font-black uppercase tracking-widest text-emerald-300">
                              <Sparkles size={11} /> Do this next
                            </div>
                            <p className="text-label leading-relaxed text-gray-200">
                              {cockpitNextAction}
                            </p>
                          </div>

                          {/* Always 2x2. This section is half of Zone 2 -- about 400px -- so four
                              columns gave each card ~85px and turned a one-line
                              description into a six-line stack. Four-up only ever
                              looked right when the text was too small to read. */}
                          {/* These four were static divs: they DESCRIBED the panel on the
                              left while sitting on the right, and read "1 2 3 4" identically
                              whether you had done nothing or finished a verified build. Two
                              panels both looking like the start, a numbered sequence that
                              never moved, and no statement of which to use first -- that is
                              the confusion, and a diagram that cannot be wrong is not a
                              guide. They now track the real state and say which step you are
                              on, so the screen answers "what do I do next" instead of
                              restating the product's vocabulary. */}
                          <div className="grid grid-cols-2 gap-3">
                            {[
                              ["Ask", "Describe the app, fix, or imported repo outcome."],
                              ["Plan", "Oracle turns the request into choices and a spec."],
                              ["Build", "Builder writes code against the chosen plan."],
                              ["Prove", "Compiler, logs, diffs, and verifier output are recorded."],
                            ].map(([label, detail], index) => (
                              <div
                                key={label}
                                data-testid={`cockpit-step-${label.toLowerCase()}`}
                                data-state={
                                  index < cockpitStep
                                    ? "done"
                                    : index === cockpitStep
                                      ? "current"
                                      : "todo"
                                }
                                className={`rounded-xl border p-3 transition-all ${
                                  index === cockpitStep
                                    ? "border-emerald-400/45 bg-emerald-950/20 shadow-[0_0_18px_rgba(53,255,138,0.10)]"
                                    : index < cockpitStep
                                      ? "border-white/10 bg-white/[0.02]"
                                      : "border-white/8 bg-white/[0.03] opacity-55"
                                }`}
                              >
                                <div
                                  className={`mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest ${
                                    index <= cockpitStep ? "text-emerald-300" : "text-gray-600"
                                  }`}
                                >
                                  <span
                                    className={`flex h-5 w-5 items-center justify-center rounded-full border font-mono text-meta ${
                                      index < cockpitStep
                                        ? "border-emerald-400/40 bg-emerald-500/20 text-emerald-300"
                                        : index === cockpitStep
                                          ? "border-emerald-400/60 bg-emerald-950/40"
                                          : "border-white/10 bg-black/30 text-gray-600"
                                    }`}
                                  >
                                    {index < cockpitStep ? "✓" : index + 1}
                                  </span>
                                  {label}
                                  {index === cockpitStep && (
                                    <span className="ml-auto text-eyebrow font-black text-emerald-400">
                                      YOU ARE HERE
                                    </span>
                                  )}
                                </div>
                                <p className="text-eyebrow leading-relaxed text-gray-500">
                                  {detail}
                                </p>
                              </div>
                            ))}
                          </div>
                        </section>

                        {/* Drag handle. Wider hit area than the visible line so it
                            is actually grabbable; double-click restores the
                            default. */}
                        <div
                          onPointerDown={cockpitSplit.startResize}
                          onDoubleClick={cockpitSplit.reset}
                          data-testid="cockpit-split-resize"
                          role="separator"
                          aria-orientation="vertical"
                          aria-label="Resize the cockpit columns (double-click to reset)"
                          title="Drag to resize — double-click to reset"
                          className={`-mx-2 w-[6px] cursor-ew-resize rounded-full transition-colors ${
                            cockpitSplit.resizing
                              ? "bg-[var(--determinex-accent)]/50"
                              : "bg-transparent hover:bg-[var(--determinex-accent)]/25"
                          }`}
                        />

                        <section className="rounded-2xl border border-white/8 bg-black/30 p-5">
                          <div className="mb-4 text-eyebrow font-black uppercase tracking-widest text-gray-600">
                            Attach What You Need
                          </div>
                          <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                            {(
                              [
                                [
                                  "Terminal",
                                  "terminal",
                                  TerminalIcon,
                                  "Run commands beside this screen",
                                ],
                                ["Code", "editor", Code2, "Inspect generated files and source"],
                                ["Build", "build", Gauge, "Watch tasks, tests, and output"],
                                [
                                  "Trace",
                                  "trace",
                                  GitBranch,
                                  "Follow worker events and run history",
                                ],
                                ["Search", "search", Search, "Find project context"],
                                [
                                  "Find in Files",
                                  "findfiles",
                                  FileSearch,
                                  "Literal text search across the workspace",
                                ],
                                ["Health", "health", LayoutGrid, "Check oracle and file readiness"],
                                // Real, oracle-verified, lock-audited surfaces (see
                                // DETERMINEX_REACT_{LEARNING_STUDIO,REPO_CLINIC,
                                // MAINTENANCE_BAY}_PANEL_LOCK_001) that previously had
                                // NO visible entry point anywhere a normal user would
                                // look -- only reachable via the command palette
                                // (Ctrl+K) or the addon-dock's own switcher dropdown,
                                // which itself only appears once some OTHER addon is
                                // already open. Ryan: "i dont understand why the main
                                // functionality is buried in favor of... a watered
                                // down version of something else on the side" --
                                // this was that exact pattern, just in a different
                                // corner of the shell than the Idea Lab one already
                                // fixed earlier this session.
                                [
                                  "Learning Studio",
                                  "learning",
                                  Brain,
                                  "Non-authorizing teaching explanations grounded in the verified corpus",
                                ],
                                [
                                  "Repo Clinic",
                                  "repoclinic",
                                  Activity,
                                  "Live oracle-backed diagnosis of the open workspace",
                                ],
                                [
                                  "Maintenance Bay",
                                  "maintenancebay",
                                  ShieldCheck,
                                  "Live dependency/secret/license/container security scan",
                                ],
                                // Round 2 of the same fix -- see quickAttachIds' comment.
                                [
                                  "Mission Control",
                                  "mission",
                                  GraduationCap,
                                  "Determinex's own release readiness -- not your project's",
                                ],
                                [
                                  "Determinex Roadmap",
                                  "roadmap",
                                  ShieldCheck,
                                  "Successor direction, exact blockers, release locks",
                                ],
                                [
                                  "Flywheel",
                                  "flywheel",
                                  RefreshCcw,
                                  "Training corpus and feedback feed",
                                ],
                                [
                                  "Runtime",
                                  "execution",
                                  Cpu,
                                  "Active hive sessions and local service status",
                                ],
                                ["Merge", "merge", GitMerge, "Resolve git merge conflicts"],
                                // `satisfies` so the second element is checked against
                                // WorkspaceAddon at COMPILE time. Without it these tuples
                                // infer as plain string and the launch call below needed an
                                // `as WorkspaceAddon` cast, which silenced the checker
                                // completely: "Product Surfaces" sat here as a dead button
                                // for one addon-id that had been deliberately retired
                                // (d0d979a280 removed the duplicate but missed this call
                                // site), compiling cleanly and doing nothing when clicked.
                              ] satisfies [string, WorkspaceAddon, LucideIcon, string][]
                            )
                              .filter(
                                ([, addon]) =>
                                  isInternalBuild() || (addon !== "mission" && addon !== "roadmap")
                              )
                              .map(([label, addon, Icon, detail]) => {
                                const ActionIcon = Icon as typeof TerminalIcon;
                                return (
                                  <button
                                    key={label as string}
                                    type="button"
                                    onClick={() => handleAddonLaunch(addon)}
                                    className="group rounded-xl border border-white/8 bg-white/[0.03] p-3 text-left transition hover:border-emerald-400/40 hover:bg-emerald-500/10"
                                  >
                                    <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-white">
                                      <ActionIcon size={13} className="text-emerald-300" />{" "}
                                      {label as string}
                                    </div>
                                    <p className="mt-1 text-eyebrow leading-relaxed text-gray-600 group-hover:text-gray-500">
                                      {detail as string}
                                    </p>
                                  </button>
                                );
                              })}
                          </div>
                        </section>
                      </div>

                      {/* "Project contract" (workspace path) is already shown in the
                    header's Workspace card above; "Proof boundary" was static
                    boilerplate text that never changed with real state -- both
                    cut as pure redundancy. Current Input is the only one of the
                    three that carried unique, real information. */}
                      <div className="mt-4 rounded-xl border border-white/8 bg-white/[0.025] p-4">
                        <div className="text-eyebrow font-black uppercase tracking-widest text-gray-600">
                          Current input
                        </div>
                        <div className="mt-2 text-label leading-relaxed text-gray-400">
                          {inputVal || "Use the left Work panel to describe what to build."}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : activeSidebar === "hub" ? (
                  <ProjectHub
                    selectedProjectName={selectedProjectName}
                    onSelectProject={handleProjectSelect}
                    onNavigate={handleProjectHubNavigate}
                    onOpenLibrary={() => setShowProjectLibrary(true)}
                  />
                ) : activeSidebar === "extensions" ? (
                  <div className="flex h-full min-h-0 flex-col overflow-hidden">
                    <div className="shrink-0 border-b border-white/10 p-6">
                      <div className="mb-2 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-pink-300">
                        <Package size={13} /> Tools Panel
                      </div>
                      <h2
                        className="text-3xl font-black leading-tight text-[var(--determinex-text)]"
                        style={{ fontFamily: "var(--determinex-font-display)" }}
                      >
                        Tools, Providers, and Add-ons
                      </h2>
                      <p className="mt-2 max-w-3xl text-body leading-relaxed text-[var(--determinex-muted)]">
                        Manage installed tools, model providers, connectors, and IDE panes here.
                        Terminal, Code, Build, Trace, Search, and Health attach to the active screen
                        instead of opening as disconnected pages.
                      </p>
                    </div>
                    <div className="min-h-0 flex-1 overflow-hidden">
                      <ToolsHub
                        toolCatalog={toolCatalog}
                        toolCoverage={toolCoverage}
                        activeTool={addonDockOpen ? activeAddon : null}
                        onLaunchTool={handleAddonLaunch}
                        onOpenBrain={() => handleProjectHubNavigate("brain")}
                        onShowServiceLogin={(id) => {
                          setShowServiceLogin(id);
                          setServiceKeyInput("");
                        }}
                      />
                    </div>
                  </div>
                ) : activeSidebar === "pipeline" ? (
                  <PipelineDashboard
                    showWarRoom={showWarRoom}
                    setShowWarRoom={setShowWarRoom}
                    lastPrompt={lastPrompt}
                    sessionId={hiveSessionId}
                  />
                ) : activeSidebar === "explorer" ? (
                  <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
                    {/* Ambient bg */}
                    <div className="pointer-events-none absolute inset-0 opacity-20">
                      <div className="matrix-rain absolute inset-0" />
                    </div>
                    <div className="relative z-10 flex min-h-0 flex-1 flex-col p-6">
                      <div className="border-b border-white/10 pb-5">
                        <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-purple-300 mb-2">
                          <Folder size={13} /> Workspace Stage
                        </div>
                        <h2
                          className="text-3xl font-black leading-tight text-[var(--determinex-text)]"
                          style={{ fontFamily: "var(--determinex-font-display)" }}
                        >
                          {selectedProjectName}
                        </h2>
                        <p className="mt-2 max-w-2xl font-mono text-body leading-relaxed text-[var(--determinex-muted)]">
                          {displayPath(explorerRoot) || "No workspace path bound yet."}
                        </p>
                      </div>

                      <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 py-6 xl:grid-cols-2">
                        <div className="rounded-2xl border border-white/10 bg-black/25 p-6">
                          <div className="mb-4 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-emerald-300">
                            <GitPullRequest size={14} /> Source
                          </div>
                          {gitBranch ? (
                            <div className="space-y-2 font-mono text-label text-gray-300">
                              <div>
                                branch <span className="text-white">{gitBranch}</span>
                              </div>
                              <div>
                                upstream{" "}
                                <span className="text-white">
                                  {explorerGitMeta.upstream ?? "none"}
                                </span>
                              </div>
                              {(explorerGitMeta.ahead > 0 || explorerGitMeta.behind > 0) && (
                                <div className="text-amber-300">
                                  {explorerGitMeta.ahead > 0 && `${explorerGitMeta.ahead} ahead`}
                                  {explorerGitMeta.ahead > 0 && explorerGitMeta.behind > 0 && " · "}
                                  {explorerGitMeta.behind > 0 && `${explorerGitMeta.behind} behind`}
                                </div>
                              )}
                              <div>
                                {explorerGitFiles.length > 0 ? (
                                  <span className="text-amber-300">
                                    {explorerGitFiles.length} uncommitted change
                                    {explorerGitFiles.length === 1 ? "" : "s"}
                                  </span>
                                ) : (
                                  <span className="text-gray-500">working tree clean</span>
                                )}
                              </div>
                            </div>
                          ) : (
                            <p className="text-label text-gray-500">
                              Not a git repository, or status could not be read.
                            </p>
                          )}
                          <button
                            type="button"
                            onClick={() => setActiveSidebar("git")}
                            className="mt-4 rounded-lg border border-emerald-400/25 bg-emerald-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-emerald-300 transition hover:bg-emerald-900/30"
                          >
                            Open Source Control
                          </button>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/25 p-6">
                          <div className="mb-4 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-blue-300">
                            <Files size={14} /> Files
                          </div>
                          <p className="font-mono text-label text-gray-300">
                            {fileTree.length > 0
                              ? `${fileTree.length} top-level entr${fileTree.length === 1 ? "y" : "ies"} scanned`
                              : isTauri()
                                ? "Scanning workspace..."
                                : "Browser mode cannot scan the real file tree."}
                          </p>
                          <div className="mt-4 flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => setWorkspaceView("files")}
                              className="rounded-lg border border-blue-400/25 bg-blue-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-blue-300 transition hover:bg-blue-900/30"
                            >
                              Browse Tree
                            </button>
                            <button
                              type="button"
                              onClick={() => handleAddonLaunch("findfiles")}
                              className="rounded-lg border border-blue-400/25 bg-blue-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-blue-300 transition hover:bg-blue-900/30"
                            >
                              Find in Files
                            </button>
                          </div>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/25 p-6">
                          <div className="mb-4 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-amber-300">
                            <Activity size={14} /> Runs
                          </div>
                          <p className="text-label text-gray-500">
                            {hiveSessionId
                              ? `Active session: ${hiveSessionId}`
                              : "No active Hive session. Start one from Work."}
                          </p>
                          <button
                            type="button"
                            onClick={() => handleSidebarLaunch("hive")}
                            className="mt-4 rounded-lg border border-amber-400/25 bg-amber-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-amber-300 transition hover:bg-amber-900/30"
                          >
                            Go to Work
                          </button>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-black/25 p-6">
                          <div className="mb-4 flex items-center gap-2 text-meta font-black uppercase tracking-widest text-purple-300">
                            <Gauge size={14} /> Quick Attach
                          </div>
                          <p className="text-label text-gray-500">
                            Attach a tool beside this screen instead of switching away from it.
                          </p>
                          <div className="mt-4 flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => handleAddonLaunch("terminal")}
                              className="rounded-lg border border-purple-400/25 bg-purple-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-purple-300 transition hover:bg-purple-900/30"
                            >
                              Terminal
                            </button>
                            <button
                              type="button"
                              onClick={() => handleAddonLaunch("editor")}
                              className="rounded-lg border border-purple-400/25 bg-purple-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-purple-300 transition hover:bg-purple-900/30"
                            >
                              Code
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : activeSidebar === "benchmark" ? (
                  <BrainStage
                    selectedModel={selectedModel}
                    modelTiers={modelTiers}
                    tandemPresets={tandemPresets}
                    onSelectModel={(id) => setSelectedModel(id)}
                    onModelAdded={refreshModelsRegistry}
                    matrixLogs={matrixLogs}
                    onOpenModelSlots={() => {
                      setSettingsTab("roles");
                      setShowSettings(true);
                    }}
                    onOpenProof={() => setActiveSidebar("proof")}
                  />
                ) : activeSidebar === "proof" ? (
                  <div className="flex flex-col h-full overflow-hidden">
                    {/* Header */}
                    <div
                      className="border-b shrink-0 p-6"
                      style={{ borderColor: "var(--determinex-border)" }}
                    >
                      <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-cyan-400 mb-2">
                        <Eye size={13} /> Project Proof
                      </div>
                      <h2
                        className="text-2xl font-black text-white"
                        style={{ fontFamily: "var(--determinex-font-display)" }}
                      >
                        {selectedProjectName} Proof
                      </h2>
                      <p
                        className="mt-1 text-body leading-relaxed"
                        style={{ color: "var(--determinex-muted)" }}
                      >
                        Project-scoped run history, build output, trace logs, code diffs, verifier
                        results, and release gates. Empty states explain exactly what proof is
                        missing.
                      </p>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setShowProjectLibrary(true)}
                          className="rounded-lg border border-cyan-400/25 bg-cyan-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-cyan-300 transition-all hover:bg-cyan-900/30"
                        >
                          Session Library
                        </button>
                        <button
                          type="button"
                          onClick={() => handleAddonLaunch("build")}
                          className="rounded-lg border border-orange-400/25 bg-orange-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-orange-300 transition-all hover:bg-orange-900/30"
                        >
                          Builds
                        </button>
                        <button
                          type="button"
                          onClick={() => handleAddonLaunch("trace")}
                          className="rounded-lg border border-violet-400/25 bg-violet-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-violet-300 transition-all hover:bg-violet-900/30"
                        >
                          Trace
                        </button>
                        <button
                          type="button"
                          onClick={() => handleAddonLaunch("review")}
                          className="rounded-lg border border-blue-400/25 bg-blue-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-blue-300 transition-all hover:bg-blue-900/30"
                        >
                          Review
                        </button>
                        <button
                          type="button"
                          onClick={() => handleAddonLaunch("health")}
                          className="rounded-lg border border-teal-400/25 bg-teal-950/20 px-3 py-2 text-meta font-black uppercase tracking-widest text-teal-300 transition-all hover:bg-teal-900/30"
                        >
                          Gates
                        </button>
                      </div>
                    </div>

                    <div className="flex-1 overflow-y-auto p-6 no-scrollbar">
                      {/* Main verdict card */}
                      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 mb-6">
                        <div
                          className={`rounded-2xl border p-5 ${
                            agentStatus.verdict && agentStatus.accepted
                              ? "border-emerald-500/25 bg-emerald-950/15"
                              : agentStatus.verdict && !agentStatus.accepted
                                ? "border-red-500/25 bg-red-950/15"
                                : "border-white/8 bg-white/[0.03]"
                          }`}
                        >
                          <div className="text-eyebrow uppercase font-bold tracking-widest text-gray-500 mb-2">
                            Oracle Verdict
                          </div>
                          <div
                            className={`text-4xl font-black mb-2 ${
                              agentStatus.verdict && agentStatus.accepted
                                ? "text-emerald-400"
                                : agentStatus.verdict && !agentStatus.accepted
                                  ? "text-red-400"
                                  : "text-gray-700"
                            }`}
                          >
                            {agentStatus.verdict ?? "-"}
                          </div>
                          {agentStatus.confidence !== null &&
                          agentStatus.confidence !== undefined ? (
                            <div className="space-y-1">
                              <div className="flex items-center justify-between text-label text-gray-500">
                                <span>Confidence</span>
                                <span className="font-mono font-bold text-white">
                                  {(agentStatus.confidence * 100).toFixed(0)}%
                                </span>
                              </div>
                              <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                                <div
                                  className={`h-full rounded-full transition-all ${agentStatus.accepted ? "bg-emerald-400" : "bg-red-400"}`}
                                  style={{ width: `${(agentStatus.confidence * 100).toFixed(0)}%` }}
                                />
                              </div>
                            </div>
                          ) : (
                            <p className="text-label text-gray-600 font-mono">
                              No pipeline run yet. Go to Work, describe your change, then
                              orchestrate.
                            </p>
                          )}
                        </div>

                        <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-5">
                          <div className="text-eyebrow uppercase font-bold tracking-widest text-gray-500 mb-2">
                            Pipeline State
                          </div>
                          <div className="space-y-2 mt-3">
                            {[
                              {
                                label: "Generated file",
                                value: generatedFile ?? "-",
                                color: generatedFile ? "text-purple-300" : "text-gray-700",
                              },
                              {
                                label: "Retry count",
                                value: retryCount > 0 ? String(retryCount) : "-",
                                color: retryCount > 0 ? "text-amber-400" : "text-gray-700",
                              },
                              {
                                label: "Accepted",
                                value:
                                  agentStatus.accepted === true
                                    ? "Yes"
                                    : agentStatus.accepted === false
                                      ? "No"
                                      : "-",
                                color:
                                  agentStatus.accepted === true
                                    ? "text-emerald-400"
                                    : agentStatus.accepted === false
                                      ? "text-red-400"
                                      : "text-gray-700",
                              },
                              {
                                label: "Error",
                                value: agentStatus.error
                                  ? `${agentStatus.error.stage}: ${agentStatus.error.message.slice(0, 60)}`
                                  : "-",
                                color: agentStatus.error ? "text-red-400" : "text-gray-700",
                              },
                            ].map(({ label, value, color }) => (
                              <div key={label} className="flex items-start justify-between gap-3">
                                <span className="text-label text-gray-600 shrink-0">{label}</span>
                                <span
                                  className={`text-label font-mono font-bold text-right truncate ${color}`}
                                >
                                  {value}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Compiler warning */}
                      {compilerWarning && (
                        <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-950/20 px-4 py-3">
                          <span className="text-amber-400 text-meta font-black uppercase tracking-widest shrink-0 mt-px">
                            Compiler
                          </span>
                          <span className="text-label text-amber-300/80 font-mono leading-relaxed">
                            {compilerWarning}
                          </span>
                        </div>
                      )}

                      {/* Live MoA pipeline view.
                          Mounted 2026-07-29. MatrixExecutionDisplay had existed unrendered:
                          page.tsx imported only its AgentStatus TYPE, so the three-agent
                          Sentinel -> Engineer -> Observer pipeline was never shown anywhere,
                          while every input it needs was already here and live --
                          agentStatus, matrixLogs, executeAbort, retryCount. The desktop
                          surface showed the verdict and a log tail but never which agent
                          held the run. Placed above the log tail so the pipeline state and
                          the lines it produced read together. */}
                      {(agentStatus.isExecuting || agentStatus.verdict) && (
                        <div className="mb-4">
                          <MatrixExecutionDisplay
                            agentStatus={agentStatus}
                            logs={matrixLogs}
                            onAbort={() => void executeAbort()}
                            retryCount={retryCount}
                          />
                        </div>
                      )}

                      {/* Log tail */}
                      {matrixLogs.length > 0 && (
                        <div className="rounded-2xl border border-white/8 bg-black/40 overflow-hidden mb-4">
                          <div className="px-4 py-2.5 border-b border-white/5 flex items-center justify-between">
                            <span className="text-eyebrow uppercase font-bold tracking-widest text-gray-500">
                              Session Log
                            </span>
                            <span className="text-meta font-mono text-gray-700">
                              {matrixLogs.length} lines
                            </span>
                          </div>
                          <div className="p-4 font-mono text-label leading-relaxed space-y-0.5 max-h-48 overflow-y-auto no-scrollbar">
                            {matrixLogs.slice(-20).map((line, i) => (
                              <div
                                key={i}
                                className={
                                  line.includes("[ERROR]")
                                    ? "text-red-400"
                                    : line.includes("[OBSERVER]")
                                      ? "text-violet-400"
                                      : line.includes("[DETERMINEX]")
                                        ? "text-cyan-400"
                                        : line.includes("[USER]")
                                          ? "text-emerald-400"
                                          : "text-gray-600"
                                }
                              >
                                {line}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Empty state */}
                      {matrixLogs.length === 0 && !agentStatus.verdict && (
                        <div className="flex flex-col items-center justify-center py-16 text-center">
                          <div className="h-16 w-16 rounded-2xl border border-white/8 bg-white/[0.03] flex items-center justify-center mb-4">
                            <Eye size={28} className="text-gray-700" />
                          </div>
                          <p className="text-body font-bold text-gray-600">No evidence yet</p>
                          <p className="mt-2 text-label text-gray-700 font-mono leading-relaxed max-w-xs">
                            Open Work, describe a change, and run the Hive. Oracle verdicts, file
                            diffs, and compiler results will appear here.
                          </p>
                          <button
                            onClick={() => setActiveSidebar("hive")}
                            className="mt-6 rounded-xl border border-emerald-500/30 bg-emerald-950/20 px-5 py-2.5 text-meta font-black uppercase tracking-widest text-emerald-400 transition-all hover:bg-emerald-900/30"
                          >
                            Go to Work
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ) : activeSidebar === "git" || activeSidebar === "audit" ? (
                  // git/audit put their full real content in the left strip and never
                  // wired a main-pane view -- this used to fall through to the generic
                  // "Select a panel to begin" placeholder even though a panel WAS
                  // selected (it's rendering, just to the left). Found live 2026-07-19
                  // during the same sweep as the Quick Attach fix below -- honest fix
                  // is to say what this space is for rather than lie about nothing
                  // being chosen.
                  <div className="flex h-full flex-col items-center justify-center gap-3 text-center opacity-40">
                    <p className="text-body font-mono text-gray-600">
                      {activeSidebar === "git" ? "Source Control" : "Audit"} detail is in the panel
                      on the left.
                    </p>
                    <p className="max-w-xs text-label text-gray-700">
                      This space is free for a tool -- use + Attach in the status bar to bring in
                      Terminal, Code, or another panel beside it.
                    </p>
                    <button
                      onClick={() => setActiveSidebar("none")}
                      className="text-meta uppercase font-bold text-gray-500 hover:text-white"
                    >
                      Close
                    </button>
                  </div>
                ) : activeSidebar ? (
                  <div className="flex flex-col items-center justify-center h-full gap-3 text-center opacity-40">
                    <p className="text-body font-mono text-gray-600">
                      Select a panel from the rail to begin.
                    </p>
                    <button
                      onClick={() => setActiveSidebar("none")}
                      className="text-meta uppercase font-bold text-gray-500 hover:text-white"
                    >
                      Close
                    </button>
                  </div>
                ) : null}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        </main>
      </div>

      {/* Free-floating addon window -- lives OUTSIDE the rail/Zone1/Zone2 flex
          row so it can be dragged over any of them, not just squeeze the one
          it used to be docked beside. Ryan: "still really buggy and no way to
          move it or position it, and no memory of how user wants it." Position/
          size is per-addon-id persisted (applyAddonLayout/commitAddonLayout). */}
      <AnimatePresence>
        {addonDockOpen && selectedAddon && (
          <motion.div
            key={selectedAddon.id}
            data-testid="workspace-addon-drawer"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 280, damping: 28, mass: 0.8 }}
            className="absolute z-40 flex flex-col overflow-hidden rounded-xl border border-white/10 backdrop-blur-3xl"
            style={{
              background: "linear-gradient(180deg, rgba(3,7,18,0.96) 0%, rgba(1,4,9,0.99) 100%)",
              boxShadow: "0 24px 60px rgba(0,0,0,0.55)",
              // Maximized leaves the 72px activity rail clickable (left: 88 = rail
              // width + gap) so switching primary screens doesn't first require
              // restoring/closing the tool -- covering it entirely regressed
              // navigation vs. the pre-floating-window docked behavior.
              ...(addonDockMaximized
                ? { left: 88, top: 0, right: 0, bottom: 0 }
                : {
                    left: addonDockX,
                    top: addonDockY,
                    width: addonDockWidth,
                    height: addonDockHeight,
                  }),
            }}
          >
            {!addonDockMaximized && (
              <>
                {/* Edge handles */}
                <div
                  onPointerDown={startAddonDockResize({ n: true })}
                  className="absolute left-2 right-2 top-0 h-1.5 cursor-ns-resize z-10"
                  title="Resize"
                />
                <div
                  onPointerDown={startAddonDockResize({ s: true })}
                  className="absolute left-2 right-2 bottom-0 h-1.5 cursor-ns-resize z-10"
                  title="Resize"
                />
                <div
                  onPointerDown={startAddonDockResize({ w: true })}
                  className="absolute top-2 bottom-2 left-0 w-1.5 cursor-ew-resize z-10"
                  title="Resize"
                />
                <div
                  onPointerDown={startAddonDockResize({ e: true })}
                  className="absolute top-2 bottom-2 right-0 w-1.5 cursor-ew-resize z-10"
                  title="Resize"
                />
                {/* Corner handles */}
                <div
                  onPointerDown={startAddonDockResize({ n: true, w: true })}
                  className="absolute left-0 top-0 h-3 w-3 cursor-nwse-resize z-20"
                  title="Resize"
                />
                <div
                  onPointerDown={startAddonDockResize({ n: true, e: true })}
                  className="absolute right-0 top-0 h-3 w-3 cursor-nesw-resize z-20"
                  title="Resize"
                />
                <div
                  onPointerDown={startAddonDockResize({ s: true, w: true })}
                  className="absolute left-0 bottom-0 h-3 w-3 cursor-nesw-resize z-20"
                  title="Resize"
                />
                <div
                  onPointerDown={startAddonDockResize({ s: true, e: true })}
                  className="absolute right-0 bottom-0 h-3 w-3 cursor-nwse-resize z-20"
                  title="Resize"
                />
              </>
            )}
            <div
              onPointerDown={startAddonDockDrag}
              className={`flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3 ${
                addonDockMaximized ? "" : "cursor-move"
              }`}
              title={addonDockMaximized ? undefined : "Drag to move"}
            >
              <div className="flex min-w-0 items-center gap-3">
                {!addonDockMaximized && (
                  <GripHorizontal size={13} className="shrink-0 text-gray-700" />
                )}
                {(() => {
                  const SelectedAddonIcon = selectedAddon.icon;
                  return (
                    <SelectedAddonIcon size={17} className={`shrink-0 ${selectedAddon.tone}`} />
                  );
                })()}
                <div className="min-w-0">
                  <div className="truncate text-meta font-black uppercase tracking-widest text-white">
                    {selectedAddon.label}
                  </div>
                  <div className="mt-0.5 truncate text-meta font-mono text-gray-600">
                    {selectedAddon.description}
                  </div>
                </div>
              </div>
              <div
                className="flex min-w-0 items-center justify-end gap-2"
                onPointerDown={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  onClick={() => {
                    const next = !addonDockMaximized;
                    setAddonDockMaximized(next);
                    if (activeAddon) commitAddonLayout(activeAddon, next);
                  }}
                  className="flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-eyebrow font-black uppercase tracking-widest text-gray-500 transition hover:bg-white/10 hover:text-white"
                  title={addonDockMaximized ? "Restore" : "Maximize"}
                >
                  {addonDockMaximized ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
                  {addonDockMaximized ? "Restore" : "Maximize"}
                </button>
                <AddonSwitcher
                  items={runtimeAddonItems}
                  activeId={selectedAddon.id}
                  activeLabel={selectedAddon.label}
                  onSelect={(id) => {
                    applyAddonLayout(id as WorkspaceAddon);
                    setActiveAddon(id as WorkspaceAddon);
                    setAddonDockOpen(true);
                  }}
                />
                <button
                  type="button"
                  onClick={closeAddon}
                  className="ml-1 flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-gray-500 transition-all hover:border-red-400/30 hover:text-red-300"
                  title="Close add-on"
                >
                  <X size={14} />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">{selectedAddon.panel}</div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showProjectLibrary && (
          <motion.div
            key="project-library-modal"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 flex items-center justify-center bg-black/70 p-6 backdrop-blur-sm"
          >
            <motion.div
              initial={{ opacity: 0, y: 24, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 24, scale: 0.98 }}
              transition={{ type: "spring", stiffness: 280, damping: 28, mass: 0.85 }}
              className="h-[78vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-white/10 shadow-2xl"
            >
              <ProjectLibrary
                onResume={handleResumeProjectSession}
                onClose={() => setShowProjectLibrary(false)}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Teacher overlay */}
      <TeacherOverlay
        open={showTeacher}
        onClose={() => setShowTeacher(false)}
        activeSidebar={activeSidebar}
        activeAddon={addonDockOpen ? activeAddon : null}
        onAskAgent={(task) => {
          setGuideAskTask(task);
          handleAddonLaunch("agents");
        }}
      />

      {/* The floating guide "advisor" pill that used to live here (absolute
          bottom-14 right-6 z-50) is gone. Ryan, live 2026-07-27: "the advisor
          addon at the bottom right is weird and it blocks things." It was
          permanently mounted with no dismiss control, so it parked a 300px
          glowing box over the bottom-right of whatever panel was open -- it
          was covering the Merge card in the Work cockpit and the composer in
          Agent Chat. It was also pure redundancy: its only button called
          setShowTeacher(true), which is exactly what the rail's GUIDE icon
          already does. The per-screen context line it displayed now rides on
          that rail button's tooltip, so no information was lost. */}

      {/* A privacy policy the backend did not apply is the one failure the user
          must never miss -- the rail's Cloak label alone would keep implying a
          posture that is not in force. Top-center and above the addon dock, but
          dismissible; the state it reports has already been rolled back to the
          policy actually in effect. */}
      {networkPolicyError && (
        <div className="absolute left-1/2 top-3 z-[300] flex max-w-[620px] -translate-x-1/2 items-start gap-2 rounded-xl border border-red-500/40 bg-red-950/90 px-4 py-2.5 shadow-2xl backdrop-blur-xl">
          <ShieldAlert size={14} className="mt-0.5 shrink-0 text-red-400" />
          <p className="flex-1 font-mono text-label leading-relaxed text-red-200">
            {networkPolicyError}
          </p>
          <button
            onClick={dismissNetworkPolicyError}
            className="shrink-0 text-red-400/70 transition-colors hover:text-red-200"
            title="Dismiss"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* Command palette */}
      <CommandPalette
        open={showPalette}
        onClose={() => setShowPalette(false)}
        commands={paletteCommands}
      />

      {/* Status bar — fixed bottom */}
      <StatusBar
        onOpenPalette={() => setShowPalette(true)}
        activeSidebar={activeSidebar}
        selectedModel={selectedModel}
        gitBranch={gitBranch}
        oracleAccepted={agentStatus.accepted}
        oracleVerdict={agentStatus.verdict}
        errorCount={statusBarErrorCount}
        keyStatus={keyStatus}
        onChangeModel={setSelectedModel}
        // Problems is a tab inside Build now rather than its own panel, and
        // BuildCenter defaults initialTool to "problems" -- so this lands on the
        // same view it always did, with one fewer duplicate entry point.
        onClickErrors={() => handleAddonLaunch("build")}
        onClickModel={() => {
          setSettingsTab("roles");
          setShowSettings(true);
        }}
        onTogglePanel={() => {
          if (addonDockOpen) closeAddon();
          else handleAddonLaunch(activeAddon ?? "terminal");
        }}
        quickAttachItems={quickAttachItems}
        activeAddonId={addonDockOpen ? activeAddon : null}
        onAttach={(id) => handleAddonLaunch(id as WorkspaceAddon)}
        onOpenToolsHub={() => setActiveSidebar("extensions")}
      />
    </div>
  );

  // -------------------------------------------------------------
  // MOBILE EXECUTIVE DASHBOARD
  // -------------------------------------------------------------
  const renderMobileView = () => (
    <div
      className="flex h-full w-full flex-col"
      style={{
        background: `radial-gradient(circle at 18% 0%, ${themePack.colors.accentGlow}, transparent 32%), var(--determinex-bg)`,
        color: "var(--determinex-text)",
      }}
    >
      <header
        className="shrink-0 border-b px-4 py-3"
        style={{
          background: "var(--determinex-panel-glass)",
          borderColor: "var(--determinex-border)",
        }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-meta font-black uppercase tracking-widest text-emerald-400">
              Determinex
            </div>
            <div className="truncate text-body font-bold text-white">Verified build cockpit</div>
          </div>
          <button
            onClick={() => setShowSettings(true)}
            className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] p-2 text-gray-400"
            title="Settings"
          >
            <Settings size={16} />
          </button>
        </div>
      </header>

      <main className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <section className="space-y-2 border-b border-[var(--dtx-code-border)] pb-3">
          <div>
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-cyan-300">
              <ShieldCheck size={13} /> Proof loop
            </div>
            <h1 className="mt-2 text-display font-black leading-tight text-white">
              Ask for the change. Keep the proof visible.
            </h1>
            <p className="mt-2 text-body leading-relaxed text-gray-500">
              Objective, verifier state, review state, and proof links stay in one path.
            </p>
          </div>

          <textarea
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            disabled={isExecutingPack}
            placeholder="Describe the repo change..."
            className="min-h-24 w-full resize-none rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg-deep)] px-3 py-3 text-body text-gray-100 outline-none focus:border-cyan-500/50"
          />

          <AiRouteSelect
            value={selectedModel}
            onChange={setSelectedModel}
            keyStatus={keyStatus}
            compact
          />

          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() =>
                setInputVal(
                  "Demo: fix an empty-input parser bug, prove it with tests, and show the review diff."
                )
              }
              className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] px-3 py-2.5 text-meta font-black uppercase tracking-widest text-cyan-300"
            >
              Load Demo
            </button>
            <button
              onClick={handleUnleash}
              disabled={isExecutingPack || inputVal.trim().length === 0}
              className={`rounded-lg border px-3 py-2.5 text-meta font-black uppercase tracking-widest ${
                isExecutingPack || inputVal.trim().length === 0
                  ? "border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] text-gray-600"
                  : "border-emerald-500/35 bg-emerald-500/15 text-emerald-300"
              }`}
            >
              {isExecutingPack ? "Running" : "Orchestrate"}
            </button>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-2">
          {[
            ["Oracle", "Compiler/test truth is the source of authority.", "emerald"],
            [
              "Approval",
              "Source mutation stays gated until a verified diff is approved.",
              "purple",
            ],
            ["Ledger", "Proof reports stay separate from release readiness.", "cyan"],
          ].map(([label, detail, tone]) => (
            <div
              key={label}
              className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)] px-3 py-2.5"
            >
              <div
                className={`text-meta font-black uppercase tracking-widest ${
                  tone === "emerald"
                    ? "text-emerald-300"
                    : tone === "purple"
                      ? "text-purple-300"
                      : "text-cyan-300"
                }`}
              >
                {label}
              </div>
              <div className="mt-1 text-label leading-snug text-gray-500">{detail}</div>
            </div>
          ))}
        </section>

        <section className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]">
          <div className="flex items-center justify-between border-b border-[var(--dtx-code-border)] px-3 py-2">
            <span className="text-meta font-black uppercase tracking-widest text-gray-400">
              Activity
            </span>
            <button
              onClick={() => setIsDiffMode(!isDiffMode)}
              className="text-meta font-bold uppercase tracking-widest text-cyan-300"
            >
              {isDiffMode ? "Log" : "Diff"}
            </button>
          </div>
          {isDiffMode ? (
            <div className="h-56">
              <DiffEditor
                height="100%"
                language="python"
                theme="vs-dark"
                original={diffData.old}
                modified={diffData.new}
                options={{
                  minimap: { enabled: false },
                  wordWrap: "on",
                  fontSize: 10,
                  disableLayerHinting: true,
                }}
              />
            </div>
          ) : (
            <div className="min-h-32 px-3 py-3 font-mono text-label leading-relaxed text-emerald-400/80">
              {matrixLogs.length > 0 ? (
                matrixLogs.slice(-12).map((log, i) => <div key={i}>{log}</div>)
              ) : (
                <div className="text-gray-600">No active run yet.</div>
              )}
            </div>
          )}
        </section>

        <nav className="grid grid-cols-2 gap-2 pb-2">
          <a
            href="/proof-center/"
            className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] px-3 py-3 text-center text-meta font-black uppercase tracking-widest text-gray-300"
          >
            Proof Center
          </a>
          <a
            href="/ide-repair/"
            className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] px-3 py-3 text-center text-meta font-black uppercase tracking-widest text-gray-300"
          >
            Repair Panel
          </a>
          <button
            onClick={() => handleSidebarLaunch("benchmark")}
            className="rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)] px-3 py-3 text-meta font-black uppercase tracking-widest text-gray-300 col-span-2"
          >
            Brain & Forge
          </button>
        </nav>
      </main>
    </div>
  );

  return (
    <div
      data-determinex-skin={theme}
      style={{
        ...skinPackStyle,
        background: "var(--determinex-bg)",
        color: "var(--determinex-text)",
      }}
      className="relative flex h-[100dvh] w-full overflow-hidden font-sans"
    >
      <SetupWizard />
      {/* Quiet unless an update exists, and never installs without being asked. */}
      <UpdateNotice />

      <div className="flex h-[100dvh] w-full relative z-10 bg-transparent">
        {isMobile ? renderMobileView() : renderDesktopView()}
      </div>

      <SettingsModal />

      <ServiceLoginModal />

      <AnimatePresence>
        {showOnboarding && (
          <WorkspaceOnboarding
            workspacePath={explorerRoot}
            onClose={() => {
              setShowOnboarding(false);
              markOnboardingDismissed(explorerRoot);
            }}
          />
        )}
        {isBootstrapping && (
          <BootOverlay
            bootError={bootError}
            bootProgress={bootProgress}
            onDismiss={dismissBootError}
          />
        )}
      </AnimatePresence>

      <HelpModal helpModal={helpModal} onClose={() => setHelpModal(null)} />
    </div>
  );
}
