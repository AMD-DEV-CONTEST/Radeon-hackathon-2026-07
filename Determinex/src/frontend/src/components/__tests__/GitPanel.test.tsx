import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import GitPanel from "../GitPanel";

const WORKSPACE = "C:\\Dev\\Determinex";

vi.mock("../../lib/api", () => ({
  isTauri: () => true,
  invokeSafe: vi.fn(async (cmd: string) => {
    if (cmd === "git_status") {
      return {
        ahead: 2,
        behind: 1,
        branch: "main",
        upstream: "origin/main",
        files: [
          { path: "EditorPanel.tsx", status: "modified", code: "M" },
          { path: "GitPanel.tsx", status: "modified", code: "M" },
          { path: "determinex_oracle.py", status: "staged", code: "A" },
        ],
      };
    }
    if (cmd === "git_list_branches") {
      return ["main", "feature/test"];
    }
    return null;
  }),
  // gitService's writes go through invokeWrite (raw invoke, so a rejection
  // propagates). Pointed at the same fake backend so these assertions keep
  // describing one backend rather than two.
  invokeWrite: vi.fn(async () => undefined),
}));

describe("GitPanel component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders header, remote status, branch selector, and staged/unstaged changes", async () => {
    render(<GitPanel workspacePath={WORKSPACE} />);
    await waitFor(() => {
      expect(screen.getByText("Source Control")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText(/Pull \(\d+\)/)).toBeInTheDocument();
      expect(screen.getByText(/Push \(\d+\)/)).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("GitPanel.tsx")).toBeInTheDocument();
    });

    const stageButtons = screen.getAllByTitle("Stage file");
    expect(stageButtons.length).toBeGreaterThan(0);
  });

  it("handles commit submit workflow", async () => {
    render(<GitPanel workspacePath={WORKSPACE} />);

    await waitFor(() => {
      expect(screen.getByText("EditorPanel.tsx")).toBeInTheDocument();
    });

    const commitBtn = screen.getByRole("button", { name: /Commit/ });
    expect(commitBtn).toBeEnabled();

    const textInput = screen.getByPlaceholderText(/Commit message.../);
    fireEvent.change(textInput, { target: { value: "feat: added code signing checks" } });

    fireEvent.click(commitBtn);

    await waitFor(() => {
      expect(textInput).toHaveValue("");
    });
  });
});
