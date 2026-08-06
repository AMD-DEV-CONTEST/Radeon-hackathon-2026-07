-- 为核心业务表补齐 tenant_id 列，闭合 dashboard 统计的租户隔离缺口。
--
-- 背景：
--   overview / quality-metrics 的 dashboard 统计此前漏掉 chat_sessions、work_orders、
--   shadow_replies、actual_replies 四张表。写入侧适配器虽已带 tenant_id，但历史
--   migration 从未补列，导致 app 层无法对这些表做租户过滤（加了 .eq 会运行时报
--   列不存在）。本 migration 与 migration-022 保持同一约定：列 NOT NULL DEFAULT
--   'default'，历史行回填 'default'（当前单租户部署，回退值即正确值）。
--
-- ⚠ 落地前必读（连锁影响）：
--   migration-031 会动态遍历所有含 tenant_id 的表并 FORCE ROW LEVEL SECURITY。
--   本 migration 执行后，这四张表会被 031 自动纳入 RLS：
--     - dashboard 走 service_role（BYPASSRLS），不受影响，仍依赖 app 层过滤；
--     - 若前端用 anon / authenticated 角色直连这些表（如实时订阅 chat_sessions），
--       FORCE RLS 在无 policy 时会全拒，可能断开前端功能。
--   因此执行本 migration 前，请先确认这四张表是否对 anon/authenticated 暴露；
--   若是，需在单独的 migration 中为它们补 tenant-aware policy，再执行本文件。
--
-- 执行方式（务必显式指定，避免误触远程库）：
--   本地验证：supabase db push --linked=false   （或起本地 supabase 后 db reset）
--   远程执行：supabase db push                   （会落到 linked 的远程项目，谨慎）

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['bot_chat_sessions', 'work_orders', 'shadow_replies', 'actual_replies']
  LOOP
    -- 补列：NOT NULL DEFAULT 'default'，历史行自动回填
    EXECUTE format(
      'ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT ''default''',
      table_name
    );
    EXECUTE format(
      'UPDATE %I SET tenant_id = ''default'' WHERE tenant_id IS NULL',
      table_name
    );
    -- 单列索引足以支撑按 tenant_id 过滤（不依赖 created_at 存在）
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I(tenant_id)',
      'idx_' || table_name || '_tenant',
      table_name
    );
  END LOOP;
END
$$;
