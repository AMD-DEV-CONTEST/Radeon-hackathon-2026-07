/**
 * Quick migration: add alert_method column + update evaluate route
 * 启动: node scripts/add-alert-column.mjs
 */
import pg from "pg";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SUPABASE_KEY) {
  console.error("Missing SUPABASE_SERVICE_ROLE_KEY");
  process.exit(1);
}

const ref = SUPABASE_URL.replace(/https?:\/\//, "").split(".")[0];

const { Pool } = pg;
const pool = new Pool({
  host: `aws-1-ap-southeast-1.pooler.supabase.com`,
  port: 6543,
  database: "postgres",
  user: `postgres.${ref}`,
  password: SUPABASE_KEY,
  ssl: { rejectUnauthorized: false },
});

async function main() {
  try {
    const client = await pool.connect();
    console.log("[Migration] Connected via pooler");

    await client.query(`
      ALTER TABLE quality_reports
        ADD COLUMN IF NOT EXISTS alert_method TEXT NOT NULL DEFAULT 'none',
        ADD COLUMN IF NOT EXISTS alert_dispatched_at TIMESTAMPTZ;
    `);
    console.log("[Migration] Columns added: alert_method, alert_dispatched_at");

    client.release();
  } catch (err) {
    console.error("[Migration] Failed:", err.message);
    console.log("Run manually in Supabase SQL Editor:");
    console.log("ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS alert_method TEXT NOT NULL DEFAULT 'none';");
    console.log("ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS alert_dispatched_at TIMESTAMPTZ;");
  }
  await pool.end();
}

main().catch(console.error);
