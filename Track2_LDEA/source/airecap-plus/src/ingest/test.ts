/**
 * Test runner stdout → L0 test_result.
 * Frameworks: pytest, vitest/jest-ish. Auto-detect by default.
 */
import type { Event, TestCaseResult, TestResultPayload } from "../types.js";
import { makeEvent } from "./ids.js";

export type TestFramework = "pytest" | "vitest" | "jest" | "auto";

export interface TestIngestOptions {
  sessionId: string;
  text: string;
  framework?: TestFramework;
  /** Original command, used as repro_key when present. */
  cmd?: string;
  outcomeId?: string;
  ts?: string;
  eventId?: string;
  exitCode?: number;
}

function detectFramework(text: string): "pytest" | "vitest" | "jest" {
  if (
    /={5,}.*(?:passed|failed|error).*in\s+[\d.]+s/i.test(text) ||
    /^\s*(?:FAILED|PASSED|ERROR|SKIPPED)\s+\S+::/m.test(text) ||
    /test session starts/i.test(text)
  ) {
    return "pytest";
  }
  if (/Test Files\s+\d+/i.test(text) || /✓|×|FAIL\s{2}\s+\S+\.test\./.test(text)) {
    return "vitest";
  }
  if (/PASS\s+\S+|FAIL\s+\S+|Tests:\s+\d+\s+failed/i.test(text)) {
    return "jest";
  }
  // default: try pytest-like nodeids, else vitest
  if (/\S+::\S+/.test(text)) return "pytest";
  return "vitest";
}

function suiteFromTests(
  tests: TestCaseResult[],
  exitCode?: number,
): TestResultPayload["suite_status"] {
  if (tests.length === 0) {
    if (exitCode === 0) return "pass";
    if (exitCode !== undefined && exitCode !== 0) return "fail";
    return "mixed";
  }
  const hasFail = tests.some((t) => t.status === "fail");
  const hasPass = tests.some((t) => t.status === "pass");
  if (hasFail && hasPass) return "mixed";
  if (hasFail) return "fail";
  if (hasPass) return "pass";
  return "mixed";
}

