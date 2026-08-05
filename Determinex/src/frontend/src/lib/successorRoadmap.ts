export type SuccessorPillarStatus = "live" | "partial" | "planned" | "blocked";

export type SuccessorPillar = {
  id: string;
  title: string;
  status: SuccessorPillarStatus;
  releaseReady: false;
  current: string;
  nextLock: string;
  blocker: string;
};

export const DETERMINEX_SUCCESSOR_BRAND_BOUNDARY = {
  publicName: "Determinex",
  formerPublicName: "Determinex",
  renamedOn: "2026-07-02",
  legacyNamespace:
    "Internal determinex_* scripts, DETERMINEX_* environment variables, model tags, repository paths, and historical docs remain until the coordinated internal rename.",
  rule: "User-facing product surfaces should say Determinex. Legacy implementation identifiers are allowed only when they name real files, commands, env vars, model tags, paths, or historical evidence.",
} as const;

export const DETERMINEX_SUCCESSOR_PILLARS: SuccessorPillar[] = [
  {
    id: "workbench-parity",
    title: "Workbench parity",
    status: "partial",
    releaseReady: false,
    current:
      "The Tauri/Next shell, Monaco editor, terminal dock, project hub, command palette, and attachable tools are present.",
    nextLock:
      "Make repository open, edit, diff, test, task, search, settings, and persisted layout flows work from a clean install.",
    blocker: "VS Code extension compatibility and workspace migration are not complete.",
  },
  {
    id: "proof-native",
    title: "Proof-native development",
    status: "partial",
    releaseReady: false,
    current:
      "Proof Center, oracle health, evidence files, claim guards, and benchmark surfaces exist as first-class workbench concepts.",
    nextLock:
      "Bind every product claim and user-visible readiness badge to a current collector, evidence path, and verifier.",
    blocker: "Several panels still expose status copy without live collector-backed proof.",
  },
  {
    id: "agentic-workbench",
    title: "Agentic workbench",
    status: "partial",
    releaseReady: false,
    current:
      "Hive sessions, agent trace, model slots, provider routing, and oracle-gated workflow primitives exist.",
    nextLock:
      "Ship replayable background lanes with pause, resume, diff review, approval, and exact failure recovery.",
    blocker:
      "First end-to-end user workflow transcript remains gated on local builder health and clean rerun evidence.",
  },
  {
    id: "execution-fabric",
    title: "Local and remote execution fabric",
    status: "partial",
    releaseReady: false,
    current:
      "Local terminal execution, ProgramBench tooling, Docker harnesses, and Hetzner workflow scripts exist.",
    nextLock:
      "Expose one operator-safe runner UI for local tasks, containers, remote shards, logs, reservations, and pullback.",
    blocker:
      "Remote benchmark orchestration is still tool-script first, not a polished IDE control plane.",
  },
  {
    id: "privacy-governance",
    title: "Privacy and governance cockpit",
    status: "partial",
    releaseReady: false,
    current:
      "Network policy settings, Project Cloak surfaces, claim scanners, and governance docs define the current boundary.",
    nextLock:
      "Replace static privacy copy with live Cloak audit ingestion, redaction previews, and policy-scoped provider routing.",
    blocker:
      "Fresh privacy-cost reruns and live leakage collectors are still required for publication-grade claims.",
  },
  {
    id: "extension-ecosystem",
    title: "VS Code/Open VSX compatibility",
    status: "planned",
    releaseReady: false,
    current:
      "A tools registry and marketplace-style shell exist; the packaged VS Code extension remains the bridge surface.",
    nextLock:
      "Define the Determinex extension API, import path, trust model, and compatibility story for existing VS Code workflows.",
    blocker:
      "The IDE does not yet run or import VS Code/Open VSX extensions as a compatibility layer.",
  },
  {
    id: "release-cockpit",
    title: "Release cockpit",
    status: "partial",
    releaseReady: false,
    current:
      "Evidence ledgers, overclaim guards, SBOM scripts, installer notes, and release readiness docs exist. The gate " +
      "collector below reads this data live -- SBOM, installer, MSI, Linux packages, legal, and first-E2E now pass.",
    nextLock:
      "Close the clean-host install proof gate, then run the deferred ProgramBench/SWE-bench/extension-compat/internal-rename gates before claiming full release readiness.",
    blocker:
      // Kept in sync with the live "Release gate collector" section manually as of 2026-07-14
      // (live: assurance/evidence/determinex_release_gate_status/release_gates_*.json) --
      // re-check against that panel's "Live gate status" line before editing this string again.
      "Clean-host install proof is blocked (installer hash mismatch); ProgramBench 200/200, fresh SWE-bench reruns, extension compatibility, and the internal rename remain deferred.",
  },
];

export const DETERMINEX_SUCCESSOR_NEXT_LOCKS = [
  "Clean-host install and first-run workspace open proof",
  "VS Code workspace and settings migration plan",
  "Extension API and marketplace compatibility contract",
  "Collector-backed privacy, proof, and release readiness badges",
  "Replayable agent lane controls with durable approvals",
  "Unified local, container, and remote runner cockpit",
] as const;

export function successorStatusLabel(status: SuccessorPillarStatus): string {
  switch (status) {
    case "live":
      return "Live";
    case "partial":
      return "Partial";
    case "planned":
      return "Planned";
    case "blocked":
      return "Blocked";
  }
}
