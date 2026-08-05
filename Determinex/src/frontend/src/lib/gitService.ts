import { invokeSafe, invokeWrite } from "./api";

/**
 * Write path for git commands, deliberately NOT invokeSafe.
 *
 * Every git mutation here returns Result<(), String> on the Rust side, so
 * success resolves to null -- and invokeSafe returns null on failure too,
 * after only a console.warn. The result was that a failed stage/commit/push
 * was indistinguishable from a successful one: the wrapper returned void
 * either way.
 *
 * That is not theoretical. GitPanel already wraps commit, branch-create and
 * checkout in try/catch with setError("Commit failed") etc., but because
 * invokeSafe never throws, those catch blocks were unreachable -- a commit
 * rejected by a pre-commit hook (this repo has no-env-file and no-api-keys
 * hooks) cleared the message box and looked like it worked. Two earlier
 * casualties of the same swallow are documented in cloneRepo and
 * resolveConflict below, both of which silently no-op'd for their whole
 * lifetime.
 *
 * The implementation moved to `api.ts` as `invokeWrite` once the same guard was
 * needed at a dozen more sites outside git; this alias is kept because the
 * reasoning above is git-specific and worth reading where the git writes live.
 */
const invokeGitWrite = invokeWrite;

export type GitFileStatus = "modified" | "untracked" | "staged" | "conflicted";

export type GitFile = {
  path: string;
  status: GitFileStatus;
  /** Raw porcelain status code (e.g. "M", "??", "AM"), for real status badges. */
  code: string;
  originalContent?: string;
  currentContent?: string;
};

export type GitBranch = {
  name: string;
  isCurrent: boolean;
};

export interface GitStatusResult {
  branch: string;
  /** The upstream this branch tracks (e.g. "origin/main"), if any. */
  upstream: string | null;
  files: GitFile[];
  ahead: number;
  behind: number;
}

export async function getGitStatus(cwd: string): Promise<GitStatusResult> {
  const res = await invokeSafe<GitStatusResult>("git_status", { cwd });
  if (!res) {
    throw new Error("Tauri git_status returned null");
  }
  // `Promise<GitStatusResult>` is a compile-time promise about a runtime value that arrives
  // over IPC, and it was being kept by assertion alone. When a backend returned a payload
  // without `files`, the undefined propagated two hooks away into
  // `explorerGitStatusMap`'s `for (const file of explorerGitFiles)`, threw
  // "explorerGitFiles is not iterable", and the error boundary unmounted the ENTIRE IDE --
  // including, on first run, the setup wizard, so a new user's app went blank mid-setup with
  // a stack trace pointing at a useMemo that was not at fault.
  //
  // Failing here instead routes into the caller's existing catch, which sets
  // `explorerGitUnavailable` -- the honest state, and one the UI already renders as "could
  // not read git" rather than the false "working tree clean".
  if (!Array.isArray(res.files)) {
    throw new Error(
      `git_status returned no file list (got ${typeof res.files}); treating the read as failed`
    );
  }
  return { ...res, ahead: res.ahead ?? 0, behind: res.behind ?? 0, upstream: res.upstream ?? null };
}

export async function stageFile(cwd: string, filePath: string): Promise<void> {
  await invokeGitWrite("git_stage", { cwd, path: filePath });
}

export async function unstageFile(cwd: string, filePath: string): Promise<void> {
  await invokeGitWrite("git_unstage", { cwd, path: filePath });
}

export async function stageAll(cwd: string): Promise<void> {
  await invokeGitWrite("git_stage_all", { cwd });
}

export async function commitChanges(cwd: string, message: string): Promise<void> {
  await invokeGitWrite("git_commit", { cwd, message });
}

export async function getGitBranches(cwd: string): Promise<GitBranch[]> {
  const branches = await invokeSafe<string[]>("git_list_branches", { cwd });
  if (!branches) {
    return [];
  }
  const currentBranchRes = await getGitStatus(cwd).catch(() => null);
  const currentBranch = currentBranchRes?.branch || "";

  return branches.map((b) => ({ name: b, isCurrent: b === currentBranch }));
}

export async function createGitBranch(cwd: string, name: string): Promise<void> {
  await invokeGitWrite("git_create_branch", { cwd, name });
}

export async function checkoutBranch(cwd: string, name: string): Promise<void> {
  await invokeGitWrite("git_checkout_branch", { cwd, name });
}

export async function pushCommits(cwd: string): Promise<void> {
  await invokeGitWrite("git_push", { cwd });
}

export async function pullCommits(cwd: string): Promise<void> {
  await invokeGitWrite("git_pull", { cwd });
}

/** Real `git clone`. Refuses (backend-side) to clone into a path that already exists. */
export async function cloneRepo(remoteUrl: string, destination: string): Promise<void> {
  // Was `remote_url` -- Tauri converts camelCase JS keys to the Rust
  // command's snake_case parameter names, so the snake_case key here meant
  // this never found a matching argument. Every "Git Clone" attempt from
  // ProjectHub failed silently (invokeSafe swallows the rejection).
  await invokeGitWrite("git_clone", { remoteUrl, destination });
}

export interface ConflictSides {
  /** Common ancestor (merge-base), stage 1 in the index. Null if git never populated it
   * (e.g. an add/add conflict has no shared ancestor). */
  base: string | null;
  /** "Our" side -- stage 2, the current branch's version. */
  ours: string | null;
  /** "Their" side -- stage 3, the incoming branch's version. */
  theirs: string | null;
  /** The raw working-tree file as git left it -- real conflict markers inline. */
  current: string | null;
}

/** The three pre-merge blobs for one conflicted file, via `git show :N:<path>`. */
export async function getConflictSides(cwd: string, path: string): Promise<ConflictSides> {
  const res = await invokeSafe<ConflictSides>("git_conflict_sides", { cwd, path });
  if (!res) {
    throw new Error("Tauri git_conflict_sides returned null");
  }
  return res;
}

/** Writes the resolved content and `git add`s the file -- marks it resolved for the merge. */
export async function resolveConflict(
  cwd: string,
  path: string,
  resolvedContent: string
): Promise<void> {
  // The snake_case key this comment used to defend by pointing at cloneRepo's
  // remote_url was the same bug, not a real convention -- Tauri converts
  // camelCase JS keys to the Rust command's snake_case parameter names, so
  // this call failed 100% of the time (every Merge Editor "resolve" was
  // silently a no-op, invokeSafe swallowing the rejection).
  await invokeGitWrite("git_resolve_conflict", { cwd, path, resolvedContent });
}