/** pytest: FAILED path::test - msg | PASSED path::test */
export function parsePytest(text: string): TestCaseResult[] {
  const tests: TestCaseResult[] = [];
  const seen = new Set<string>();

  const lineRe =
    /^\s*(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+?)(?:\s+-\s+(.*))?$/gm;
  let m: RegExpExecArray | null;
  while ((m = lineRe.exec(text)) !== null) {
    const raw = m[1]!.toUpperCase();
    const nodeid = m[2]!;
    const message = m[3]?.trim();
    let status: TestCaseResult["status"] = "pass";
    if (raw === "FAILED" || raw === "ERROR") status = "fail";
    else if (raw === "SKIPPED" || raw === "XFAIL") status = "skip";
    else status = "pass";

    const file = nodeid.includes("::") ? nodeid.split("::")[0] : undefined;
    const name = nodeid;
    const key = `${status}:${name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tests.push({ name, status, file, message });
  }

  // short test summary section often repeats — already captured
  // failures in traceback headers: _________________ test_name _________________
  if (tests.length === 0) {
    const failHeaders =
      /^_{5,}\s+(\S.*?)\s+_{5,}$/gm;
    while ((m = failHeaders.exec(text)) !== null) {
      const name = m[1]!.trim();
      if (seen.has(`fail:${name}`)) continue;
      seen.add(`fail:${name}`);
      const file = name.includes("::") ? name.split("::")[0] : undefined;
      tests.push({ name, status: "fail", file });
    }
  }

  return tests;
}

/**
 * Vitest / Jest-ish lines:
 *   ✓ name
 *   × name
 *   FAIL  path > suite > test
 *   PASS  path
 *   ✓ tests/foo.test.ts (3)
 */
export function parseVitest(text: string): TestCaseResult[] {
  const tests: TestCaseResult[] = [];
  const seen = new Set<string>();

  // FAIL  file > a > b
  const failBlock = /^\s*(?:FAIL|×|✕|x)\s+(\S+\.(?:test|spec)\.[a-zA-Z]+)\s*(?:>\s*(.+))?$/gm;
  let m: RegExpExecArray | null;
  while ((m = failBlock.exec(text)) !== null) {
    const file = m[1]!;
    const rest = (m[2] ?? "").trim();
    const name = rest ? `${file} > ${rest}` : file;
    const key = `fail:${name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tests.push({ name, status: "fail", file });
  }

  // PASS file (file-level) — weak, skip if we have finer names
  // Individual: " ✓ does something" under a file header is hard without state machine.
  // Capture " ✓ tests/foo.test.ts > suite > test" single-line form if present.
  const passLine =
    /^\s*(?:✓|√|PASS)\s+(\S+\.(?:test|spec)\.[a-zA-Z]+)\s*(?:>\s*(.+))?$/gm;
  while ((m = passLine.exec(text)) !== null) {
    const file = m[1]!;
    const rest = (m[2] ?? "").trim();
    // skip pure file summary like "✓ tests/foo.test.ts (3)"
    if (!rest && /\(\d+\)\s*$/.test(m[0]!)) continue;
    if (!rest) continue;
    const name = `${file} > ${rest}`;
    const key = `pass:${name}`;
    if (seen.has(`fail:${name}`) || seen.has(key)) continue;
    seen.add(key);
    tests.push({ name, status: "pass", file });
  }

  // Nested indented results: "   ✓ does x" — pair with last file header
  let currentFile: string | undefined;
  for (const line of text.split(/\r?\n/)) {
    const fileHeader = line.match(
      /^\s*(?:✓|×|✕|FAIL|PASS)\s+(\S+\.(?:test|spec)\.[a-zA-Z]+)\s*(?:\(|$)/,
    );
    if (fileHeader) {
      currentFile = fileHeader[1];
      continue;
    }
    const leaf = line.match(/^\s{2,}(✓|×|✕|√|x)\s+(.+?)\s*(?:\(?\d+\s*ms\)?)?\s*$/);
    if (leaf && currentFile) {
      const mark = leaf[1]!;
      const title = leaf[2]!.trim();
      if (/\.(?:test|spec)\./.test(title)) continue;
      const status: TestCaseResult["status"] =
        mark === "✓" || mark === "√" ? "pass" : "fail";
      const name = `${currentFile} > ${title}`;
      const key = `${status}:${name}`;
      if (seen.has(key) || seen.has(`fail:${name}`)) continue;
      seen.add(key);
      tests.push({ name, status, file: currentFile });
    }
  }

  // Jest: FAIL path/to/file.test.js
  const jestFail = /^\s*FAIL\s+(\S+\.(?:test|spec)\.[a-zA-Z]+)\s*$/gm;
  while ((m = jestFail.exec(text)) !== null) {
    const file = m[1]!;
    const name = file;
    const key = `fail:${name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tests.push({ name, status: "fail", file });
  }

  return tests;
}

export function parseTestOutput(
  text: string,
  framework: TestFramework = "auto",
): { framework: string; tests: TestCaseResult[] } {
  const fw = framework === "auto" ? detectFramework(text) : framework;
  if (fw === "pytest") {
    return { framework: "pytest", tests: parsePytest(text) };
  }
  // vitest + jest share parser
  return { framework: fw, tests: parseVitest(text) };
}

export function buildTestResultEvent(
  sessionId: string,
  data: {
    framework?: string;
    tests: TestCaseResult[];
    suite_status: TestResultPayload["suite_status"];
    repro_key?: string;
    outcome_id?: string;
  },
  opts?: { ts?: string; id?: string },
): Event {
  return makeEvent({
    id: opts?.id,
    ts: opts?.ts,
    session_id: sessionId,
    actor: "tool",
    kind: "test_result",
    refs: data.tests.slice(0, 30).map((t) => ({
      kind: "test" as const,
      value: t.name,
    })),
    payload: {
      framework: data.framework,
      tests: data.tests,
      suite_status: data.suite_status,
      repro_key: data.repro_key,
      outcome_id: data.outcome_id,
    },
  });
}

export function ingestTestOutput(opts: TestIngestOptions): Event[] {
  const { framework, tests } = parseTestOutput(
    opts.text,
    opts.framework ?? "auto",
  );
  // If nothing parsed but exit code known, synthesize suite-level result
  let finalTests = tests;
  if (finalTests.length === 0 && opts.exitCode !== undefined) {
    finalTests = [
      {
        name: opts.cmd ?? "suite",
        status: opts.exitCode === 0 ? "pass" : "fail",
      },
    ];
  }
  if (finalTests.length === 0) return [];

  const suite_status = suiteFromTests(finalTests, opts.exitCode);
  return [
    buildTestResultEvent(
      opts.sessionId,
      {
        framework,
        tests: finalTests,
        suite_status,
        repro_key: opts.cmd,
        outcome_id: opts.outcomeId,
      },
      { ts: opts.ts, id: opts.eventId },
    ),
  ];
}
