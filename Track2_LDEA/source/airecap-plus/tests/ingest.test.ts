import { describe, expect, it } from "vitest";
import {
  buildFileChangeEvent,
  ingestClaim,
  ingestGit,
  ingestTestOutput,
  parseGitNameStatus,
  parseGitNumstat,
  parsePytest,
  parseTestOutput,
  parseVitest,
  replay,
  type GitRunner,
} from "../src/index.js";

describe("git parsers", () => {
  it("parses name-status and numstat into path changes", () => {
    const ns = parseGitNameStatus(
      [
        "M\tsrc/auth/controller.py",
        "A\ttests/test_auth.py",
        "D\told.py",
        "R100\tsrc/a.py\tsrc/b.py",
      ].join("\n"),
    );
    expect(ns.get("src/auth/controller.py")).toBe("mod");
    expect(ns.get("tests/test_auth.py")).toBe("add");
    expect(ns.get("old.py")).toBe("del");
    expect(ns.get("src/b.py")).toBe("rename");

    const num = parseGitNumstat(
      [
        "8\t2\tsrc/auth/controller.py",
        "15\t0\ttests/test_auth.py",
        "-\t-\tassets/logo.png",
        "1\t1\tsrc/a.py => src/b.py",
      ].join("\n"),
    );
    expect(num.get("src/auth/controller.py")).toEqual({ plus: 8, minus: 2 });
    expect(num.get("assets/logo.png")).toEqual({ plus: 0, minus: 0 });
    expect(num.get("src/b.py")).toEqual({ plus: 1, minus: 1 });
  });

  it("ingestGit merges runner output into one file_change event", async () => {
    const runner: GitRunner = async (args) => {
      const joined = args.join(" ");
      if (joined.includes("--name-status")) {
        return {
          stdout: "M\tsrc/auth/controller.py\nA\ttests/test_auth.py\n",
          stderr: "",
        };
      }
      if (joined.includes("--numstat")) {
        return {
          stdout: "8\t2\tsrc/auth/controller.py\n15\t0\ttests/test_auth.py\n",
          stderr: "",
        };
      }
      return { stdout: "", stderr: "" };
    };

    const events = await ingestGit({
      sessionId: "ses_g",
      runner,
      eventId: "evt_git_1",
      ts: "2026-07-28T10:00:00.000Z",
    });
    expect(events).toHaveLength(1);
    const e = events[0]!;
    expect(e.kind).toBe("file_change");
    if (e.kind !== "file_change") return;
    expect(e.payload.paths).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: "src/auth/controller.py",
          change: "mod",
          plus: 8,
          minus: 2,
        }),
        expect.objectContaining({
          path: "tests/test_auth.py",
          change: "add",
          plus: 15,
          minus: 0,
        }),
      ]),
    );
  });

  it("marks revert commits via subject", async () => {
    const runner: GitRunner = async (args) => {
      const joined = args.join(" ");
      if (joined.includes("-s") && joined.includes("--format")) {
        return { stdout: "abc123\nRevert \"bad fix\"\n", stderr: "" };
      }
      if (joined.includes("--name-status")) {
        return { stdout: "M\tsrc/x.ts\n", stderr: "" };
      }
      if (joined.includes("--numstat")) {
        return { stdout: "1\t5\tsrc/x.ts\n", stderr: "" };
      }
      return { stdout: "", stderr: "" };
    };
    const events = await ingestGit({
      sessionId: "ses_rev",
      mode: { kind: "commit", sha: "abc123" },
      runner,
    });
    expect(events[0]!.kind).toBe("file_change");
    if (events[0]!.kind === "file_change") {
      expect(events[0]!.payload.is_revert).toBe(true);
      expect(events[0]!.payload.commit).toBe("abc123");
    }
  });
});

describe("test parsers", () => {
  it("parses pytest FAILED/PASSED nodeids", () => {
    const text = `
============================= test session starts ==============================
collected 2 items
tests/test_auth.py::test_login_ok FAILED                                 [ 50%]
tests/test_auth.py::test_logout PASSED                                   [100%]
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_login_ok - AssertionError: 500
PASSED tests/test_auth.py::test_logout
========================= 1 failed, 1 passed in 0.12s ==========================
`;
    const tests = parsePytest(text);
    expect(tests.some((t) => t.name.includes("test_login_ok") && t.status === "fail")).toBe(
      true,
    );
    expect(tests.some((t) => t.name.includes("test_logout") && t.status === "pass")).toBe(
      true,
    );
    const { framework } = parseTestOutput(text);
    expect(framework).toBe("pytest");
  });

  it("parses vitest-style FAIL/leaf marks", () => {
    const text = `
 RUN  v3.2.7

 ✓ tests/ok.test.ts (1)
   ✓ works
 × tests/bad.test.ts (1)
   × breaks on null

 Test Files  1 failed | 1 passed (2)
`;
    const tests = parseVitest(text);
    expect(
      tests.some(
        (t) => t.status === "fail" && t.file === "tests/bad.test.ts",
      ),
    ).toBe(true);
  });

  it("ingestTestOutput builds suite_status and repro_key", () => {
    const text = `
FAILED tests/test_auth.py::test_login_ok - boom
========================= 1 failed in 0.01s ==========================
`;
    const events = ingestTestOutput({
      sessionId: "ses_t",
      text,
      cmd: "pytest tests/test_auth.py::test_login_ok",
      eventId: "evt_t1",
      ts: "2026-07-28T10:01:00.000Z",
    });
    expect(events).toHaveLength(1);
    const e = events[0]!;
    expect(e.kind).toBe("test_result");
    if (e.kind !== "test_result") return;
    expect(e.payload.suite_status).toBe("fail");
    expect(e.payload.repro_key).toContain("pytest");
    expect(e.payload.tests[0]!.status).toBe("fail");
  });

  it("synthesizes suite-level result from exit code when unparsed", () => {
    const events = ingestTestOutput({
      sessionId: "ses_t2",
      text: "garbage output with no markers",
      exitCode: 0,
      cmd: "npm test",
    });
    expect(events).toHaveLength(1);
    if (events[0]!.kind === "test_result") {
      expect(events[0]!.payload.suite_status).toBe("pass");
      expect(events[0]!.payload.tests[0]!.name).toBe("npm test");
    }
  });
});

