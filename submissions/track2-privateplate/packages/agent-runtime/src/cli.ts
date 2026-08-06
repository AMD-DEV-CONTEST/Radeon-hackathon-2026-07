#!/usr/bin/env node
/**
 * PrivatePlate CLI (offline smoke)
 *
 * Uses PrivatePlateAgent + ScriptedProductProvider (test double, not model evidence).
 * Real model Agent: start server with PRIVATEPLATE_AGENT_PROVIDER=local_vllm.
 *
 *   --smoke   non-interactive main product path
 *   (default) interactive REPL with mock provider
 */
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

const BANNER =
  "PrivatePlate offline smoke (ScriptedProductProvider mock — not model/Radeon evidence)";

function createAgent(domain: PrivatePlateDomain, sessionId?: string) {
  return new PrivatePlateAgent(
    domain,
    sessionId ?? `cli-${Date.now()}`,
    new ScriptedProductProvider()
  );
}

async function runSmoke(domain: PrivatePlateDomain): Promise<void> {
  const agent = createAgent(domain, "cli-smoke");

  const turns = [
    "中午我们三个人吃什么？豆腐今天最好吃掉，但我不想再吃鸡腿了。",
    "蒸蛋今天也不想吃，换一道，其他都保留。",
    "发给保姆"
  ];

  for (const text of turns) {
    console.log(`\n你: ${text}`);
    const result = await agent.handleUserMessage(text);
    console.log(`助手:\n${result.answer}`);
    console.log(
      `[trace] phase=${result.phase} tools=${result.toolTrace.map((t: { tool: string }) => t.tool).join(">") || "-"} valid=${result.validationOk} evidence=${result.routingEvidenceKind ?? "model_routed"}`
    );
    if (result.uiOnly) {
      console.log(
        `[ui-only token] ${result.uiOnly.confirmationToken.slice(0, 12)}… (full token only in memory)`
      );
      const confirm = agent.confirmPending({
        confirmationToken: result.uiOnly.confirmationToken,
        idempotencyKey: "cli-smoke-confirm-1"
      });
      console.log(
        confirm.ok
          ? `[confirm] ok action=${confirm.actionType} replayed=${confirm.receipt.replayed}`
          : `[confirm] failed ${"code" in confirm ? confirm.code : "error"}`
      );
    }
  }
}

async function runRepl(): Promise<void> {
  const domain = await PrivatePlateDomain.create(":memory:");
  const agent = createAgent(domain);
  const rl = createInterface({ input, output });

  console.log(BANNER);
  console.log("输入中文需求；/confirm <token> 确认任务卡；/quit 退出；/smoke 跑主路径。");

  while (true) {
    const line = (await rl.question("\n你> ")).trim();
    if (!line) continue;
    if (line === "/quit" || line === "/exit") break;
    if (line === "/smoke") {
      await runSmoke(domain);
      continue;
    }
    if (line.startsWith("/confirm ")) {
      const token = line.slice("/confirm ".length).trim();
      const result = agent.confirmPending({
        confirmationToken: token,
        idempotencyKey: `cli-${Date.now()}`
      });
      console.log(JSON.stringify(result, null, 2));
      continue;
    }

    const result = await agent.handleUserMessage(line);
    console.log(`\n助手>\n${result.answer}`);
    if (result.uiOnly) {
      console.log(
        `\n[UI-only] 确认令牌（仅显示一次）:\n${result.uiOnly.confirmationToken}`
      );
      console.log(
        `使用: /confirm ${result.uiOnly.confirmationToken.slice(0, 8)}…`
      );
    }
  }

  rl.close();
  domain.close();
}

if (process.argv.includes("--smoke") || process.argv.includes("--demo")) {
  const domain = await PrivatePlateDomain.create(":memory:");
  console.log(BANNER);
  await runSmoke(domain);
  domain.close();
} else {
  await runRepl();
}
