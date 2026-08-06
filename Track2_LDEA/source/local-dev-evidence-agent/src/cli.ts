#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { initSession, readStore, sessionPaths } from "airecap-plus";
import { runAgent, runClose, runDeterministicPipeline } from "./agent.js";
import { loadConfig } from "./config.js";
import { LlmClient } from "./llm.js";
import {
  formatSessionList,
  listSessionSummaries,
  summarizeSession,
  writeSessionMeta,
} from "./session-meta.js";

function usage(): string {
  return `Local Dev Evidence Agent (ldea)

立场：拒绝未验证的完成叙事（仅 verified = 已完成；LLM 不能自证）。

Daily ledger:
  ldea close --claim "..." [options]   End-of-day evidence close (no LLM)
  ldea ls [--status verified|abandoned|...]
  ldea show [sessionId] [--json] [--outcomes]

Agent / demo:
  ldea doctor
  ldea init [sessionId]
  ldea run <goal...> [--session id]
  ldea demo                 双故事：空口 abandoned → 证据 verified
  ldea demo --suite         四故事全景（录像推荐，无需 GPU）
  ldea demo --empty|--code|--failing|--verified
  ldea demo --live          含糊目标 + 本地 LLM 工具循环
  ldea help

close options:
  --claim <text>          required (or positional after close)
  --type <outcome_type>   feature|bugfix|...
  --test <cmd>            run tests, e.g. "pytest -q"
  --test-log <file>       ingest captured test stdout
  --prior-fail-log <file> fail log before fix (bugfix R-V1)
  --no-git                skip git_diff
  --session <id>
  --title <report title>

Env:
  LDEA_LLM_BASE_URL   default http://127.0.0.1:8000/v1
  LDEA_LLM_MODEL      default qwen2.5-7b-instruct
  LDEA_ROOT           default .ldea
  LDEA_CWD            default cwd
`;
}

function argFlag(argv: string[], name: string): boolean {
  return argv.includes(name);
}

function takeArg(argv: string[], name: string): string | undefined {
  const i = argv.indexOf(name);
  if (i >= 0 && argv[i + 1]) return argv[i + 1];
  return undefined;
}

/** Collect "--claim value" or bare words not belonging to other flags. */
function takeClaim(argv: string[]): string {
  const fromFlag = takeArg(argv, "--claim");
  if (fromFlag) return fromFlag;
  const skip = new Set([
    "--claim",
    "--type",
    "--test",
    "--test-log",
    "--prior-fail-log",
    "--session",
    "--title",
    "--status",
  ]);
  const parts: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--no-git" || a === "--json" || a === "--outcomes" || a === "--live" || a === "--empty") {
      continue;
    }
    if (skip.has(a)) {
      i += 1;
      continue;
    }
    if (a.startsWith("--")) continue;
    parts.push(a);
  }
  return parts.join(" ").trim();
}

function newSessionId(prefix = "sess"): string {
  const d = new Date();
  const stamp = d.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  return `${prefix}-${stamp}`;
}

async function cmdDoctor(): Promise<number> {
  const config = loadConfig();
  console.log("LDEA doctor");
  console.log(`  cwd:   ${config.cwd}`);
  console.log(`  root:  ${config.root}`);
  console.log(`  model: ${config.llmModel}`);
  console.log(`  llm:   ${config.llmBaseUrl}`);

  const llm = new LlmClient({
    baseUrl: config.llmBaseUrl,
    apiKey: config.llmApiKey,
    model: config.llmModel,
    timeoutMs: 8_000,
  });
  try {
    const models = await llm.listModels();
    console.log("  LLM:   OK");
    console.log(`  models: ${JSON.stringify(models).slice(0, 300)}`);
    return 0;
  } catch (err) {
    console.log(`  LLM:   FAIL — ${err instanceof Error ? err.message : String(err)}`);
    console.log("  hint:  start vLLM on radeon-gpu, then tunnel e.g.");
    console.log("         ssh -L 8000:127.0.0.1:8000 radeon-gpu");
    console.log(
      "         vLLM flags: --attention-backend TRITON_ATTN --enable-auto-tool-choice --tool-call-parser hermes",
    );
    return 1;
  }
}