describe("claim ingest", () => {
  it("infers bugfix from fix wording", () => {
    const e = ingestClaim({
      sessionId: "ses_c",
      text: "fix login NPE in AuthController",
      titleHint: "Fix login NPE",
      scopePaths: ["src/auth/"],
      eventId: "evt_c1",
      ts: "2026-07-28T09:00:00.000Z",
    });
    expect(e.kind).toBe("claim_made");
    if (e.kind !== "claim_made") return;
    expect(e.payload.claim_kind).toBe("fixed");
    expect(e.payload.type_hint).toBe("bugfix");
    expect(e.payload.scope_hint?.paths).toEqual(["src/auth/"]);
  });
});

describe("ingest → aggregator golden path", () => {
  it("claim + git file_change + pytest fail/pass → verified", async () => {
    const ses = "ses_live";
    const claim = ingestClaim({
      sessionId: ses,
      text: "fix login NPE",
      typeHint: "bugfix",
      titleHint: "Fix login NPE",
      scopePaths: ["src/auth/"],
      actor: "agent",
      eventId: "e1",
      ts: "2026-07-28T10:00:00.000Z",
    });

    const fail = ingestTestOutput({
      sessionId: ses,
      text: "FAILED tests/test_auth.py::test_login_ok - 500\n",
      cmd: "pytest tests/test_auth.py::test_login_ok",
      eventId: "e2",
      ts: "2026-07-28T10:01:00.000Z",
    })[0]!;

    const files = buildFileChangeEvent(
      ses,
      {
        paths: [
          {
            path: "src/auth/controller.py",
            change: "mod",
            plus: 8,
            minus: 2,
          },
          { path: "tests/test_auth.py", change: "mod", plus: 10, minus: 0 },
        ],
      },
      { id: "e3", ts: "2026-07-28T10:05:00.000Z" },
    );

    const pass = ingestTestOutput({
      sessionId: ses,
      text: "PASSED tests/test_auth.py::test_login_ok\n",
      cmd: "pytest tests/test_auth.py::test_login_ok",
      eventId: "e4",
      ts: "2026-07-28T10:06:00.000Z",
    })[0]!;

    const store = replay(ses, [claim, fail, files, pass]);
    expect(store.outcomes).toHaveLength(1);
    expect(store.outcomes[0]!.status).toBe("verified");
    expect(store.outcomes[0]!.type).toBe("bugfix");
    expect(store.outcomes[0]!.title).toBe("Fix login NPE");
  });

  it("mixed pytest suite still closes R-V1 on matching nodeid", () => {
    const ses = "ses_mixed";
    const failText = `
FAILED tests/test_auth.py::test_login_ok - 500
PASSED tests/test_auth.py::test_logout
========================= 1 failed, 1 passed in 0.12s ==========================
`;
    const passText = `
PASSED tests/test_auth.py::test_login_ok
PASSED tests/test_auth.py::test_logout
============================== 2 passed in 0.10s ===============================
`;
    const events = [
      ingestClaim({
        sessionId: ses,
        text: "fix login",
        typeHint: "bugfix",
        titleHint: "Fix login",
        scopePaths: ["src/auth/"],
        eventId: "m1",
        ts: "2026-07-28T10:00:00.000Z",
      }),
      ingestTestOutput({
        sessionId: ses,
        text: failText,
        cmd: "pytest tests/test_auth.py",
        eventId: "m2",
        ts: "2026-07-28T10:01:00.000Z",
      })[0]!,
      buildFileChangeEvent(
        ses,
        {
          paths: [
            {
              path: "src/auth/controller.py",
              change: "mod",
              plus: 3,
              minus: 1,
            },
          ],
        },
        { id: "m3", ts: "2026-07-28T10:02:00.000Z" },
      ),
      ingestTestOutput({
        sessionId: ses,
        text: passText,
        cmd: "pytest tests/test_auth.py",
        eventId: "m4",
        ts: "2026-07-28T10:03:00.000Z",
      })[0]!,
    ];
    const store = replay(ses, events);
    expect(store.outcomes[0]!.status).toBe("verified");
  });
});
