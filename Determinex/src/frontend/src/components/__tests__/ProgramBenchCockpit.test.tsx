import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProgramBenchCockpit } from "../ProgramBenchCockpit";

vi.mock("@/lib/api", () => ({
  getProgramBenchSnapshot: vi.fn(async () => ({
    run_id: "fixture-run",
    generated_at: "2026-05-31T00:00:00Z",
    n_completed_tasks: 3,
    progress: { expected_total: 115, pct_done: 2.6, complete: false },
    rolling_avg_score: 42.5,
    total_passed: 10,
    total_tests: 20,
    pct_tests_passing: 50,
    perfect_scores: 1,
    zero_scores: 0,
    top_families: [{ family: "cli", failures: 2, tools_affected: 1 }],
    recommended_patch: { title: "fixture patch", estimated_lift_pp: 1.2 },
    locked_count: 2,
    locked_tools: [
      {
        name: "ripgrep",
        score: 100,
        passed: 2536,
        runnable_total: 2536,
        evidence_path: "corpus/programbench/locked/ripgrep/eval_report.json",
      },
      {
        name: "zoxide",
        score: 100,
        passed: 577,
        runnable_total: 577,
        evidence_path: "corpus/programbench/locked/zoxide/eval_report.json",
      },
    ],
  })),
}));

describe("ProgramBenchCockpit", () => {
  it("renders real lock-board drilldown bound to the snapshot, with boundary text", async () => {
    render(<ProgramBenchCockpit />);

    await waitFor(() => {
      expect(screen.getByText("fixture-run - 3/115 tools")).toBeInTheDocument();
    });

    expect(screen.getByTestId("programbench-tool-drilldown")).toBeInTheDocument();
    // Rows come from snapshot.locked_tools (the real lock board), not hardcoded fixtures.
    // Label changed from "locks" to "archived" -- these are real archived pass-rates, not
    // a claim of legitimate reimplementation (see the 2026-06-30 provenance audit banner).
    expect(screen.getByTestId("programbench-lock-count")).toHaveTextContent("2 archived");
    expect(screen.getByTestId("programbench-tool-ripgrep")).toHaveTextContent("ripgrep");
    expect(screen.getByTestId("programbench-tool-zoxide")).toHaveTextContent("577/577");
    expect(screen.getAllByTestId("programbench-tool-evidence")[0]).toHaveTextContent(
      "corpus/programbench/locked/ripgrep/eval_report.json"
    );
    expect(screen.getByTestId("programbench-boundary")).toHaveTextContent(
      "No unbounded benchmark run"
    );
  });
});
