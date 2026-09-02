import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ProjectAuditPanel } from "../ProjectAuditPanel";
import * as api from "../../lib/api";

vi.mock("../../lib/api", () => ({
  invokeSafe: vi.fn(),
}));

describe("ProjectAuditPanel component", () => {
  beforeEach(() => {
    (api.invokeSafe as any).mockResolvedValue({
      score: 95,
      categories: [
        {
          title: "Mocked Health",
          score: 100,
          status: "pass",
          details: "Mocked passed health test",
        },
      ],
      blockers: [],
      snykOutput: "Mocked Snyk Output",
    });
  });

  it("renders Audit panel, runs scan and displays scorecard details", async () => {
    render(<ProjectAuditPanel />);

    // Verify initial layout elements are present
    expect(screen.getByText("Shippable Project Audit")).toBeInTheDocument();
    expect(screen.getByText("Audit Scorecard Ready")).toBeInTheDocument();

    const runBtn = screen.getByText("Run Audit Scan");
    expect(runBtn).toBeInTheDocument();

    // Click run scan
    fireEvent.click(runBtn);
    expect(screen.getByText(/Scanning codebase workspace/i)).toBeInTheDocument();

    // Wait for mock audit to resolve and output results
    await waitFor(
      () => {
        expect(screen.getByText("Shippable Status Score")).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    expect(screen.getByText("95/100")).toBeInTheDocument();
    expect(screen.getByText("Mocked Health")).toBeInTheDocument();
  });
});
