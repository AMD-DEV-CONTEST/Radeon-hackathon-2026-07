#!/usr/bin/env node
// ============================================================================
// Dify Knowledge Push CLI
// 一键将 qa-system 知识库推送到 Dify 云服务器
// 用法: node scripts/push-to-dify.mjs [--category faq] [--limit 100]
// 前提: 设置 DIFY_BASE_URL 和 DIFY_API_KEY 环境变量
// ============================================================================

import { createClient } from "@supabase/supabase-js";
import { pushKnowledgeEntries } from "../src/lib/dify-client.js";
import { config } from "dotenv";

// Load .env.local
config({ path: ".env.local" });

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error("❌ SUPABASE_SERVICE_ROLE_KEY 未设置");
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: { autoRefreshToken: false, persistSession: false },
});

async function main() {
  const args = process.argv.slice(2);
  const category = args.includes("--category") ? args[args.indexOf("--category") + 1] : null;
  const limitIdx = args.indexOf("--limit");
  const limit = limitIdx !== -1 ? parseInt(args[limitIdx + 1]) || 100 : 100;

  console.log("📤 正在从 qa-system 拉取知识条目...");

  let query = supabase
    .from("knowledge_entries")
    .select("id, title, content, category, tags")
    .eq("status", "published")
    .order("hit_count", { ascending: false })
    .limit(limit);

  if (category) query = query.eq("category", category);

  const { data: entries, error } = await query;
  if (error) { console.error("❌ 查询失败:", error.message); process.exit(1); }
  if (!entries || entries.length === 0) {
    console.log("📭 没有已发布的知识条目需要推送");
    process.exit(0);
  }

  console.log(`📚 共 ${entries.length} 条知识，正在推送到 Dify...\n`);

  const result = await pushKnowledgeEntries(
    entries.map((e) => ({ title: e.title, content: e.content, category: e.category })),
    (current, total, title, status) => {
      const icon = status === "ok" ? "✅" : "❌";
      process.stdout.write(`\r${icon} [${current}/${total}] ${title.slice(0, 40)}${status !== "ok" ? ` - ${status}` : ""}`);
    },
  );

  console.log("\n");
  console.log("═".repeat(50));
  console.log("  推送完成");
  console.log("═".repeat(50));
  console.log(`  知识库:  ${result.dataset_name} (${result.dataset_id})`);
  console.log(`  总计:    ${result.total}`);
  console.log(`  成功:    ${result.succeeded}`);
  console.log(`  失败:    ${result.failed}`);
  if (result.errors.length > 0) {
    console.log(`  错误:`);
    result.errors.slice(0, 5).forEach((e) => console.log(`    - ${e}`));
  }
  console.log("═".repeat(50));
}

main().catch((err) => {
  console.error("❌ 推送失败:", err.message);
  process.exit(1);
});
