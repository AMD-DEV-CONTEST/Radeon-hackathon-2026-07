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

function base(
  partial: Omit<Event, "signal" | "refs"> &
    Partial<Pick<Event, "signal" | "refs">>,
): Event {
  return {
    signal: "high",
    refs: [],
    ...partial,
  } as Event;
}

/** Build a verified bugfix via fail→pass (R-V1), same shape as golden path. */
function verifiedBugfixEvents(ses: string, prefix = "v"): Event[] {
  return [
    base({
      id: `${prefix}_claim`,
      ts: "2026-07-28T10:00:00.000Z",
      session_id: ses,
      actor: "agent",
      kind: "claim_made",
      payload: {
        text: "fix login NPE",
        claim_kind: "fixed",
        type_hint: "bugfix",
        title_hint: "Fix login NPE",
        scope_hint: { paths: ["src/auth/"] },
      },
    }),
    base({
      id: `${prefix}_fail`,
      ts: "2026-07-28T10:01:00.000Z",
      session_id: ses,
      actor: "tool",
      kind: "test_result",
      payload: {
        suite_status: "fail",
        repro_key: "pytest tests/test_auth.py::test_login_ok",
        tests: [
          {
            name: "test_login_ok",
            status: "fail",
            file: "tests/test_auth.py",
          },
        ],
      },
    }),
    base({
      id: `${prefix}_patch`,
      ts: "2026-07-28T10:05:00.000Z",
      session_id: ses,
      actor: "tool",
      kind: "file_change",
      payload: {
        paths: [
          {
            path: "src/auth/controller.py",
            change: "mod",
            plus: 5,
            minus: 1,
          },
        ],
      },
    }),
    base({
      id: `${prefix}_pass`,
      ts: "2026-07-28T10:06:00.000Z",
      session_id: ses,
      actor: "tool",
      kind: "test_result",
      payload: {
        suite_status: "pass",
        repro_key: "pytest tests/test_auth.py::test_login_ok",
        tests: [
          {
            name: "test_login_ok",
            status: "pass",
            file: "tests/test_auth.py",
          },
        ],
      },
    }),
  ];
}

