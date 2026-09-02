import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { VerifiedSearch } from "../VerifiedSearch";

const invokeMock = vi.fn();
const readFileMock = vi.fn();
const rawInvokeMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    isTauri: () => true,
    invokeSafe: (...args: unknown[]) => invokeMock(...args),
    readFileContent: (...args: unknown[]) => readFileMock(...args),
  };
});

// Staging uses raw invoke, not invokeSafe: stage_diff_for_review returns
// Result<(), String>, so success resolves to null and is indistinguishable
// from invokeSafe's error-null. Mocked separately so the two paths stay
// distinguishable in these tests too.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => rawInvokeMock(...args),
}));

const BUILD_OK = {
  status: "IDE_COMMAND_TEMP_ONLY",
  payload: {
    solved: true,
    n_checks: 3,
    samples: 4,
    proof: "3/3 oracle checks passed",
    program: "def solution(x):\n    return x\n",
    oracle_tests: "def test_symbol_exists():\n    assert callable(solution)\n",
    next_moves: [],
  },
  notes: [],
};

async function runVerify() {
  fireEvent.change(screen.getByPlaceholderText(/Describe a single function/i), {
    target: { value: "identity function" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Verify/i }));
  await waitFor(() => expect(screen.getByText(/Oracle-verified/i)).toBeInTheDocument());
}

describe("VerifiedSearch", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    readFileMock.mockReset();
    rawInvokeMock.mockReset();
    invokeMock.mockResolvedValue(BUILD_OK);
    // A void Tauri command resolves to null on SUCCESS -- that is the whole
    // reason staging cannot use invokeSafe.
    rawInvokeMock.mockResolvedValue(null);
    // Default: the target file does not exist yet, which is the normal case.
    readFileMock.mockRejectedValue(new Error("not found"));
  });

  it("calls the real build_idea command, not the phantom verified_search", async () => {
    render(<VerifiedSearch selectedModel="auto" workspacePath={"C:\\ws"} />);
    await runVerify();

    const commands = invokeMock.mock.calls.map((c) => c[0]);
    expect(commands).toContain("build_idea");
    // Regression guard: this panel shipped invoking a command that was never
    // registered on the Rust side, so every search silently failed.
    expect(commands).not.toContain("verified_search");
  });

  it("renders real backend numbers rather than invented per-candidate rows", async () => {
    render(<VerifiedSearch selectedModel="auto" workspacePath={"C:\\ws"} />);
    await runVerify();

    expect(screen.getByText(/4 samples drawn/i)).toBeInTheDocument();
    expect(screen.getByText(/3 oracle checks synthesized/i)).toBeInTheDocument();
  });

  it("stages the verified program with the camelCase shape StagedDiff expects", async () => {
    render(<VerifiedSearch selectedModel="auto" workspacePath={"C:\\ws"} />);
    await runVerify();

    fireEvent.click(screen.getByRole("button", { name: /Stage for review/i }));
    await waitFor(() =>
      expect(screen.getByText(/Staged solution\.py for review/i)).toBeInTheDocument()
    );

    const stageCall = rawInvokeMock.mock.calls.find((c) => c[0] === "stage_diff_for_review");
    expect(stageCall).toBeTruthy();
    const diff = (stageCall![1] as any).diff;
    // Rust's StagedDiff is #[serde(rename_all = "camelCase")] -- snake_case here
    // deserializes to nothing and the stage silently no-ops.
    expect(diff).toMatchObject({
      path: "C:\\ws\\solution.py",
      originalContent: "",
      proposedContent: "def solution(x):\n    return x\n",
    });
    expect(typeof diff.id).toBe("string");
  });

  it("refuses to stage when no workspace is open", async () => {
    render(<VerifiedSearch selectedModel="auto" />);
    await runVerify();

    // Button is disabled without a workspace, so a staged diff can never be
    // built with a path outside a workspace boundary.
    expect(screen.getByRole("button", { name: /Stage for review/i })).toBeDisabled();
    expect(rawInvokeMock.mock.calls.some((c) => c[0] === "stage_diff_for_review")).toBe(false);
  });

  it("treats a null return as success, because a void command resolves to null", async () => {
    render(<VerifiedSearch selectedModel="auto" workspacePath={"C:\\ws"} />);
    await runVerify();

    // Regression guard for a real false negative: stage_diff_for_review returns
    // Result<(), String>, so success IS null. Reporting that as a refusal told
    // the user nothing was queued when it had been -- and invited a retry that
    // silently staged the same diff twice (observed live as two Review rows).
    rawInvokeMock.mockResolvedValueOnce(null);
    fireEvent.click(screen.getByRole("button", { name: /Stage for review/i }));
    await waitFor(() =>
      expect(screen.getByText(/Staged solution\.py for review/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/refused|could not stage/i)).not.toBeInTheDocument();
  });

  it("reports a real rejection instead of claiming it staged", async () => {
    render(<VerifiedSearch selectedModel="auto" workspacePath={"C:\\ws"} />);
    await runVerify();

    rawInvokeMock.mockRejectedValueOnce(new Error("outside workspace boundary"));
    fireEvent.click(screen.getByRole("button", { name: /Stage for review/i }));
    await waitFor(() =>
      expect(screen.getByText(/outside workspace boundary/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/Staged solution\.py for review/i)).not.toBeInTheDocument();
  });
});
