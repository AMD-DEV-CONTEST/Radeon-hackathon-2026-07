import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MatrixExecutionDisplay, type AgentStatus } from "@/components/MatrixExecutionDisplay";

/**
 * The MoA pipeline view.
 *
 * WHY THIS EXISTS
 * This file used to contain ONLY constants, the AgentStatus type and a props interface --
 * no component. React hooks, four icons and VanguardToggle were imported and unused: the
 * body had been deleted and the scaffolding left behind. page.tsx imported the TYPE alone,
 * so the three-agent pipeline was never rendered anywhere, while every input it needs
 * (agentStatus, matrixLogs, executeAbort, retryCount) already existed and was live.
 *
 * The component was implemented against the surviving props interface, so these tests pin
 * the behaviour that interface implies -- particularly the states that must NOT be guessed:
 * an unrecorded acceptance is not a pass, and a failed stage is not a completed one.
 */

const IDLE: AgentStatus = {
  currentAgent: null,
  isExecuting: false,
  verdict: null,
  confidence: null,
  accepted: null,
  error: null,
};

function renderIt(status: Partial<AgentStatus>, logs: string[] = [], onAbort = vi.fn()) {
  const merged = { ...IDLE, ...status };
  render(
    <MatrixExecutionDisplay agentStatus={merged} logs={logs} onAbort={onAbort} retryCount={0} />
  );
  return onAbort;
}

const stageState = (id: string) =>
  screen.getByTestId(`matrix-stage-${id}`).getAttribute("data-state");

describe("MatrixExecutionDisplay", () => {
  it("renders all three MoA stages", () => {
    renderIt({});
    for (const id of ["sentinel", "engineer", "observer"]) {
      expect(screen.getByTestId(`matrix-stage-${id}`)).toBeTruthy();
    }
  });

  it("marks the running agent active and earlier ones done", () => {
    renderIt({ currentAgent: "engineer", isExecuting: true });
    expect(stageState("sentinel")).toBe("done");
    expect(stageState("engineer")).toBe("active");
    expect(stageState("observer")).toBe("idle");
  });

  it("shows every stage done once a verdict has landed", () => {
    renderIt({ verdict: "CLEAN", accepted: true, confidence: 0.9 });
    for (const id of ["sentinel", "engineer", "observer"]) {
      expect(stageState(id)).toBe("done");
    }
  });

  it("marks the failing stage failed rather than done", () => {
    // A hard abort in the engineer stage must not render as a completed pipeline.
    renderIt({ verdict: "PARTIAL", error: { stage: "engineer", message: "compile failed" } });
    expect(stageState("engineer")).toBe("failed");
    expect(screen.getByText(/compile failed/)).toBeTruthy();
  });

  it("names the model each agent runs", () => {
    // "Which agent" is half the question; "running which model" is the half that makes a
    // run reproducible. Pinned elsewhere against CURRENT_MODEL_IDS.
    renderIt({});
    expect(screen.getByText("determinex-engineer-v11-dsl")).toBeTruthy();
    expect(screen.getByText("determinex-observer-v6-dsl")).toBeTruthy();
    expect(screen.getByText("determinex-sentinel-v5-dsl")).toBeTruthy();
  });

  it("offers Abort only while executing", () => {
    renderIt({ isExecuting: true, currentAgent: "sentinel" });
    expect(screen.getByTitle("Abort the running pipeline")).toBeTruthy();
  });

  it("does not offer Abort when idle", () => {
    renderIt({});
    expect(screen.queryByTitle("Abort the running pipeline")).toBeNull();
  });

  it("says so when acceptance was never recorded", () => {
    // accepted === null is neither pass nor fail. Defaulting it either way would be the
    // overclaim pattern: a verdict with no acceptance decision rendered as accepted.
    renderIt({ verdict: "CLEAN", accepted: null, confidence: 0.5 });
    expect(screen.getByText(/acceptance not recorded/)).toBeTruthy();
  });

  it("renders a bounded log tail rather than thousands of lines", () => {
    const logs = Array.from({ length: 500 }, (_, i) => `line ${i}`);
    renderIt({}, logs);
    expect(screen.getByText("line 499")).toBeTruthy();
    expect(screen.queryByText("line 0")).toBeNull();
  });

  it("renders nothing log-shaped when there are no logs", () => {
    renderIt({}, []);
    expect(screen.queryByText(/line /)).toBeNull();
  });
});
