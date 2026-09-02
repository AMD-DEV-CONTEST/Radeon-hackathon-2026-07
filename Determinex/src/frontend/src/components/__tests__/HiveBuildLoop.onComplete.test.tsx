import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { HiveBuildLoop, type HiveBuildCompletionResult } from "../HiveBuildLoop";

// The proof-pipeline gap this closes: HiveBuildLoop previously had NO completion callback at
// all, so a real compiler-oracle-verified build result never reached agentStatus / the Proof
// rail. These tests exist specifically to catch the false-positive/false-negative risk that
// deferred this wiring in the first place -- onComplete must fire the RIGHT verdict, exactly
// once, and never for an intermediate (non-terminal) status.

function makeStep(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 1,
    instruction: "write foo.rs",
    status: "complete",
    target_file: "foo.rs",
    write_mode: "create",
    compiler_result: "PASS",
    compiler_output: "",
    monitor_verdict: "CLEAN",
    adjudication_score: 1,
    retries: 0,
    quality: "good",
    ...overrides,
  };
}

const sessionStatusMock = vi.fn();

vi.mock("../../lib/api", () => ({
  getHiveSessionStatus: (...args: unknown[]) => sessionStatusMock(...args),
  runHiveSession: vi.fn(async () => ({})),
  killHiveSession: vi.fn(async () => ({})),
  streamHiveSessionLog: vi.fn(async () => ({})),
  readHiveWorkspaceFile: vi.fn(async () => null),
  invokeSafe: vi.fn(async () => null),
  exploreWorkspace: vi.fn(async () => ({ files: [] })),
  diagnoseWorkspace: vi.fn(async () => ({})),
  probeHardware: vi.fn(async () => null),
  recommendedAmplifyK: vi.fn(() => 6),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
}));

describe("HiveBuildLoop onComplete", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fires with phase='done' and accepted=true when every step compiles clean", async () => {
    sessionStatusMock.mockResolvedValue({
      session_id: "s1",
      lang: "rust",
      project_root: "/tmp/s1",
      steps: [makeStep({ id: 1, status: "complete" }), makeStep({ id: 2, status: "complete" })],
      api_cost_usd: 0,
      session_budget_usd: 1,
      budget_exhausted: false,
      scaffolding_validated: true,
      created_at: "",
      updated_at: "",
    });

    const onComplete = vi.fn();
    render(<HiveBuildLoop sessionId="s1" onComplete={onComplete} />);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    const result: HiveBuildCompletionResult = onComplete.mock.calls[0][0];
    expect(result.phase).toBe("done");
    expect(result.sessionId).toBe("s1");
    expect(result.stepCount).toBe(2);
    expect(result.completeCount).toBe(2);
    expect(result.failedCount).toBe(0);
  });

  it("fires with phase='failed' and the real failed steps when a step fails and nothing is in_progress", async () => {
    sessionStatusMock.mockResolvedValue({
      session_id: "s2",
      lang: "rust",
      project_root: "/tmp/s2",
      steps: [
        makeStep({ id: 1, status: "complete" }),
        makeStep({ id: 2, status: "failed", compiler_output: "E0308 mismatched types" }),
      ],
      api_cost_usd: 0,
      session_budget_usd: 1,
      budget_exhausted: false,
      scaffolding_validated: true,
      created_at: "",
      updated_at: "",
    });

    const onComplete = vi.fn();
    render(<HiveBuildLoop sessionId="s2" onComplete={onComplete} />);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    const result: HiveBuildCompletionResult = onComplete.mock.calls[0][0];
    expect(result.phase).toBe("failed");
    expect(result.failedCount).toBe(1);
    expect(result.failedSteps).toHaveLength(1);
    expect(result.failedSteps[0].id).toBe(2);
  });

  it("never fires while a step is still in_progress (no premature verdict)", async () => {
    sessionStatusMock.mockResolvedValue({
      session_id: "s3",
      lang: "rust",
      project_root: "/tmp/s3",
      steps: [makeStep({ id: 1, status: "in_progress" })],
      api_cost_usd: 0,
      session_budget_usd: 1,
      budget_exhausted: false,
      scaffolding_validated: true,
      created_at: "",
      updated_at: "",
    });

    const onComplete = vi.fn();
    render(<HiveBuildLoop sessionId="s3" onComplete={onComplete} />);

    // Give the first poll (fires immediately on mount) plenty of time to resolve.
    await new Promise((r) => setTimeout(r, 300));
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("fires exactly once even as polling continues to report the same settled status", async () => {
    sessionStatusMock.mockResolvedValue({
      session_id: "s4",
      lang: "rust",
      project_root: "/tmp/s4",
      steps: [makeStep({ id: 1, status: "complete" })],
      api_cost_usd: 0,
      session_budget_usd: 1,
      budget_exhausted: false,
      scaffolding_validated: true,
      created_at: "",
      updated_at: "",
    });

    const onComplete = vi.fn();
    render(<HiveBuildLoop sessionId="s4" onComplete={onComplete} />);

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    // Wait past the 750ms initial poll interval so at least one more real poll happens.
    await new Promise((r) => setTimeout(r, 900));
    expect(onComplete).toHaveBeenCalledTimes(1);
  }, 10000);
});
