import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { listSessions, readStore, sessionPaths, type SessionStore } from "airecap-plus";
import type { LdeaConfig } from "./config.js";

export interface SessionMeta {
  session_id: string;
  kind?: "close" | "run" | "demo" | "init" | "pipeline";
  goal?: string;
  claim?: string;
  cwd?: string;
  created_at: string;
  updated_at?: string;
  tags?: string[];
}

export interface SessionSummary {
  id: string;
  kind?: string;
  goal?: string;
  claim?: string;
  cwd?: string;
  created_at?: string;
  updated_at?: string;
  store_status?: string;
  counts: {
    verified: number;
    evidenced: number;
    claimed: number;
    contradicted: number;
    abandoned: number;
    total: number;
  };
  titles: string[];
  has_report: boolean;
  session_dir: string;
}

function metaPath(sessionDir: string): string {
  return path.join(sessionDir, "meta.json");
}

export async function writeSessionMeta(
  config: Pick<LdeaConfig, "cwd" | "root">,
  sessionId: string,
  patch: Partial<SessionMeta>,
): Promise<SessionMeta> {
  const paths = sessionPaths(sessionId, { cwd: config.cwd, root: config.root });
  let prev: Partial<SessionMeta> = {};
  try {
    prev = JSON.parse(await readFile(metaPath(paths.sessionDir), "utf8")) as SessionMeta;
  } catch {
    /* new */
  }
  const now = new Date().toISOString();
  const next: SessionMeta = {
    ...prev,
    ...patch,
    session_id: sessionId,
    created_at: prev.created_at ?? now,
    updated_at: now,
  };
  await writeFile(metaPath(paths.sessionDir), JSON.stringify(next, null, 2) + "\n", "utf8");
  return next;
}

export async function readSessionMeta(
  config: Pick<LdeaConfig, "cwd" | "root">,
  sessionId: string,
): Promise<SessionMeta | null> {
  const paths = sessionPaths(sessionId, { cwd: config.cwd, root: config.root });
  try {
    return JSON.parse(await readFile(metaPath(paths.sessionDir), "utf8")) as SessionMeta;
  } catch {
    return null;
  }
}

function countStatuses(store: SessionStore | null) {
  const active = store?.outcomes.filter((o) => o.status !== "superseded") ?? [];
  return {
    verified: active.filter((o) => o.status === "verified").length,
    evidenced: active.filter((o) => o.status === "evidenced").length,
    claimed: active.filter((o) => o.status === "claimed").length,
    contradicted: active.filter((o) => o.status === "contradicted").length,
    abandoned: active.filter((o) => o.status === "abandoned").length,
    total: active.length,
  };
}

export async function summarizeSession(
  config: Pick<LdeaConfig, "cwd" | "root">,
  sessionId: string,
): Promise<SessionSummary> {
  const paths = sessionPaths(sessionId, { cwd: config.cwd, root: config.root });
  const meta = await readSessionMeta(config, sessionId);
  const store = await readStore(paths);
  let hasReport = false;
  try {
    await readFile(path.join(paths.sessionDir, "report.md"), "utf8");
    hasReport = true;
  } catch {
    hasReport = false;
  }
  const counts = countStatuses(store);
  const titles =
    store?.outcomes
      .filter((o) => o.status !== "superseded")
      .slice()
      .sort((a, b) => b.confidence - a.confidence)
      .map((o) => o.title)
      .slice(0, 3) ?? [];

  return {
    id: sessionId,
    kind: meta?.kind,
    goal: meta?.goal,
    claim: meta?.claim,
    cwd: meta?.cwd ?? config.cwd,
    created_at: meta?.created_at ?? store?.started_at,
    updated_at: meta?.updated_at ?? store?.updated_at,
    store_status: store?.status,
    counts,
    titles,
    has_report: hasReport,
    session_dir: paths.sessionDir,
  };
}

export async function listSessionSummaries(
  config: Pick<LdeaConfig, "cwd" | "root">,
  opts?: { status?: string },
): Promise<SessionSummary[]> {
  const ids = await listSessions({ cwd: config.cwd, root: config.root });
  const rows: SessionSummary[] = [];
  for (const id of ids) {
    const row = await summarizeSession(config, id);
    if (opts?.status) {
      const key = opts.status as keyof SessionSummary["counts"];
      if (key === "total") {
        if (row.counts.total === 0) continue;
      } else if (typeof row.counts[key] === "number") {
        if (row.counts[key] <= 0) continue;
      } else {
        continue;
      }
    }
    rows.push(row);
  }
  rows.sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
  return rows;
}

export function formatSessionList(rows: SessionSummary[]): string {
  if (!rows.length) return "(no sessions)";
  const lines: string[] = [];
  lines.push(
    pad("SESSION", 28) +
      pad("V/E/C/A", 12) +
      pad("STATE", 8) +
      pad("KIND", 8) +
      "TITLE / GOAL",
  );
  lines.push("-".repeat(90));
  for (const r of rows) {
    const ve = `${r.counts.verified}/${r.counts.evidenced}/${r.counts.claimed}/${r.counts.abandoned}`;
    const title = r.titles[0] ?? r.claim ?? r.goal ?? "(empty)";
    lines.push(
      pad(r.id, 28) +
        pad(ve, 12) +
        pad(r.store_status ?? "?", 8) +
        pad(r.kind ?? "-", 8) +
        truncate(title, 48),
    );
  }
  lines.push("");
  lines.push("V/E/C/A = verified / evidenced / claimed / abandoned");
  return lines.join("\n");
}

function pad(s: string, n: number): string {
  const t = s.length > n ? s.slice(0, n - 1) + "…" : s;
  return t + " ".repeat(Math.max(1, n - t.length));
}

function truncate(s: string, n: number): string {
  const one = s.replace(/\s+/g, " ").trim();
  return one.length > n ? one.slice(0, n - 1) + "…" : one;
}