async function cmdInit(sessionId?: string): Promise<number> {
  const config = loadConfig();
  const id = sessionId ?? newSessionId("init");
  const paths = await initSession(id, { cwd: config.cwd, root: config.root });
  await writeSessionMeta(config, id, { kind: "init", cwd: config.cwd });
  console.log(`session ready: ${id}`);
  console.log(`  dir: ${paths.sessionDir}`);
  return 0;
}

async function cmdLs(argv: string[]): Promise<number> {
  const config = loadConfig();
  const status = takeArg(argv, "--status");
  const rows = await listSessionSummaries(config, status ? { status } : undefined);
  if (argFlag(argv, "--json")) {
    console.log(JSON.stringify(rows, null, 2));
  } else {
    console.log(formatSessionList(rows));
    console.log(`root: ${sessionPaths("_", { cwd: config.cwd, root: config.root }).sessionsDir}`);
  }
  return 0;
}

async function cmdShow(argv: string[]): Promise<number> {
  const config = loadConfig();
  const asJson = argFlag(argv, "--json");
  const outcomesOnly = argFlag(argv, "--outcomes");
  const positional = argv.find((a) => !a.startsWith("--"));
  let id = positional;
  if (!id) {
    const rows = await listSessionSummaries(config);
    if (!rows.length) {
      console.error("no sessions — try: ldea close --claim \"...\"");
      return 1;
    }
    id = rows[0]!.id;
  }

  const summary = await summarizeSession(config, id);
  const paths = sessionPaths(id, { cwd: config.cwd, root: config.root });
  const store = await readStore(paths);

  if (asJson) {
    console.log(
      JSON.stringify(
        {
          summary,
          store: outcomesOnly
            ? store?.outcomes.filter((o) => o.status !== "superseded")
            : store,
        },
        null,
        2,
      ),
    );
    return 0;
  }

  console.log(`session: ${summary.id}`);
  console.log(`  kind:    ${summary.kind ?? "-"}`);
  console.log(`  state:   ${summary.store_status ?? "?"}`);
  console.log(
    `  counts:  V=${summary.counts.verified} E=${summary.counts.evidenced} C=${summary.counts.claimed} A=${summary.counts.abandoned}`,
  );
  if (summary.goal) console.log(`  goal:    ${summary.goal}`);
  if (summary.claim) console.log(`  claim:   ${summary.claim}`);
  console.log(`  dir:     ${summary.session_dir}`);
  console.log("");

  if (outcomesOnly || !summary.has_report) {
    const outs = store?.outcomes.filter((o) => o.status !== "superseded") ?? [];
    if (!outs.length) {
      console.log("(no outcomes)");
    } else {
      for (const o of outs) {
        console.log(`- [${o.status}] ${o.title}  conf=${o.confidence.toFixed(2)}`);
        if (o.scope?.paths?.length) console.log(`    paths: ${o.scope.paths.join(", ")}`);
        if (o.terminal_reason) console.log(`    reason: ${o.terminal_reason}`);
      }
    }
    return 0;
  }

  try {
    console.log(await readFile(path.join(paths.sessionDir, "report.md"), "utf8"));
  } catch {
    console.log("(no report.md)");
  }
  return 0;
}

