#!/usr/bin/env node
/**
 * 把训练/开发候选（training/data/train.jsonl · dev.jsonl）转换为 LoRA SFT 格式。
 *
 * 输出格式：JSONL，每行 { system, user, assistant }
 *   - system    ：质检裁判指令（与系统 QUALITY_STANDARDS 对齐，见 src/lib/qa/evaluate-core.ts）
 *   - user      ：客服会话原文
 *   - assistant ：期望的判定 JSON（risk_level / violations[] / needs_human_review 等）
 *
 * 训练时模型学习「客服会话 → 质检 JSON」映射；输出 schema 与 E-Sentinel
 * 解析器（evaluate-goldset normalizePrediction）一致，确保微调后可直接被系统消费。
 *
 * 用法：
 *   node scripts/prepare-lora-data.mjs \
 *     [--in training/data] [--out training/data/sft] [--split ratio]
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] ?? def : def;
}
const IN_DIR = arg("--in", "training/data");
const OUT_DIR = arg("--out", "training/data/sft");

const SYSTEM_PROMPT = `你是客服质检裁判。请评估以下客服会话中【客服】的行为，判定风险等级并列出违规项。

【质检标准】
一、服务态度（20分）：禁止辱骂/威胁/贬低/讽刺客户、推诿敷衍、消极放弃、与客户争执。
二、专业性（30分）：严禁错误产品信息/价格/政策；严禁虚假承诺、隐含承诺、绝对化承诺；未核实信息不得断言。
三、响应效率（15分）：复杂问题需告知预计处理时间并跟进；禁止长时间无响应后直接结束。
四、解决问题（25分）：必须给出可执行的方案；涉及退款/赔付须按标准流程；不得拒绝受理/拒绝升级。
五、合规与隐私（10分）：严禁索要验证码/完整银行卡/密码；严禁泄露客户信息；严禁索要好处费/私下交易；禁止绝对化宣传。

【判定规则】
1. 只判定客服行为；客户发言只是上下文，永远不作为违规证据。
2. 客户说退款/12315/假货/投诉等关键词本身不是违规，客服处理得当则该会话不因此升为 high/critical。
3. 客服合规提醒（如"请勿把验证码发给任何人"）不是索要，不构成违规。
4. 共情话术（"抱歉给您带来不便"）、已告知处理时间并跟进，不是敷衍/效率违规。
5. 每条违规必须给出 source_quote：客服原句逐字引用，必须是会话中连续片段。
6. 任一硬红线（索要验证码/银行卡/威胁/辱骂/绝对化宣传/泄露隐私）→ critical，不可降级。
7. 信息不足/检索无来源 → needs_human_review=true，风险保守填 low，violations 置空。

【输出】严格输出纯 JSON（不要 markdown 代码块），格式：
{
  "risk_level": "low|medium|high|critical",
  "violations": [
    { "category": "service_attitude|professionalism|efficiency|problem_solving|compliance_privacy",
      "rule": "标准内规则描述",
      "severity": "minor|major|critical",
      "source_quote": "客服原句" }
  ],
  "needs_human_review": false,
  "requires_tool": false
}`;

function toAssistant(label) {
  const obj = {
    risk_level: label.risk_level,
    violations: label.violations || [],
    needs_human_review: label.needs_human_review === true,
    requires_tool: label.requires_tool === true,
  };
  return JSON.stringify(obj, null, 2);
}

const rows = [];
for (const split of ["train", "dev"]) {
  const file = path.join(ROOT, IN_DIR, `${split}.jsonl`);
  const data = readFileSync(file, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  for (const r of data) {
    // B′：tool_context（检索返回的政策/证据）注入 user 消息，训练模型结合工具返回判定
    const userMsg = r.tool_context
      ? `${r.conversation}\n\n【检索到的政策资料】\n${r.tool_context}`
      : r.conversation;
    rows.push({
      id: r.id,
      template_seed: r.template_seed,
      split,
      system: SYSTEM_PROMPT,
      user: userMsg,
      assistant: toAssistant(r.label),
    });
  }
}

mkdirSync(path.join(ROOT, OUT_DIR), { recursive: true });
for (const split of ["train", "dev"]) {
  const part = rows.filter((r) => r.split === split).map((r) => JSON.stringify(r));
  writeFileSync(path.join(ROOT, OUT_DIR, `${split}.jsonl`), part.join("\n") + "\n");
}
const trainN = rows.filter((r) => r.split === "train").length;
const devN = rows.filter((r) => r.split === "dev").length;
console.log(`转换完成：train ${trainN} / dev ${devN} → ${OUT_DIR}`);
console.log(`样例 id: ${rows[0].id} | 输出 risk=${JSON.parse(rows[0].assistant).risk_level}`);
