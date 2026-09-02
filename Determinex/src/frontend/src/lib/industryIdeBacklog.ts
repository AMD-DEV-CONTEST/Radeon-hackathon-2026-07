export type IndustryBacklogStatus = "done" | "partial" | "blocked" | "planned";
export type IndustryBacklogPriority = "P0" | "P1" | "P2";

export type IndustryBacklogCategoryId =
  | "release"
  | "ide-parity"
  | "universal-code"
  | "agentic"
  | "guide"
  | "extensions"
  | "privacy"
  | "execution"
  | "quality"
  | "differentiators";

export type IndustryBacklogCategory = {
  id: IndustryBacklogCategoryId;
  title: string;
  objective: string;
};

export type IndustryIdeBacklogItem = {
  id: string;
  category: IndustryBacklogCategoryId;
  priority: IndustryBacklogPriority;
  title: string;
  status: IndustryBacklogStatus;
  evidence: string[];
  blocker: string;
  nextAction: string;
};

export type IndustryIdeBacklogSummary = Record<IndustryBacklogStatus, number> & {
  total: number;
  checked: number;
};

export const INDUSTRY_BACKLOG_STATUS_ORDER: Record<IndustryBacklogStatus, number> = {
  blocked: 0,
  partial: 1,
  planned: 2,
  done: 3,
};

export const INDUSTRY_BACKLOG_PRIORITY_ORDER: Record<IndustryBacklogPriority, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
};

export const DETERMINEX_INDUSTRY_BACKLOG_CATEGORIES: IndustryBacklogCategory[] = [
  {
    id: "release",
    title: "Release Trust",
    objective:
      "Make install, launch, update, uninstall, signing, and public distribution provable.",
  },
  {
    id: "ide-parity",
    title: "Core IDE Parity",
    objective:
      "Match the daily editing, navigation, terminal, git, task, and settings workflows users expect.",
  },
  {
    id: "universal-code",
    title: "Universal Code Support",
    objective: "Detect, run, test, build, debug, and repair real projects across major stacks.",
  },
  {
    id: "agentic",
    title: "Agentic Workbench",
    objective: "Make long-running AI work observable, bounded, reviewable, and recoverable.",
  },
  {
    id: "guide",
    title: "Interactive Guide",
    objective:
      "Turn setup, proof, privacy, repair, and release blockers into contextual next actions.",
  },
  {
    id: "extensions",
    title: "Extension Ecosystem",
    objective:
      "Define how Determinex imports, trusts, runs, or bridges existing VS Code/Open VSX workflows.",
  },
  {
    id: "privacy",
    title: "Privacy And Governance",
    objective:
      "Back every privacy and product claim with live policy, Cloak, audit, and evidence collectors.",
  },
  {
    id: "execution",
    title: "Execution Fabric",
    objective:
      "Unify local shell, WSL, Docker, remote jobs, logs, reservations, and artifact pullback.",
  },
  {
    id: "quality",
    title: "Quality Bar",
    objective:
      "Prove UI, IPC, packaging, setup, hardware, performance, and accessibility behavior repeatedly.",
  },
  {
    id: "differentiators",
    title: "Exceptional Differentiators",
    objective: "Ship the proof-native workflows that make Determinex more than a VS Code clone.",
  },
];