async function cmdClose(argv: string[]): Promise<number> {
  const claim = takeClaim(argv);
  if (!claim) {
    console.error('claim required: ldea close --claim "已完成 xxx"');
    return 2;
  }
  const config = loadConfig();
  const sessionId = takeArg(argv, "--session") ?? newSessionId("close");
  const testLog = takeArg(argv, "--test-log");
  const priorFailLog = takeArg(argv, "--prior-fail-log");
  let testOutput: string | undefined;
  let priorFailTestOutput: string | undefined;
  if (testLog) {
    testOutput = await readFile(path.resolve(config.cwd, testLog), "utf8");
  }
  if (priorFailLog) {
    priorFailTestOutput = await readFile(path.resolve(config.cwd, priorFailLog), "utf8");
  }

  console.log(`close session=${sessionId}`);
  console.log(`claim: ${claim}`);

  const result = await runClose({
    config,
    sessionId,
    claimText: claim,
    claimType: takeArg(argv, "--type"),
    testCmd: takeArg(argv, "--test"),
    testOutput,
    priorFailTestOutput,
    skipGit: argFlag(argv, "--no-git"),
    reportTitle: takeArg(argv, "--title"),
  });

  await writeSessionMeta(config, sessionId, {
    kind: "close",
    claim,
    cwd: config.cwd,
    goal: claim,
  });

  if (result.markdown) console.log("\n" + result.markdown);
  const s = result.report?.summary;
  if (s) {
    console.log(
      `\nsummary: verified=${s.verified} evidenced=${s.evidenced} claimed=${s.claimed} abandoned=${s.abandoned}`,
    );
  }
  console.log(`artifacts: ${sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir}`);
  console.log(`tools: ${result.toolTrace.map((t) => t.name).join(" → ")}`);
  return result.report ? 0 : 1;
}

async function cmdRun(goalParts: string[], sessionFromFlag?: string): Promise<number> {
  const goal = goalParts.join(" ").trim();
  if (!goal) {
    console.error("goal required: ldea run <goal text>");
    return 2;
  }
  const config = loadConfig();
  const sessionId = sessionFromFlag ?? newSessionId("run");
  console.log(`running agent session=${sessionId}`);
  console.log(`goal: ${goal}`);
  await writeSessionMeta(config, sessionId, { kind: "run", goal, cwd: config.cwd });
  const result = await runAgent({ config, sessionId, goal });
  await writeSessionMeta(config, sessionId, { kind: "run", goal, cwd: config.cwd });
  console.log(`rounds=${result.rounds} tools=${result.toolTrace.map((t) => t.name).join(",")}`);
  if (result.markdown) {
    console.log("\n" + result.markdown);
  } else if (result.finalAssistant) {
    console.log(result.finalAssistant);
  }
  const out = sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir;
  console.log(`\nartifacts: ${out}`);
  return 0;
}

async function ensureDemoFixture(demoRoot: string): Promise<void> {
  await mkdir(path.join(demoRoot, "src"), { recursive: true });
  await mkdir(path.join(demoRoot, "tests"), { recursive: true });

  const authPy = `"""Minimal auth error classifier — demo fixture for LDEA."""

def classify_login_error(code: str | int | None) -> str:
    """Map login failure codes to stable categories.

    Returns one of: invalid_credentials | locked | rate_limited | unknown
    """
    if code is None:
        return "unknown"
    c = str(code).strip().upper()
    if c in {"AUTH_INVALID", "401", "E_BAD_PASS"}:
        return "invalid_credentials"
    if c in {"AUTH_LOCKED", "423", "E_LOCKED"}:
        return "locked"
    if c in {"AUTH_RATE", "429", "E_RATE"}:
        return "rate_limited"
    return "unknown"
`;

  const testPy = `from src.auth import classify_login_error

def test_invalid_password():
    assert classify_login_error("AUTH_INVALID") == "invalid_credentials"
    assert classify_login_error(401) == "invalid_credentials"

def test_locked_account():
    assert classify_login_error("AUTH_LOCKED") == "locked"

def test_rate_limited():
    assert classify_login_error(429) == "rate_limited"

def test_unknown():
    assert classify_login_error("WTF") == "unknown"
    assert classify_login_error(None) == "unknown"
`;

  await writeFile(path.join(demoRoot, "src", "__init__.py"), "", "utf8");
  await writeFile(path.join(demoRoot, "src", "auth.py"), authPy, "utf8");
  await writeFile(path.join(demoRoot, "tests", "test_auth.py"), testPy, "utf8");
  await writeFile(path.join(demoRoot, "pytest.ini"), "[pytest]\npythonpath = .\n", "utf8");

  await writeFile(
    path.join(demoRoot, "notes_private.untracked.txt"),
    "contact demo@example.com\nOPENAI_API_KEY=sk-demoonlynotreal0123456789abcdef\n",
    "utf8",
  );
  await writeFile(
    path.join(demoRoot, ".gitignore"),
    "notes_private.untracked.txt\n.ldea/\n__pycache__/\n.pytest_cache/\n",
    "utf8",
  );

  await mkdir(path.join(demoRoot, "captured"), { recursive: true });
  await writeFile(
    path.join(demoRoot, "captured", "pytest_before.txt"),
    `============================= test session starts ==============================
collected 4 items
FAILED tests/test_auth.py::test_invalid_password
FAILED tests/test_auth.py::test_locked_account
PASSED tests/test_auth.py::test_rate_limited
PASSED tests/test_auth.py::test_unknown
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_invalid_password
FAILED tests/test_auth.py::test_locked_account
========================= 2 failed, 2 passed in 0.04s ==========================
`,
    "utf8",
  );
  await writeFile(
    path.join(demoRoot, "captured", "pytest_after.txt"),
    `============================= test session starts ==============================
collected 4 items
PASSED tests/test_auth.py::test_invalid_password
PASSED tests/test_auth.py::test_locked_account
PASSED tests/test_auth.py::test_rate_limited
PASSED tests/test_auth.py::test_unknown
============================== 4 passed in 0.03s ===============================
`,
    "utf8",
  );
}