describe("R-X2: test regression verified → contradicted", () => {
  it("same-anchor pass→fail pulls verified back to contradicted", () => {
    const ses = "ses_rx2";
    const events: Event[] = [
      ...verifiedBugfixEvents(ses),
      base({
        id: "rx2_reg",
        ts: "2026-07-28T10:20:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "test_result",
        payload: {
          suite_status: "fail",
          repro_key: "pytest tests/test_auth.py::test_login_ok",
          tests: [
            {
              name: "test_login_ok",
              status: "fail",
              file: "tests/test_auth.py",
              message: "regression: 500 again",
            },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    expect(store.outcomes).toHaveLength(1);
    const o = store.outcomes[0]!;
    expect(o.status).toBe("contradicted");
    expect(o.terminal_reason).toBe("test_regressed");
    expect(o.once_verified).toBe(true);
    expect(o.verified_at).toBeUndefined();
    expect(o.confidence).toBeLessThanOrEqual(0.4);
    // ceiling only when raw would exceed 0.40; otherwise clamp_reason stays none
    if (o.confidence_raw > 0.4) {
      expect(o.clamp_reason).toBe("ceiling_contradicted");
    }
    expect(o.counter_evidence.some((l) => l.relation === "refutes")).toBe(true);
    // anchor stripped so a later pass can re-close via fresh fail→pass
    expect(
      o.verification_anchors.some(
        (a) => a.key === "pytest tests/test_auth.py::test_login_ok",
      ),
    ).toBe(false);
  });

  it("R-R1: new non-llm evidence resurrects contradicted → evidenced", () => {
    const ses = "ses_rr1";
    const events: Event[] = [
      ...verifiedBugfixEvents(ses),
      base({
        id: "rr1_reg",
        ts: "2026-07-28T10:20:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "test_result",
        payload: {
          suite_status: "fail",
          repro_key: "pytest tests/test_auth.py::test_login_ok",
          tests: [
            { name: "test_login_ok", status: "fail", file: "tests/test_auth.py" },
          ],
        },
      }),
      base({
        id: "rr1_patch2",
        ts: "2026-07-28T10:30:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            {
              path: "src/auth/controller.py",
              change: "mod",
              plus: 3,
              minus: 1,
            },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const o = store.outcomes[0]!;
    expect(o.status).toBe("evidenced");
    expect(o.terminal_reason).toBeUndefined();
    expect(o.once_verified).toBe(true);
  });
});

describe("R-X1: revert → contradicted", () => {
  it("is_revert on verified outcome marks contradicted", () => {
    const ses = "ses_rx1";
    const events: Event[] = [
      ...verifiedBugfixEvents(ses),
      base({
        id: "rx1_revert",
        ts: "2026-07-28T10:25:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          is_revert: true,
          paths: [
            {
              path: "src/auth/controller.py",
              change: "mod",
              plus: 1,
              minus: 5,
            },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const o = store.outcomes[0]!;
    expect(o.status).toBe("contradicted");
    expect(o.terminal_reason).toBe("reverted");
    expect(o.verified_at).toBeUndefined();
    expect(o.once_verified).toBe(true);
    expect(o.counter_evidence.length).toBeGreaterThan(0);
  });

  it("is_revert on evidenced (never verified) also contradicts", () => {
    const ses = "ses_rx1b";
    const events: Event[] = [
      base({
        id: "c1",
        ts: "2026-07-28T11:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "refactor utils",
          claim_kind: "progress",
          type_hint: "refactor",
          title_hint: "Refactor utils",
          scope_hint: { paths: ["src/utils/"] },
        },
      }),
      base({
        id: "f1",
        ts: "2026-07-28T11:01:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            { path: "src/utils/helpers.ts", change: "mod", plus: 20, minus: 8 },
          ],
        },
      }),
      base({
        id: "f2",
        ts: "2026-07-28T11:05:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          is_revert: true,
          paths: [
            { path: "src/utils/helpers.ts", change: "mod", plus: 8, minus: 20 },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const o = store.outcomes[0]!;
    expect(o.status).toBe("contradicted");
    expect(o.terminal_reason).toBe("reverted");
    expect(o.once_verified).toBe(false);
  });
});

describe("R-V4: feature verified + feat_verified_cap", () => {
  it("associated test pass verifies feature and caps confidence at 0.85", () => {
    const ses = "ses_rv4";
    const events: Event[] = [
      base({
        id: "f_claim",
        ts: "2026-07-28T12:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "add oauth login",
          claim_kind: "implemented",
          type_hint: "feature",
          title_hint: "OAuth login",
          scope_hint: { paths: ["src/oauth/"] },
        },
      }),
      base({
        id: "f_files",
        ts: "2026-07-28T12:05:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            { path: "src/oauth/handler.ts", change: "add", plus: 120, minus: 0 },
            { path: "tests/oauth.test.ts", change: "add", plus: 40, minus: 0 },
          ],
        },
      }),
      base({
        id: "f_pass",
        ts: "2026-07-28T12:06:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "test_result",
        payload: {
          suite_status: "pass",
          repro_key: "vitest tests/oauth.test.ts",
          tests: [
            {
              name: "oauth_login_redirect",
              status: "pass",
              file: "tests/oauth.test.ts",
            },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const o = store.outcomes[0]!;
    expect(o.type).toBe("feature");
    expect(o.status).toBe("verified");
    expect(o.once_verified).toBe(true);
    expect(o.confidence).toBeLessThanOrEqual(0.85);
    // either hit the cap or stay under it; if raw would exceed, reason is feat_verified_cap
    if (o.confidence_raw > 0.85) {
      expect(o.clamp_reason).toBe("feat_verified_cap");
      expect(o.confidence).toBe(0.85);
    }
    expect(o.evidence_links.some((l) => l.relation === "verifies")).toBe(true);
    expect(o.verification_anchors.length).toBeGreaterThan(0);
  });

  it("feature without file/test evidence does not jump to verified on bare test pass", () => {
    // claimed feature, only a green test with no prior supports → R-V4 needs non-claim evidence or scope paths
    // scope_hint alone puts paths on outcome at create → that counts. Use claim without scope.
    const ses = "ses_rv4_bare";
    const events: Event[] = [
      base({
        id: "b_claim",
        ts: "2026-07-28T12:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "maybe done",
          claim_kind: "completed",
          type_hint: "feature",
          title_hint: "Vague feature",
        },
      }),
      // test pass bound via focus, but no file_change and no scope paths
      base({
        id: "b_pass",
        ts: "2026-07-28T12:01:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "test_result",
        payload: {
          suite_status: "pass",
          tests: [{ name: "unrelated_suite", status: "pass" }],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const o = store.outcomes[0]!;
    // R-E3 lifts claimed→evidenced on any bound test; R-V4 must NOT verify without evidence/scope
    expect(o.status).not.toBe("verified");
    expect(["evidenced", "claimed"]).toContain(o.status);
  });
});

describe("parallel claims: focus switch, no silent cross-bind", () => {
  it("second claim switches focus; subsequent files bind to new focus", () => {
    const ses = "ses_focus";
    resetIdSeq();
    const opts = { idFactory: idSeq() };
    const store = createStore(ses, opts);

    onEvent(
      store,
      base({
        id: "a_claim",
        ts: "2026-07-28T13:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "work on auth",
          claim_kind: "progress",
          type_hint: "bugfix",
          title_hint: "Auth work",
          scope_hint: { paths: ["src/auth/"] },
        },
      }),
      opts,
    );
    const authId = store.focus_outcome_id!;
    expect(authId).toBeTruthy();

    onEvent(
      store,
      base({
        id: "a_file",
        ts: "2026-07-28T13:01:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            { path: "src/auth/login.ts", change: "mod", plus: 4, minus: 1 },
          ],
        },
      }),
      opts,
    );

    // switch work-stream
    onEvent(
      store,
      base({
        id: "b_claim",
        ts: "2026-07-28T13:10:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "work on billing",
          claim_kind: "progress",
          type_hint: "feature",
          title_hint: "Billing work",
          scope_hint: { paths: ["src/billing/"] },
        },
      }),
      opts,
    );
    const billingId = store.focus_outcome_id!;
    expect(billingId).toBeTruthy();
    expect(billingId).not.toBe(authId);

    onEvent(
      store,
      base({
        id: "b_file",
        ts: "2026-07-28T13:11:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            {
              path: "src/billing/invoice.ts",
              change: "mod",
              plus: 10,
              minus: 0,
            },
          ],
        },
      }),
      opts,
    );

    const auth = store.outcomes.find((o) => o.id === authId)!;
    const billing = store.outcomes.find((o) => o.id === billingId)!;

    expect(auth.status).toBe("evidenced");
    expect(billing.status).toBe("evidenced");

    // billing file must NOT appear on auth outcome
    expect(auth.scope.paths.some((p) => p.includes("billing"))).toBe(false);
    expect(billing.scope.paths.some((p) => p.includes("billing"))).toBe(true);

    // auth file must NOT appear on billing
    expect(billing.scope.paths.some((p) => p.includes("auth/login"))).toBe(
      false,
    );
    expect(auth.evidence_links.some((l) => l.event_id === "b_file")).toBe(
      false,
    );
    expect(billing.evidence_links.some((l) => l.event_id === "b_file")).toBe(
      true,
    );
    expect(billing.evidence_links.some((l) => l.method === "focus")).toBe(true);
  });

  it("explicit outcome_id still wins over stale focus (structured > focus)", () => {
    const ses = "ses_struct";
    resetIdSeq();
    const opts = { idFactory: idSeq() };
    const store = createStore(ses, opts);

    onEvent(
      store,
      base({
        id: "c1",
        ts: "2026-07-28T14:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "A",
          claim_kind: "progress",
          title_hint: "Outcome A",
          type_hint: "chore",
          scope_hint: { paths: ["src/a/"] },
        },
      }),
      opts,
    );
    const aId = store.focus_outcome_id!;

    onEvent(
      store,
      base({
        id: "c2",
        ts: "2026-07-28T14:01:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "B",
          claim_kind: "progress",
          title_hint: "Outcome B",
          type_hint: "chore",
          scope_hint: { paths: ["src/b/"] },
        },
      }),
      opts,
    );
    // focus is now B
    expect(store.focus_outcome_id).not.toBe(aId);

    // structured bind back to A despite focus=B
    onEvent(
      store,
      base({
        id: "fa",
        ts: "2026-07-28T14:02:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          outcome_id: aId,
          paths: [{ path: "src/a/x.ts", change: "mod", plus: 2, minus: 0 }],
        },
      }),
      opts,
    );

    const a = store.outcomes.find((o) => o.id === aId)!;
    const b = store.outcomes.find((o) => o.id !== aId)!;
    expect(a.evidence_links.some((l) => l.event_id === "fa")).toBe(true);
    expect(a.evidence_links.find((l) => l.event_id === "fa")!.method).toBe(
      "structured",
    );
    expect(b.evidence_links.some((l) => l.event_id === "fa")).toBe(false);
  });
});

describe("R-M1 online merge + R-M3 guard", () => {
  it("merges two same-scope non-verified fragments and supersedes victim", () => {
    const ses = "ses_rm1";
    // Two claims with nearly identical scope/title → after scope fills, R-M1 should fire.
    // Create A, file on A, create B with same scope paths via structured?
    // Actually second claim creates new outcome. Then file_change on B with same paths
    // as A should trigger merge check after B's scope update.
    //
    // Trick: both need overlapping scope.paths. Claim scope_hint seeds paths.
    // After B gets a file_change under same path set, jaccard may be high enough.
    const events: Event[] = [
      base({
        id: "m_a",
        ts: "2026-07-28T15:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "fix login null pointer",
          claim_kind: "fixed",
          type_hint: "bugfix",
          title_hint: "Fix login null pointer",
          scope_hint: {
            paths: ["src/auth/controller.py", "tests/test_auth.py"],
          },
        },
      }),
      base({
        id: "m_a_file",
        ts: "2026-07-28T15:01:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            {
              path: "src/auth/controller.py",
              change: "mod",
              plus: 4,
              minus: 1,
            },
          ],
        },
      }),
      // second claim — will become focus; same title tokens + same seeded paths
      base({
        id: "m_b",
        ts: "2026-07-28T15:02:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "fix login null pointer again",
          claim_kind: "fixed",
          type_hint: "bugfix",
          title_hint: "Fix login null pointer",
          scope_hint: {
            paths: ["src/auth/controller.py", "tests/test_auth.py"],
          },
        },
      }),
      // touch B so maybeOnlineMerge runs with updated scopes
      base({
        id: "m_b_file",
        ts: "2026-07-28T15:03:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            {
              path: "tests/test_auth.py",
              change: "mod",
              plus: 6,
              minus: 0,
            },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const active = store.outcomes.filter((o) => o.status !== "superseded");
    const superseded = store.outcomes.filter((o) => o.status === "superseded");

    expect(superseded.length).toBeGreaterThanOrEqual(1);
    expect(active.length).toBe(1);

    const survivor = active[0]!;
    const victim = superseded[0]!;
    expect(victim.superseded_by).toBe(survivor.id);
    expect(victim.terminal_reason).toBe("merged");
    expect(survivor.merge_of).toContain(victim.id);
    // evidence union
    expect(survivor.evidence_links.length).toBeGreaterThan(
      victim.evidence_links.length > 0 ? 1 : 0,
    );
    // focus points at survivor if it was on victim
    if (store.focus_outcome_id) {
      expect(store.focus_outcome_id).toBe(survivor.id);
    }
  });

  it("R-M3: does not auto-merge verified with non-verified same scope", () => {
    const ses = "ses_rm3";
    const events: Event[] = [
      ...verifiedBugfixEvents(ses, "rm3"),
      // second claimed outcome, same paths — must NOT swallow the verified one
      base({
        id: "rm3_dup",
        ts: "2026-07-28T10:30:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "fix login NPE",
          claim_kind: "fixed",
          type_hint: "bugfix",
          title_hint: "Fix login NPE",
          scope_hint: {
            paths: [
              "src/auth/",
              "src/auth/controller.py",
              "tests/test_auth.py",
            ],
          },
        },
      }),
      base({
        id: "rm3_dup_file",
        ts: "2026-07-28T10:31:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [
            {
              path: "src/auth/controller.py",
              change: "mod",
              plus: 1,
              minus: 0,
            },
          ],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    const verified = store.outcomes.filter((o) => o.status === "verified");
    const superseded = store.outcomes.filter((o) => o.status === "superseded");

    expect(verified).toHaveLength(1);
    expect(verified[0]!.title).toBe("Fix login NPE");
    // claimed/evidenced twin may exist, but verified must not be superseded
    expect(superseded.every((o) => o.id !== verified[0]!.id)).toBe(true);
    expect(
      store.outcomes.some(
        (o) => o.status === "verified" && o.once_verified === true,
      ),
    ).toBe(true);
  });

  it("R-M4: type conflict feature vs bugfix does not merge", () => {
    const ses = "ses_rm4";
    const events: Event[] = [
      base({
        id: "t_a",
        ts: "2026-07-28T16:00:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "auth work",
          claim_kind: "fixed",
          type_hint: "bugfix",
          title_hint: "Auth path work",
          scope_hint: { paths: ["src/auth/x.ts"] },
        },
      }),
      base({
        id: "t_a_f",
        ts: "2026-07-28T16:01:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [{ path: "src/auth/x.ts", change: "mod", plus: 3, minus: 1 }],
        },
      }),
      base({
        id: "t_b",
        ts: "2026-07-28T16:02:00.000Z",
        session_id: ses,
        actor: "agent",
        kind: "claim_made",
        payload: {
          text: "auth work",
          claim_kind: "implemented",
          type_hint: "feature",
          title_hint: "Auth path work",
          scope_hint: { paths: ["src/auth/x.ts"] },
        },
      }),
      base({
        id: "t_b_f",
        ts: "2026-07-28T16:03:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "file_change",
        payload: {
          paths: [{ path: "src/auth/x.ts", change: "mod", plus: 2, minus: 0 }],
        },
      }),
    ];

    const store = replay(ses, events, { idFactory: idSeq() });
    expect(store.outcomes.filter((o) => o.status === "superseded")).toHaveLength(
      0,
    );
    expect(store.outcomes).toHaveLength(2);
    const types = new Set(store.outcomes.map((o) => o.type));
    expect(types.has("bugfix")).toBe(true);
    expect(types.has("feature")).toBe(true);
  });
});

describe("regression suite invariants", () => {
  it("all high-risk fixtures stay deterministic under double replay", () => {
    const ses = "ses_det";
    const events = [
      ...verifiedBugfixEvents(ses),
      base({
        id: "det_reg",
        ts: "2026-07-28T10:20:00.000Z",
        session_id: ses,
        actor: "tool",
        kind: "test_result",
        payload: {
          suite_status: "fail",
          repro_key: "pytest tests/test_auth.py::test_login_ok",
          tests: [
            { name: "test_login_ok", status: "fail", file: "tests/test_auth.py" },
          ],
        },
      }),
    ];
    const a = replay(ses, events, { idFactory: idSeq() });
    const b = replay(ses, events, { idFactory: idSeq() });
    const strip = (o: OutcomeCandidate) => ({
      status: o.status,
      confidence: o.confidence,
      confidence_raw: o.confidence_raw,
      clamp_reason: o.clamp_reason,
      terminal_reason: o.terminal_reason,
      links: o.evidence_links,
      counters: o.counter_evidence,
    });
    expect(strip(a.outcomes[0]!)).toEqual(strip(b.outcomes[0]!));
  });
});
