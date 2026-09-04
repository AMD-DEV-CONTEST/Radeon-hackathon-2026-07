import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { initSession, readStore, rebuildStore, sessionPaths } from "airecap-plus";
import type { LdeaConfig } from "./config.js";
import { LlmClient, type ChatMessage, type ToolCall } from "./llm.js";
import { executeTool, TOOL_SPECS, type ToolContext } from "./tools.js";
import { buildStructuredReport, renderReportMarkdown, type EvidenceReport } from "./report.js";

const SYSTEM_PROMPT = `你是 Local Dev Evidence Agent（本地开发证据整理智能体）。
目标：弄清“到底做成了什么”，拒绝未验证的完成叙事；不是复述聊天，也不是美化总结。

硬规则：
1. 事实以工具返回的 L1 outcome 账本为准。
2. 只有 status=verified 才能写成“已完成/已修复”。
3. claimed 且无代码/测试证据，不能当成果；session 结束后应 abandoned。
4. 你不能直接把 outcome 改成 verified；验证只能来自测试/verification 工具证据。
5. 目标含糊时先侦查再下结论：git_diff 看改了什么 → show_outcomes/claim → 用测试交叉验证；允许“部分完成”。
6. 需要信息时调用工具：git_diff、run_tests 或 ingest_test_output、claim、scan_privacy、show_outcomes、render_report。
7. 最终必须调用 render_report；narrative 可写判断过程，不得编造文件/测试/通过结果。
8. 若用户空口说完成，先 claim，再 git_diff/run_tests；无证据必须明确未验证，禁止恭维式“已完成”。
9. 每轮优先只调用 1 个工具（最多 2 个）；使用 API tool_calls，不要把工具写成纯文本。`;

export interface AgentRunResult {
  sessionId: string;
  rounds: number;
  toolTrace: Array<{ name: string; args: string; resultTail: string }>;
  finalAssistant?: string;
  report?: EvidenceReport;
  markdown?: string;
  messages: ChatMessage[];
}

function sessionOutDir(config: LdeaConfig, sessionId: string): string {
  return sessionPaths(sessionId, { cwd: config.cwd, root: config.root }).sessionDir;
}

/** Fallback when model emits Hermes/XML tool calls in content instead of tool_calls[]. */
export function parseTextToolCalls(content: string | null | undefined): ToolCall[] {
  if (!content) return [];
  const out: ToolCall[] = [];
  const re = /<tool_call>\s*([\s\S]*?)\s*<\/tool_call>/gi;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(content)) !== null) {
    const body = m[1]!.trim();
    try {
      const obj = JSON.parse(body) as { name?: string; arguments?: unknown };
      if (!obj.name) continue;
      const args =
        typeof obj.arguments === "string"
          ? obj.arguments
          : JSON.stringify(obj.arguments ?? {});
      i += 1;
      out.push({
        id: `text_tool_${i}`,
        type: "function",
        function: { name: obj.name, arguments: args },
      });
    } catch {
      const nameMatch = body.match(/"name"\s*:\s*"([^"]+)"/);
      const argsMatch = body.match(/"arguments"\s*:\s*(\{[\s\S]*\})/);
      if (nameMatch) {
        i += 1;
        out.push({
          id: `text_tool_${i}`,
          type: "function",
          function: {
            name: nameMatch[1]!,
            arguments: argsMatch?.[1] ?? "{}",
          },
        });
      }
    }
  }
  return out;
}

function extractToolCalls(msg: ChatMessage): ToolCall[] {
  if (msg.tool_calls?.length) return msg.tool_calls;
  return parseTextToolCalls(msg.content);
}