async function runEmptyClaimDemo(
  configBase: ReturnType<typeof loadConfig>,
  ledgerRoot: string,
  opts?: { quietReport?: boolean; storyKey?: string },
): Promise<StoryResult> {
  const storyKey = opts?.storyKey ?? "A";
  const sessionId = newSessionId("demo-empty");
  const config = loadConfig({ cwd: configBase.cwd, root: ledgerRoot });
  console.log(`\n======== 故事 ${storyKey} · 空口声称 → 期望 abandoned ========`);
  console.log(`session=${sessionId}`);
  const claim = "今天全部做完了，完美收工。";
  const result = await runClose({
    config,
    sessionId,
    claimText: claim,
    skipGit: true,
    reportTitle: "开发证据报告 · 空口声称",
  });
  await writeSessionMeta(config, sessionId, {
    kind: "demo",
    claim,
    cwd: config.cwd,
    tags: ["empty-claim", "contrast-a"],
  });
  if (result.markdown && !opts?.quietReport) console.log("\n" + result.markdown);
  const abandoned = result.report?.summary.abandoned ?? 0;
  const verified = result.report?.summary.verified ?? 0;
  const evidenced = result.report?.summary.evidenced ?? 0;
  console.log(
    `${storyKey} summary: abandoned=${abandoned} verified=${verified} evidenced=${evidenced}`,
  );
  console.log(`artifacts: ${sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir}`);
  return {
    ok: abandoned >= 1 && verified === 0,
    sessionId,
    abandoned,
    verified,
    evidenced,
    label: "empty-claim",
    markdown: result.markdown,
  };
}

async function prepareDemoFixture(demoRoot: string): Promise<void> {
  await ensureDemoFixture(demoRoot);
  try {
    const { execFile } = await import("node:child_process");
    const { promisify } = await import("node:util");
    const execFileAsync = promisify(execFile);
    const run = async (args: string[]) =>
      execFileAsync("git", args, { cwd: demoRoot, windowsHide: true });
    try {
      await run(["rev-parse", "--is-inside-work-tree"]);
    } catch {
      await run(["init"]);
      await run(["config", "user.email", "ldea-demo@local"]);
      await run(["config", "user.name", "LDEA Demo"]);
    }
    await run(["add", "src", "tests", "pytest.ini", ".gitignore"]);
    try {
      await run(["commit", "-m", "demo: login error classifier baseline"]);
    } catch {
      /* nothing */
    }
    const authPath = path.join(demoRoot, "src", "auth.py");
    const body = await readFile(authPath, "utf8");
    const marker = "# demo note: categories stabilized for product support";
    if (!body.includes(marker)) {
      await writeFile(authPath, `${body.trimEnd()}\n\n${marker}\n`, "utf8");
    } else {
      await writeFile(authPath, body.replace(marker, `${marker} · rerun`), "utf8");
    }
  } catch (err) {
    console.warn(`git fixture setup warning: ${err instanceof Error ? err.message : err}`);
  }
}

