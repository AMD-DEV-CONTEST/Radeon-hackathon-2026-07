import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";
import { EditorPanel } from "../EditorPanel";

describe("EditorPanel component", () => {
  // Tab state persists to localStorage; without this, a file created in one test
  // (e.g. "untitled-1.py") leaks into the next test's "fresh" render.
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders an honest empty state (no fake demo files) and handles split view toggle", async () => {
    render(<EditorPanel />);

    // No fake demo files -- the real empty state, not a seeded "hive.py".
    expect(screen.getByText("No files open")).toBeInTheDocument();

    // Verify split screen toggle is present (available even with no files open)
    // and starts inactive.
    const splitBtn = screen.getByTitle("Split Editor");
    expect(splitBtn).toBeInTheDocument();
    expect(screen.queryByText(/Right:/)).not.toBeInTheDocument();
  });

  it("handles file tab creation and tab close (does not claim to delete from disk)", async () => {
    render(<EditorPanel />);

    const createBtn = screen.getByTitle("New File");
    fireEvent.click(createBtn);

    // Creates the first untitled python file tab (no demo files precede it).
    expect(screen.getAllByText("untitled-1.py").length).toBeGreaterThan(0);

    // The close-tab button is honestly labeled -- it never claimed to delete
    // from disk, only to close the tab.
    const closeBtn = screen.getByTitle("Close Tab (does not delete the file from disk)");
    expect(closeBtn).toBeInTheDocument();
  });

  it("opens a real file passed via pendingFile (file-explorer click) as a new tab", async () => {
    const { rerender } = render(<EditorPanel pendingFile={null} />);
    // No demo tabs, no real file yet -- the honest empty state.
    expect(screen.getByText("No files open")).toBeInTheDocument();
    expect(screen.queryByText("real_module.py")).not.toBeInTheDocument();

    rerender(
      <EditorPanel
        pendingFile={{
          path: "C:/Dev/Determinex/scripts/real_module.py",
          content: "print('real')",
          requestId: 1,
        }}
      />
    );

    // Renders as a new tab (and in the path breadcrumb) -- the file-explorer click
    // is now visible in the editor, instead of silently updating dead state.
    await waitFor(() => {
      expect(screen.getAllByText("real_module.py").length).toBeGreaterThan(0);
    });
  });

  it("re-focuses an already-open pendingFile instead of duplicating its tab", async () => {
    const first = {
      path: "C:/Dev/Determinex/scripts/real_module.py",
      content: "print('v1')",
      requestId: 1,
    };
    const { rerender } = render(<EditorPanel pendingFile={first} />);
    await waitFor(() => expect(screen.getAllByText("real_module.py").length).toBeGreaterThan(0));
    // "real_module.py" renders once in the tab strip and once in the path breadcrumb
    // (activeFile.path.split("/")) -- capture that baseline count, not a hardcoded number.
    const countAfterFirstOpen = screen.getAllByText("real_module.py").length;

    rerender(
      <EditorPanel pendingFile={{ path: first.path, content: "print('v2')", requestId: 2 }} />
    );

    // Re-opening the SAME path must refresh/refocus the existing tab, not add a second one.
    await waitFor(() =>
      expect(screen.getAllByText("real_module.py").length).toBe(countAfterFirstOpen)
    );
  });
});