export async function runAgent(opts: {
  config: LdeaConfig;
  sessionId: string;
  goal: string;
  llm?: LlmClient;
}): Promise<AgentRunResult> {
  const { config, sessionId, goal } = opts;
  await initSession(sessionId, { cwd: config.cwd, root: config.root });

  const llm =
    opts.llm ??
    new LlmClient({
      baseUrl: config.llmBaseUrl,
      apiKey: config.llmApiKey,
      model: config.llmModel,
    });

  const ctx: ToolContext = {
    sessionId,
    cwd: config.cwd,
    root: config.root,
    modelName: llm.modelName,
    lastPrivacyRisks: [],
  };

  const messages: ChatMessage[] = [
    { role: "system", content: SYSTEM_PROMPT },
    {
      role: "user",
      content:
        `${goal}\n\n` +
        `工作目录: ${config.cwd}\n` +
        `请使用工具收集证据并生成可核验报告。每轮只调用必要工具，完成后调用 render_report。`,
    },
  ];

  const toolTrace: AgentRunResult["toolTrace"] = [];
  let finalAssistant: string | undefined;
  let rounds = 0;

  for (let i = 0; i < config.maxToolRounds; i++) {
    rounds = i + 1;
    const resp = await llm.chat({
      messages,
      tools: TOOL_SPECS,
      toolChoice: "auto",
      maxTokens: 900,
      temperature: 0,
    });
    const msg = resp.choices[0]?.message;
    if (!msg) break;

    const toolCalls = extractToolCalls(msg);
    messages.push({
      role: "assistant",
      content: msg.content ?? "",
      tool_calls: toolCalls.length ? toolCalls : undefined,
    });

    if (!toolCalls.length) {
      finalAssistant = msg.content ?? "";
      if (!ctx.lastMarkdown) {
        await finalizeDeterministic(ctx);
      }
      break;
    }

    for (const tc of toolCalls) {
      const name = tc.function.name;
      const args = tc.function.arguments ?? "{}";
      let result = await executeTool(ctx, name, args);
      // Keep subsequent chat payloads JSON-safe for picky OpenAI-compatible servers.
      result = result
        .split("")
        .filter((ch) => {
          const c = ch.charCodeAt(0);
          return c === 9 || c === 10 || c === 13 || (c >= 32 && c !== 127);
        })
        .join("");
      toolTrace.push({
        name,
        args,
        resultTail: result.length > 1200 ? `${result.slice(0, 1200)}…` : result,
      });
      messages.push({
        role: "tool",
        tool_call_id: tc.id,
        name,
        content: result,
      });
    }

    if (ctx.lastMarkdown) {
      finalAssistant =
        messages.filter((m) => m.role === "assistant").at(-1)?.content ?? "";
      break;
    }
  }

  if (!ctx.lastMarkdown) {
    await finalizeDeterministic(ctx);
  }

  const outDir = sessionOutDir(config, sessionId);
  await mkdir(outDir, { recursive: true });
  if (ctx.lastReport) {
    await writeFile(
      path.join(outDir, "report.json"),
      JSON.stringify(ctx.lastReport, null, 2),
      "utf8",
    );
  }
  if (ctx.lastMarkdown) {
    await writeFile(path.join(outDir, "report.md"), ctx.lastMarkdown, "utf8");
  }
  await writeFile(
    path.join(outDir, "agent-trace.json"),
    JSON.stringify({ goal, rounds, toolTrace, finalAssistant }, null, 2),
    "utf8",
  );

  return {
    sessionId,
    rounds,
    toolTrace,
    finalAssistant,
    report: ctx.lastReport,
    markdown: ctx.lastMarkdown,
    messages,
  };
}

async function finalizeDeterministic(ctx: ToolContext): Promise<void> {
  const paths = sessionPaths(ctx.sessionId, { cwd: ctx.cwd, root: ctx.root });
  let store = await readStore(paths);
  if (!store) {
    store = await rebuildStore(ctx.sessionId, { cwd: ctx.cwd, root: ctx.root });
  }
  const report = buildStructuredReport({
    store,
    privacyRisks: ctx.lastPrivacyRisks,
    model: ctx.modelName,
  });
  ctx.lastReport = report;
  ctx.lastMarkdown = renderReportMarkdown(report);
}

export interface CloseOptions {
  config: LdeaConfig;
  sessionId: string;
  claimText: string;
  claimType?: string;
  /** Skip git_diff (bare claim / no-repo close). */
  skipGit?: boolean;
  gitMode?: "worktree" | "workdir" | "staged";
  /** Run tests via shell (e.g. pytest -q). Ignored if testOutput set. */
  testCmd?: string;
  /** Inject captured test log instead of running. */
  testOutput?: string;
  testFramework?: string;
  priorFailTestOutput?: string;
  privacyPaths?: string[];
  reportTitle?: string;
  /** end_session + render always on unless false */
  finalize?: boolean;
}

/**
 * Daily close path: claim → (optional fail log) → git → tests → privacy → end → report.
 * No LLM required.
 */