async function runVerifiedDemo(
  configBase: ReturnType<typeof loadConfig>,
  ledgerRoot: string,
  opts?: { quietReport?: boolean; live?: boolean; storyKey?: string },
): Promise<StoryResult> {
  const storyKey = opts?.storyKey ?? (opts?.live ? "LIVE" : "B");
  const demoRoot = path.join(configBase.cwd, "fixtures", "login-error-demo");
  await prepareDemoFixture(demoRoot);

  const sessionId = newSessionId(opts?.live ? "demo-live" : "demo");
  const config = loadConfig({ cwd: demoRoot, root: ledgerRoot });
  const priorFail = (
    await readFile(path.join(demoRoot, "captured", "pytest_before.txt"), "utf8")
  ).trim();
  const samplePytest = (
    await readFile(path.join(demoRoot, "captured", "pytest_after.txt"), "utf8")
  ).trim();

  console.log(
    `\n======== 故事 ${storyKey} · 代码+测试证据（fail→pass）→ 期望 verified ========`,
  );
  console.log(`session=${sessionId}`);
  console.log(`fixture: ${demoRoot}`);
  console.log(opts?.live ? "mode: live LLM agent（含糊目标）" : "mode: deterministic rules");

  if (opts?.live) {
    const result = await runAgent({
      config: { ...config, maxToolRounds: Math.max(config.maxToolRounds, 14) },
      sessionId,
      goal:
        "工作区刚改过登录相关代码。有人说修好了，也有人说今天收工了。\n" +
        "请弄清：登录错误分类 invalid/locked/rate_limited 是否有可核验完成。\n\n" +
        "证据绑定顺序（必须按序，每轮只调 1 个工具）：\n" +
        "1 claim: type=bugfix kind=fixed text=已修复登录错误分类 invalid_credentials/locked/rate_limited\n" +
        "2 ingest_test_output: framework=pytest cmd=pytest -q exit_code=1 text=BEFORE日志\n" +
        "3 git_diff mode=worktree\n" +
        "4 ingest_test_output: framework=pytest cmd=pytest -q exit_code=0 text=AFTER日志\n" +
        "5 scan_privacy paths=[\"notes_private.untracked.txt\"]\n" +
        "6 show_outcomes\n" +
        "7 end_session\n" +
        "8 render_report（禁止把 claimed 说成已完成）\n" +
        "禁止 run_tests。只有 verified 才能说已修复。\n\n" +
        "BEFORE日志:\n" +
        priorFail.replace(/[=]{5,}/g, "---") +
        "\n\nAFTER日志:\n" +
        samplePytest.replace(/[=]{5,}/g, "---"),
    });
    await writeSessionMeta(config, sessionId, {
      kind: "demo",
      goal: "含糊核验：登录相关到底修没修完",
      cwd: demoRoot,
      tags: ["live", "ambiguous-goal"],
    });
    if (result.markdown && !opts.quietReport) console.log("\n" + result.markdown);
    const abandoned = result.report?.summary.abandoned ?? 0;
    const verified = result.report?.summary.verified ?? 0;
    const evidenced = result.report?.summary.evidenced ?? 0;
    const tools = result.toolTrace.map((t) => t.name).join(" → ");
    console.log(
      `${storyKey} summary: abandoned=${abandoned} verified=${verified} evidenced=${evidenced}`,
    );
    console.log(`tools: ${tools}`);
    console.log(
      `artifacts: ${sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir}`,
    );
    return {
      ok: Boolean(result.report),
      sessionId,
      abandoned,
      verified,
      evidenced,
      tools,
      label: "live",
    };
  }

  const result = await runDeterministicPipeline({
    config,
    sessionId,
    claimText: "已修复登录错误分类：invalid_credentials / locked / rate_limited，并补了 pytest。",
    claimType: "bugfix",
    priorFailTestOutput: priorFail,
    testOutput: samplePytest,
    testCmd: "pytest -q",
    gitMode: "worktree",
    privacyPaths: ["notes_private.untracked.txt", "src/auth.py"],
    reportTitle: "开发证据报告 · 登录错误分类",
  });
  await writeSessionMeta(config, sessionId, {
    kind: "demo",
    claim: "已修复登录错误分类",
    cwd: demoRoot,
    tags: ["verified-path", "contrast-verified"],
  });
  if (result.markdown && !opts?.quietReport) console.log("\n" + result.markdown);
  const abandoned = result.report?.summary.abandoned ?? 0;
  const verified = result.report?.summary.verified ?? 0;
  const evidenced = result.report?.summary.evidenced ?? 0;
  console.log(
    `${storyKey} summary: abandoned=${abandoned} verified=${verified} evidenced=${evidenced}`,
  );
  console.log(
    `artifacts: ${sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir}`,
  );
  return {
    ok: verified >= 1,
    sessionId,
    abandoned,
    verified,
    evidenced,
    tools: result.toolTrace.map((t) => t.name).join(" → "),
    label: "verified-path",
  };
}

