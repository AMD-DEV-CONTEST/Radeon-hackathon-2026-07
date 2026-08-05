import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MissionControlPanel } from "../MissionControlPanel";
import {
  DETERMINEX_MISSION_CONTROL_MISSIONS,
  MISSION_CONTROL_CLAIM_BOUNDARY,
  getMissionControlCompletionLabel,
  resolveMissionControlMission,
} from "@/lib/missionControl";
import { DETERMINEX_RELEASE_GATES } from "@/lib/releaseGateStatus";

describe("MissionControlPanel", () => {
  it("renders an interactive Determinex guide without granting release readiness", () => {
    render(<MissionControlPanel />);

    expect(screen.getByText("Determinex Mission Control")).toBeInTheDocument();
    expect(screen.getByTestId("mission-control-boundary")).toHaveTextContent(
      MISSION_CONTROL_CLAIM_BOUNDARY
    );
    expect(DETERMINEX_RELEASE_GATES.releaseReady).toBe(false);
    expect(DETERMINEX_RELEASE_GATES.authorityGranted).toBe(false);
  });

  it("binds every mission to at least one current release gate", () => {
    for (const mission of DETERMINEX_MISSION_CONTROL_MISSIONS) {
      const resolved = resolveMissionControlMission(mission.id);
      expect(resolved.totalGates).toBeGreaterThan(0);
      expect(getMissionControlCompletionLabel(resolved)).toMatch(/\d+\/\d+ gates passed/);
      expect(resolved.gates.every((gate) => gate.releaseReady === false)).toBe(true);
    }
  });

  it("starts on release readiness and shows exact clean-host blocker guidance", () => {
    render(<MissionControlPanel />);

    expect(
      within(screen.getByTestId("mission-active-card")).getByText("Prepare a release")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Current runner cannot access Docker Desktop state; rerun the clean-host probe outside the sandbox."
      )
    ).toBeInTheDocument();
    expect(screen.getAllByText(/full_release_closure.py/).length).toBeGreaterThan(0);
  });

  it("switches missions and updates the next-action focus", () => {
    render(<MissionControlPanel />);

    fireEvent.click(screen.getByTestId("mission-tab-vscode-successor"));

    const nextAction = screen.getByTestId("mission-next-action");
    expect(
      within(screen.getByTestId("mission-active-card")).getByText("Become the VS Code successor")
    ).toBeInTheDocument();
    expect(within(nextAction).getByText("VS Code/Open VSX compatibility")).toBeInTheDocument();
    expect(within(nextAction).getByText("Deferred")).toBeInTheDocument();
    expect(
      within(nextAction).getByText(/runtime compatibility packet has not passed/)
    ).toBeInTheDocument();
  });

  it("includes an LLM-neutral program advisor mission with a proof boundary", () => {
    const mission = DETERMINEX_MISSION_CONTROL_MISSIONS.find(
      (candidate) => candidate.id === "llm-program-advisor"
    );
    expect(mission).toBeDefined();
    expect(mission?.userOutcome).toMatch(/Codex, Claude, Gemini, OpenAI, Ollama/);
    expect(mission?.proofBoundary).toMatch(/not proof that every language or program/);

    render(<MissionControlPanel />);
    fireEvent.click(screen.getByTestId("mission-tab-llm-program-advisor"));

    expect(
      within(screen.getByTestId("mission-active-card")).getByText("Brief any LLM on a program")
    ).toBeInTheDocument();
    expect(screen.getByText(/model-neutral guidance/)).toBeInTheDocument();
  });
});
