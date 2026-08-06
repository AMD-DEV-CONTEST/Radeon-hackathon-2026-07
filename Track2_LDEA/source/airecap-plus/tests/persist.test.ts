import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { Event } from "../src/index.js";
import {
  appendEvents,
  initSession,
  listSessions,
  loadEventsFromFile,
  readEvents,
  readStore,
  rebuildStore,
  sessionPaths,
  writeStore,
} from "../src/persist.js";
import { createStore } from "../src/index.js";

const dirs: string[] = [];

async function tmpRoot(): Promise<string> {
  const d = await mkdtemp(path.join(os.tmpdir(), "airecap-"));
  dirs.push(d);
  return d;
}

afterEach(async () => {
  while (dirs.length) {
    const d = dirs.pop()!;
    await rm(d, { recursive: true, force: true });
  }
});

const loginEvents = (ses: string): Event[] => [
  {
    id: "evt_01",
    ts: "2026-07-28T04:00:00.000Z",
    session_id: ses,
    actor: "user",
    kind: "goal_set",
    signal: "high",
    payload: {
      statement: "修复登录页 500",
      success_criteria: ["测试绿"],
    },
  },
  {
    id: "evt_02",
    ts: "2026-07-28T04:05:00.000Z",
    session_id: ses,
    actor: "agent",
    kind: "claim_made",
    signal: "high",
    payload: {
      text: "fix NPE",
      claim_kind: "other",
      type_hint: "bugfix",
      title_hint: "Fix login NPE",
      scope_hint: { paths: ["src/auth/"] },
    },
  },
  {
    id: "evt_03",
    ts: "2026-07-28T04:06:00.000Z",
    session_id: ses,
    actor: "tool",
    kind: "test_result",
    signal: "high",
    payload: {
      suite_status: "fail",
      repro_key: "pytest tests/test_auth.py::test_login_ok",
      tests: [
        { name: "test_login_ok", status: "fail", file: "tests/test_auth.py" },
      ],
    },
  },
  {
    id: "evt_04",
    ts: "2026-07-28T04:12:00.000Z",
    session_id: ses,
    actor: "tool",
    kind: "file_change",
    signal: "high",
    payload: {
      paths: [
        { path: "src/auth/controller.py", change: "mod", plus: 8, minus: 2 },
        { path: "tests/test_auth.py", change: "mod", plus: 15, minus: 0 },
      ],
    },
  },
  {
    id: "evt_05",
    ts: "2026-07-28T04:13:00.000Z",
    session_id: ses,
    actor: "tool",
    kind: "test_result",
    signal: "high",
    payload: {
      suite_status: "pass",
      repro_key: "pytest tests/test_auth.py::test_login_ok",
      tests: [
        { name: "test_login_ok", status: "pass", file: "tests/test_auth.py" },
      ],
    },
  },
  {
    id: "evt_06",
    ts: "2026-07-28T04:20:00.000Z",
    session_id: ses,
    actor: "system",
    kind: "session_end",
    signal: "high",
    payload: { reason: "normal", apply_ab2: true },
  },
];

describe("persist", () => {
  it("init creates events.jsonl and store.json", async () => {
    const root = await tmpRoot();
    const paths = await initSession("ses_a", { root });
    expect(paths.eventsPath).toContain("ses_a");
    const store = await readStore(paths);
    expect(store?.session_id).toBe("ses_a");
    expect(store?.outcomes).toEqual([]);
    const ev = await readEvents(paths);
    expect(ev).toEqual([]);
  });

  it("append writes jsonl and rebuilds verified outcome", async () => {
    const root = await tmpRoot();
    const ses = "ses_login";
    const { store, appended, paths } = await appendEvents(
      ses,
      loginEvents(ses),
      { root },
    );
    expect(appended).toBe(6);
    expect(store.outcomes).toHaveLength(1);
    expect(store.outcomes[0]!.status).toBe("verified");
    expect(store.status).toBe("ended");

    const disk = await readFile(paths.eventsPath, "utf8");
    expect(disk.trim().split(/\n/)).toHaveLength(6);

    const loaded = await readStore(paths);
    expect(loaded?.outcomes[0]?.status).toBe("verified");
    // no _events on disk
    expect((loaded as { _events?: unknown })._events).toBeUndefined();
  });

  it("append is idempotent on event id", async () => {
    const root = await tmpRoot();
    const ses = "ses_idemp";
    await appendEvents(ses, loginEvents(ses), { root });
    const second = await appendEvents(ses, loginEvents(ses), { root });
    expect(second.appended).toBe(0);
    const paths = sessionPaths(ses, { root });
    const ev = await readEvents(paths);
    expect(ev).toHaveLength(6);
  });

  it("replay rebuilds same status from jsonl alone", async () => {
    const root = await tmpRoot();
    const ses = "ses_replay";
    await appendEvents(ses, loginEvents(ses), { root });
    const paths = sessionPaths(ses, { root });
    // corrupt store
    await writeStore(paths, createStore(ses));
    const rebuilt = await rebuildStore(ses, { root });
    expect(rebuilt.outcomes[0]!.status).toBe("verified");
    expect(rebuilt.outcomes[0]!.title).toBe("Fix login NPE");
  });

  it("listSessions", async () => {
    const root = await tmpRoot();
    await initSession("b", { root });
    await initSession("a", { root });
    expect(await listSessions({ root })).toEqual(["a", "b"]);
  });

  it("loadEventsFromFile supports json array", async () => {
    const root = await tmpRoot();
    const f = path.join(root, "ev.json");
    const ses = "s";
    const { writeFile } = await import("node:fs/promises");
    await writeFile(f, JSON.stringify(loginEvents(ses)), "utf8");
    const ev = await loadEventsFromFile(f);
    expect(ev).toHaveLength(6);
  });

  it("rejects cross-session append", async () => {
    const root = await tmpRoot();
    await expect(
      appendEvents(
        "ses_x",
        [
          {
            id: "e1",
            ts: "2026-07-28T00:00:00.000Z",
            session_id: "other",
            actor: "user",
            kind: "claim_made",
            signal: "high",
            payload: { text: "x", claim_kind: "other" },
          },
        ],
        { root },
      ),
    ).rejects.toThrow(/session_id/);
  });
});
