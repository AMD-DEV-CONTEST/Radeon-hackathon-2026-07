import {
  DETERMINEX_RELEASE_GATES,
  type ReleaseGateStatus,
  type ReleaseGateView,
} from "@/lib/releaseGateStatus";
import { type SuccessorPillar, DETERMINEX_SUCCESSOR_PILLARS } from "@/lib/successorRoadmap";

export type MissionControlMissionId =
  | "release-readiness"
  | "first-run-proof"
  | "vscode-successor"
  | "llm-program-advisor"
  | "agent-operations"
  | "proof-center";

export type MissionControlMission = {
  id: MissionControlMissionId;
  title: string;
  audience: string;
  objective: string;
  userOutcome: string;
  proofBoundary: string;
  primaryAction: string;
  gateIds: string[];
  pillarIds: string[];
};

export type MissionControlResolvedMission = MissionControlMission & {
  gates: ReleaseGateView[];
  pillars: SuccessorPillar[];
  counts: Record<ReleaseGateStatus, number>;
  totalGates: number;
  passedGates: number;
};

export const MISSION_CONTROL_CLAIM_BOUNDARY =
  "Mission Control guides operators through current evidence and runbooks; it does not grant release readiness or replace deterministic verifiers.";

export const DETERMINEX_MISSION_CONTROL_MISSIONS: MissionControlMission[] = [
  {
    id: "release-readiness",
    title: "Prepare a release",
    audience: "Release operator",
    objective: "Walk the remaining release gates in the order that reduces launch risk fastest.",
    userOutcome:
      "Know exactly why Determinex is not public-release ready yet and which proof to collect next.",
    proofBoundary:
      "A completed checklist here is advisory until the release gate collector marks every gate passed.",
    primaryAction:
      "Start with blocked gates, then close partial gates, then refresh the collector.",
    gateIds: [
      "first_e2e",
      "clean_host",
      "windows_trust",
      "legal_public_distribution",
      "windows_msi",
      "linux_packages",
      "programbench_200",
      "swebench_fresh",
      "installer",
      "extension_compat",
      "internal_rename",
      "sbom",
    ],
    pillarIds: ["release-cockpit", "proof-native", "workbench-parity"],
  },
  {
    id: "first-run-proof",
    title: "Prove the first user workflow",
    audience: "Builder lane owner",
    objective: "Move the first E2E workflow from exact blocker to a fresh passing transcript.",
    userOutcome:
      "A user can see the path from project idea to verified run without reading evidence folders.",
    proofBoundary:
      "Builder health is only a preflight proof; the E2E workflow remains blocked until a full transcript passes.",
    primaryAction:
      "Create or reset the E2E session with enough budget, then rerun from a quiet local model runtime.",
    gateIds: ["first_e2e", "clean_host"],
    pillarIds: ["agentic-workbench", "execution-fabric"],
  },
  {
    id: "vscode-successor",
    title: "Become the VS Code successor",
    audience: "IDE product owner",
    objective:
      "Track the compatibility, migration, and workbench-parity locks needed for a natural VS Code transition.",
    userOutcome:
      "A VS Code user understands what transfers today and what remains a planned compatibility layer.",
    proofBoundary:
      "Roadmap parity is not extension compatibility. Existing Open VSX support remains planned until implemented and verified.",
    primaryAction:
      "Define the extension API, import path, trust model, and clean workspace migration proof.",
    gateIds: ["extension_compat", "internal_rename", "clean_host"],
    pillarIds: ["workbench-parity", "extension-ecosystem"],
  },
  {
    id: "llm-program-advisor",
    title: "Brief any LLM on a program",
    audience: "Developer using local or external models",
    objective:
      "Generate a verifier-first advisory packet for creation, upkeep, or repair without tying the workflow to one provider.",
    userOutcome:
      "A user can hand Codex, Claude, Gemini, OpenAI, Ollama, or another model the same bounded program brief.",
    proofBoundary:
      "The advisory packet is model-neutral guidance, not proof that every language or program is verified-supported.",
    primaryAction:
      "Generate the advisory packet, inspect the verifier plan, then run the listed checks before trusting output.",
    gateIds: ["first_e2e", "clean_host", "extension_compat"],
    pillarIds: ["agentic-workbench", "proof-native", "privacy-governance"],
  },
  {
    id: "agent-operations",
    title: "Operate agent lanes safely",
    audience: "Agent operator",
    objective:
      "Keep background agents observable, bounded, and recoverable while they work on real repositories.",
    userOutcome:
      "Operators can see which lane is active, why it is blocked, and how to retry without resource floods.",
    proofBoundary:
      "Visible agent controls are not proof of correctness; verifier output and evidence records remain authoritative.",
    primaryAction:
      "Use health, trace, runbook, and evidence panels together before launching or retrying long-running work.",
    gateIds: ["first_e2e", "clean_host"],
    pillarIds: ["agentic-workbench", "execution-fabric", "privacy-governance"],
  },
  {
    id: "proof-center",
    title: "Explain proof to a new user",
    audience: "New Determinex user",
    objective:
      "Translate proof status into visible, helpful guidance instead of raw evidence folder spelunking.",
    userOutcome:
      "A user can understand passed, partial, blocked, and planned states in one screen.",
    proofBoundary:
      "Evidence visibility does not certify support, approval, or readiness by itself.",
    primaryAction:
      "Read the blocker, open the evidence path, run the listed collector, then compare the refreshed status.",
    gateIds: [
      "sbom",
      "installer",
      "windows_trust",
      "legal_public_distribution",
      "windows_msi",
      "linux_packages",
      "clean_host",
      "first_e2e",
      "programbench_200",
      "swebench_fresh",
      "extension_compat",
      "internal_rename",
    ],
    pillarIds: ["proof-native", "release-cockpit", "privacy-governance"],
  },
];

const EMPTY_COUNTS: Record<ReleaseGateStatus, number> = {
  passed: 0,
  partial: 0,
  blocked: 0,
  deferred: 0,
  planned: 0,
};

export function resolveMissionControlMission(
  missionId: MissionControlMissionId,
  gatesSnapshot: typeof DETERMINEX_RELEASE_GATES = DETERMINEX_RELEASE_GATES
): MissionControlResolvedMission {
  const mission =
    DETERMINEX_MISSION_CONTROL_MISSIONS.find((candidate) => candidate.id === missionId) ??
    DETERMINEX_MISSION_CONTROL_MISSIONS[0];
  const gates = mission.gateIds
    .map((gateId) => gatesSnapshot.gates.find((gate) => gate.gateId === gateId))
    .filter((gate): gate is ReleaseGateView => Boolean(gate));
  const pillars = mission.pillarIds
    .map((pillarId) => DETERMINEX_SUCCESSOR_PILLARS.find((pillar) => pillar.id === pillarId))
    .filter((pillar): pillar is SuccessorPillar => Boolean(pillar));
  const counts = gates.reduce(
    (acc, gate) => {
      acc[gate.status] += 1;
      return acc;
    },
    { ...EMPTY_COUNTS }
  );

  return {
    ...mission,
    gates,
    pillars,
    counts,
    totalGates: gates.length,
    passedGates: counts.passed,
  };
}

export function getMissionControlCompletionLabel(mission: MissionControlResolvedMission): string {
  return `${mission.passedGates}/${mission.totalGates} gates passed`;
}