export const DETERMINEX_INDUSTRY_IDE_BACKLOG: IndustryIdeBacklogItem[] = [
  {
    id: "release-clean-host-proof",
    category: "release",
    priority: "P0",
    title: "Clean-host install, launch, workflow, and uninstall proof",
    status: "blocked",
    evidence: [
      "frontend/src/lib/releaseGateStatus.ts:clean_host",
      "assurance/evidence/full_release_closure/clean_host_runner_preflight_20260708.json",
      "scripts/release/clean_host_install_transcript.py",
    ],
    blocker:
      "Current runner cannot access Docker Desktop state; clean-host transcript must run outside this sandbox.",
    nextAction:
      "Generate the transcript template, then run install/launch/Proof Center/workspace smoke/uninstall on an unsandboxed clean Windows host.",
  },
  {
    id: "release-code-signing",
    category: "release",
    priority: "P0",
    title: "Windows code signing and SmartScreen trust",
    status: "blocked",
    evidence: [
      "frontend/src/lib/releaseGateStatus.ts:windows_trust",
      "docs/release/DETERMINEX_PROTECTED_RELEASE_PACKETS.md",
    ],
    blocker: "No determinex-windows-trust-evidence-v1 packet has passed.",
    nextAction:
      "Sign the installer, verify Authenticode and SmartScreen trust, then record the Windows trust packet.",
  },
  {
    id: "release-msi-or-nsis",
    category: "release",
    priority: "P0",
    title: "MSI/WiX packaging fix or explicit NSIS-only decision",
    status: "blocked",
    evidence: [
      "frontend/src/lib/releaseGateStatus.ts:windows_msi",
      "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
      ".tmp/determinex-cargo-target-release/release/bundle/nsis/Determinex_0.1.0_x64-setup.exe",
    ],
    blocker: "NSIS bundle exists; MSI/WiX evidence packet is not proven.",
    nextAction:
      "Build and smoke a WiX/MSI package or explicitly ship an NSIS-only release decision packet.",
  },
  {
    id: "release-updater-rollback",
    category: "release",
    priority: "P0",
    title: "Auto-updater and rollback path",
    status: "planned",
    evidence: ["frontend/src-tauri/tauri.conf.json"],
    blocker: "No audited updater and rollback transcript is attached to release gates.",
    nextAction:
      "Define update manifest signing, update install, rollback, and failed-update recovery tests.",
  },
  {
    id: "release-public-scrub",
    category: "release",
    priority: "P0",
    title: "Public repository scrub",
    status: "partial",
    evidence: [
      "scripts/claim_scanner/day_one_public_claim_scanner.py",
      "frontend/src/lib/successorRoadmap.ts",
    ],
    blocker:
      "Claim scanner passes for authority anchors, but public repo scrub and private path review are not complete.",
    nextAction:
      "Run a release scrub for secrets, private paths, stale Determinex user copy, generated artifacts, and oversized files.",
  },
  {
    id: "release-legal-ip",
    category: "release",
    priority: "P0",
    title: "Legal, license, IP, and model notice packet",
    status: "blocked",
    evidence: [
      "frontend/src/lib/releaseGateStatus.ts:legal_public_distribution",
      "docs/release/DETERMINEX_PROTECTED_RELEASE_PACKETS.md",
    ],
    blocker: "No determinex-legal-public-distribution-evidence-v1 packet has passed.",
    nextAction:
      "Finalize license, notices, model disclosures, third-party attributions, secret scan, and public repo scrub.",
  },
  {
    id: "release-dashboard",
    category: "release",
    priority: "P0",
    title: "Single release dashboard tied to collectors",
    status: "partial",
    evidence: [
      "frontend/src/components/SuccessorRoadmapPanel.tsx",
      "frontend/src/lib/releaseGateStatus.ts",
    ],
    blocker:
      "Dashboard is static snapshot data until every gate is refreshed by current collector output.",
    nextAction:
      "Regenerate release gate status from collector and wire timestamp freshness into the UI.",
  },
  {
    id: "release-go-command",
    category: "release",
    priority: "P0",
    title: "Final GO/BLOCKED release command",
    status: "partial",
    evidence: ["scripts/release/determinex_release_gates.py"],
    blocker: "Full final release verification stack has not passed on this release commit.",
    nextAction:
      "Run the full release verification stack and require machine-readable GO/BLOCKED output.",
  },
  {
    id: "ide-open-workspace",
    category: "ide-parity",
    priority: "P1",
    title: "Open workspace flow with recent projects",
    status: "partial",
    evidence: ["frontend/src/components/ProjectHub.tsx", "frontend/src/app/page.tsx"],
    blocker: "Workspace open/recent-project behavior is not proven from a packaged clean install.",
    nextAction: "Add a packaged-app smoke that opens a fresh repository and persists it as recent.",
  },
  {
    id: "ide-file-explorer-crud",
    category: "ide-parity",
    priority: "P1",
    title: "File explorer create, rename, move, delete, reveal, refresh",
    status: "partial",
    evidence: ["frontend/src/components/FileSystemNode.tsx", "frontend/src/app/page.tsx"],
    blocker: "Explorer reads files, but full file CRUD is not audited as a user workflow.",
    nextAction:
      "Implement and test file create, rename, move, delete, reveal, and refresh commands.",
  },
  {
    id: "ide-editor-persistence",
    category: "ide-parity",
    priority: "P1",
    title: "Editor save, dirty state, tabs, and split view",
    status: "partial",
    evidence: ["frontend/src/components/EditorPanel.tsx", "frontend/src/app/page.tsx"],
    blocker: "Monaco exists, but save/dirty/split persistence is not fully proven.",
    nextAction:
      "Add editor persistence tests covering save, dirty indicators, tab restore, and split layout.",
  },
  {
    id: "ide-global-search-replace",
    category: "ide-parity",
    priority: "P1",
    title: "Global search and replace",
    status: "partial",
    evidence: ["frontend/src/components/VerifiedSearch.tsx"],
    blocker: "Verified search exists; global replace is not proven as an IDE workflow.",
    nextAction:
      "Add replace preview, diff review, apply, and rollback around verified search results.",
  },
  {
    id: "ide-symbol-search-outline",
    category: "ide-parity",
    priority: "P1",
    title: "Symbol search and outline",
    status: "planned",
    evidence: ["frontend/src/components/CommandPalette.tsx"],
    blocker: "No audited symbol index or outline provider is attached to workspace state.",
    nextAction:
      "Add language-server-backed outline and symbol search for the first supported language.",
  },
  {
    id: "ide-git-panel",
    category: "ide-parity",
    priority: "P1",
    title: "Git status, diff, stage, commit, branch, pull, push, and conflict view",
    status: "partial",
    evidence: [
      "frontend/src/components/GitPanel.tsx",
      "frontend/src/components/MergeEditor.tsx",
      "frontend/src/components/__tests__/MergeEditor.test.tsx",
      "frontend/src-tauri/src/git.rs:git_conflict_sides",
    ],
    blocker:
      "Status, stage, commit, branch, pull, push, and a dedicated ours/theirs/result conflict editor are all implemented; not yet proven from a packaged clean install.",
    nextAction:
      "Add packaged-app smoke coverage that stages a real merge conflict and resolves it through the Merge panel end to end.",
  },
  {
    id: "ide-terminal-tasks",
    category: "ide-parity",
    priority: "P1",
    title: "Terminal task runner with persisted tasks",
    status: "partial",
    evidence: [
      "frontend/src/components/TerminalPanel.tsx",
      "frontend/src/components/buildtools/TasksRunner.tsx",
    ],
    blocker:
      "Terminal and tasks exist, but packaged task persistence and error UX are not fully proven.",
    nextAction:
      "Add task schema validation, packaged smoke coverage, and task output linking to proof records.",
  },
  {
    id: "ide-debugger-lsp",
    category: "ide-parity",
    priority: "P1",
    title: "Debugger and LSP integration",
    status: "planned",
    evidence: ["frontend/src/components/EditorPanel.tsx"],
    blocker: "No debugger or language server contract is release-proven.",
    nextAction: "Implement one debugger/LSP path end to end, then generalize the adapter contract.",
  },
  {
    id: "ide-settings-sync",
    category: "ide-parity",
    priority: "P1",
    title: "Settings export, import, and sync",
    status: "partial",
    evidence: [
      "frontend/src/contexts/SettingsContext.tsx",
      "frontend/src/components/modals/SettingsModal.tsx",
    ],
    blocker: "Settings exist locally; export/import/sync is not proven.",
    nextAction: "Add settings export/import, redacted backup, and restore tests.",
  },
  {
    id: "ide-layout-persistence",
    category: "ide-parity",
    priority: "P1",
    title: "Stable pane and layout persistence",
    status: "partial",
    evidence: ["frontend/src/app/page.tsx", "frontend/src/components/StatusBar.tsx"],
    blocker: "Several states persist, but full layout restoration across restart is not tested.",
    nextAction:
      "Persist dock mode, dock size, active panels, splits, and reopened workspace in one schema.",
  },
  {
    id: "universal-toolchain-detector",
    category: "universal-code",
    priority: "P1",
    title: "Toolchain detector for major languages",
    status: "partial",
    evidence: ["scripts/validators", "frontend/src/lib/work-readiness.ts"],
    blocker:
      "Model readiness exists; language/toolchain readiness is not proven for every major stack.",
    nextAction:
      "Add a detector matrix for Python, JS/TS, Rust, Go, Java, C/C++, C#, PHP, Ruby, Swift, Kotlin, and shell.",
  },
  {
    id: "universal-run-test-build",
    category: "universal-code",
    priority: "P1",
    title: "Per-language run, test, build, format, and lint commands",
    status: "partial",
    evidence: ["scripts/validators", "frontend/src/components/BuildCenter.tsx"],
    blocker: "Build Center exists, but commands are not proven across the full language matrix.",
    nextAction:
      "Wire per-language command recipes to workspace detection and add fixture projects for each stack.",
  },
  {
    id: "universal-open-any-repo",
    category: "universal-code",
    priority: "P1",
    title: "Open-any-repository readiness scan",
    status: "partial",
    evidence: ["frontend/src/components/ProjectHub.tsx", "frontend/src/lib/work-readiness.ts"],
    blocker: "Project readiness is not yet a full repository health scan.",
    nextAction:
      "Create a repo scan that reports stack, commands, missing deps, tests, risks, and first verifier.",
  },
  {
    id: "universal-dependency-advisor",
    category: "universal-code",
    priority: "P1",
    title: "Missing dependency installer and advisor",
    status: "planned",
    evidence: ["frontend/src/components/BuildCenter.tsx"],
    blocker: "No audited dependency advisor or safe installer flow is release-proven.",
    nextAction: "Add safe install suggestions with commands, risk labels, and user approval gates.",
  },
  {
    id: "universal-cross-platform",
    category: "universal-code",
    priority: "P1",
    title: "Windows, WSL, Linux, and macOS validation plan",
    status: "planned",
    evidence: ["docs/release"],
    blocker: "Current package proof is Windows-focused and clean-host blocked.",
    nextAction:
      "Define OS matrix, test host requirements, and per-platform installer/workflow transcripts.",
  },
  {
    id: "universal-project-templates",
    category: "universal-code",
    priority: "P1",
    title: "Project templates for common application types",
    status: "partial",
    evidence: [
      "frontend/src/components/ConceptLab.tsx",
      "frontend/src/components/ProjectArchitect.tsx",
    ],
    blocker:
      "Idea guidance exists, but template creation is not proven across all target project classes.",
    nextAction:
      "Add templates for CLI, web app, desktop app, API, library, data/ML, and game projects.",
  },
  {
    id: "universal-repair-loop",
    category: "universal-code",
    priority: "P1",
    title: "Universal repair loop",
    status: "partial",
    evidence: ["scripts/determinex_hive.py", "frontend/src/components/HiveBuildLoop.tsx"],
    blocker:
      "Hive repair primitives exist, but one clean user-facing repair loop for arbitrary repos is not fully proven.",
    nextAction:
      "Prove detect failure, patch, verify, explain, and rollback on a clean fixture repo.",
  },
  {
    id: "agent-pause-resume-cancel",
    category: "agentic",
    priority: "P1",
    title: "Replayable agent lanes with pause, resume, cancel, and retry",
    status: "partial",
    evidence: [
      "frontend/src/components/AgentTrace.tsx",
      "frontend/src/components/HiveBuildLoop.tsx",
    ],
    blocker: "Agent trace exists; durable lane controls are not fully proven.",
    nextAction:
      "Add lane state machine tests and UI controls for pause, resume, cancel, retry, and replay.",
  },
  {
    id: "agent-diff-review",
    category: "agentic",
    priority: "P1",
    title: "Diff review before apply",
    status: "partial",
    evidence: ["frontend/src/app/page.tsx", "frontend/src/components/EditorPanel.tsx"],
    blocker: "Diff editor exists, but review-before-apply is not enforced for agent patches.",
    nextAction: "Require agent patch previews with accept/reject and evidence record links.",
  },
  {
    id: "agent-worktree-isolation-toggle",
    category: "agentic",
    priority: "P1",
    title: "Git worktree isolation choice when starting an agent session",
    status: "planned",
    evidence: ["scripts/determinex_swebench_agent.py", "frontend/src/components/HiveBuildLoop.tsx"],
    blocker:
      "Isolated git worktrees are already used by the compile gate and SWE-bench agent at the script layer, but the IDE's session-start flow exposes no worktree/isolation choice at all -- parity gap vs. VS Code 1.129's worktree checkbox in the agent session picker.",
    nextAction:
      "Add a worktree-isolation toggle to the session-start flow, backed by a Tauri command that creates/cleans up the worktree and binds it to the session record.",
  },
  {
    id: "agent-multi-window-session-view",
    category: "agentic",
    priority: "P2",
    title: "Same agent session viewable from more than one window",
    status: "planned",
    evidence: ["frontend/src/components/AgentTrace.tsx"],
    blocker:
      "AgentTrace lists sessions in one table inside the single main window; there is no dedicated session-server process or second-window view of a running session, unlike VS Code 1.129's agent host process shared across windows.",
    nextAction:
      "Decide whether this needs a real multi-window Tauri architecture (new window + shared session state) before scoping further; this is a bigger architectural change than a single panel and needs an explicit go-ahead.",
  },
  {
    id: "agent-rollback",
    category: "agentic",
    priority: "P1",
    title: "Rollback and checkpoint restore",
    status: "planned",
    evidence: ["sessions", "frontend/src/components/AgentTrace.tsx"],
    blocker: "No audited checkpoint restore flow is available in the IDE.",
    nextAction: "Add checkpoint snapshots, restore command, and post-restore verifier run.",
  },
  {
    id: "agent-budget-controls",
    category: "agentic",
    priority: "P1",
    title: "Budget, time, and token controls",
    status: "partial",
    evidence: ["frontend/src/components/HiveBuildLoop.tsx", "scripts/determinex_hive.py"],
    blocker: "Some budget fields exist; user-facing controls and enforcement proof are incomplete.",
    nextAction:
      "Expose budget caps, timeout caps, retry caps, and cost summaries in the agent lane UI.",
  },
  {
    id: "agent-failure-recovery",
    category: "agentic",
    priority: "P1",
    title: "Failure recovery with exact next action",
    status: "partial",
    evidence: [
      "frontend/src/lib/missionControl.ts",
      "frontend/src/components/MissionControlPanel.tsx",
    ],
    blocker: "Mission Control explains gates; agent-level failure recovery is not uniformly wired.",
    nextAction:
      "Map each agent failure type to a recovery command, evidence path, and user-safe explanation.",
  },
  {
    id: "agent-background-queue",
    category: "agentic",
    priority: "P1",
    title: "Background job queue with logs and artifacts",
    status: "partial",
    evidence: ["frontend/src/components/AgentTrace.tsx", "logs"],
    blocker: "Logs exist, but queued job orchestration is not a single IDE control plane.",
    nextAction:
      "Add a jobs table with command, PID, status, log stream, artifacts, and cancellation.",
  },
  {
    id: "agent-trace-proof-links",
    category: "agentic",
    priority: "P1",
    title: "Agent trace linked to files, commands, tests, and proof",
    status: "partial",
    evidence: [
      "frontend/src/components/AgentTrace.tsx",
      "frontend/src/components/ProofOperatorCenterPanel.tsx",
    ],
    blocker: "Trace and proof surfaces exist separately; cross-links are incomplete.",
    nextAction:
      "Attach every trace step to touched files, command output, verifier result, and proof artifact.",
  },
  {
    id: "agent-repair-this-repo",
    category: "agentic",
    priority: "P1",
    title: "One repair-this-repo flow from clean install",
    status: "partial",
    evidence: [
      "frontend/src/lib/missionControl.ts",
      "frontend/src/lib/releaseGateStatus.ts:first_e2e",
    ],
    blocker: "First E2E is passed in snapshot, but clean-host install proof remains blocked.",
    nextAction:
      "Run a packaged clean-host repair-this-repo transcript and bind it to release evidence.",
  },
  {
    id: "guide-context-aware",
    category: "guide",
    priority: "P1",
    title: "Context-aware guide",
    status: "partial",
    evidence: [
      "frontend/src/components/TeacherOverlay.tsx",
      "frontend/src/components/MissionControlPanel.tsx",
    ],
    blocker:
      "Guide exists, but it does not yet fully inspect current screen, setup state, and failed gates.",
    nextAction:
      "Feed active screen, setup state, release gates, and selected project into guide step resolution.",
  },
  {
    id: "guide-setup-walkthrough",
    category: "guide",
    priority: "P1",
    title: "Setup walkthrough for APIs, local models, Local, Cloak, and Cloud",
    status: "partial",
    evidence: ["frontend/src/components/SetupWizard.tsx", "frontend/src/lib/networkPolicy.ts"],
    blocker:
      "Setup wizard explains core options, but guide-driven setup completion is not fully tied to readiness.",
    nextAction:
      "Add guide actions that open setup sections, validate keys/models, and explain privacy modes.",
  },
  {
    id: "guide-first-project",
    category: "guide",
    priority: "P1",
    title: "First project walkthrough",
    status: "partial",
    evidence: ["frontend/src/components/ConceptLab.tsx", "frontend/src/components/ProjectHub.tsx"],
    blocker: "Idea guidance exists, but a packaged first-project walkthrough is not proven.",
    nextAction:
      "Create a guided first project path that ends with a verifier result and saved project.",
  },
  {
    id: "guide-repair-walkthrough",
    category: "guide",
    priority: "P1",
    title: "Repair walkthrough",
    status: "planned",
    evidence: ["frontend/src/lib/missionControl.ts"],
    blocker: "No dedicated repair tutorial is wired to a real failing repository fixture.",
    nextAction:
      "Add a repair tutorial using a known broken fixture and proof-backed success/failure states.",
  },
  {
    id: "guide-proof-center",
    category: "guide",
    priority: "P1",
    title: "Proof Center walkthrough",
    status: "partial",
    evidence: [
      "frontend/src/components/MissionControlPanel.tsx",
      "frontend/src/app/proof-center/page.tsx",
    ],
    blocker: "Proof guidance exists, but not all evidence links are live and refreshed.",
    nextAction:
      "Add guide cards that open each proof surface and explain passed, partial, blocked, and planned.",
  },
  {
    id: "guide-addons-providers",
    category: "guide",
    priority: "P1",
    title: "Add-ons and providers walkthrough",
    status: "partial",
    evidence: ["frontend/src/components/MarketplacePanel.tsx", "frontend/src/lib/addonStorage.ts"],
    blocker: "Add-on state is migrated, but guide actions for provider setup are not complete.",
    nextAction:
      "Wire guide actions to provider install, API key setup, and model readiness checks.",
  },
  {
    id: "guide-release-gates",
    category: "guide",
    priority: "P1",
    title: "Release gate walkthrough",
    status: "partial",
    evidence: [
      "frontend/src/components/MissionControlPanel.tsx",
      "frontend/src/lib/releaseGateStatus.ts",
    ],
    blocker:
      "Mission Control lists gates; direct execution of runbook commands from the guide is not implemented.",
    nextAction:
      "Add copy/run affordances for safe collector commands and refresh gate status after execution.",
  },
  {
    id: "guide-clickable-actions",
    category: "guide",
    priority: "P1",
    title: "Clickable next actions from guide cards",
    status: "partial",
    evidence: [
      "frontend/src/components/TeacherOverlay.tsx",
      "frontend/src/components/MissionControlPanel.tsx",
    ],
    blocker: "Some navigation exists; guide cards are not universally actionable.",
    nextAction:
      "Add typed guide actions for open panel, run collector, copy command, open evidence, and rerun setup.",
  },
  {
    id: "guide-blocker-explanations",
    category: "guide",
    priority: "P1",
    title: "Why am I blocked explanations from real gate data",
    status: "partial",
    evidence: ["frontend/src/lib/releaseGateStatus.ts", "frontend/src/lib/missionControl.ts"],
    blocker:
      "Gate blockers are displayed, but not translated into per-user remediation workflows everywhere.",
    nextAction:
      "Attach blocker explanations, prerequisites, commands, and success criteria to every blocked gate.",
  },
  {
    id: "extensions-api-contract",
    category: "extensions",
    priority: "P1",
    title: "Determinex extension API contract",
    status: "partial",
    evidence: [
      "frontend/vscode-extension",
      "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md",
      "frontend/src/lib/releaseGateStatus.ts:extension_compat",
    ],
    blocker: "Extension API contract exists, but runtime compatibility evidence has not passed.",
    nextAction:
      "Run VSIX import, Open VSX metadata, activation-event, and sandbox permission smokes.",
  },
  {
    id: "extensions-vscode-migration",
    category: "extensions",
    priority: "P1",
    title: "VS Code settings and workspace migration plan",
    status: "partial",
    evidence: [
      "frontend/vscode-extension/package.json",
      "frontend/vscode-extension/src/extension.ts",
    ],
    blocker:
      "VS Code extension surface is renamed, but workspace/settings migration is not implemented.",
    nextAction:
      "Build migration import for workspace folders, settings, tasks, launch configs, and extensions inventory.",
  },
  {
    id: "extensions-open-vsx-prototype",
    category: "extensions",
    priority: "P1",
    title: "Open VSX compatibility prototype",
    status: "planned",
    evidence: ["frontend/src/lib/successorRoadmap.ts:extension-ecosystem"],
    blocker: "The IDE does not import or run VS Code/Open VSX extensions.",
    nextAction: "Prototype extension metadata import and a limited command contribution bridge.",
  },
  {
    id: "extensions-trust-model",
    category: "extensions",
    priority: "P1",
    title: "Extension trust model",
    status: "partial",
    evidence: [
      "frontend/src/components/MarketplacePanel.tsx",
      "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md",
    ],
    blocker:
      "Trust boundary is defined in contract, but install/runtime enforcement evidence has not passed.",
    nextAction:
      "Attach signed source, permission list, sandbox policy, install prompt, and uninstall cleanup evidence.",
  },
  {
    id: "extensions-install-state",
    category: "extensions",
    priority: "P1",
    title: "Built-in add-on install and uninstall state",
    status: "done",
    evidence: [
      "frontend/src/lib/addonStorage.ts",
      "frontend/src/lib/__tests__/addonStorage.test.ts",
      "commit 9d844aaf5",
    ],
    blocker: "",
    nextAction:
      "Expand install state into real extension package lifecycle when the API contract exists.",
  },
  {
    id: "extensions-community-hub",
    category: "extensions",
    priority: "P1",
    title: "Local registry first, public registry later",
    status: "partial",
    evidence: ["frontend/src/components/MarketplacePanel.tsx", "frontend/src/lib/addons.ts"],
    blocker:
      "Community hub is a local add-on manager; public publishing is intentionally not enabled.",
    nextAction:
      "Implement local registry metadata, package import, trust review, and then plan public publishing.",
  },
  {
    id: "privacy-live-cloak-audit",
    category: "privacy",
    priority: "P1",
    title: "Live Cloak audit ingestion",
    status: "partial",
    evidence: [
      "scripts/determinex_cloak.py",
      "scripts/verify_cloak.py",
      "frontend/src/components/PrivacyCockpit.tsx",
    ],
    blocker: "Cloak tools exist, but live UI ingestion of fresh audit artifacts is incomplete.",
    nextAction:
      "Ingest Cloak audit logs into Privacy Cockpit with timestamps, request counts, and leak verdicts.",
  },
  {
    id: "privacy-redaction-preview",
    category: "privacy",
    priority: "P1",
    title: "Redaction preview before cloud calls",
    status: "planned",
    evidence: ["frontend/src/components/PrivacyCockpit.tsx", "scripts/determinex_cloak.py"],
    blocker: "No universal preflight preview shows exactly what cloud providers will see.",
    nextAction:
      "Add before/after preview, token counts, semantic glossary, and explicit approval for cloud routing.",
  },
  {
    id: "privacy-policy-routing",
    category: "privacy",
    priority: "P1",
    title: "Provider routing by Offline, Cloaked, and Cloud policy",
    status: "partial",
    evidence: [
      "frontend/src/lib/networkPolicy.ts",
      "frontend/playwright-tests/network_policy.spec.ts",
    ],
    blocker: "Network policy exists; enforcement proof across all provider calls is incomplete.",
    nextAction:
      "Route every provider call through a single policy gate and add tests for allowed/blocked calls.",
  },
  {
    id: "privacy-leakage-detector",
    category: "privacy",
    priority: "P1",
    title: "Leakage detector with evidence artifact",
    status: "partial",
    evidence: ["scripts/verify_cloak.py", "docs/SECURITY_POSTURE.md"],
    blocker:
      "Leakage verification exists for Cloak artifacts, but is not continuously collected in the app.",
    nextAction: "Generate a machine-readable leakage report for each cloud-assisted workflow.",
  },
  {
    id: "privacy-fresh-reruns",
    category: "privacy",
    priority: "P1",
    title: "Fresh SWE-bench privacy-cost reruns",
    status: "blocked",
    evidence: ["AGENTS.md:SWE-bench Ablation", "docs/WHITE_PAPER.md"],
    blocker: "Fresh B/E and privacy-cost reruns are required before publication-grade claims.",
    nextAction:
      "Rerun B-Uncloaked and RegionControl cleanly, then compare to fresh Cloaked results.",
  },
  {
    id: "privacy-collector-badges",
    category: "privacy",
    priority: "P1",
    title: "Privacy badges backed by collector output",
    status: "partial",
    evidence: [
      "frontend/src/components/PrivacyCockpit.tsx",
      "frontend/src/lib/releaseGateStatus.ts",
    ],
    blocker: "Some badges are static copy rather than fresh collector-backed status.",
    nextAction: "Bind every privacy badge to collector output, timestamp, and evidence path.",
  },
  {
    id: "execution-unified-runner",
    category: "execution",
    priority: "P2",
    title: "Unified runner UI for local shell, Docker, WSL, and remote hosts",
    status: "partial",
    evidence: [
      "frontend/src/components/BuildCenter.tsx",
      "frontend/src/components/TerminalPanel.tsx",
    ],
    blocker: "Execution surfaces exist, but no single runner spans all targets.",
    nextAction:
      "Create runner target schema and one UI for local, WSL, Docker, and remote execution.",
  },
  {
    id: "execution-remote-reservations",
    category: "execution",
    priority: "P2",
    title: "Remote job reservations and status",
    status: "partial",
    evidence: ["scripts/pb_hetzner_pool.py", "CAMPAIGN_DIRECTIVE_001.md"],
    blocker: "Remote reservations are script-first and not surfaced as IDE state.",
    nextAction: "Expose remote reservations, active jobs, leases, and queue state in the IDE.",
  },
  {
    id: "execution-log-streaming",
    category: "execution",
    priority: "P2",
    title: "Log streaming and artifact pullback",
    status: "partial",
    evidence: ["logs", "frontend/src/components/AgentTrace.tsx"],
    blocker: "Logs and artifacts exist, but streaming/pullback is not unified.",
    nextAction: "Add log stream panes with artifact discovery, download, and proof attachment.",
  },
  {
    id: "execution-remote-setup",
    category: "execution",
    priority: "P2",
    title: "Remote host setup wizard",
    status: "planned",
    evidence: ["docs/hetzner_docker_tooling.md", "scripts/pb_hetzner_pool.py"],
    blocker: "Remote host setup is documented and scripted, not guided in the app.",
    nextAction:
      "Add remote host preflight for SSH, Docker, disk, memory, keys, and runner compatibility.",
  },
  {
    id: "execution-disk-monitor",
    category: "execution",
    priority: "P2",
    title: "Container health and disk-space monitor",
    status: "partial",
    evidence: ["frontend/src/components/HealthMap.tsx", "docs/hetzner_docker_tooling.md"],
    blocker:
      "Health surfaces exist, but C/T/temp/build cleanup and remote disk monitors are not one flow.",
    nextAction:
      "Add local and remote disk inventory with safe cleanup recommendations and proof logs.",
  },
  {
    id: "execution-safe-cleanup",
    category: "execution",
    priority: "P2",
    title: "Safe cleanup tools for C, T, temp, and build artifacts",
    status: "planned",
    evidence: ["scripts/release"],
    blocker: "No audited cleanup UI exists for user-visible storage recovery.",
    nextAction:
      "Build a read-only inventory first, then explicit per-path cleanup with before/after byte counts.",
  },
  {
    id: "quality-playwright-primary",
    category: "quality",
    priority: "P2",
    title: "Playwright E2E suite for every primary screen",
    status: "partial",
    evidence: ["frontend/playwright-tests", "assurance/evidence/first_gui_hive_ipc"],
    blocker: "Rendered QA exists for selected flows, not every primary screen.",
    nextAction:
      "Add Playwright coverage for hub, work, space, proof, tools, setup, guide, and release dashboard.",
  },
  {
    id: "quality-packaged-smoke",
    category: "quality",
    priority: "P2",
    title: "Packaged-app smoke tests",
    status: "partial",
    evidence: ["assurance/evidence/determinex_download_bundle_20260707/download_manifest.json"],
    blocker: "Package exists, but clean-host packaged smoke remains blocked.",
    nextAction:
      "Run packaged executable smoke on clean host and save screenshots, logs, and uninstall proof.",
  },
  {
    id: "quality-tauri-ipc-contract",
    category: "quality",
    priority: "P2",
    title: "Tauri IPC contract tests",
    status: "partial",
    evidence: ["frontend/src-tauri/src/ipc_hive", "frontend/src-tauri/tests"],
    blocker: "IPC tests exist, but every UI command is not covered by a stable contract test.",
    nextAction:
      "Generate IPC command inventory and require request/response tests for each public command.",
  },
  {
    id: "quality-installer-tests",
    category: "quality",
    priority: "P2",
    title: "Installer tests",
    status: "partial",
    evidence: [
      "scripts/release/build_release_package.ps1",
      "frontend/src/lib/releaseGateStatus.ts",
    ],
    blocker: "Installer package exists; install/uninstall automation is not passed on clean host.",
    nextAction: "Automate installer launch, app start, setup, smoke, uninstall, and residue scan.",
  },
  {
    id: "quality-addon-provider-tests",
    category: "quality",
    priority: "P2",
    title: "Add-on and provider tests",
    status: "partial",
    evidence: [
      "frontend/src/lib/__tests__/addonStorage.test.ts",
      "frontend/src/components/MarketplacePanel.tsx",
    ],
    blocker:
      "Add-on storage is tested; provider install/auth/readiness flows are not fully covered.",
    nextAction:
      "Add tests for install/uninstall, provider key validation, local model readiness, and guide integration.",
  },
  {
    id: "quality-setup-rerun",
    category: "quality",
    priority: "P2",
    title: "Setup rerun tests",
    status: "done",
    evidence: ["frontend/src/lib/__tests__/networkPolicy.test.ts", "commit d50f66f94"],
    blocker: "",
    nextAction: "Keep setup rerun coverage in the packaged smoke suite.",
  },
  {
    id: "quality-hardware-detection",
    category: "quality",
    priority: "P2",
    title: "Hardware detection including VRAM edge cases",
    status: "partial",
    evidence: ["frontend/src-tauri/src/hardware.rs", "frontend/src/components/SetupWizard.tsx"],
    blocker: "VRAM bug was addressed earlier, but cross-device hardware fixtures are not complete.",
    nextAction:
      "Add fixture tests for physical VRAM, inference budget, CPU-only, low-RAM, and multi-GPU hosts.",
  },
  {
    id: "quality-accessibility",
    category: "quality",
    priority: "P2",
    title: "Accessibility and keyboard navigation pass",
    status: "planned",
    evidence: ["frontend/src/components"],
    blocker: "No full accessibility audit is attached to release gates.",
    nextAction: "Run keyboard, focus, contrast, labels, reduced-motion, and screen-reader checks.",
  },
  {
    id: "quality-performance-budget",
    category: "quality",
    priority: "P2",
    title: "Performance budget for startup, project open, search, and agent run",
    status: "planned",
    evidence: ["frontend/src/components/HealthMap.tsx"],
    blocker: "No release performance budget and measurement artifact exists.",
    nextAction: "Add startup, render, project-open, search, and agent-run timing collectors.",
  },
  {
    id: "quality-crash-log-viewer",
    category: "quality",
    priority: "P2",
    title: "Crash and error telemetry local log viewer",
    status: "partial",
    evidence: ["frontend/src/components/ErrorToast.tsx", "frontend/src/components/HealthMap.tsx"],
    blocker: "Errors surface as toasts; persistent crash/log viewer is incomplete.",
    nextAction: "Add local error log browser with export bundle for support and proof evidence.",
  },
  {
    id: "diff-proof-status",
    category: "differentiators",
    priority: "P2",
    title: "Proof-native status on every AI action",
    status: "partial",
    evidence: [
      "frontend/src/components/ProofOperatorCenterPanel.tsx",
      "scripts/claim_scanner/day_one_public_claim_scanner.py",
    ],
    blocker:
      "Proof surfaces exist, but every AI action does not yet display current verifier status.",
    nextAction:
      "Require each AI action to show proposed, running, passed, failed, or blocked proof state.",
  },
  {
    id: "diff-teach-me",
    category: "differentiators",
    priority: "P2",
    title: "Teach me what changed after every fix",
    status: "partial",
    evidence: [
      "frontend/src/components/TeacherOverlay.tsx",
      "frontend/src/components/AgentTrace.tsx",
    ],
    blocker: "Guide and trace exist; post-fix teaching is not automatic.",
    nextAction:
      "Generate a short explanation from diff, verifier output, and changed files after each repair.",
  },
  {
    id: "diff-repo-map",
    category: "differentiators",
    priority: "P2",
    title: "Automatic repository map and architecture summary",
    status: "partial",
    evidence: [
      "frontend/src/components/ProjectArchitect.tsx",
      "frontend/src/components/BrainStage.tsx",
    ],
    blocker:
      "Architecture concepts exist, but automatic repo map output is not proven for arbitrary repos.",
    nextAction:
      "Build a repo-map collector and render modules, commands, tests, risks, and ownership hints.",
  },
  {
    id: "diff-multi-agent-debate",
    category: "differentiators",
    priority: "P2",
    title: "Multi-agent debate with oracle as judge",
    status: "partial",
    evidence: ["frontend/src/components/MatrixExecutionDisplay.tsx", "scripts/determinex_hive.py"],
    blocker: "Multi-agent primitives exist, but debate is not a polished user workflow.",
    nextAction:
      "Add compare-proposals mode where candidates are scored by deterministic verifier output.",
  },
  {
    id: "diff-flywheel-view",
    category: "differentiators",
    priority: "P2",
    title: "Training flywheel view",
    status: "partial",
    evidence: ["frontend/src/components/FlywheelFeed.tsx", "scripts/determinex_flywheel.py"],
    blocker:
      "Flywheel surface exists, but reusable failure-to-fix examples are not linked from every run.",
    nextAction: "Attach failure, fix, verifier, and training row links to each completed workflow.",
  },
  {
    id: "diff-benchmark-cockpit",
    category: "differentiators",
    priority: "P2",
    title: "Benchmark cockpit for ProgramBench and SWE-bench validation",
    status: "partial",
    evidence: [
      "frontend/src/components/BenchmarkRunner.tsx",
      "corpus/programbench/eval_index.json",
    ],
    blocker: "Benchmark tooling exists, but public claims remain gated by fresh official evidence.",
    nextAction:
      "Render current benchmark status from canonical indices and block stale or cached overclaims.",
  },
  {
    id: "diff-shippable-audit",
    category: "differentiators",
    priority: "P2",
    title: "One-click make-this-project-shippable audit",
    status: "planned",
    evidence: [
      "frontend/src/components/BuildCenter.tsx",
      "frontend/src/components/MissionControlPanel.tsx",
    ],
    blocker:
      "No single project shipping audit combines tests, security, dependencies, docs, packaging, and release gates.",
    nextAction:
      "Create a shippability collector that emits exact blockers and proof paths for a selected repo.",
  },
  {
    id: "diff-project-memory",
    category: "differentiators",
    priority: "P2",
    title: "Natural-language project memory that is searchable and bounded",
    status: "partial",
    evidence: [
      "frontend/src-tauri/tests/companion_rag_natural_language_query_eval.rs",
      "docs/companions",
    ],
    blocker:
      "Memory/RAG tests exist, but project memory is not a polished user-facing control plane.",
    nextAction:
      "Expose project memory sources, citations, freshness, scope, and delete/export controls.",
  },
  {
    id: "diff-local-first",
    category: "differentiators",
    priority: "P2",
    title: "Local-first mode that feels first-class",
    status: "partial",
    evidence: ["frontend/src/lib/networkPolicy.ts", "frontend/src/components/SetupWizard.tsx"],
    blocker:
      "Offline/local mode exists, but missing model/toolchain flows still need better recovery.",
    nextAction:
      "Make local model install, health, fallback, and repair guidance complete without cloud keys.",
  },
  {
    id: "diff-cloud-assisted-privacy",
    category: "differentiators",
    priority: "P2",
    title: "Cloud-assisted mode with visible privacy guarantees",
    status: "partial",
    evidence: ["frontend/src/components/PrivacyCockpit.tsx", "scripts/determinex_cloak.py"],
    blocker:
      "Cloak exists, but live cloud-call previews and fresh leakage evidence are incomplete.",
    nextAction:
      "Show exactly what leaves the machine, why, through which provider, and with which audit verdict.",
  },
];

