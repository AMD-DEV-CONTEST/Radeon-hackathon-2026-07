import { render, screen } from "@testing-library/react";
import { within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SuccessorRoadmapPanel } from "../SuccessorRoadmapPanel";
import {
  DETERMINEX_SUCCESSOR_BRAND_BOUNDARY,
  DETERMINEX_SUCCESSOR_PILLARS,
} from "@/lib/successorRoadmap";
import { DETERMINEX_RELEASE_GATES } from "@/lib/releaseGateStatus";
import {
  DETERMINEX_INDUSTRY_IDE_BACKLOG,
  getIndustryIdeBacklogSummary,
} from "@/lib/industryIdeBacklog";

describe("SuccessorRoadmapPanel", () => {
  it("renders Determinex as the public product name without pretending release readiness", () => {
    render(<SuccessorRoadmapPanel />);

    expect(screen.getByText("Determinex IDE Roadmap")).toBeInTheDocument();
    expect(screen.getByTestId("successor-roadmap-boundary")).toHaveTextContent(
      "Roadmap status, not release readiness"
    );
    expect(screen.getAllByText("VS Code/Open VSX compatibility").length).toBeGreaterThan(0);
  });

  it("keeps the rename boundary exact and avoids all-live successor claims", () => {
    expect(DETERMINEX_SUCCESSOR_BRAND_BOUNDARY.publicName).toBe("Determinex");
    expect(DETERMINEX_SUCCESSOR_BRAND_BOUNDARY.legacyNamespace).toContain("determinex_*");
    expect(DETERMINEX_SUCCESSOR_PILLARS.some((pillar) => pillar.status !== "live")).toBe(true);
    expect(DETERMINEX_SUCCESSOR_PILLARS.every((pillar) => pillar.releaseReady === false)).toBe(
      true
    );
  });

  it("renders collector-backed release gates without granting release readiness", () => {
    render(<SuccessorRoadmapPanel />);

    expect(screen.getByText("Release gate collector")).toBeInTheDocument();
    expect(screen.getByText("Clean-host install proof")).toBeInTheDocument();
    expect(screen.getByText("Windows signing and SmartScreen trust")).toBeInTheDocument();
    expect(screen.getByText("Legal/IP public distribution packet")).toBeInTheDocument();
    expect(screen.getByText("Windows MSI/WiX distribution")).toBeInTheDocument();
    expect(screen.getByText("Linux package distribution")).toBeInTheDocument();
    expect(screen.getByText("ProgramBench 200/200 strict locks")).toBeInTheDocument();
    expect(screen.getByText("Fresh SWE-bench publication reruns")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Current runner cannot access Docker Desktop state; rerun the clean-host probe outside the sandbox."
      )
    ).toBeInTheDocument();
    expect(screen.getByText(/No Windows signing and SmartScreen trust packet/)).toBeInTheDocument();
    expect(screen.getByText(/AGPLv3 source license evidence is present/)).toBeInTheDocument();
    expect(screen.getByText(/No Windows MSI\/WiX evidence packet/)).toBeInTheDocument();
    expect(screen.getByText(/No Linux package artifact/)).toBeInTheDocument();
    expect(screen.getByText(/ProgramBench strict official locks are 0\/200/)).toBeInTheDocument();
    expect(
      screen.getByText(/No fresh official SWE-bench privacy-mode rerun packet/)
    ).toBeInTheDocument();
    expect(screen.getByText("First end-to-end user workflow")).toBeInTheDocument();
    expect(screen.getAllByText("Passed").length).toBeGreaterThan(0);
    expect(DETERMINEX_RELEASE_GATES.releaseReady).toBe(false);
    expect(DETERMINEX_RELEASE_GATES.gates.every((gate) => gate.releaseReady === false)).toBe(true);
    expect(DETERMINEX_RELEASE_GATES.gates.every((gate) => gate.runbookCommands.length > 0)).toBe(
      true
    );
  });

  it("renders the audited industry IDE checklist without checking everything off", () => {
    render(<SuccessorRoadmapPanel />);

    const summary = getIndustryIdeBacklogSummary();
    const checklist = screen.getByTestId("industry-ide-checklist");
    expect(checklist).toHaveTextContent("Industry IDE checklist");
    expect(screen.getByText("Release Trust")).toBeInTheDocument();
    expect(
      screen.getByText("Clean-host install, launch, workflow, and uninstall proof")
    ).toBeInTheDocument();
    expect(within(checklist).getAllByText("Blocked").length).toBeGreaterThan(0);
    expect(summary.checked).toBeLessThan(summary.total);
    expect(DETERMINEX_INDUSTRY_IDE_BACKLOG.some((item) => item.status === "done")).toBe(true);
    expect(DETERMINEX_INDUSTRY_IDE_BACKLOG.some((item) => item.status === "blocked")).toBe(true);
  });
});
