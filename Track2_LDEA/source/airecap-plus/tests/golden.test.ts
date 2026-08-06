import { describe, expect, it } from "vitest";
import {
  createStore,
  onEvent,
  replay,
  resetIdSeq,
  type Event,
  type OutcomeCandidate,
} from "../src/index.js";

function idSeq() {
  let n = 0;
  return () => {
    n += 1;
    return `id_${String(n).padStart(2, "0")}`;
  };
}

const ses = "ses_01";

/** README golden path: login NPE fail→pass → verified via focus bind. */
function loginNpeEvents(): Event[] {
  return [
    {
      id: "evt_01",
      ts: "2026-07-28T04:00:00.000Z",
      session_id: ses,
      actor: "user",
      kind: "goal_set",
      signal: "high",
      refs: [],
      payload: {
        statement: "修复登录页 500，并补回归测试",
        success_criteria: ["复现消失", "相关测试绿"],
      },
    },
    {
      id: "evt_02",
      ts: "2026-07-28T04:05:00.000Z",
      session_id: ses,
      actor: "agent",
      kind: "claim_made",
      signal: "high",
      refs: [],
      payload: {
        text: "我会修 AuthController 空指针并加测试",
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
      refs: [{ kind: "test", value: "test_login_ok" }],
      payload: {
        framework: "pytest",
        suite_status: "fail",
        repro_key: "pytest tests/test_auth.py::test_login_ok",
        tests: [
          {
            name: "test_login_ok",
            status: "fail",
            file: "tests/test_auth.py",
            message: "500 Internal Server Error",
          },
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
      refs: [{ kind: "file", value: "src/auth/controller.py" }],
      payload: {
        paths: [
          {
            path: "src/auth/controller.py",
            change: "mod",
            plus: 8,
            minus: 2,
            blob_ref: "blob:sha256:deadbeef",
          },
          {
            path: "tests/test_auth.py",
            change: "mod",
            plus: 15,
            minus: 0,
          },
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
      refs: [],
      payload: {
        framework: "pytest",
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
      refs: [],
      payload: { reason: "normal", apply_ab2: true },
    },
  ];
}

/** Empty completion claim → abandoned on session_end (R-AB2). */
function emptyClaimEvents(): Event[] {
  return [
    {
      id: "evt_c1",
      ts: "2026-07-28T05:00:00.000Z",
      session_id: "ses_empty",
      actor: "agent",
      kind: "claim_made",
      signal: "high",
      refs: [],
      payload: {
        text: "登录已经修好了",
        claim_kind: "completed",
        title_hint: "Login fixed (claim only)",
        type_hint: "bugfix",
      },
    },
    {
      id: "evt_c2",
      ts: "2026-07-28T05:10:00.000Z",
      session_id: "ses_empty",
      actor: "system",
      kind: "session_end",
      signal: "high",
      refs: [],
      payload: { reason: "normal", apply_ab2: true },
    },
  ];
}

describe("golden: login NPE fail→pass", () => {
  it("creates bugfix outcome, focus-binds evidence, verifies via R-V1", () => {
    resetIdSeq();
    const factory = idSeq();
    const store = replay(ses, loginNpeEvents(), { idFactory: factory });

    expect(store.status).toBe("ended");
    expect(store.goals).toHaveLength(1);
    expect(store.goals[0]!.statement).toContain("登录");
    expect(store.outcomes).toHaveLength(1);

    const o = store.outcomes[0]! as OutcomeCandidate;
    expect(o.type).toBe("bugfix");
    expect(o.title).toBe("Fix login NPE");
    expect(o.status).toBe("verified");
    expect(o.once_verified).toBe(true);
    expect(o.verified_at).toBe("2026-07-28T04:13:00.000Z");
    expect(o.confidence).toBeGreaterThanOrEqual(0.7);
    expect(o.confidence_raw).toBeGreaterThan(0);
    expect(o.clamp_reason).toBeDefined();

    // focus bind used for events without outcome_id
    const methods = new Set(o.evidence_links.map((l) => l.method));
    expect(methods.has("focus")).toBe(true);

    // has defines + supports + verifies
    const rels = new Set(o.evidence_links.map((l) => l.relation));
    expect(rels.has("defines")).toBe(true);
    expect(rels.has("verifies")).toBe(true);

    expect(o.scope.paths).toEqual(
      expect.arrayContaining([
        "src/auth/",
        "src/auth/controller.py",
        "tests/test_auth.py",
      ]),
    );
    expect(o.verification_anchors.some((a) => a.key.includes("test_login") || a.key.includes("pytest"))).toBe(
      true,
    );

    // session_end clears focus; verified not abandoned
    expect(store.focus_outcome_id).toBeUndefined();
    expect(store.orphan_event_ids).toEqual([]);
  });

  it("is deterministic under replay", () => {
    const a = replay(ses, loginNpeEvents(), { idFactory: idSeq() });
    const b = replay(ses, loginNpeEvents(), { idFactory: idSeq() });
    expect(a.outcomes[0]!.status).toBe(b.outcomes[0]!.status);
    expect(a.outcomes[0]!.confidence).toBe(b.outcomes[0]!.confidence);
    expect(a.outcomes[0]!.evidence_links).toEqual(b.outcomes[0]!.evidence_links);
  });
});

describe("golden: empty claim → abandoned", () => {
  it("R-AB2 abandons unevidenced claimed at session_end", () => {
    const store = replay("ses_empty", emptyClaimEvents(), {
      idFactory: idSeq(),
    });
    expect(store.outcomes).toHaveLength(1);
    const o = store.outcomes[0]!;
    expect(o.status).toBe("abandoned");
    expect(o.terminal_reason).toBe("session_end_unevidenced_claim");
    expect(store.focus_outcome_id).toBeUndefined();
    expect(store.status).toBe("ended");
  });
});

describe("focus bind", () => {
  it("binds file_change to focus without structured outcome_id", () => {
    resetIdSeq();
    const opts = { idFactory: idSeq() };
    const store = createStore("ses_f", opts);
    onEvent(
      store,
      {
        id: "e1",
        ts: "2026-07-28T01:00:00.000Z",
        session_id: "ses_f",
        actor: "agent",
        kind: "claim_made",
        signal: "high",
        payload: {
          text: "work on foo",
          claim_kind: "progress",
          title_hint: "Foo",
          type_hint: "feature",
        },
      },
      opts,
    );
    expect(store.focus_outcome_id).toBeTruthy();
    onEvent(
      store,
      {
        id: "e2",
        ts: "2026-07-28T01:01:00.000Z",
        session_id: "ses_f",
        actor: "tool",
        kind: "file_change",
        signal: "high",
        payload: {
          paths: [{ path: "src/foo.ts", change: "mod", plus: 3, minus: 1 }],
        },
      },
      opts,
    );
    const o = store.outcomes[0]!;
    expect(o.status).toBe("evidenced");
    expect(o.evidence_links.some((l) => l.method === "focus")).toBe(true);
    expect(store.orphan_event_ids).toEqual([]);
  });
});

describe("confidence observability", () => {
  it("clamps claimed display confidence to ≤0.45", () => {
    const store = replay(
      "ses_c",
      [
        {
          id: "e1",
          ts: "2026-07-28T01:00:00.000Z",
          session_id: "ses_c",
          actor: "user",
          kind: "claim_made",
          signal: "high",
          payload: {
            text: "done",
            claim_kind: "completed",
            title_hint: "X",
          },
        },
      ],
      { idFactory: idSeq() },
    );
    const o = store.outcomes[0]!;
    expect(o.status).toBe("claimed");
    expect(o.confidence).toBeLessThanOrEqual(0.45);
    expect(o.confidence_raw).toBeGreaterThanOrEqual(0);
  });
});