export function industryBacklogStatusLabel(status: IndustryBacklogStatus): string {
  switch (status) {
    case "done":
      return "Checked";
    case "partial":
      return "Partial";
    case "blocked":
      return "Blocked";
    case "planned":
      return "Planned";
  }
}

export function isIndustryBacklogItemChecked(item: IndustryIdeBacklogItem): boolean {
  return item.status === "done";
}

export function getIndustryIdeBacklogSummary(
  items: IndustryIdeBacklogItem[] = DETERMINEX_INDUSTRY_IDE_BACKLOG
): IndustryIdeBacklogSummary {
  const summary: IndustryIdeBacklogSummary = {
    done: 0,
    partial: 0,
    blocked: 0,
    planned: 0,
    total: items.length,
    checked: 0,
  };
  for (const item of items) {
    summary[item.status] += 1;
    if (isIndustryBacklogItemChecked(item)) summary.checked += 1;
  }
  return summary;
}

export function getIndustryIdeCategorySummary(categoryId: IndustryBacklogCategoryId) {
  return getIndustryIdeBacklogSummary(
    DETERMINEX_INDUSTRY_IDE_BACKLOG.filter((item) => item.category === categoryId)
  );
}

export function getTopIndustryIdeNextActions(limit = 12): IndustryIdeBacklogItem[] {
  return DETERMINEX_INDUSTRY_IDE_BACKLOG.filter((item) => !isIndustryBacklogItemChecked(item))
    .sort((a, b) => {
      const priorityDelta =
        INDUSTRY_BACKLOG_PRIORITY_ORDER[a.priority] - INDUSTRY_BACKLOG_PRIORITY_ORDER[b.priority];
      if (priorityDelta !== 0) return priorityDelta;
      const statusDelta =
        INDUSTRY_BACKLOG_STATUS_ORDER[a.status] - INDUSTRY_BACKLOG_STATUS_ORDER[b.status];
      if (statusDelta !== 0) return statusDelta;
      return a.id.localeCompare(b.id);
    })
    .slice(0, limit);
}
