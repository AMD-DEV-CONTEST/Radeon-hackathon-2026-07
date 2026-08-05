import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DiffViewer } from "../DiffViewer";

const { invokeSafeMock, invokeWriteMock } = vi.hoisted(() => ({
  invokeSafeMock: vi.fn(),
  invokeWriteMock: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return { ...actual, invokeSafe: invokeSafeMock, invokeWrite: invokeWriteMock };
});

const ONE_DIFF = [
  { id: "d1", path: "src/lib.rs", originalContent: "fn old() {}", proposedContent: "fn new() {}" },
];

describe("DiffViewer (BuildCenter) -- real staged-diff backend, not hardcoded patches", () => {
  beforeEach(() => {
    invokeSafeMock.mockReset();
    invokeWriteMock.mockReset();
    invokeWriteMock.mockResolvedValue(undefined);
  });

  it("shows an honest empty state when there are no staged diffs", async () => {
    invokeSafeMock.mockResolvedValue([]);
    render(<DiffViewer />);
    await waitFor(() => {
      expect(screen.getByText("No AI changes pending review.")).toBeInTheDocument();
    });
    expect(invokeSafeMock).toHaveBeenCalledWith("get_staged_diffs", {});
  });

  it("renders a real staged diff from get_staged_diffs and calls apply_staged_diff on Apply", async () => {
    invokeSafeMock.mockImplementation(async (cmd: string) =>
      cmd === "get_staged_diffs" ? ONE_DIFF : undefined
    );
    render(<DiffViewer />);

    await waitFor(() => {
      expect(screen.getByText("src/lib.rs")).toBeInTheDocument();
    });
    expect(screen.getByText("fn old() {}")).toBeInTheDocument();
    expect(screen.getByText("fn new() {}")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Apply"));
    await waitFor(() => {
      // Must be the WRITE transport. apply_staged_diff returns Result<(), String>
      // and does refuse (it enforces the workspace boundary), so on invokeSafe a
      // refusal resolved to null, the queue refreshed with the diff still in it,
      // and the button merely looked inert -- inviting a second click on a write
      // the backend had already denied.
      expect(invokeWriteMock).toHaveBeenCalledWith("apply_staged_diff", { id: "d1" });
    });
  });

  it("surfaces a refused apply instead of silently leaving the diff queued", async () => {
    invokeSafeMock.mockImplementation(async (cmd: string) =>
      cmd === "get_staged_diffs" ? ONE_DIFF : undefined
    );
    invokeWriteMock.mockRejectedValue(new Error("path escapes the workspace boundary"));
    render(<DiffViewer />);

    await waitFor(() => expect(screen.getByText("src/lib.rs")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Apply"));

    await waitFor(() => {
      expect(screen.getByText(/Could not apply src\/lib\.rs/)).toBeInTheDocument();
      expect(screen.getByText(/escapes the workspace boundary/)).toBeInTheDocument();
    });
  });

  it("surfaces a refused reject the same way", async () => {
    invokeSafeMock.mockImplementation(async (cmd: string) =>
      cmd === "get_staged_diffs" ? ONE_DIFF : undefined
    );
    invokeWriteMock.mockRejectedValue(new Error("no such staged diff"));
    render(<DiffViewer />);

    await waitFor(() => expect(screen.getByText("src/lib.rs")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Reject"));

    await waitFor(() => {
      expect(screen.getByText(/Could not reject src\/lib\.rs/)).toBeInTheDocument();
    });
  });
});
