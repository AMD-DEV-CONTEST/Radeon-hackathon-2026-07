import { mkdir, readFile, readdir, writeFile, appendFile, access } from "node:fs/promises";
import path from "node:path";
import {
  createStore,
  onEvent,
  resetIdSeq,
  toJSONStore,
  type AggregatorOptions,
} from "./aggregator.js";
import type { Event, SessionStore } from "./types.js";

export const DEFAULT_AIRECAP_DIR = ".airecap";

export interface PersistPaths {
  root: string;
  sessionsDir: string;
  sessionDir: string;
  eventsPath: string;
  storePath: string;
}

export function resolveRoot(cwd = process.cwd(), rootName = DEFAULT_AIRECAP_DIR): string {
  return path.isAbsolute(rootName) ? rootName : path.join(cwd, rootName);
}

export function sessionPaths(
  sessionId: string,
  opts?: { cwd?: string; root?: string },
): PersistPaths {
  const root = opts?.root
    ? path.isAbsolute(opts.root)
      ? opts.root
      : path.join(opts.cwd ?? process.cwd(), opts.root)
    : resolveRoot(opts?.cwd);
  const sessionsDir = path.join(root, "sessions");
  const sessionDir = path.join(sessionsDir, sessionId);
  return {
    root,
    sessionsDir,
    sessionDir,
    eventsPath: path.join(sessionDir, "events.jsonl"),
    storePath: path.join(sessionDir, "store.json"),
  };
}

async function exists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

/** Create session directory + empty events.jsonl + initial store.json. */
export async function initSession(
  sessionId: string,
  opts?: { cwd?: string; root?: string; startedAt?: string } & AggregatorOptions,
): Promise<PersistPaths> {
  if (!sessionId || /[\\/]/.test(sessionId)) {
    throw new Error(`invalid session id: ${JSON.stringify(sessionId)}`);
  }
  const paths = sessionPaths(sessionId, opts);
  await mkdir(paths.sessionDir, { recursive: true });

  if (!(await exists(paths.eventsPath))) {
    await writeFile(paths.eventsPath, "", "utf8");
  }

  if (!(await exists(paths.storePath))) {
    const store = createStore(sessionId, opts);
    if (opts?.startedAt) {
      store.started_at = opts.startedAt;
      store.updated_at = opts.startedAt;
    }
    await writeStore(paths, store);
  }

  return paths;
}

export async function readEvents(paths: PersistPaths): Promise<Event[]> {
  if (!(await exists(paths.eventsPath))) return [];
  const text = await readFile(paths.eventsPath, "utf8");
  if (!text.trim()) return [];
  const events: Event[] = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();
    if (!line) continue;
    try {
      events.push(JSON.parse(line) as Event);
    } catch (err) {
      throw new Error(
        `invalid JSONL at ${paths.eventsPath}:${i + 1}: ${(err as Error).message}`,
      );
    }
  }
  return events;
}

export async function readStore(paths: PersistPaths): Promise<SessionStore | null> {
  if (!(await exists(paths.storePath))) return null;
  const raw = JSON.parse(await readFile(paths.storePath, "utf8")) as SessionStore;
  return raw;
}

export async function writeStore(
  paths: PersistPaths,
  store: SessionStore,
): Promise<void> {
  await mkdir(paths.sessionDir, { recursive: true });
  const json = JSON.stringify(toJSONStore(store), null, 2) + "\n";
  await writeFile(paths.storePath, json, "utf8");
}

/**
 * Append events to jsonl (durable first), then full-replay rebuild store.json.
 * Full replay keeps L1 deterministic from L0; S sessions stay small.
 */
export async function appendEvents(
  sessionId: string,
  events: Event[],
  opts?: { cwd?: string; root?: string } & AggregatorOptions,
): Promise<{ paths: PersistPaths; store: SessionStore; appended: number }> {
  if (events.length === 0) {
    const paths = sessionPaths(sessionId, opts);
    const store = (await readStore(paths)) ?? createStore(sessionId, opts);
    return { paths, store, appended: 0 };
  }

  for (const e of events) {
    if (e.session_id !== sessionId) {
      throw new Error(
        `event ${e.id} session_id=${e.session_id} != ${sessionId}`,
      );
    }
  }

  const paths = await initSession(sessionId, opts);
  const existing = await readEvents(paths);
  const seen = new Set(existing.map((e) => e.id));
  const fresh = events.filter((e) => !seen.has(e.id));

  if (fresh.length) {
    const chunk =
      fresh.map((e) => JSON.stringify(e)).join("\n") + "\n";
    await appendFile(paths.eventsPath, chunk, "utf8");
  }

  const store = await rebuildStore(sessionId, opts);
  return { paths, store, appended: fresh.length };
}

/** Rebuild store.json from events.jsonl (source of truth). */
export async function rebuildStore(
  sessionId: string,
  opts?: { cwd?: string; root?: string } & AggregatorOptions,
): Promise<SessionStore> {
  const paths = sessionPaths(sessionId, opts);
  if (!(await exists(paths.eventsPath))) {
    throw new Error(`no session events at ${paths.eventsPath}`);
  }
  const events = await readEvents(paths);
  resetIdSeq();
  const store = createStore(sessionId, opts);
  // stable-ish ids for goals/outcomes across rebuilds: derive from event order
  let n = 0;
  const idFactory = opts?.idFactory ?? (() => {
    n += 1;
    return `l1_${sessionId}_${String(n).padStart(4, "0")}`;
  });
  const aggOpts: AggregatorOptions = { ...opts, idFactory };
  for (const e of [...events].sort(
    (a, b) => Date.parse(a.ts) - Date.parse(b.ts) || a.id.localeCompare(b.id),
  )) {
    onEvent(store, e, aggOpts);
  }
  await writeStore(paths, store);
  return store;
}

export async function listSessions(opts?: {
  cwd?: string;
  root?: string;
}): Promise<string[]> {
  const root = opts?.root
    ? path.isAbsolute(opts.root)
      ? opts.root
      : path.join(opts.cwd ?? process.cwd(), opts.root)
    : resolveRoot(opts?.cwd);
  const sessionsDir = path.join(root, "sessions");
  if (!(await exists(sessionsDir))) return [];
  const entries = await readdir(sessionsDir, { withFileTypes: true });
  return entries
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();
}

/** Parse a file as JSON array, single JSON event, or JSONL. */
export async function loadEventsFromFile(filePath: string): Promise<Event[]> {
  const text = await readFile(filePath, "utf8");
  const trimmed = text.trim();
  if (!trimmed) return [];

  if (trimmed.startsWith("[")) {
    const arr = JSON.parse(trimmed) as Event[];
    if (!Array.isArray(arr)) throw new Error("JSON root must be Event[]");
    return arr;
  }

  // try single object
  if (trimmed.startsWith("{") && !trimmed.includes("\n{")) {
    try {
      const one = JSON.parse(trimmed) as Event;
      if (one && typeof one === "object" && "kind" in one) return [one];
    } catch {
      // fall through to jsonl
    }
  }

  const events: Event[] = [];
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) continue;
    events.push(JSON.parse(t) as Event);
  }
  return events;
}