type StoryResult = {
  ok: boolean;
  sessionId: string;
  abandoned: number;
  verified: number;
  evidenced?: number;
  claimed?: number;
  label?: string;
  tools?: string;
  markdown?: string;
};

async function runCodeOnlyDemo(
  configBase: ReturnType<typeof loadConfig>,
  ledgerRoot: string,
  opts?: { quietReport?: boolean; storyKey?: string },
): Promise<StoryResult> {
  const storyKey = opts?.storyKey ?? "B";
  const demoRoot = path.join(configBase.cwd, "fixtures", "login-error-demo");
  await prepareDemoFixture(demoRoot);
  const sessionId = newSessionId("demo-code");
  const config = loadConfig({ cwd: demoRoot, root: ledgerRoot });
  console.log(
    `\n======== 故事 ${storyKey} · 只有代码改动、无测试 → 期望 evidenced（未 verified）========`,
  );
  console.log(`session=${sessionId}`);
  console.log(`fixture: ${demoRoot}`);
  const claim = "完成了登录错误分类重构，可以上线了。";
  const result = await runClose({
    config,
    sessionId,
    claimText: claim,
    claimType: "refactor",
    // git only — no test evidence
    privacyPaths: ["src/auth.py"],
    reportTitle: "开发证据报告 · 仅有代码无验证",
  });
  await writeSessionMeta(config, sessionId, {
    kind: "demo",
    claim,
    cwd: demoRoot,
    tags: ["code-only", "contrast-b"],
  });
  if (result.markdown && !opts?.quietReport) console.log("\n" + result.markdown);
  const abandoned = result.report?.summary.abandoned ?? 0;
  const verified = result.report?.summary.verified ?? 0;
  const evidenced = result.report?.summary.evidenced ?? 0;
  console.log(
    `${storyKey} summary: evidenced=${evidenced} verified=${verified} abandoned=${abandoned}`,
  );
  console.log(`artifacts: ${sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir}`);
  return {
    ok: verified === 0 && evidenced >= 1,
    sessionId,
    abandoned,
    verified,
    evidenced,
    label: "code-only",
  };
}

