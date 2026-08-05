import { describe, expect, it, vi, beforeEach } from "vitest";

const rawInvoke = vi.fn();
const safeInvoke = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => rawInvoke(...args),
}));

// The Tauri runtime marker api.ts's isTauri() looks for. Set so the REAL
// invokeWrite runs its real path (guard + raw invoke) instead of being stubbed:
// the guard is part of what these tests are pinning, and a stubbed invokeWrite
// would have made this suite pass no matter what gitService did with it.
(globalThis as unknown as { window: Record<string, unknown> }).window ??=
  globalThis as unknown as Record<string, unknown>;
(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {
  transformCallback: () => {},
};

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, invokeSafe: (...args: unknown[]) => safeInvoke(...args) };
});

import {
  stageFile,
  stageAll,
  unstageFile,
  commitChanges,
  pushCommits,
  pullCommits,
  createGitBranch,
  checkoutBranch,
  cloneRepo,
  resolveConflict,
} from "../gitService";

/**
 * Every git mutation returns Result<(), String> in Rust, so success resolves to
 * null -- the same value invokeSafe returns on failure. Routing writes through
 * invokeSafe therefore made a rejected commit indistinguishable from a
 * successful one, and left GitPanel's existing
 * `catch { setError("Commit failed") }` blocks permanently unreachable.
 *
 * These tests pin the two halves of the contract: a real rejection must
 * propagate, and a null (success) must not be mistaken for an error.
 */
describe("gitService write operations propagate backend failures", () => {
  beforeEach(() => {
    rawInvoke.mockReset();
    safeInvoke.mockReset();
  });

  const cases: Array<[string, () => Promise<void>, string]> = [
    ["stageFile", () => stageFile("C:\\ws", "a.ts"), "git_stage"],
    ["unstageFile", () => unstageFile("C:\\ws", "a.ts"), "git_unstage"],
    ["stageAll", () => stageAll("C:\\ws"), "git_stage_all"],
    ["commitChanges", () => commitChanges("C:\\ws", "msg"), "git_commit"],
    ["pushCommits", () => pushCommits("C:\\ws"), "git_push"],
    ["pullCommits", () => pullCommits("C:\\ws"), "git_pull"],
    ["createGitBranch", () => createGitBranch("C:\\ws", "b"), "git_create_branch"],
    ["checkoutBranch", () => checkoutBranch("C:\\ws", "b"), "git_checkout_branch"],
    ["cloneRepo", () => cloneRepo("https://x/y.git", "C:\\ws\\y"), "git_clone"],
    ["resolveConflict", () => resolveConflict("C:\\ws", "a.ts", "text"), "git_resolve_conflict"],
  ];

  it.each(cases)("%s rejects when the backend rejects", async (_name, call, cmd) => {
    rawInvoke.mockRejectedValueOnce(new Error(`${cmd} exploded`));
    await expect(call()).rejects.toThrow(`${cmd} exploded`);
  });

  it.each(cases)("%s resolves when the backend succeeds (null)", async (_name, call, cmd) => {
    // A void Tauri command resolves to null on SUCCESS.
    rawInvoke.mockResolvedValueOnce(null);
    await expect(call()).resolves.toBeUndefined();
    expect(rawInvoke.mock.calls[0][0]).toBe(cmd);
  });

  it("never routes a write through invokeSafe, which cannot report failure", async () => {
    rawInvoke.mockResolvedValue(null);
    await commitChanges("C:\\ws", "msg");
    await pushCommits("C:\\ws");
    expect(safeInvoke).not.toHaveBeenCalled();
  });

  it("sends camelCase arg keys, which Tauri maps to snake_case params", async () => {
    // Both cloneRepo and resolveConflict previously shipped snake_case keys and
    // silently no-op'd for their entire lifetime because no parameter matched.
    rawInvoke.mockResolvedValue(null);
    await cloneRepo("https://x/y.git", "C:\\ws\\y");
    expect(rawInvoke).toHaveBeenCalledWith("git_clone", {
      remoteUrl: "https://x/y.git",
      destination: "C:\\ws\\y",
    });

    rawInvoke.mockClear();
    await resolveConflict("C:\\ws", "a.ts", "text");
    expect(rawInvoke).toHaveBeenCalledWith("git_resolve_conflict", {
      cwd: "C:\\ws",
      path: "a.ts",
      resolvedContent: "text",
    });
  });
});
