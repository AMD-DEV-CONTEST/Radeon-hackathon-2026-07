import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeacherOverlay } from "../TeacherOverlay";

describe("TeacherOverlay", () => {
  beforeEach(() => {
    // Checklist progress persists to localStorage now -- clear between
    // tests so one test's toggled checklist item can't bleed into another.
    window.localStorage.clear();
  });

  it("offers interactive setup and local cloak walkthrough topics", () => {
    render(<TeacherOverlay open onClose={vi.fn()} activeSidebar="marketplace" />);

    fireEvent.click(screen.getByText("First-Run Setup"));
    expect(screen.getAllByText("First-Run Setup").length).toBeGreaterThan(0);
    expect(screen.getByText("Add provider keys or intentionally skip them")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Add provider keys or intentionally skip them"));
    expect(screen.getByText("Add provider keys or intentionally skip them")).toHaveClass(
      "text-emerald-300/80"
    );

    fireEvent.click(screen.getByText("Local vs Cloak"));
    expect(screen.getByText(/Local means models run on this machine/)).toBeInTheDocument();
    expect(
      screen.getByText("Use Cloak when local hardware is tight but privacy gates are required")
    ).toBeInTheDocument();
  });

  it("auto-syncs to the step matching activeSidebar (a primary rail selection)", () => {
    render(<TeacherOverlay open onClose={vi.fn()} activeSidebar="hive" />);
    // "Work" is the step whose panel is "hive" -- the real PrimaryWorkspace
    // value the Work rail button actually sets -- so it should be the one
    // shown, not the first step. Was "Hive Sessions" (a separate step) until
    // that step's stale/unreachable content got folded into "Work" itself.
    // "Work" text itself appears twice (header title + Jump To button), so
    // assert on the step's unique subtitle instead of getByText("Work").
    expect(screen.getByText(/The universal entry point for a new idea/)).toBeInTheDocument();
  });

  it("auto-syncs to the step matching activeAddon (an attached tool, distinct from activeSidebar)", () => {
    // Regression test: steps mapped to addon ids (terminal/editor/cloak/etc)
    // previously could never sync because only activeSidebar was checked,
    // and those steps' panel values are WorkspaceAddon ids, not
    // PrimaryWorkspace ids -- they'd never match regardless of value.
    render(<TeacherOverlay open onClose={vi.fn()} activeSidebar="none" activeAddon="terminal" />);
    expect(screen.getByText("Tools Dock")).toBeInTheDocument();
  });
});