async function runStillFailingDemo(
  configBase: ReturnType<typeof loadConfig>,
  ledgerRoot: string,
  opts?: { quietReport?: boolean; storyKey?: string },
): Promise<StoryResult> {
  const storyKey = opts?.storyKey ?? "C";
  const demoRoot = path.join(configBase.cwd, "fixtures", "login-error-demo");
  await prepareDemoFixture(demoRoot);
  const sessionId = newSessionId("demo-fail");
  const config = loadConfig({ cwd: demoRoot, root: ledgerRoot });
  const stillFail = (
    await readFile(path.join(demoRoot, "captured", "pytest_before.txt"), "utf8")
  ).trim();
  console.log(`\n======== 故事 ${storyKey} · 声称已修复但测试仍失败 → 不得 verified ========`);
  console.log(`session=${sessionId}`);
  console.log(`fixture: ${demoRoot}`);
  const claim = "已修复登录错误分类，测试应该都绿了。";
  const result = await runClose({
    config,
    sessionId,
    claimText: claim,
    claimType: "bugfix",
    testOutput: stillFail,
    testCmd: "pytest -q",
    privacyPaths: ["src/auth.py"],
    reportTitle: "开发证据报告 · 测试仍红",
  });
  await writeSessionMeta(config, sessionId, {
    kind: "demo",
    claim,
    cwd: demoRoot,
    tags: ["still-failing", "contrast-c"],
  });
  if (result.markdown && !opts?.quietReport) console.log("\n" + result.markdown);
  const abandoned = result.report?.summary.abandoned ?? 0;
  const verified = result.report?.summary.verified ?? 0;
  const evidenced = result.report?.summary.evidenced ?? 0;
  console.log(
    `${storyKey} summary: evidenced=${evidenced} verified=${verified} abandoned=${abandoned}`,
  );
  console.log(`artifacts: ${sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir}`);
  return {
    ok: verified === 0,
    sessionId,
    abandoned,
    verified,
    evidenced,
    label: "still-failing",
  };
}

function printContrastFooter(a: StoryResult, b: StoryResult): void {
  console.log(`\n======== 门禁对照（竞赛主叙事）========`);
  console.log(
    `A ${a.sessionId}\n   空口「今天全做完了」→ abandoned=${a.abandoned} verified=${a.verified}  ⇒ 不得写成已完成`,
  );
  console.log(
    `B ${b.sessionId}\n   git diff + fail→pass 测试 → abandoned=${b.abandoned} verified=${b.verified}  ⇒ 才可公开为完成`,
  );
  console.log(
    `产品立场：LDEA 不是总结今天干了啥，而是拒绝未验证的完成叙事的本地证据 Agent。`,
  );
  console.log(`查看：ldea ls   |   ldea show ${a.sessionId}   |   ldea show ${b.sessionId}`);
}

function printSuiteMatrix(rows: Array<{ key: string; title: string; r: StoryResult }>): void {
  console.log(`\n======== 多故事门禁矩阵（Agent 作用一览）========`);
  console.log(
    pad("ID", 6) + pad("SESSION", 30) + pad("V", 4) + pad("E", 4) + pad("A", 4) + "结论",
  );
  console.log("-".repeat(88));
  for (const row of rows) {
    const v = row.r.verified;
    const e = row.r.evidenced ?? 0;
    const a = row.r.abandoned;
    let verdict = "未闭合";
    if (v >= 1) verdict = "可公开为完成 (verified)";
    else if (a >= 1) verdict = "空口被拒 (abandoned)";
    else if (e >= 1) verdict = "有痕迹但未验证 (evidenced)";
    console.log(
      pad(row.key, 6) +
        pad(row.r.sessionId, 30) +
        pad(String(v), 4) +
        pad(String(e), 4) +
        pad(String(a), 4) +
        `${row.title} → ${verdict}`,
    );
  }
  console.log("");
  console.log("V/E/A = verified / evidenced / abandoned");
  console.log("读法：同一句「做完了」，证据不同 → 账本状态不同；LLM 不能把 E/A 说成 V。");
  console.log("产品立场：LDEA 用多场景证明——完成叙事必须过门禁，不是聊天总结。");
  console.log(`查看：ldea ls`);
  for (const row of rows) {
    console.log(`  ldea show ${row.r.sessionId}`);
  }
}

