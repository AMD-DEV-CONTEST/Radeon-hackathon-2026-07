import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";
import { runDeterministicPipeline } from "../src/agent.js";

const execFileAsync = promisify(execFile);
const tmpDirs: string[] = [];

afterEach(async () => {
  for (const d of tmpDirs.splice(0)) {
    await rm(d, { recursive: true, force: true });
  }
});

async function makeGitFixture(): Promise<string> {
  const dir = await mkdtemp(path.join(os.tmpdir(), "ldea-pipe-"));
  tmpDirs.push(dir);
  await mkdir(path.join(dir, "src"), { recursive: true });
  await writeFile(
    path.join(dir, "src", "auth.py"),
    "def classify(x):\n    return 'invalid_credentials' if x == 401 else 'unknown'\n",
    "utf8",
  );
  const run = (args: string[]) =>
    execFileAsync("git", args, { cwd: dir, windowsHide: true });
  await run(["init"]);
  await run(["config", "user.email", "t@local"]);
  await run(["config", "user.name", "t"]);
  await run(["add", "-A"]);
  await run(["commit", "-m", "init"]);
  await writeFile(
    path.join(dir, "src", "auth.py"),
    "def classify(x):\n    if x == 401: return 'invalid_credentials'\n    if x == 423: return 'locked'\n    return 'unknown'\n",
    "utf8",
  );
  await writeFile(
    path.join(dir, "leak.txt"),
    "reach me at owner@example.com\n",
    "utf8",
  );
  return dir;
}

describe("deterministic pipeline", () => {
  it("promotes claim with code+test evidence and flags privacy", async () => {
    const cwd = await makeGitFixture();
    const root = path.join(cwd, ".ldea-test");
    const config = loadConfig({ cwd, root, maxToolRounds: 4 });
    const result = await runDeterministicPipeline({
      config,
      sessionId: "pipe-1",
      claimText: "已修复登录错误分类 locked/invalid",
      claimType: "bugfix",
      priorFailTestOutput: `FAILED tests/test_auth.py::test_locked
FAILED tests/test_auth.py::test_invalid
========================= 2 failed in 0.01s =========================
`,
      testOutput: `PASSED tests/test_auth.py::test_locked
PASSED tests/test_auth.py::test_invalid
============================== 2 passed in 0.01s ==============================
`,
      testCmd: "pytest -q",
      privacyPaths: ["leak.txt"],
    });

    expect(result.report).toBeTruthy();
    expect(result.markdown).toContain("公开风险");
    expect(result.report!.privacy_risks.some((r) => r.kind === "email")).toBe(true);
    expect(result.report!.summary.verified).toBeGreaterThanOrEqual(1);
    const statuses = result.report!.outcomes.map((o) => o.status);
    expect(statuses).toContain("verified");
    expect(result.markdown).toMatch(/代码证据|验证证据/);
    expect(result.markdown).toContain("## 成果");
  }, 30_000);
});
