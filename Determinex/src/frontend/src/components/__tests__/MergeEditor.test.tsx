import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MergeEditor } from "../MergeEditor";

const WORKSPACE = "C:\\Dev\\Determinex";

// Monaco's real editor needs a browser layout engine jsdom doesn't provide -- stub both
// Editor and DiffEditor with minimal, inspectable substitutes, matching how other panels in
// this codebase test Monaco-backed components without booting the real editor.
vi.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value }: { value?: string }) => <div data-testid="result-editor">{value}</div>,
  DiffEditor: ({
    original,
    modified,
    options,
  }: {
    original?: string;
    modified?: string;
    options?: { renderSideBySide?: boolean };
  }) => (
    <div data-testid="diff-editor" data-side-by-side={String(options?.renderSideBySide ?? false)}>
      <span data-testid="diff-original">{original}</span>
      <span data-testid="diff-modified">{modified}</span>
    </div>
  ),
}));

const defaultImpl = async (cmd: string, _args?: Record<string, unknown>) => {
  if (cmd === "git_status") {
    return {
      branch: "main",
      upstream: "origin/main" as string | null,
      ahead: 0,
      behind: 0,
      files: [
        { path: "src/lib.rs", status: "conflicted", code: "UU" },
        { path: "src/other.rs", status: "modified", code: "M" },
      ],
    };
  }
  if (cmd === "git_conflict_sides") {
    return {
      base: "fn f() { 1 }",
      ours: "fn f() { 2 }",
      theirs: "fn f() { 3 }",
      current: "fn f() { <<<<<<< OURS 2 ======= 3 >>>>>>> THEIRS }",
    };
  }
  if (cmd === "git_resolve_conflict") {
    return null;
  }
  return null;
};

const invokeSafeMock = vi.fn(defaultImpl);

vi.mock("../../lib/api", () => ({
  isTauri: () => true,
  invokeSafe: (cmd: string, args?: Record<string, unknown>) => invokeSafeMock(cmd, args),
  // Writes go through invokeWrite now; same mock so one backend answers both.
  invokeWrite: async (cmd: string, args?: Record<string, unknown>) => {
    await invokeSafeMock(cmd, args);
  },
}));

// gitService's write path (git_resolve_conflict here) deliberately uses raw
// invoke rather than invokeSafe, so that a backend rejection propagates instead
// of being swallowed into an indistinguishable null. Point both transports at
// the same mock so these assertions keep describing one backend.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (cmd: string, args?: Record<string, unknown>) => invokeSafeMock(cmd, args),
}));

describe("MergeEditor component", () => {
  beforeEach(() => {
    // mockClear() alone leaves a prior test's mockImplementation() override in place --
    // reset to the shared default before every test so overrides don't leak forward.
    invokeSafeMock.mockReset();
    invokeSafeMock.mockImplementation(defaultImpl);
  });

  it("lists only conflicted files, not all modified files", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => {
      expect(screen.getByText("lib.rs")).toBeInTheDocument();
    });
    expect(screen.queryByText("other.rs")).not.toBeInTheDocument();
  });

  it("shows an honest empty state when there are no conflicts", async () => {
    invokeSafeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "git_status") {
        return { branch: "main", upstream: null, ahead: 0, behind: 0, files: [] };
      }
      return null;
    });
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => {
      expect(screen.getByText("No conflicts to resolve.")).toBeInTheDocument();
    });
  });

  it("loads and displays the three conflict sides for the selected file", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => {
      expect(screen.getByText("lib.rs")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(invokeSafeMock).toHaveBeenCalledWith(
        "git_conflict_sides",
        expect.objectContaining({ cwd: WORKSPACE, path: "src/lib.rs" })
      );
    });
    await waitFor(() => {
      const diffEditors = screen.getAllByTestId("diff-editor");
      expect(diffEditors.length).toBe(2); // base-vs-ours, base-vs-theirs
    });
  });

  it("defaults context diffs to inline and the toggle switches both panes to side-by-side", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => {
      const diffEditors = screen.getAllByTestId("diff-editor");
      expect(diffEditors.length).toBe(2);
      for (const el of diffEditors) {
        expect(el.getAttribute("data-side-by-side")).toBe("false");
      }
    });

    fireEvent.click(screen.getByTitle("Switch context diffs to side-by-side"));

    await waitFor(() => {
      const diffEditors = screen.getAllByTestId("diff-editor");
      for (const el of diffEditors) {
        expect(el.getAttribute("data-side-by-side")).toBe("true");
      }
    });
  });

  it("Use Ours replaces the result pane with the ours content", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => screen.getByText("Use Ours"));
    fireEvent.click(screen.getByText("Use Ours"));
    await waitFor(() => {
      expect(screen.getByTestId("result-editor").textContent).toBe("fn f() { 2 }");
    });
  });

  it("Use Theirs replaces the result pane with the theirs content", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => screen.getByText("Use Theirs"));
    fireEvent.click(screen.getByText("Use Theirs"));
    await waitFor(() => {
      expect(screen.getByTestId("result-editor").textContent).toBe("fn f() { 3 }");
    });
  });

  it("Use Both concatenates ours and theirs", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => screen.getByText("Use Both"));
    fireEvent.click(screen.getByText("Use Both"));
    await waitFor(() => {
      expect(screen.getByTestId("result-editor").textContent).toBe("fn f() { 2 }\nfn f() { 3 }");
    });
  });

  it("Mark Resolved calls git_resolve_conflict with the current result text and cwd/path", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => screen.getByText("Mark Resolved"));
    fireEvent.click(screen.getByText("Use Ours"));
    await waitFor(() => {
      expect(screen.getByTestId("result-editor").textContent).toBe("fn f() { 2 }");
    });
    fireEvent.click(screen.getByText("Mark Resolved"));
    await waitFor(() => {
      expect(invokeSafeMock).toHaveBeenCalledWith(
        "git_resolve_conflict",
        expect.objectContaining({
          cwd: WORKSPACE,
          path: "src/lib.rs",
          resolvedContent: "fn f() { 2 }",
        })
      );
    });
  });

  it("resolving a conflict removes it from the list once git_status no longer reports it", async () => {
    render(<MergeEditor workspacePath={WORKSPACE} />);
    await waitFor(() => screen.getByText("Mark Resolved"));

    // after resolution, the backend would no longer report this file as conflicted
    invokeSafeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "git_status") {
        return { branch: "main", upstream: null, ahead: 0, behind: 0, files: [] };
      }
      if (cmd === "git_resolve_conflict") return null;
      return null;
    });

    fireEvent.click(screen.getByText("Mark Resolved"));
    await waitFor(() => {
      expect(screen.getByText("No conflicts to resolve.")).toBeInTheDocument();
    });
  });
});
