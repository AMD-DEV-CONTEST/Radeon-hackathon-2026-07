import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";
import { runClose } from "../src/agent.js";
import {
  formatSessionList,
  listSessionSummaries,
  writeSessionMeta,
} from "../src/session-meta.js";

const execFileAsync = promisify(execFile);
const tmpDirs: string[] = [];

afterEach(async () => {
  for (const d of tmpDirs.splice(0)) {
    await rm(d, { recursive: true, force: true });
  }
});

describe("close + multi-session", () => {
  it("bare claim without evidence becomes abandoned", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "ldea-close-"));
    tmpDirs.push(dir);
    const config = loadConfig({ cwd: dir, root: path.join(dir, ".ldea") });
    const result = await runClose({
      config,
      sessionId: "bare-1",
      claimText: "今天全部做完了",
      skipGit: true,
    });
    expect(result.report?.summary.abandoned).toBeGreaterThanOrEqual(1);
    expect(result.report?.summary.verified).toBe(0);
    expect(result.markdown).toMatch(/abandoned|未闭合|不可公开/);
  });

  it("lists sessions with status filter", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "ldea-ls-"));
    tmpDirs.push(dir);
    await mkdir(path.join(dir, "src"), { recursive: true });
    await writeFile(path.join(dir, "src", "a.py"), "x=1\n", "utf8");
    const run = (args: string[]) =>
      execFileAsync("git", args, { cwd: dir, windowsHide: true });
    await run(["init"]);
    await run(["config", "user.email", "t@local"]);
    await run(["config", "user.name", "t"]);
    await run(["add", "-A"]);
    await run(["commit", "-m", "i"]);
    await writeFile(path.join(dir, "src", "a.py"), "x=2\n", "utf8");

    const config = loadConfig({ cwd: dir, root: path.join(dir, ".ldea") });

    await runClose({
      config,
      sessionId: "s-empty",
      claimText: "空口完成",
      skipGit: true,
    });
    await writeSessionMeta(config, "s-empty", { kind: "close", claim: "空口完成" });

    await runClose({
      config,
      sessionId: "s-code",
      claimText: "改了一行",
      claimType: "chore",
    });
    await writeSessionMeta(config, "s-code", { kind: "close", claim: "改了一行" });

    const all = await listSessionSummaries(config);
    expect(all.length).toBeGreaterThanOrEqual(2);
    const abandoned = await listSessionSummaries(config, { status: "abandoned" });
    expect(abandoned.some((r) => r.id === "s-empty")).toBe(true);
    const text = formatSessionList(all);
    expect(text).toContain("s-empty");
    expect(text).toContain("V/E/C/A");
  }, 30_000);
});