function pad(s: string, n: number): string {
  const t = s.length > n ? s.slice(0, n - 1) + "…" : s;
  return t + " ".repeat(Math.max(1, n - t.length));
}

async function cmdDemo(argv: string[]): Promise<number> {
  const live = argFlag(argv, "--live");
  const empty = argFlag(argv, "--empty");
  const verifiedOnly = argFlag(argv, "--verified");
  const codeOnly = argFlag(argv, "--code");
  const failingOnly = argFlag(argv, "--failing");
  const suite = argFlag(argv, "--suite") || argFlag(argv, "--all") || argFlag(argv, "--cases");
  const configBase = loadConfig();
  const ledgerRoot = path.isAbsolute(configBase.root)
    ? configBase.root
    : path.join(configBase.cwd, configBase.root);

  console.log("LDEA demo — 拒绝未验证的完成叙事");

  if (empty) {
    const a = await runEmptyClaimDemo(configBase, ledgerRoot);
    return a.ok ? 0 : 1;
  }
  if (codeOnly) {
    const b = await runCodeOnlyDemo(configBase, ledgerRoot);
    return b.ok ? 0 : 1;
  }
  if (failingOnly) {
    const c = await runStillFailingDemo(configBase, ledgerRoot);
    return c.ok ? 0 : 1;
  }
  if (live) {
    const b = await runVerifiedDemo(configBase, ledgerRoot, { live: true });
    return b.ok ? 0 : 1;
  }
  if (verifiedOnly) {
    const b = await runVerifiedDemo(configBase, ledgerRoot);
    return b.ok ? 0 : 1;
  }

  if (suite) {
    // Four-story panorama for recording / judging — offline, no GPU.
    const a = await runEmptyClaimDemo(configBase, ledgerRoot, {
      quietReport: false,
      storyKey: "A",
    });
    const b = await runCodeOnlyDemo(configBase, ledgerRoot, {
      quietReport: false,
      storyKey: "B",
    });
    const c = await runStillFailingDemo(configBase, ledgerRoot, {
      quietReport: false,
      storyKey: "C",
    });
    const d = await runVerifiedDemo(configBase, ledgerRoot, {
      quietReport: false,
      storyKey: "D",
    });
    printSuiteMatrix([
      { key: "A", title: "空口「今天全做完了」", r: a },
      { key: "B", title: "只有 git、无测试", r: b },
      { key: "C", title: "声称已修但测试仍红", r: c },
      { key: "D", title: "git + fail→pass + 隐私扫描", r: d },
    ]);
    return a.ok && b.ok && c.ok && d.ok ? 0 : 1;
  }

  // Default: short dual contrast (offline, no GPU)
  const a = await runEmptyClaimDemo(configBase, ledgerRoot, {
    quietReport: false,
    storyKey: "A",
  });
  const d = await runVerifiedDemo(configBase, ledgerRoot, {
    quietReport: false,
    storyKey: "B",
  });
  printContrastFooter(a, d);
  return a.ok && d.ok ? 0 : 1;
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const cmd = argv[0] ?? "help";
  const rest = argv.slice(1);
  switch (cmd) {
    case "help":
    case "-h":
    case "--help":
      console.log(usage());
      return 0;
    case "doctor":
      return cmdDoctor();
    case "init":
      return cmdInit(rest[0]);
    case "ls":
    case "list":
      return cmdLs(rest);
    case "close":
      return cmdClose(rest);
    case "run": {
      let session: string | undefined;
      const goalParts: string[] = [];
      for (let i = 0; i < rest.length; i++) {
        if (rest[i] === "--session") {
          session = rest[i + 1];
          i += 1;
          continue;
        }
        goalParts.push(rest[i]!);
      }
      return cmdRun(goalParts, session);
    }
    case "demo":
      return cmdDemo(rest);
    case "show":
      return cmdShow(rest);
    default:
      console.error(`unknown command: ${cmd}\n`);
      console.log(usage());
      return 2;
  }
}

const isDirect =
  process.argv[1] &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isDirect) {
  main()
    .then((code) => process.exit(code))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}

export { main };
