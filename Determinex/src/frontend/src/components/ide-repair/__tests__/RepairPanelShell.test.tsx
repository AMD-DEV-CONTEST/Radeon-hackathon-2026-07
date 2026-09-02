import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RepairPanelShell } from "../RepairPanelShell";

describe("RepairPanelShell", () => {
  it("mounts shipped repair panels instead of permanent loading placeholders", () => {
    render(<RepairPanelShell workspacePath="C:/Dev/Determinex" />);

    expect(screen.getByTestId("workspace-status-panel")).toBeInTheDocument();
    expect(screen.getByTestId("source-apply-dry-run-panel")).toBeInTheDocument();
    expect(screen.getByTestId("model-route-panel")).toBeInTheDocument();
    expect(screen.getByTestId("local-model-settings-panel")).toBeInTheDocument();
    expect(screen.getAllByTestId("diagnose-and-patch-plan-panel").length).toBeGreaterThan(0);
    expect(screen.getByTestId("temp-verify-panel")).toBeInTheDocument();
    expect(screen.getByTestId("human-approval-panel")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-viewer-panel")).toBeInTheDocument();

    const shell = screen.getByTestId("ide-repair-panel-shell");
    expect(within(shell).queryByTestId("repair-section-placeholder")).not.toBeInTheDocument();
  });
});