export async function runClose(opts: CloseOptions): Promise<AgentRunResult> {
  const { config, sessionId } = opts;
  await initSession(sessionId, { cwd: config.cwd, root: config.root });
  const ctx: ToolContext = {
    sessionId,
    cwd: config.cwd,
    root: config.root,
    modelName: "close-rules",
    lastPrivacyRisks: [],
  };
  const toolTrace: AgentRunResult["toolTrace"] = [];
  const testCmd = opts.testCmd;
  const framework = opts.testFramework ?? "auto";

  const steps: Array<[string, string]> = [
    [
      "claim",
      JSON.stringify({
        text: opts.claimText,
        actor: "user",
        ...(opts.claimType ? { type: opts.claimType } : {}),
      }),
    ],
  ];

  if (opts.priorFailTestOutput) {
    steps.push([
      "ingest_test_output",
      JSON.stringify({
        text: opts.priorFailTestOutput,
        cmd: testCmd ?? "pytest -q",
        framework: "pytest",
        exit_code: 1,
      }),
    ]);
  }

  if (!opts.skipGit) {
    steps.push(["git_diff", JSON.stringify({ mode: opts.gitMode ?? "worktree" })]);
  }

  if (opts.testOutput) {
    const looksFailed =
      /\bFAILED\b/i.test(opts.testOutput) && !/\d+ passed/.test(opts.testOutput);
    steps.push([
      "ingest_test_output",
      JSON.stringify({
        text: opts.testOutput,
        cmd: testCmd ?? "pytest -q",
        framework: opts.testFramework ?? "pytest",
        exit_code: looksFailed ? 1 : 0,
      }),
    ]);
  } else if (testCmd) {
    steps.push([
      "run_tests",
      JSON.stringify({ cmd: testCmd, framework }),
    ]);
  }

  steps.push([
    "scan_privacy",
    JSON.stringify(opts.privacyPaths?.length ? { paths: opts.privacyPaths } : {}),
  ]);

  if (opts.finalize !== false) {
    steps.push(["end_session", JSON.stringify({})]);
    steps.push([
      "render_report",
      JSON.stringify({
        title: opts.reportTitle ?? `收工证据 · ${sessionId}`,
      }),
    ]);
  }

  for (const [name, args] of steps) {
    const result = await executeTool(ctx, name, args);
    toolTrace.push({
      name,
      args,
      resultTail: result.length > 1200 ? `${result.slice(0, 1200)}…` : result,
    });
  }

  const outDir = sessionOutDir(config, sessionId);
  await mkdir(outDir, { recursive: true });
  if (ctx.lastReport) {
    await writeFile(
      path.join(outDir, "report.json"),
      JSON.stringify(ctx.lastReport, null, 2),
      "utf8",
    );
  }
  if (ctx.lastMarkdown) {
    await writeFile(path.join(outDir, "report.md"), ctx.lastMarkdown, "utf8");
  }
  await writeFile(
    path.join(outDir, "close-trace.json"),
    JSON.stringify({ claim: opts.claimText, steps: toolTrace.map((t) => t.name) }, null, 2),
    "utf8",
  );

  return {
    sessionId,
    rounds: steps.length,
    toolTrace,
    report: ctx.lastReport,
    markdown: ctx.lastMarkdown,
    messages: [],
  };
}

/** Offline path: no LLM, pure tools/rules for demos & CI. */
export async function runDeterministicPipeline(opts: {
  config: LdeaConfig;
  sessionId: string;
  claimText: string;
  /** Optional prior failing output (bugfix R-V1 needs fail→pass). */
  priorFailTestOutput?: string;
  testOutput?: string;
  testCmd?: string;
  gitMode?: "worktree" | "workdir" | "staged";
  claimType?: string;
  privacyPaths?: string[];
  reportTitle?: string;
  skipGit?: boolean;
}): Promise<AgentRunResult> {
  return runClose({
    config: opts.config,
    sessionId: opts.sessionId,
    claimText: opts.claimText,
    claimType: opts.claimType,
    priorFailTestOutput: opts.priorFailTestOutput,
    testOutput: opts.testOutput,
    testCmd: opts.testOutput ? opts.testCmd : opts.testCmd,
    gitMode: opts.gitMode,
    privacyPaths: opts.privacyPaths,
    reportTitle: opts.reportTitle ?? "开发证据报告（确定性管道）",
    skipGit: opts.skipGit,
  });
}
