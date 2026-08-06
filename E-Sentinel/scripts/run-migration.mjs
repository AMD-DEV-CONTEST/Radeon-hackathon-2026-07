/**
 * 执行数据库迁移（pgvector + shadow mode）
 * 启动: node scripts/run-migration.mjs
 */

import pg from "pg";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SUPABASE_KEY) {
  console.error("Missing SUPABASE_SERVICE_ROLE_KEY");
  process.exit(1);
}

// Extract project ref from URL
const ref = SUPABASE_URL.replace(/https?:\/\//, "").split(".")[0];

const { Pool } = pg;
const pool = new Pool({
  host: `db.${ref}.supabase.co`,
  port: 5432,
  database: "postgres",
  user: "postgres",
  password: SUPABASE_KEY,
  ssl: { rejectUnauthorized: false },
});

async function main() {
  console.log("=== Running Migration (RAG + Shadow Mode) ===\n");

  const sqlPath = path.join(__dirname, "..", "supabase", "migration-rag-shadow.sql");
  const sql = fs.readFileSync(sqlPath, "utf-8");

  try {
    const client = await pool.connect();
    console.log("[Migration] Connected to Supabase PostgreSQL");

    const result = await client.query(sql);
    console.log("[Migration] SQL executed successfully");

    // Verify tables exist
    const { rows: tables } = await client.query(`
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name IN ('quality_rules')
    `);
    console.log("[Migration] Tables found:", tables.map(r => r.table_name).join(", "));

    client.release();
  } catch (err) {
    console.error("[Migration] Failed:", err.message);
    console.error("Please run the SQL manually in Supabase SQL Editor:");
    console.error(`  File: supabase/migration-rag-shadow.sql`);
  }

  await pool.end();
  console.log("\n[Migration] Done!");
}

main().catch(console.error);
