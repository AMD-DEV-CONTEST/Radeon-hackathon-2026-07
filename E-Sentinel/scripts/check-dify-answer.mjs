#!/usr/bin/env node
// ============================================================================
// 切换模型后的快速验证：给拼多多应用发一条测试问题
// 用法: node scripts/check-dify-answer.mjs [问题]
// ============================================================================
import fs from "node:fs";

const query = process.argv[2] || "质保多久？退货运费谁出？";
const keyFile = process.env.DIFY_APP_KEY_FILE || "/tmp/pdd_token.txt";
if (!fs.existsSync(keyFile)) {
  console.error(`找不到应用 Key 文件: ${keyFile}（可用 DIFY_APP_KEY_FILE 指定）`);
  process.exit(1);
}
const key = fs.readFileSync(keyFile, "utf8").trim();
const base = process.env.DIFY_BASE_URL || "http://62.234.28.57/v1";

const t0 = Date.now();
const res = await fetch(`${base}/chat-messages`, {
  method: "POST",
  headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
  body: JSON.stringify({ inputs: {}, query, user: "model-check", response_mode: "blocking", conversation_id: "" }),
});
const j = await res.json();
const ms = Date.now() - t0;

if (res.status === 200 && j.answer) {
  console.log(`✅ 回答正常 (${ms}ms): ${j.answer.replace(/\s+/g, " ").slice(0, 200)}`);
  process.exit(0);
} else {
  console.error(`❌ 回答失败 (HTTP ${res.status}, ${ms}ms): ${JSON.stringify(j).slice(0, 300)}`);
  process.exit(1);
}
