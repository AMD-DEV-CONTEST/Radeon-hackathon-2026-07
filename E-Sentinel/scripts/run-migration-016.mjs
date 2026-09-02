import fs from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import { createClient } from '@supabase/supabase-js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runMigration() {
  const sql = fs.readFileSync(
    path.join(__dirname, '..', 'supabase', 'migration-016-hybrid-search-compat.sql'),
    'utf-8'
  );

  // 从 .env.local 读取配置
  const envPath = path.join(__dirname, '..', '.env.local');
  const text = fs.readFileSync(envPath, 'utf-8');
  const env = {};
  for (const line of text.split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const eq = t.indexOf('=');
    if (eq === -1) continue;
    env[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
  }

  const supabaseUrl = env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !serviceKey) {
    console.error('❌ .env.local 缺少 Supabase 配置');
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  console.log('正在通过 Supabase REST API 执行 migration...');

  // Supabase 不支持直接执行原始 SQL 的 REST API，
  // 但我们可以通过 rpc 调用 pg_ddl 或者通过 SQL Editor
  // 这里改用打印 SQL 到控制台供复制到 Dashboard

  console.log('\n' + '='.repeat(60));
  console.log('请在 Supabase Dashboard → SQL Editor 中执行以下 SQL：');
  console.log('='.repeat(60));
  console.log(sql);
  console.log('='.repeat(60));
  const projectRef = new URL(supabaseUrl).hostname.split('.')[0];
  console.log('\n📋 Supabase 地址:', `https://supabase.com/project/${projectRef}/sql/new`);
  console.log('\n或者手动登录:', `https://supabase.com/dashboard/project/${projectRef}`);
}

runMigration().catch(console.error);
