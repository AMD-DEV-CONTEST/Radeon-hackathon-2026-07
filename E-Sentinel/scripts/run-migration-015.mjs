import pg from 'pg';
import fs from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
const { Pool } = pg;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runMigration() {
  const envPath = path.join(__dirname, '..', '.env.local');
  if (fs.existsSync(envPath)) {
    const text = fs.readFileSync(envPath, 'utf-8');
    for (const line of text.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eq = trimmed.indexOf('=');
      if (eq === -1) continue;
      const key = trimmed.slice(0, eq).trim();
      let value = trimmed.slice(eq + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      process.env[key] ||= value;
    }
  }

  const sql = fs.readFileSync(
    path.join(__dirname, '..', 'supabase', 'migration-015-unresolved-questions.sql'),
    'utf-8'
  );

  const databaseUrl = process.env.DATABASE_URL;
  const dbPassword = process.env.SUPABASE_DB_PASSWORD || process.env.SUPABASE_DATABASE_PASSWORD;

  if (!databaseUrl && !dbPassword) {
    console.error('❌ 请设置 Supabase 数据库密码，不是 service role key');
    console.error('   方式一: $env:SUPABASE_DB_PASSWORD="数据库密码" ; node scripts/run-migration-015.mjs');
    console.error('   方式二: $env:DATABASE_URL="postgresql://..." ; node scripts/run-migration-015.mjs');
    process.exit(1);
  }

  const pool = databaseUrl
    ? new Pool({
        connectionString: databaseUrl,
        ssl: { rejectUnauthorized: false },
        max: 1,
      })
    : new Pool({
        host: 'aws-1-ap-southeast-1.pooler.supabase.com',
        port: 5432,
        database: 'postgres',
        user: `postgres.${new URL(process.env.NEXT_PUBLIC_SUPABASE_URL).hostname.split('.')[0]}`,
        password: dbPassword,
        ssl: { rejectUnauthorized: false },
        max: 1,
      });

  const client = await pool.connect();
  try {
    console.log('已连接 Supabase，正在执行 migration-015...');
    await client.query(sql);
    console.log('✅ migration-015 执行成功！');

    // 验证表已创建
    const { rows } = await client.query(
      "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'unresolved%' ORDER BY table_name"
    );
    console.log('已创建的表:', rows.map(r => r.table_name).join(', '));

    // 验证 RPC
    const { rows: rpcs } = await client.query(
      "SELECT proname FROM pg_proc WHERE proname LIKE '%unresolved%' ORDER BY proname"
    );
    console.log('已创建的RPC:', rpcs.map(r => r.proname).join(', '));

  } catch (err) {
    console.error('❌ 执行失败:', err.message);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

runMigration();
