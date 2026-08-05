import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const rawInvoke = vi.fn();
const invokeSafeMock = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => rawInvoke(...args),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    isTauri: () => true,
    invokeSafe: (...args: unknown[]) => invokeSafeMock(...args),
    readFileContent: vi.fn(async () => null),
    getFileSystemTree: vi.fn(async () => ({ tree: [] })),
  };
});

vi.mock("@/lib/lspService", () => ({
  getLspDiagnostics: vi.fn(async () => []),
  getLspSymbols: vi.fn(async () => []),
}));

// Monaco needs a real layout engine; substitute a textarea we can type into.
vi.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value, onChange }: { value?: string; onChange?: (v?: string) => void }) => (
    <textarea
      data-testid="editor"
      value={value ?? ""}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

import { EditorPanel } from "../EditorPanel";

const FILE = { path: "C:\\ws\\a.ts", content: "original\n", requestId: 1 };

/**
 * Regression guard for a data-loss bug.
 *
 * handleSave used invokeSafe (which swallows a rejection and returns null) and
 * then cleared `dirty` UNCONDITIONALLY. write_file_content genuinely can fail --
 * it refuses a path outside the workspace boundary, and the write can fail on a
 * read-only or locked file -- so a failed save marked the tab clean. The user
 * closed it and the edits were gone, with no error shown anywhere.
 */
describe("EditorPanel save never lies about success", () => {
  beforeEach(() => {
    rawInvoke.mockReset();
    invokeSafeMock.mockReset();
    localStorage.clear();
  });

  const openAndEdit = async () => {
    render(<EditorPanel pendingFile={FILE} workspacePath={"C:\\ws"} />);
    const editor = await screen.findByTestId("editor");
    fireEvent.change(editor, { target: { value: "edited content\n" } });
    return editor;
  };

  it("keeps the file dirty and shows why when the save is refused", async () => {
    rawInvoke.mockRejectedValue(new Error("Access denied: path is outside workspace boundary"));
    await openAndEdit();

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(screen.getByText(/Could not save/i)).toBeInTheDocument());
    expect(screen.getByText(/outside workspace boundary/i)).toBeInTheDocument();
    // The wording must tell the user their work is still only in the buffer.
    expect(screen.getByText(/still in the editor, unsaved/i)).toBeInTheDocument();
  });

  it("clears dirty only after the write actually succeeds", async () => {
    rawInvoke.mockResolvedValue({ content: "edited content\n" });
    await openAndEdit();

    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(rawInvoke).toHaveBeenCalledWith(
        "write_file_content",
        expect.objectContaining({ path: FILE.path, content: "edited content\n" })
      )
    );
    expect(screen.queryByText(/Could not save/i)).not.toBeInTheDocument();
  });

  it("routes the save through invoke, never invokeSafe", async () => {
    rawInvoke.mockResolvedValue({ content: "x" });
    await openAndEdit();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(rawInvoke).toHaveBeenCalled());
    // invokeSafe cannot report a write failure, so it must not carry the save.
    const viaSafe = invokeSafeMock.mock.calls.filter((c) => c[0] === "write_file_content");
    expect(viaSafe).toHaveLength(0);
  });
});
