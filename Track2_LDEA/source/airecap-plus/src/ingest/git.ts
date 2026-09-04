/**
 * Git → L0 file_change.
 *
 * Modes:
 *   worktree (default)  git diff HEAD --numstat/--name-status  (staged+unstaged)
 *   --staged            git diff --cached
 *   --commit <sha>      git show <sha>
 *   --range <a> <b>     git diff a..b
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { Event, PathChange } from "../types.js";
import { makeEvent } from "./ids.js";

const execFileAsync = promisify(execFile);

export type GitIngestMode =
  | { kind: "worktree"; staged?: boolean }
  | { kind: "commit"; sha: string }
  | { kind: "range"; from: string; to: string };

export interface GitIngestOptions {
  sessionId: string;
  cwd?: string;
  mode?: GitIngestMode;
  isRevert?: boolean;
  outcomeId?: string;
  ts?: string;
  eventId?: string;
  runner?: GitRunner;
}

export type GitRunner = (
  args: string[],
  cwd: string,
) => Promise<{ stdout: string; stderr: string }>;

const defaultRunner: GitRunner = async (args, cwd) => {
  const { stdout, stderr } = await execFileAsync("git", args, {
    cwd,
    maxBuffer: 8 * 1024 * 1024,
    windowsHide: true,
  });
  return { stdout: String(stdout), stderr: String(stderr) };
};

function parseNameStatus(text: string): Map<string, PathChange["change"]> {
  const map = new Map<string, PathChange["change"]>();
  for (const line of text.split(/\r?\n/)) {
    const t = line.trimEnd();
    if (!t) continue;
    const parts = t.split("\t");
    if (parts.length < 2) continue;
    const code = parts[0] ?? "";
    const statusChar = code[0] ?? "";
    if (statusChar === "R" || statusChar === "C") {
      const to = parts[2] ?? parts[1];
      if (to) map.set(to, "rename");
      continue;
    }
    const path = parts[1];
    if (!path) continue;
    if (statusChar === "A") map.set(path, "add");
    else if (statusChar === "D") map.set(path, "del");
    else map.set(path, "mod");
  }
  return map;
}

function parseNumstat(
  text: string,
): Map<string, { plus: number; minus: number }> {
  const map = new Map<string, { plus: number; minus: number }>();
  for (const line of text.split(/\r?\n/)) {
    const t = line.trimEnd();
    if (!t) continue;
    const m = t.match(/^(\d+|-)\t(\d+|-)\t(.+)$/);
    if (!m) continue;
    let path = m[3]!;
    if (path.includes(" => ")) {
      path = path.split(" => ").pop()!.trim();
    }
    map.set(path, {
      plus: m[1] === "-" ? 0 : Number(m[1]),
      minus: m[2] === "-" ? 0 : Number(m[2]),
    });
  }
  return map;
}

function mergePaths(
  nameStatus: Map<string, PathChange["change"]>,
  numstat: Map<string, { plus: number; minus: number }>,
): PathChange[] {
  const keys = new Set([...nameStatus.keys(), ...numstat.keys()]);
  const out: PathChange[] = [];
  for (const path of [...keys].sort()) {
    const stats = numstat.get(path);
    out.push({
      path: path.replace(/\\/g, "/"),
      change: nameStatus.get(path) ?? "mod",
      plus: stats?.plus ?? 0,
      minus: stats?.minus ?? 0,
    });
  }
  return out;
}

function lookLikeRevert(message: string): boolean {
  return /^\s*revert\b/i.test(message);
}

async function runGit(
  runner: GitRunner,
  cwd: string,
  args: string[],
): Promise<string> {
  const { stdout } = await runner(args, cwd);
  return stdout;
}

export async function collectGitDiff(opts: GitIngestOptions): Promise<{
  paths: PathChange[];
  commit?: string;
  is_revert: boolean;
  summary?: string;
}> {
  const cwd = opts.cwd ?? process.cwd();
  const runner = opts.runner ?? defaultRunner;
  const mode: GitIngestMode = opts.mode ?? { kind: "worktree", staged: false };

  let nameStatus = "";
  let numstat = "";
  let commit: string | undefined;
  let subject = "";

  if (mode.kind === "worktree") {
    const diffBase = mode.staged ? ["diff", "--cached"] : ["diff", "HEAD"];
    nameStatus = await runGit(runner, cwd, [...diffBase, "--name-status"]);
    numstat = await runGit(runner, cwd, [...diffBase, "--numstat"]);
  } else if (mode.kind === "commit") {
    const meta = await runGit(runner, cwd, [
      "show",
      "-s",
      "--format=%H%n%s",
      mode.sha,
    ]);
    const metaLines = meta.trim().split(/\r?\n/);
    commit = metaLines[0] || mode.sha;
    subject = metaLines.slice(1).join("\n");
    nameStatus = await runGit(runner, cwd, [
      "show",
      "--format=",
      "--name-status",
      mode.sha,
    ]);
    numstat = await runGit(runner, cwd, [
      "show",
      "--format=",
      "--numstat",
      mode.sha,
    ]);
  } else {
    nameStatus = await runGit(runner, cwd, [
      "diff",
      `${mode.from}..${mode.to}`,
      "--name-status",
    ]);
    numstat = await runGit(runner, cwd, [
      "diff",
      `${mode.from}..${mode.to}`,
      "--numstat",
    ]);
  }

  const paths = mergePaths(parseNameStatus(nameStatus), parseNumstat(numstat));
  const is_revert =
    opts.isRevert === true || (subject ? lookLikeRevert(subject) : false);

  return {
    paths,
    commit,
    is_revert,
    summary: subject || undefined,
  };
}

export function parseGitNameStatus(
  text: string,
): Map<string, PathChange["change"]> {
  return parseNameStatus(text);
}

export function parseGitNumstat(
  text: string,
): Map<string, { plus: number; minus: number }> {
  return parseNumstat(text);
}

export function buildFileChangeEvent(
  sessionId: string,
  data: {
    paths: PathChange[];
    commit?: string;
    is_revert?: boolean;
    summary?: string;
    outcome_id?: string;
  },
  opts?: { ts?: string; id?: string },
): Event {
  return makeEvent({
    id: opts?.id,
    ts: opts?.ts,
    session_id: sessionId,
    actor: "tool",
    kind: "file_change",
    refs: [
      ...data.paths
        .slice(0, 20)
        .map((p) => ({ kind: "file" as const, value: p.path })),
      ...(data.commit ? [{ kind: "commit" as const, value: data.commit }] : []),
    ],
    payload: {
      paths: data.paths,
      commit: data.commit,
      is_revert: data.is_revert || undefined,
      summary: data.summary,
      outcome_id: data.outcome_id,
    },
  });
}

export async function ingestGit(opts: GitIngestOptions): Promise<Event[]> {
  const diff = await collectGitDiff(opts);
  if (diff.paths.length === 0) return [];
  return [
    buildFileChangeEvent(
      opts.sessionId,
      {
        paths: diff.paths,
        commit: diff.commit,
        is_revert: diff.is_revert,
        summary: diff.summary,
        outcome_id: opts.outcomeId,
      },
      { ts: opts.ts, id: opts.eventId },
    ),
  ];
}
