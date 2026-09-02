#!/usr/bin/env node
// ============================================================================
// DeepSeek 健康监控 + 飞书告警
// 用法:
//   node scripts/check-deepseek-health.mjs                # 检查最近 5 分钟，阈值 3 次
//   node scripts/check-deepseek-health.mjs --minutes 10 --threshold 5
// 建议 cron: */5 * * * * cd /path/to/qa-system && node scripts/check-deepseek-health.mjs >> /tmp/deepseek-health.log 2>&1
// ============================================================================
import { execFileSync } from "node:child_process";
import { config as loadEnv } from "dotenv";
import fs from "node:fs";

loadEnv({ path: ".env.local" });

const SSH_KEY = process.env.DIFY_SSH_KEY || "/Users/xieweikai/Downloads/key.pem";
const HOST = process.env.DIFY_SSH_HOST || "62.234.28.57";
const USER = process.env.DIFY_SSH_USER || "ubuntu";

const args = process.argv.slice(2);
const minutes = parseInt(args[args.indexOf("--minutes") + 1] || "5", 10);
const threshold = parseInt(args[args.indexOf("--threshold") + 1] || "3", 10);

function sshRun(script) {
  return execFileSync("ssh", [
    "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
    `${USER}@${HOST}`, script,
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
}

const QUERY = `sudo docker exec docker-db_postgres-1 psql -U postgres -d dify -t -A -F "|" -c "SELECT count(*) FROM workflow_runs WHERE status = 'failed' AND error ILIKE '%deepseek%' AND created_at > now() - interval '${minutes} minutes';"`;
const MODEL_QUERY = `sudo docker exec docker-db_postgres-1 psql -U postgres -d dify -t -A -c "SELECT w.graph FROM workflows w WHERE w.id = '2a9cad67-cb84-45d4-bdfc-4543ec03ebbe';"`;

let failures = 0;
let currentModel = "unknown";
try {
  failures = parseInt(sshRun(QUERY).trim() || "0", 10);
  const graphRaw = sshRun(MODEL_QUERY);
  const m = graphRaw.match(/"type":\s*"llm"[^}]*?"id":\s*"llm_text"/);
  // 简化：直接找 llm_text 节点的 model name
  const nameMatch = graphRaw.match(/"name":\s*"(deepseek-chat|qwen-plus|qwen-max|qwen-turbo)"/);
  currentModel = nameMatch?.[1] || "unknown";
} catch (e) {
  console.error("监控脚本连接失败:", e.message);
  process.exit(2);
}

const ts = new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" });
console.log(`[${ts}] 近 ${minutes} 分钟 DeepSeek 失败: ${failures} 次 | 当前文字模型: ${currentModel}`);

if (failures >= threshold) {
  const msg =
    `⚠️ DeepSeek 模型连续失败告警\n` +
    `时间: ${ts}\n` +
    `近 ${minutes} 分钟失败次数: ${failures}（阈值 ${threshold}）\n` +
    `当前文字模型: ${currentModel}\n\n` +
    `机器人文字回答可能大面积失败，请尽快处理：\n` +
    `1) 切换到千问: node scripts/switch-dify-model.mjs qwen-plus\n` +
    `2) 恢复后切回: node scripts/switch-dify-model.mjs deepseek-chat`;

  const webhook = process.env.FEISHU_WEBHOOK_URL;
  if (webhook) {
    try {
      const res = await fetch(webhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ msg_type: "text", content: { text: msg } }),
      });
      console.log(`飞书告警已发送: HTTP ${res.status}`);
    } catch (e) {
      console.error("飞书告警发送失败:", e.message);
      process.exit(3);
    }
  } else {
    console.warn("未配置 FEISHU_WEBHOOK_URL，跳过飞书通知（请手动查看）");
  }
  process.exit(1); // 有告警时退出码 1，方便外部感知
}

console.log("状态正常 ✅");
process.exit(0);
