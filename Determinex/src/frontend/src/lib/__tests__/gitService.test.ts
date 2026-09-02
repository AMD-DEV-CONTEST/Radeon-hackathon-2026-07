import { describe, test, expect, vi, beforeEach } from "vitest";
import {
  getGitStatus,
  stageFile,
  unstageFile,
  stageAll,
  commitChanges,
  getGitBranches,
  createGitBranch,
  checkoutBranch,
  pushCommits,
  pullCommits,
  GitFile,
} from "../gitService";

const CWD = "C:\\Dev\\Determinex";

// One fake backend behind BOTH transports.
//
// This file used to mock only invokeSafe, and in doing so it mocked away the
// bug it was meant to catch: the real invokeSafe swallows a rejection and
// returns null, but a vi.fn() that throws propagates. So
// "commitChanges rejects on empty staged changes" passed here while
// production silently reported success for every failed commit.
//
// Reads still go through invokeSafe; writes now go through invoke() precisely
// so failures propagate. Both are wired to the same handler so this suite
// exercises the real split instead of hiding it.
const { backend } = vi.hoisted(() => ({ backend: vi.fn() }));

// Runtime marker so the real isTauri()/invokeWrite take their real paths; only
// invokeSafe is swapped, and it is pointed at the same fake backend as the raw
// invoke below so both transports hit one handler.
(globalThis as unknown as { window: Record<string, unknown> }).window ??=
  globalThis as unknown as Record<string, unknown>;
(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {
  transformCallback: () => {},
};

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, invokeSafe: (...args: unknown[]) => backend(...args) };
});

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => backend(...args),
}));

describe("gitService contract tests", () => {
  let mockFiles: GitFile[];

  beforeEach(() => {
    mockFiles = [
      {
        path: "test.ts",
        status: "modified",
        code: "M",
        originalContent: "A",
        currentContent: "B",
      },
    ];

    backend.mockImplementation(async (cmd: string, args: any) => {
      if (cmd === "git_status") {
        return {
          branch: "main",
          upstream: "origin/main",
          files: [...mockFiles],
          ahead: 0,
          behind: 0,
        };
      } else if (cmd === "git_stage") {
        const file = mockFiles.find((f) => f.path === args.path);
        if (file) file.status = "staged";
        return;
      } else if (cmd === "git_unstage") {
        const file = mockFiles.find((f) => f.path === args.path);
        if (file) file.status = "modified";
        return;
      } else if (cmd === "git_stage_all") {
        mockFiles.forEach((f) => (f.status = "staged"));
        return;
      } else if (cmd === "git_commit") {
        const stagedCount = mockFiles.filter((f) => f.status === "staged").length;
        if (stagedCount === 0) throw new Error("No staged changes to commit");
        mockFiles = mockFiles.filter((f) => f.status !== "staged");
        return;
      } else if (cmd === "git_list_branches") {
        return ["main", "feature/test"];
      } else if (cmd === "git_create_branch") {
        return;
      } else if (cmd === "git_checkout_branch") {
        return;
      } else if (cmd === "git_push" || cmd === "git_pull") {
        return;
      }
      return null;
    });
  });

  test("getGitStatus retrieves list of changes", async () => {
    const status = await getGitStatus(CWD);
    expect(status.branch).toBeDefined();
    expect(status.upstream).toBe("origin/main");
    expect(status.files.length).toBeGreaterThan(0);
  });

  test("stageFile and unstageFile transition statuses correctly", async () => {
    const status = await getGitStatus(CWD);
    const testFile = status.files[0];
    const path = testFile.path;

    await stageFile(CWD, path);
    let updated = await getGitStatus(CWD);
    let updatedFile = updated.files.find((f) => f.path === path);
    expect(updatedFile?.status).toBe("staged");

    await unstageFile(CWD, path);
    updated = await getGitStatus(CWD);
    updatedFile = updated.files.find((f) => f.path === path);
    expect(updatedFile?.status).not.toBe("staged");
  });

  test("stageAll marks all files staged", async () => {
    await stageAll(CWD);
    const status = await getGitStatus(CWD);
    const allStaged = status.files.every((f) => f.status === "staged");
    expect(allStaged).toBe(true);
  });

  test("commitChanges throws on empty staged changes, succeeds when staged exists", async () => {
    // Attempt to commit with no staged files
    await expect(commitChanges(CWD, "Empty test")).rejects.toThrow();

    // Now stage one and commit it.
    const status = await getGitStatus(CWD);
    await stageFile(CWD, status.files[0].path);
    await expect(commitChanges(CWD, "Real commit test")).resolves.toBeUndefined();
  });

  test("branch operations", async () => {
    const branches = await getGitBranches(CWD);
    expect(branches.length).toBeGreaterThan(1);

    await createGitBranch(CWD, "test/new-branch");
    await checkoutBranch(CWD, "test/new-branch");
  });

  test("push and pull resolve without error", async () => {
    await expect(pushCommits(CWD)).resolves.toBeUndefined();
    await expect(pullCommits(CWD)).resolves.toBeUndefined();
  });
});
