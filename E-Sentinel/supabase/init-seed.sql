-- ============================================================
-- E-Sentinel DEMO INIT (single-file) — run in Supabase SQL Editor
-- Generated 2026-08-05
-- ============================================================

-- ============================================================
-- E-Sentinel DEMO INIT — prerequisite tables
-- prompts / prompt_versions / bots / model_configs / pipeline_jobs
-- were created by legacy project migrations; E-Sentinel migrations
-- reference them, so they must exist before schema.sql.
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id TEXT, status TEXT DEFAULT 'PENDING', transcript TEXT,
  segments JSONB, result JSONB, error TEXT,
  source_channel TEXT DEFAULT 'WEB_APP',
  created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS prompts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id UUID,
  name TEXT NOT NULL, scene TEXT NOT NULL, system_prompt TEXT NOT NULL,
  variables JSONB DEFAULT '[]', temperature NUMERIC(3,2) DEFAULT 0.7,
  max_tokens INTEGER DEFAULT 1024, version INTEGER DEFAULT 1,
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
  is_active BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS prompt_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prompt_id UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, system_prompt TEXT NOT NULL,
  variables JSONB DEFAULT '[]', temperature NUMERIC(3,2) DEFAULT 0.7,
  max_tokens INTEGER DEFAULT 1024, created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id UUID,
  name TEXT NOT NULL, avatar TEXT,
  welcome_message TEXT DEFAULT '您好，我是AI客服助手，请问有什么可以帮您？',
  prompt_id UUID REFERENCES prompts(id) ON DELETE SET NULL, model_config_id UUID,
  platform TEXT DEFAULT 'feishu',
  working_hours JSONB DEFAULT '{"start":"09:00","end":"22:00","timezone":"Asia/Shanghai"}',
  transfer_keywords JSONB DEFAULT '["转人工"]', is_active BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS model_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id UUID,
  name TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('deepseek','kimi','moonshot','openai','zhipu','qwen')),
  model_name TEXT NOT NULL, api_key TEXT, api_url TEXT,
  temperature NUMERIC(3,2) DEFAULT 0.7, max_tokens INTEGER DEFAULT 2048,
  top_p NUMERIC(3,2) DEFAULT 1.0, is_default BOOLEAN DEFAULT false,
  is_active BOOLEAN DEFAULT true, priority INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS idx_prompts_scene ON prompts(scene);
CREATE INDEX IF NOT EXISTS idx_prompts_status ON prompts(status);
CREATE INDEX IF NOT EXISTS idx_bots_platform ON bots(platform);
CREATE INDEX IF NOT EXISTS idx_model_configs_provider ON model_configs(provider);

-- >>> schema.sql
-- ============================================================
-- QA System · 客服质检系统 · Database Schema
-- 执行方式: 在 Supabase SQL Editor 中全量执行此文件
-- ============================================================

-- ── 0. 清理（仅首次调试用，生产环境删除） ────────────────
-- DROP TABLE IF EXISTS bad_cases CASCADE;
-- DROP TABLE IF EXISTS quality_reports CASCADE;
-- DROP TABLE IF EXISTS profiles CASCADE;

-- ── 1. 人员与权限表 (profiles) ────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'agent' CHECK (role IN ('agent', 'team_lead', 'operator', 'viewer', 'admin')),
  team_id       TEXT,                          -- 归属团队，team_lead 通过 team_id 查看下属数据
  feishu_open_id TEXT,                         -- 飞书私信推送目标
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_profiles_role ON profiles(role);
CREATE INDEX IF NOT EXISTS idx_profiles_team ON profiles(team_id);

-- 种子数据
INSERT INTO profiles (name, role, team_id) VALUES
  ('老板', 'admin', 'alpha'),
  ('张建国', 'team_lead', 'alpha'),
  ('王五', 'agent', 'alpha'),
  ('孙七', 'agent', 'alpha'),
  ('李六', 'agent', 'alpha')
ON CONFLICT DO NOTHING;

-- ── 2. 质检报告表 (quality_reports) ───────────────────────
CREATE TABLE IF NOT EXISTS quality_reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id       TEXT NOT NULL,               -- 外部会话 ID
  agent_id        UUID REFERENCES profiles(id),-- 被质检的客服
  reviewer_id     UUID REFERENCES profiles(id),-- 所属组长
  conversation    TEXT NOT NULL,               -- 脱敏后的客服对话全文
  intent          TEXT,                        -- AI 识别的客户意图
  sentiment_score INT CHECK (sentiment_score BETWEEN 1 AND 5), -- 1=平静 5=极怒
  total_score     INT CHECK (total_score BETWEEN 0 AND 100),   -- 质检总分
  violations      JSONB NOT NULL DEFAULT '[]', -- [{rule, deduction, source_quote, severity}]
  risk_level      TEXT NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
  status          TEXT NOT NULL DEFAULT 'pending_review'
                  CHECK (status IN ('pending_review', 'confirmed', 'overturned', 'archived')),
  overturned_by   UUID REFERENCES profiles(id),
  overturned_reason TEXT,
  correlation_id  TEXT NOT NULL,               -- 全链路追踪 ID
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_reports_agent ON quality_reports(agent_id);
CREATE INDEX IF NOT EXISTS idx_reports_reviewer ON quality_reports(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_reports_risk ON quality_reports(risk_level);
CREATE INDEX IF NOT EXISTS idx_reports_status ON quality_reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_correlation ON quality_reports(correlation_id);
CREATE INDEX IF NOT EXISTS idx_reports_created ON quality_reports(created_at DESC);

-- ── 3. 误判案例表 (bad_cases) ─────────────────────────────
CREATE TABLE IF NOT EXISTS bad_cases (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quality_report_id   UUID NOT NULL REFERENCES quality_reports(id) ON DELETE CASCADE,
  original_judgment   JSONB NOT NULL,          -- AI 原始判定: {score, violations, risk_level}
  corrected_judgment  JSONB NOT NULL,          -- 人工修正后: {score, violations, risk_level}
  overturn_reason     TEXT NOT NULL,           -- 驳回原因（人工填写）
  corrected_by        UUID NOT NULL REFERENCES profiles(id),
  analysis_report     TEXT,                    -- 离线 Coze/LLM 分析报告（后续补充）
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bad_cases_report ON bad_cases(quality_report_id);

-- ============================================================
-- RLS (Row Level Security) · 三级权限隔离
-- ============================================================

-- 启用 RLS
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE bad_cases ENABLE ROW LEVEL SECURITY;

-- ── profiles 表 RLS ─────────────────────────────────────

-- Policy: 所有人可读 profiles（花名册是公开的）
CREATE POLICY "Anyone can read profiles"
  ON profiles FOR SELECT
  USING (true);

-- Policy: 仅 admin 可写 profiles
CREATE POLICY "Admin can insert profiles"
  ON profiles FOR INSERT
  WITH CHECK (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) = 'admin'
  );

CREATE POLICY "Admin can update profiles"
  ON profiles FOR UPDATE
  USING (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) = 'admin'
  );

-- ── quality_reports 表 RLS ──────────────────────────────

-- Policy 1: Agent 仅看自己的报告
CREATE POLICY "Agent sees own reports"
  ON quality_reports FOR SELECT
  USING (
    agent_id = (SELECT auth.uid())
  );

-- Policy 2: Team lead 看自己团队的报告
CREATE POLICY "Team lead sees team reports"
  ON quality_reports FOR SELECT
  USING (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) IN ('team_lead', 'operator')
    AND (SELECT team_id FROM profiles WHERE id = quality_reports.agent_id)
        = (SELECT team_id FROM profiles WHERE id = (SELECT auth.uid()))
  );

-- Policy 3: Admin 看全部
CREATE POLICY "Admin sees all reports"
  ON quality_reports FOR SELECT
  USING (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) = 'admin'
  );

-- Policy 4: Admin / team_lead 可更新（驳回/确认）
CREATE POLICY "Admin and team_lead can update reports"
  ON quality_reports FOR UPDATE
  USING (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) IN ('admin', 'team_lead', 'operator')
  );

-- ── bad_cases 表 RLS ────────────────────────────────────

-- Policy: Admin 和对应组长可读
CREATE POLICY "Admin and team_lead read bad_cases"
  ON bad_cases FOR SELECT
  USING (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) IN ('admin', 'team_lead', 'operator')
  );

CREATE POLICY "Admin and team_lead insert bad_cases"
  ON bad_cases FOR INSERT
  WITH CHECK (
    (SELECT role FROM profiles WHERE id = (SELECT auth.uid())) IN ('admin', 'team_lead', 'operator')
  );

-- >>> migration-003-ecommerce-ops.sql
-- ============================================================================
-- Migration 003: E-Commerce Customer Service Bot Operations Platform
-- Extends E-Sentinel to cover 7 job responsibilities:
--   1. Multi-platform bot script/config optimization
--   2. Daily chat QA & problem extraction
--   3. Knowledge base optimization
--   4. Campaign/product KB sync
--   5. Inquiry loss analysis → conversion rate
--   6. Satisfaction analysis (good/bad reviews)
--   7. Daily/weekly/monthly reports + industry benchmarking
-- ============================================================================

-- Ensure pgvector extension is available (reuses migration-rag-shadow.sql setup)
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ============================================================================
-- Table: platforms — 8 e-commerce platforms
-- ============================================================================
CREATE TABLE IF NOT EXISTS platforms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    code        TEXT NOT NULL UNIQUE,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    bot_type    TEXT NOT NULL DEFAULT 'third_party' CHECK (bot_type IN ('third_party', 'native', 'hybrid')),
    api_endpoint TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Table: bot_configs — pre-sale / post-sale script configuration per platform
-- Responsibility 1 core table. Versioned for audit trail.
-- ============================================================================
CREATE TABLE IF NOT EXISTS bot_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     UUID NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
    config_type     TEXT NOT NULL CHECK (config_type IN ('pre_sale', 'post_sale')),
    config_key      TEXT NOT NULL,
    config_value    JSONB NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    updated_by      UUID REFERENCES profiles(id),
    change_summary  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, config_type, config_key, version)
);
CREATE INDEX IF NOT EXISTS idx_bot_configs_platform ON bot_configs(platform_id, config_type, status);
CREATE INDEX IF NOT EXISTS idx_bot_configs_active ON bot_configs(platform_id, config_type, config_key) WHERE status = 'active';

-- ============================================================================
-- Table: knowledge_entries — custom knowledge base
-- Core table for responsibilities 1, 3, 4. pgvector RAG enabled.
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category    TEXT NOT NULL CHECK (category IN ('product', 'faq', 'after_sales_policy', 'campaign', 'greeting')),
    platform_id UUID REFERENCES platforms(id),
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    keywords    TEXT[] NOT NULL DEFAULT '{}',
    tags        TEXT[] NOT NULL DEFAULT '{}',
    priority    INT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    source      TEXT,
    embedding   vector(1536),
    updated_by  UUID REFERENCES profiles(id),
    version     INT NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_entries(category, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_platform ON knowledge_entries(platform_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON knowledge_entries
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- RPC: match_knowledge_entries — same pattern as match_quality_rules
CREATE OR REPLACE FUNCTION match_knowledge_entries(
    query_embedding vector(1536),
    match_count int DEFAULT 5
)
RETURNS TABLE(
    id UUID,
    category TEXT,
    title TEXT,
    content TEXT,
    keywords TEXT[],
    tags TEXT[],
    priority INT,
    status TEXT,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ke.id,
        ke.category,
        ke.title,
        ke.content,
        ke.keywords,
        ke.tags,
        ke.priority,
        ke.status,
        (1 - (ke.embedding <=> query_embedding))::float AS similarity
    FROM knowledge_entries ke
    WHERE ke.status = 'published'
      AND ke.embedding IS NOT NULL
    ORDER BY ke.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================================
-- Table: bot_chat_sessions — bot chat logs
-- Responsibility 2 core data. Separate from quality_reports for scale.
-- ============================================================================
CREATE TABLE IF NOT EXISTS bot_chat_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id         UUID NOT NULL REFERENCES platforms(id),
    session_type        TEXT NOT NULL CHECK (session_type IN ('pre_sale', 'post_sale')),
    external_session_id TEXT,
    customer_id         TEXT,
    bot_handled         BOOLEAN NOT NULL DEFAULT true,
    transfer_reason     TEXT,
    is_inquiry          BOOLEAN NOT NULL DEFAULT false,
    inquiry_result      TEXT CHECK (inquiry_result IN ('converted', 'lost', 'pending', null)),
    sentiment_score     INT CHECK (sentiment_score BETWEEN 1 AND 5),
    satisfaction        TEXT CHECK (satisfaction IN ('good', 'neutral', 'bad', null)),
    total_messages      INT NOT NULL DEFAULT 0,
    first_response_ms   INT,
    resolution_ms       INT,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    conversation        TEXT NOT NULL,
    correlation_id      TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_platform ON bot_chat_sessions(platform_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_type ON bot_chat_sessions(session_type, satisfaction);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_inquiry ON bot_chat_sessions(is_inquiry, inquiry_result);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_created ON bot_chat_sessions(created_at DESC);

-- ============================================================================
-- Table: optimization_tasks — tracked optimization items
-- Responsibilities 2, 3, 5, 6. Bridges analysis to actionable tasks.
-- ============================================================================
CREATE TABLE IF NOT EXISTS optimization_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source              TEXT NOT NULL CHECK (source IN ('chat_inspection', 'inquiry_loss', 'satisfaction', 'campaign', 'manual', 'knowledge_gap')),
    category            TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    priority            TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'wont_fix')),
    platform_id         UUID REFERENCES platforms(id),
    related_chat_id     UUID REFERENCES bot_chat_sessions(id),
    related_knowledge_id UUID REFERENCES knowledge_entries(id),
    assigned_to         UUID REFERENCES profiles(id),
    resolution          TEXT,
    impact_estimate     TEXT,
    created_by          UUID REFERENCES profiles(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_opt_tasks_status ON optimization_tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_opt_tasks_source ON optimization_tasks(source);
CREATE INDEX IF NOT EXISTS idx_opt_tasks_assigned ON optimization_tasks(assigned_to) WHERE status != 'resolved';

-- ============================================================================
-- Table: robot_reports — daily/weekly/monthly reports
-- Responsibility 7. LLM-generated structured reports.
-- ============================================================================
CREATE TABLE IF NOT EXISTS robot_reports (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type       TEXT NOT NULL CHECK (report_type IN ('daily', 'weekly', 'monthly')),
    period_start      DATE NOT NULL,
    period_end        DATE NOT NULL,
    platform_id       UUID REFERENCES platforms(id),
    summary_md        TEXT NOT NULL,
    metrics           JSONB NOT NULL,
    optimization_plan TEXT,
    industry_compare  JSONB,
    generated_by      TEXT NOT NULL DEFAULT 'auto',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(report_type, period_start, platform_id)
);
CREATE INDEX IF NOT EXISTS idx_robot_reports_period ON robot_reports(report_type, period_start DESC);

-- ============================================================================
-- Table: industry_benchmarks — reference data for responsibility 7
-- ============================================================================
CREATE TABLE IF NOT EXISTS industry_benchmarks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name   TEXT NOT NULL,
    industry_avg  NUMERIC NOT NULL,
    industry_top  NUMERIC,
    category      TEXT,
    period        TEXT NOT NULL DEFAULT '2025',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Table: knowledge_update_logs — audit trail for responsibility 3
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_update_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id    UUID REFERENCES knowledge_entries(id) ON DELETE SET NULL,
    update_type     TEXT NOT NULL CHECK (update_type IN ('create', 'update', 'publish', 'archive', 'batch_import')),
    field_changed   TEXT,
    old_value       TEXT,
    new_value       TEXT,
    updated_by      UUID REFERENCES profiles(id),
    correlation_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_logs_entry ON knowledge_update_logs(knowledge_id, created_at DESC);

-- ============================================================================
-- Extend quality_reports with bot session and platform references
-- ============================================================================
ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS is_bot_session BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS bot_session_id UUID REFERENCES bot_chat_sessions(id);
ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS platform_id UUID REFERENCES platforms(id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_bot_session ON quality_reports(bot_session_id) WHERE is_bot_session = true;

-- ============================================================================
-- Seed data: 8 e-commerce platforms
-- ============================================================================
INSERT INTO platforms (name, code, bot_type) VALUES
    ('天猫', 'tmall', 'third_party'),
    ('京东', 'jd', 'third_party'),
    ('唯品会', 'vip', 'third_party'),
    ('抖音', 'douyin', 'third_party'),
    ('拼多多', 'pdd', 'third_party'),
    ('快手', 'kuaishou', 'third_party'),
    ('小红书', 'xiaohongshu', 'native'),
    ('官微', 'weibo', 'hybrid')
ON CONFLICT (code) DO NOTHING;

-- ============================================================================
-- Seed data: industry benchmarks
-- ============================================================================
INSERT INTO industry_benchmarks (metric_name, industry_avg, industry_top, category, period) VALUES
    ('independent_reception_rate', 65, 85, '全品类', '2025'),
    ('conversion_rate', 12, 22, '全品类', '2025'),
    ('satisfaction_rate', 78, 92, '全品类', '2025'),
    ('avg_resolution_time_sec', 180, 90, '全品类', '2025'),
    ('transfer_to_human_rate', 35, 12, '全品类', '2025'),
    ('first_response_time_sec', 15, 5, '全品类', '2025'),
    ('independent_reception_rate', 58, 80, '美妆', '2025'),
    ('independent_reception_rate', 70, 88, '3C', '2025'),
    ('independent_reception_rate', 62, 83, '服饰', '2025'),
    ('independent_reception_rate', 67, 85, '食品', '2025')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- RLS: Enable on new tables where applicable
-- ============================================================================
ALTER TABLE platforms ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE optimization_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE robot_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_update_logs ENABLE ROW LEVEL SECURITY;

-- Public read for reference tables
CREATE POLICY "Platforms are publicly readable" ON platforms FOR SELECT USING (true);
CREATE POLICY "Industry benchmarks are publicly readable" ON industry_benchmarks FOR SELECT USING (true);

-- Authenticated read/write for operational tables (UI uses supabaseAdmin which bypasses RLS;
-- these policies provide defense-in-depth for any client-side queries)
CREATE POLICY "Bot configs readable by all authenticated users" ON bot_configs FOR SELECT USING (true);
CREATE POLICY "Knowledge entries readable by all authenticated users" ON knowledge_entries FOR SELECT USING (true);
CREATE POLICY "Chat sessions readable by all authenticated users" ON bot_chat_sessions FOR SELECT USING (true);
CREATE POLICY "Optimization tasks readable by all authenticated users" ON optimization_tasks FOR SELECT USING (true);
CREATE POLICY "Robot reports readable by all authenticated users" ON robot_reports FOR SELECT USING (true);
CREATE POLICY "Knowledge logs readable by all authenticated users" ON knowledge_update_logs FOR SELECT USING (true);

-- >>> LEGACY COLUMN BACKFILL
ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS hit_count INTEGER DEFAULT 0;
ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'professional';
ALTER TABLE bot_chat_sessions ADD COLUMN IF NOT EXISTS bot_id UUID REFERENCES bots(id) ON DELETE SET NULL;
ALTER TABLE prompts ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT false;

-- >>> migration-022-tenant-foundation.sql
-- Minimal tenant isolation for the existing SaaS core tables.
CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'standard',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO tenants (id, code, name)
VALUES ('default', 'default', 'Default tenant')
ON CONFLICT (id) DO NOTHING;

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS tenant_id TEXT;
ALTER TABLE profiles
  ALTER COLUMN tenant_id SET DEFAULT 'default';
UPDATE profiles SET tenant_id = 'default' WHERE tenant_id IS NULL;

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['knowledge_entries', 'bot_configs', 'bot_chat_sessions', 'quality_reports', 'optimization_tasks']
  LOOP
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT ''default''', table_name);
    EXECUTE format('UPDATE %I SET tenant_id = ''default'' WHERE tenant_id IS NULL', table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(tenant_id, created_at DESC)', 'idx_' || table_name || '_tenant_created', table_name);
  END LOOP;
END $$;

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
  CREATE POLICY "Tenants require matching JWT tenant" ON tenants
    FOR SELECT USING (auth.uid() IS NOT NULL AND id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- >>> supabase/migration-004-industry-benchmarks.sql
-- Migration 004: Create industry_benchmarks table with seed data
-- Run this in Supabase SQL Editor if the table doesn't exist yet

-- Create table
CREATE TABLE IF NOT EXISTS public.industry_benchmarks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_name TEXT NOT NULL,
  industry_avg NUMERIC(5,2) NOT NULL,
  industry_top NUMERIC(5,2),
  category TEXT,
  period TEXT DEFAULT '2025Q4',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Enable RLS
ALTER TABLE public.industry_benchmarks ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read
CREATE POLICY "Allow read for authenticated" ON public.industry_benchmarks
  FOR SELECT USING (auth.role() = 'authenticated');

-- Allow service_role to insert/update
CREATE POLICY "Allow insert for service_role" ON public.industry_benchmarks
  FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow update for service_role" ON public.industry_benchmarks
  FOR UPDATE USING (true);

-- Seed data: industry benchmarks for e-commerce customer service robots
INSERT INTO public.industry_benchmarks (metric_name, industry_avg, industry_top, category, period) VALUES
  ('独立接待率', 65.0, 85.0, '接待效率', '2025Q4'),
  ('首次响应时间(秒)', 12.0, 3.0, '接待效率', '2025Q4'),
  ('平均响应时间(秒)', 45.0, 15.0, '接待效率', '2025Q4'),
  ('好评率', 82.0, 95.0, '满意度', '2025Q4'),
  ('差评率', 8.0, 2.0, '满意度', '2025Q4'),
  ('询单转化率', 28.0, 45.0, '转化', '2025Q4'),
  ('流失率', 35.0, 15.0, '转化', '2025Q4'),
  ('知识库命中率', 70.0, 90.0, '知识库', '2025Q4'),
  ('话术覆盖率', 60.0, 88.0, '话术配置', '2025Q4'),
  ('问题解决率', 72.0, 92.0, '服务质量', '2025Q4'),
  ('转人工率', 25.0, 8.0, '接待效率', '2025Q4'),
  ('客户复购率', 22.0, 40.0, '转化', '2025Q4'),
  ('响应满意度', 78.0, 93.0, '满意度', '2025Q4'),
  ('退货退款处理时长(小时)', 48.0, 12.0, '售后效率', '2025Q4'),
  ('工单关闭率', 85.0, 98.0, '售后效率', '2025Q4')
ON CONFLICT (id) DO NOTHING;

-- >>> supabase/migration-004-rbac-audit.sql
-- ============================================================================
-- Migration 004: RBAC roles + audit logs + dynamic platforms seed update
-- ============================================================================

-- ── User Roles ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'agent', 'viewer')),
  assigned_by UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (profile_id)
);

COMMENT ON TABLE user_roles IS 'RBAC role assignments for each profile';

-- ── Audit Logs ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  action TEXT NOT NULL,
  user_id UUID,
  user_name TEXT,
  resource_type TEXT,
  resource_id TEXT,
  detail JSONB,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);

COMMENT ON TABLE audit_logs IS 'Comprehensive audit log for auth, operations, AI calls, QA changes';

-- ── RLS for user_roles ───────────────────────────────────────────────────────
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Admins can manage roles" ON user_roles;
CREATE POLICY "Admins can manage roles" ON user_roles
  FOR ALL
  USING (EXISTS (
    SELECT 1 FROM user_roles ur
    WHERE ur.profile_id = auth.uid() AND ur.role = 'admin'
  ));

DROP POLICY IF EXISTS "Users can read own role" ON user_roles;
CREATE POLICY "Users can read own role" ON user_roles
  FOR SELECT
  USING (profile_id = auth.uid());

-- ── RLS for audit_logs ───────────────────────────────────────────────────────
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Admins can read all logs" ON audit_logs;
CREATE POLICY "Admins can read all logs" ON audit_logs
  FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM user_roles ur
    WHERE ur.profile_id = auth.uid() AND ur.role = 'admin'
  ));

DROP POLICY IF EXISTS "Operators can read team logs" ON audit_logs;
CREATE POLICY "Operators can read team logs" ON audit_logs
  FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM user_roles ur
    WHERE ur.profile_id = auth.uid() AND ur.role IN ('admin', 'operator')
  ));

-- ── Seed: assign admin role to first profile ─────────────────────────────────
INSERT INTO user_roles (profile_id, role)
SELECT id, 'admin'
FROM profiles
WHERE NOT EXISTS (SELECT 1 FROM user_roles)
LIMIT 1;

-- >>> supabase/migration-005-correction-samples.sql
-- ============================================================
-- Migration 005: Correction Samples + Few-Shot RPC
-- Enables dynamic Few-Shot learning: human corrections →
-- embedding → semantic retrieval → LLM prompt injection.
-- ============================================================

-- ── 1. 人工纠错样本库 (correction_samples) ──────────────────
CREATE TABLE IF NOT EXISTS correction_samples (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       UUID,
  conversation     TEXT NOT NULL,
  conversation_hash TEXT NOT NULL,
  ai_prediction    JSONB NOT NULL DEFAULT '{}',
  human_correction JSONB NOT NULL DEFAULT '{}',
  correction_type  TEXT NOT NULL DEFAULT 'risk_level',
  embedding        vector(1536),
  used_count       INT NOT NULL DEFAULT 0,
  last_used_at     TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correction_samples_hash ON correction_samples(conversation_hash);
CREATE INDEX IF NOT EXISTS idx_correction_samples_embedding
  ON correction_samples USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);
CREATE INDEX IF NOT EXISTS idx_correction_samples_type ON correction_samples(correction_type);

-- ── 2. RPC: 语义检索相似纠错案例 ────────────────────────────
CREATE OR REPLACE FUNCTION match_correction_samples(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.65,
  match_count int DEFAULT 3
)
RETURNS TABLE (
  id UUID,
  conversation TEXT,
  ai_prediction JSONB,
  human_correction JSONB,
  correction_type TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    cs.id,
    cs.conversation,
    cs.ai_prediction,
    cs.human_correction,
    cs.correction_type,
    1 - (cs.embedding <=> query_embedding) AS similarity
  FROM correction_samples cs
  WHERE 1 - (cs.embedding <=> query_embedding) >= match_threshold
  ORDER BY cs.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── 3. 更新 match_quality_rules 增加 threshold 过滤 ─────────
-- Drop old 2-param version to avoid overload ambiguity
DROP FUNCTION IF EXISTS match_quality_rules(vector(1536), int);
CREATE OR REPLACE FUNCTION match_quality_rules(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.6,
  match_count int DEFAULT 5
)
RETURNS TABLE (
  id BIGINT,
  category TEXT,
  rule_text TEXT,
  deduction_min INT,
  deduction_max INT,
  severity TEXT,
  examples TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    qr.id,
    qr.category,
    qr.rule_text,
    qr.deduction_min,
    qr.deduction_max,
    qr.severity,
    qr.examples,
    1 - (qr.embedding <=> query_embedding) AS similarity
  FROM quality_rules qr
  WHERE 1 - (qr.embedding <=> query_embedding) >= match_threshold
  ORDER BY qr.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- >>> supabase/migration-006-knowledge-loop.sql
-- ============================================================================
-- Migration 006: Knowledge Loop — effect tracking + review workflow
-- Adds gap_source_count, last_hit_at, hit_count to knowledge_entries
-- ============================================================================

-- 1. Add effect tracking columns to knowledge_entries
ALTER TABLE knowledge_entries
  ADD COLUMN IF NOT EXISTS gap_source_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS hit_count INT NOT NULL DEFAULT 0;

-- 2. Index for pending review queries
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_status ON knowledge_entries(status, created_at DESC);

-- 3. Update the match_knowledge_entries RPC to increment hit counters
--    (drop old version first to avoid overload conflict)
DROP FUNCTION IF EXISTS match_knowledge_entries(vector(1536), int);

CREATE OR REPLACE FUNCTION match_knowledge_entries(
  query_embedding vector(1536),
  match_count int DEFAULT 5
)
RETURNS TABLE(
  id uuid,
  category text,
  title text,
  content text,
  keywords text[],
  priority int,
  status text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  -- Increment hit counters for matched entries
  UPDATE knowledge_entries
  SET hit_count = COALESCE(hit_count, 0) + 1,
      last_hit_at = NOW()
  WHERE id IN (
    SELECT ke.id
    FROM knowledge_entries ke
    WHERE ke.status = 'published' AND ke.embedding IS NOT NULL
    ORDER BY ke.embedding <=> query_embedding
    LIMIT match_count
  );

  RETURN QUERY
  SELECT ke.id, ke.category, ke.title, ke.content, ke.keywords, ke.priority, ke.status,
         (1 - (ke.embedding <=> query_embedding))::float AS similarity
  FROM knowledge_entries ke
  WHERE ke.status = 'published' AND ke.embedding IS NOT NULL
  ORDER BY ke.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- >>> supabase/migration-007-effect-tracking.sql
-- ============================================================================
-- Migration 007: Bot Config Effect Tracking
-- Adds effect_metrics, source tracing, dedup index
-- ============================================================================

-- 1. Add effect_metrics JSONB column for pre/post publish comparison
ALTER TABLE bot_configs
  ADD COLUMN IF NOT EXISTS effect_metrics JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN bot_configs.effect_metrics IS 'Effect tracking: {pre_publish_satisfaction, post_publish_satisfaction, problem_session_count, resolved_count}';

-- 2. Add source tracing columns for audit trail
ALTER TABLE bot_configs
  ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'manual' CHECK (source_type IN ('manual', 'inspect_script', 'llm_suggest', 'bootstrap', 'knowledge_loop'));

ALTER TABLE bot_configs
  ADD COLUMN IF NOT EXISTS source_session_ids UUID[] DEFAULT '{}';

-- 3. Index for dedup queries (find existing drafts within 7 days)
CREATE INDEX IF NOT EXISTS idx_bot_configs_draft_dedup ON bot_configs(platform_id, config_key, status, created_at DESC);

-- 4. Function to snapshot satisfaction before publish
CREATE OR REPLACE FUNCTION snapshot_bot_config_effect(p_config_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
  v_platform_id UUID;
  v_config_sessions UUID[];
  v_avg_satisfaction NUMERIC;
  v_problem_count INT;
BEGIN
  SELECT platform_id INTO v_platform_id FROM bot_configs WHERE id = p_config_id;

  -- Find sessions linked to this config's platform that may be affected
  -- Uses the source_session_ids if available, otherwise platform-wide
  SELECT source_session_ids INTO v_config_sessions FROM bot_configs WHERE id = p_config_id;

  -- Calculate pre-publish satisfaction (7-day window)
  SELECT COALESCE(AVG(
    CASE satisfaction
      WHEN 'good' THEN 5
      WHEN 'neutral' THEN 3
      WHEN 'bad' THEN 1
    END
  ), 0)
  INTO v_avg_satisfaction
  FROM bot_chat_sessions
  WHERE platform_id = v_platform_id
    AND created_at >= NOW() - INTERVAL '7 days';

  -- Count recent problem sessions
  SELECT COUNT(*)
  INTO v_problem_count
  FROM bot_chat_sessions
  WHERE platform_id = v_platform_id
    AND (satisfaction = 'bad' OR bot_handled = false)
    AND created_at >= NOW() - INTERVAL '7 days';

  UPDATE bot_configs
  SET effect_metrics = jsonb_set(
        jsonb_set(
          jsonb_set(
            effect_metrics,
            '{pre_publish_satisfaction}', to_jsonb(v_avg_satisfaction)
          ),
          '{problem_session_count}', to_jsonb(v_problem_count)
        ),
        '{snapshot_at}', to_jsonb(NOW()::text)
      )
  WHERE id = p_config_id;
END;
$$;

-- >>> supabase/migration-008-knowledge-effect-tracking.sql
-- ============================================================================
-- Migration 008: Knowledge Entry Effect Tracking
-- Adds effect_metrics JSONB to knowledge_entries for auto-publish parity
-- ============================================================================

-- 1. Add effect_metrics JSONB column
ALTER TABLE knowledge_entries
  ADD COLUMN IF NOT EXISTS effect_metrics JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN knowledge_entries.effect_metrics IS 'Effect tracking: {llm_confidence, auto_published, dedup_skipped}';

-- 2. Index for dedup queries (find existing drafts within 7 days)
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_draft_dedup ON knowledge_entries(source, title, status, created_at DESC);

-- >>> supabase/migration-008-state-machine-compat.sql
-- Forward-only compatibility migration for the Feishu pipeline state machine.
-- This is intentionally explicit because the historical 008 file can be
-- skipped by a fresh-project runner when its base pipeline tables are absent.

CREATE TABLE IF NOT EXISTS public.execution_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_job_id UUID REFERENCES public.pipeline_jobs(id) ON DELETE CASCADE,
  step_name TEXT NOT NULL,
  step_order INT NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'PENDING',
  suspend_reason TEXT,
  step_input JSONB,
  step_output JSONB,
  resume_token TEXT,
  error TEXT,
  timeout_at TIMESTAMPTZ,
  retry_count INT DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_steps_job
  ON public.execution_steps(pipeline_job_id, step_order);
CREATE INDEX IF NOT EXISTS idx_execution_steps_status
  ON public.execution_steps(status, timeout_at);

ALTER TABLE public.pipeline_jobs
  ADD COLUMN IF NOT EXISTS current_step_id UUID REFERENCES public.execution_steps(id),
  ADD COLUMN IF NOT EXISTS suspend_reason TEXT,
  ADD COLUMN IF NOT EXISTS timeout_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.feishu_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id TEXT NOT NULL,
  chat_id TEXT,
  message_type TEXT DEFAULT 'interactive',
  content JSONB,
  related_task_id UUID,
  related_step_id UUID REFERENCES public.execution_steps(id),
  status TEXT DEFAULT 'sent',
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_feishu_messages_task
  ON public.feishu_messages(related_task_id);
CREATE INDEX IF NOT EXISTS idx_feishu_messages_step
  ON public.feishu_messages(related_step_id);

CREATE OR REPLACE FUNCTION public.feishuflow_scan_suspended()
RETURNS TABLE(step_id UUID, action_taken TEXT, job_id UUID)
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT es.id, es.status, es.pipeline_job_id, es.retry_count
    FROM public.execution_steps AS es
    WHERE es.status IN ('SUSPENDED_ASR', 'SUSPENDED_HITL')
      AND es.timeout_at IS NOT NULL
      AND es.timeout_at <= NOW()
    ORDER BY es.timeout_at ASC
    LIMIT 50
  LOOP
    IF rec.status = 'SUSPENDED_ASR' AND rec.retry_count < 3 THEN
      UPDATE public.execution_steps
      SET status = 'PENDING', retry_count = rec.retry_count + 1,
          timeout_at = NOW() + INTERVAL '5 minutes'
      WHERE id = rec.id;
      UPDATE public.pipeline_jobs
      SET status = 'PROCESSING', suspend_reason = NULL, timeout_at = NULL,
          updated_at = NOW()
      WHERE id = rec.pipeline_job_id;
      RETURN QUERY SELECT rec.id, 'retry_asr'::TEXT, rec.pipeline_job_id;
    ELSE
      UPDATE public.execution_steps
      SET status = 'FAILED', error = CASE WHEN rec.status = 'SUSPENDED_ASR'
          THEN 'ASR retry exhausted after 3 attempts' ELSE 'HITL timeout (30min)' END,
          completed_at = NOW()
      WHERE id = rec.id;
      UPDATE public.pipeline_jobs
      SET status = 'FAILED', error = CASE WHEN rec.status = 'SUSPENDED_ASR'
          THEN 'ASR retry exhausted' ELSE 'HITL timeout' END,
          suspend_reason = CASE WHEN rec.status = 'SUSPENDED_ASR'
            THEN suspend_reason ELSE 'hitl_timeout' END,
          updated_at = NOW()
      WHERE id = rec.pipeline_job_id;
      RETURN QUERY SELECT rec.id,
        CASE WHEN rec.status = 'SUSPENDED_ASR' THEN 'mark_dead_asr' ELSE 'mark_failed_hitl' END,
        rec.pipeline_job_id;
    END IF;
  END LOOP;
END;
$$;

-- >>> supabase/migration-009-compliance.sql
-- ============================================================================
-- Migration 009: Compliance Engine — 4-level risk prevention system
-- Covers: Advertising Law 34 prohibitions + e-commerce platform banned terms
-- Risk levels: fatal (1) / high (2) / medium (3) / low (4)
-- ============================================================================

-- 1. Compliance rules table
CREATE TABLE IF NOT EXISTS compliance_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_text       TEXT NOT NULL,
    pattern         TEXT NOT NULL,              -- regex pattern for matching
    risk_level      INT NOT NULL CHECK (risk_level BETWEEN 1 AND 4),
    category        TEXT NOT NULL CHECK (category IN (
        'advertising_law',     -- 广告法禁令
        'absolute_claim',      -- 绝对化用语
        'false_promise',       -- 虚假承诺
        'platform_rule',       -- 平台规则
        'competitor_mention',  -- 竞品提及
        'tone_violation',      -- 语气不当
        'sensitive_word'       -- 通用敏感词
    )),
    action_type     TEXT NOT NULL DEFAULT 'block' CHECK (action_type IN ('block', 'warn', 'flag')),
    description     TEXT,
    exemption_tags  TEXT[] DEFAULT '{}',        -- 豁免场景标签
    is_active       BOOLEAN NOT NULL DEFAULT true,
    match_count     INT NOT NULL DEFAULT 0,     -- times this rule matched
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_risk ON compliance_rules(risk_level, is_active);
CREATE INDEX IF NOT EXISTS idx_compliance_category ON compliance_rules(category);

-- 2. Compliance audit log
CREATE TABLE IF NOT EXISTS compliance_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('knowledge_entry', 'bot_config', 'chat_message')),
    source_id       UUID,
    content_snippet TEXT NOT NULL,              -- first 200 chars of checked content
    risk_level      INT,                       -- highest risk level found
    matched_rules   JSONB DEFAULT '[]',         -- [{rule_id, rule_text, category, action}]
    decision        TEXT NOT NULL CHECK (decision IN ('blocked', 'flagged', 'passed')),
    reviewed_by     UUID REFERENCES profiles(id),
    review_notes    TEXT,
    correlation_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_logs_source ON compliance_audit_logs(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_compliance_logs_decision ON compliance_audit_logs(decision, created_at DESC);

-- 3. Seed data: Advertising Law + e-commerce forbidden terms

-- === FATAL (risk_level=1): Advertising Law absolute prohibitions ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    -- Art.9: 使用或变相使用国旗、国徽等
    ('禁止使用国家级/最高级/最佳等绝对化用语', '国家级|最高级|最佳|最优|第一品牌|独一无二|顶级|极品|全网第一|全球第一|全国第一|万能|全能', 1, 'absolute_claim', 'block', '广告法第9条：禁止使用绝对化用语'),
    ('禁止使用国家标志或暗示国家背书', '国宴|国宾|人民大会堂|国务院|中南海|中央军委|国家免检|国家推荐', 1, 'advertising_law', 'block', '广告法第9条：禁止使用或变相使用国家机关名义'),
    ('禁止声称治愈率或有效率', '治愈率|有效率|根治|药到病除|永不复发|彻底治愈|无任何副作用|100%有效|纯天然无添加', 1, 'advertising_law', 'block', '广告法第16条：禁止含有表示功效的安全性的断言或保证'),
    ('禁止声称疾病预防/治疗功能（非药品）', '治疗|预防疾病|抗癌|防癌|抑制肿瘤|降血压|降血糖|降血脂|排毒|消炎|抗菌|抑菌', 1, 'advertising_law', 'block', '广告法第17条：除药品/医疗器械外禁止声称疾病治疗功能'),
    ('禁止虚假或引人误解的宣传', '假一赔万|假一赔命|假一赔十亿|绝不|永不|永久有效|终身保修|终身免费|万无一失', 1, 'false_promise', 'block', '广告法第28条：禁止虚假或引人误解的宣传'),
    ('禁止损害国家尊严或社会公共利益', '台独|港独|藏独|疆独|法轮功|邪教|分裂', 1, 'advertising_law', 'block', '广告法第9条：禁止危害国家统一和社会稳定'),
    ('禁止使用"最"字类极限用语', '(?<![不没无])最[高低大小好坏多少强弱快慢新老远近长短轻重](?!于|的|程度|范围|限度)', 1, 'absolute_claim', 'block', '广告法第9条：禁止使用极限用语（含"最X"结构）'),
    ('禁止使用"第一"类排他性用语', '行业第一|销量第一|口碑第一|服务第一|品质第一|市场第一|中国第一|世界第一|全球首发|全国首发|独家首发', 1, 'absolute_claim', 'block', '广告法第9条：禁止排他性绝对化表述')
ON CONFLICT DO NOTHING;

-- === HIGH (risk_level=2): False promises & misleading claims ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('禁止虚假承诺美容/减肥效果', '立刻见效|瞬间|立即变|马上白|秒变|一喷即白|一抹即白|永不反弹|绝不反弹|躺着瘦|不运动也能瘦', 2, 'false_promise', 'block', '禁止对美容/减肥等效果进行虚假承诺'),
    ('禁止虚假承诺投资理财收益', '稳赚不赔|保本保息|零风险|高收益|年化率|日息|月息|本金保障|收益翻倍|一夜暴富', 2, 'false_promise', 'block', '禁止对金融产品收益进行承诺性宣传'),
    ('禁止虚假承诺教育培训效果', '包过|保过|包拿证|包录取|包就业|包分配|一次通过|100%通过|签证必过|政审必过', 2, 'false_promise', 'block', '禁止对教育/培训效果做出明示或暗示的保证性承诺'),
    ('禁止贬低其他生产经营者', '比.*好[得多百倍千倍万倍]|远超|秒杀|吊打|完胜|碾压|甩.*几条街|别人.*不行|其他.*不如|只有我们', 2, 'competitor_mention', 'block', '广告法第13条：禁止贬低其他生产经营者的商品或服务'),
    ('禁止违规比较广告', '比.*便宜|比.*优惠|价格最低|全网最低价|历史最低|跌破底价|亏本|血亏|赔本', 2, 'platform_rule', 'warn', '各平台禁止未经证实的比较广告和最低价宣称')
ON CONFLICT DO NOTHING;

-- === MEDIUM (risk_level=3): Platform-specific & sensitive content ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('禁止诱导点击/虚假诱导文案', '点击领取|免费领取|点击抽奖|点击有惊喜|不点就亏了|点开有惊喜|马上抢|疯狂抢购', 3, 'platform_rule', 'warn', '各平台禁止虚假诱导点击行为'),
    ('禁止在非授权情况下使用平台名义', '天猫认证|京东认证|官方授权(?!书|牌|证|文件)|平台推荐(?!商品|好物)', 3, 'platform_rule', 'warn', '禁止未经授权使用平台名义进行宣传'),
    ('禁止使用禁用营销词', '最后一天|仅此一天|限时抢购|秒杀(?!活动|专区|价)|清仓|倒闭|破产|跑路|老板哭了|老板疯了|挥泪|跳楼价', 3, 'platform_rule', 'flag', '平台管控禁用营销用语'),
    ('竞品平台提及检测', '天猫(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|优品|会员|积分|优惠|活动|双1|6|年货)|京东(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|自营|会员|PLUS|物流|快递|优品|优惠|活动|618|年货)|拼多多(?!店|店铺|官方|客服|平台)|抖音(?!店|店铺|官方|客服|平台|商城|直播)|小红书(?!店|店铺|官方|客服|平台|商城)', 3, 'competitor_mention', 'flag', '提及竞品平台需上下文审核'),
    ('敏感话题检测', '政治|宗教|种族|性别歧视|地域歧视|色情|暴力|赌博|毒品|枪支|弹药', 3, 'sensitive_word', 'block', '禁止涉及敏感话题和政治相关内容')
ON CONFLICT DO NOTHING;

-- === LOW (risk_level=4): Tone & style suggestions ===
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('多处感叹号可能令客户感到压迫', '[！!]{2,}', 4, 'tone_violation', 'flag', '多个感叹号连续使用会让客户感到压迫感'),
    ('连续问号可能显得不耐烦', '[？?]{3,}', 4, 'tone_violation', 'flag', '连续问号可能传达不耐烦的情绪'),
    ('全大写英文可能被视为咆哮', '\\b[A-Z]{8,}\\b', 4, 'tone_violation', 'flag', '全大写英文在客服沟通中可能被视为不友好'),
    ('建议避免使用粗俗/不文明用语', '傻逼|脑残|废物|笨蛋|蠢|垃圾(?!分类|桶|短信|邮件|文件|清理|广告|信息|数据|内容)', 4, 'tone_violation', 'warn', '客服沟通中应避免粗俗用语')
ON CONFLICT DO NOTHING;

-- 4. RLS
ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Compliance rules readable by all authenticated" ON compliance_rules FOR SELECT USING (true);
CREATE POLICY "Compliance audit logs readable by all authenticated" ON compliance_audit_logs FOR SELECT USING (true);

-- >>> supabase/migration-010-system-config.sql
-- ============================================================================
-- Migration 010: System Runtime Configuration
-- Enables online adjustment of key thresholds without redeployment
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key  TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    value_type  TEXT NOT NULL DEFAULT 'string' CHECK (value_type IN ('string', 'number', 'boolean', 'json')),
    description TEXT,
    category    TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa')),
    updated_by  UUID REFERENCES profiles(id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_system_configs_category ON system_configs(category);

-- Seed data: current hardcoded defaults
INSERT INTO system_configs (config_key, config_value, value_type, description, category) VALUES
    ('auto_publish_threshold', '0.95', 'number', 'Minimum LLM confidence for auto-publish (0-1)', 'auto_publish'),
    ('auto_publish_max_change_length', '50', 'number', 'Maximum change description length for auto-publish', 'auto_publish'),
    ('feishu_timeout_ms', '10000', 'number', 'Feishu API request timeout in milliseconds', 'feishu'),
    ('feishu_retry_count', '3', 'number', 'Number of retries for Feishu dispatch', 'feishu'),
    ('feishu_night_window_start', '22', 'number', 'Night window start hour (0-23), suppress non-critical alerts', 'feishu'),
    ('feishu_night_window_end', '8', 'number', 'Night window end hour (0-23)', 'feishu'),
    ('llm_rate_limit_per_minute', '30', 'number', 'LLM API rate limit (calls per minute)', 'llm'),
    ('llm_cache_ttl_hours', '24', 'number', 'LLM result cache TTL in hours', 'llm'),
    ('llm_max_retries', '3', 'number', 'LLM API retry count', 'llm'),
    ('knowledge_gap_similarity_threshold', '0.15', 'number', 'Minimum similarity to consider a knowledge match (0-1)', 'qa'),
    ('qa_kappa_alert_threshold', '0.4', 'number', 'Cohen Kappa below this triggers alert', 'qa'),
    ('compliance_auto_block_threshold', '2', 'number', 'Auto-block when compliance risk level <= this value', 'compliance'),
    ('dedup_window_days', '7', 'number', 'Deduplication window in days for auto-generated content', 'general')
ON CONFLICT (config_key) DO NOTHING;

-- RLS
ALTER TABLE system_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "System configs readable by all authenticated" ON system_configs FOR SELECT USING (true);

-- >>> supabase/migration-011-intent-accuracy.sql
-- ============================================================================
-- Migration 011: Intent Recognition Accuracy Tracking
-- Enables monitoring of intent recognition accuracy with 99.8% target
-- ============================================================================

CREATE TABLE IF NOT EXISTS intent_accuracy_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     UUID REFERENCES platforms(id),
    period_date     DATE NOT NULL,
    total_recognitions  INT NOT NULL DEFAULT 0,
    correct_recognitions INT NOT NULL DEFAULT 0,
    incorrect_recognitions INT NOT NULL DEFAULT 0,
    accuracy        NUMERIC(5,4) NOT NULL DEFAULT 0, -- e.g. 0.9980 = 99.80%
    coverage_rate   NUMERIC(5,4),  -- % of user questions matched to an intent
    target_met      BOOLEAN NOT NULL DEFAULT false, -- accuracy >= 0.998
    bad_case_ids    UUID[] DEFAULT '{}',
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, period_date)
);

CREATE INDEX IF NOT EXISTS idx_intent_accuracy_date ON intent_accuracy_logs(period_date DESC);
CREATE INDEX IF NOT EXISTS idx_intent_accuracy_target ON intent_accuracy_logs(target_met, period_date DESC);

-- Alert threshold config: accuracy < 0.99 triggers Feishu alert (stored in system_configs)
ALTER TABLE intent_accuracy_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Intent accuracy readable by all authenticated" ON intent_accuracy_logs FOR SELECT USING (true);

-- >>> supabase/migration-011-platform-credentials-compat.sql
-- Forward-only PostgreSQL 17 compatible replacement for migration-011-platform-credentials.sql.
-- The published migration used BIGINT for platform_id although platforms.id is UUID.

ALTER TABLE public.platforms
  ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}';

CREATE TABLE IF NOT EXISTS public.platform_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform_id UUID NOT NULL REFERENCES public.platforms(id) ON DELETE CASCADE,
  credential_key TEXT NOT NULL,
  credential_value TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(platform_id, credential_key)
);

CREATE INDEX IF NOT EXISTS idx_platform_creds_lookup
  ON public.platform_credentials(platform_id, credential_key);

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'oauth2',
  'auth_url', 'https://oauth.taobao.com/authorize',
  'token_url', 'https://oauth.taobao.com/token',
  'api_base_url', 'https://eco.taobao.com/router/rest',
  'webhook_verify_method', 'md5',
  'timeout_ms', 5000,
  'rate_limit_per_minute', 60
) WHERE code = 'tmall';

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'oauth2',
  'timeout_ms', 5000,
  'webhook_verify_method', 'sha256'
) WHERE code = 'jd';

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'oauth2',
  'timeout_ms', 2000,
  'webhook_verify_method', 'md5'
) WHERE code = 'douyin';

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'websocket',
  'timeout_ms', 10000,
  'webhook_verify_method', 'hmac'
) WHERE code = 'pdd';

ALTER TABLE public.system_configs DROP CONSTRAINT IF EXISTS system_configs_category_check;
ALTER TABLE public.system_configs ADD CONSTRAINT system_configs_category_check
  CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa', 'platform'));

INSERT INTO public.system_configs (config_key, config_value, value_type, description, category)
VALUES
  ('tmall_reply_enabled', 'false', 'boolean', 'Enable real reply dispatch to Tmall', 'platform'),
  ('tmall_reply_ratio', '0.1', 'number', 'Tmall reply traffic ratio (0-1)', 'platform'),
  ('tmall_circuit_error_rate', '0.05', 'number', 'Tmall circuit breaker error rate threshold', 'platform'),
  ('tmall_circuit_cooldown_seconds', '300', 'number', 'Tmall circuit breaker cooldown in seconds', 'platform')
ON CONFLICT (config_key) DO NOTHING;

-- >>> supabase/migration-011-platform-credentials.sql
-- ============================================================================
-- Migration 011: Platform Credentials & Multi-Platform Adapter Support
-- Supabase SQL Editor compatible (no DO $$ blocks)
-- Safe to re-run: all operations are idempotent
-- ============================================================================

-- 1. Add config JSONB column to platforms (stores platform-specific settings)
ALTER TABLE platforms ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}';

-- 2. Create platform_credentials table for OAuth tokens / API keys
CREATE TABLE IF NOT EXISTS platform_credentials (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id      BIGINT NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
    credential_key   TEXT NOT NULL,
    credential_value TEXT NOT NULL,
    expires_at       TIMESTAMPTZ,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, credential_key)
);

COMMENT ON TABLE platform_credentials IS 'OAuth tokens and API keys per platform. credential_value should be encrypted at rest in production.';
COMMENT ON COLUMN platform_credentials.credential_key IS 'e.g. access_token, refresh_token, app_key, app_secret, sign_key';
COMMENT ON COLUMN platform_credentials.metadata IS 'Extra fields: seller_nick, shop_id, scope, etc.';

-- Index for fast token lookup by platform + key
CREATE INDEX IF NOT EXISTS idx_platform_creds_lookup
    ON platform_credentials(platform_id, credential_key);

-- 3. Seed platform configs for e-commerce platforms
UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'oauth2',
    'auth_url', 'https://oauth.taobao.com/authorize',
    'token_url', 'https://oauth.taobao.com/token',
    'api_base_url', 'https://eco.taobao.com/router/rest',
    'webhook_verify_method', 'md5',
    'timeout_ms', 5000,
    'rate_limit_per_minute', 60
) WHERE code = 'tmall';

UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'oauth2',
    'timeout_ms', 5000,
    'webhook_verify_method', 'sha256'
) WHERE code = 'jd';

UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'oauth2',
    'timeout_ms', 2000,
    'webhook_verify_method', 'md5'
) WHERE code = 'douyin';

UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'websocket',
    'timeout_ms', 10000,
    'webhook_verify_method', 'hmac'
) WHERE code = 'pdd';

-- 4. Add platform category to system_configs CHECK constraint
ALTER TABLE system_configs DROP CONSTRAINT IF EXISTS system_configs_category_check;
ALTER TABLE system_configs ADD CONSTRAINT system_configs_category_check
    CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa', 'platform'));

-- 5. Seed platform-specific system_configs for traffic gating
INSERT INTO system_configs (config_key, config_value, value_type, description, category)
VALUES
    ('tmall_reply_enabled', 'false', 'boolean', 'Enable real reply dispatch to Tmall', 'platform'),
    ('tmall_reply_ratio', '0.1', 'number', 'Tmall reply traffic ratio (0-1)', 'platform'),
    ('tmall_circuit_error_rate', '0.05', 'number', 'Tmall circuit breaker error rate threshold', 'platform'),
    ('tmall_circuit_cooldown_seconds', '300', 'number', 'Tmall circuit breaker cooldown in seconds', 'platform')
ON CONFLICT (config_key) DO NOTHING;

-- >>> supabase/migration-012-shadow-replies.sql
-- ============================================================================
-- Migration 012: Shadow Replies — store generated-but-not-sent replies
-- Tracks LLM latency, fallback rate, gate decisions for gradual rollout.
-- Safe to re-run: all operations are idempotent.
-- ============================================================================

-- 1. Create shadow_replies table
CREATE TABLE IF NOT EXISTS shadow_replies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     TEXT NOT NULL,  -- maps to platforms.code or platforms.id
    session_id      TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    customer_id     TEXT,
    original_text   TEXT NOT NULL,
    generated_reply TEXT NOT NULL,
    reply_mode      TEXT NOT NULL DEFAULT 'shadow',   -- shadow | gradual | full
    llm_latency_ms  INTEGER,
    was_fallback    BOOLEAN DEFAULT false,
    cached          BOOLEAN DEFAULT false,
    gate_reason     TEXT,
    gate_tier       TEXT,
    quality_score   REAL,                              -- post-hoc QA score (Phase 3)
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE shadow_replies IS 'LLM replies generated but NOT sent to the platform. Used for quality validation before Phase 3 gradual rollout.';
COMMENT ON COLUMN shadow_replies.reply_mode IS 'shadow = never sent, gradual = sampled send, full = always send';
COMMENT ON COLUMN shadow_replies.gate_reason IS 'Why the gate allowed (or would have allowed) this reply: whitelist_match, simple_question_match, traffic_ratio_hit';
COMMENT ON COLUMN shadow_replies.gate_tier IS 'Gate tier at time of generation: off, whitelist, simple_questions, ratio';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_shadow_replies_session
    ON shadow_replies(session_id);
CREATE INDEX IF NOT EXISTS idx_shadow_replies_platform_date
    ON shadow_replies(platform_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_replies_message_id
    ON shadow_replies(message_id);

-- 2. Shadow configs are set via env vars (SHADOW_REPLY_ENABLED, SHADOW_REPLY_TIER, etc.)
--    Daily quota defaults to 1000 if tmall_shadow_daily_quota is not in system_configs.

-- >>> supabase/migration-012-work-orders.sql
-- ============================================================================
-- Migration 012: Work Orders — auto-generated from QA + Feishu integration
-- Critical QA findings → actionable work orders with status tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS work_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('qa_evaluate', 'compliance_block', 'inspection', 'manual', 'cron')),
    source_id       UUID,                        -- e.g. quality_report id, compliance_audit_log id
    priority        TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    category        TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'compliance', 'script_fix', 'knowledge_gap', 'customer_complaint', 'system_issue')),
    platform_id     UUID REFERENCES platforms(id),
    assigned_to     UUID REFERENCES profiles(id),
    resolved_by     UUID REFERENCES profiles(id),
    resolution      TEXT,
    feishu_message_id TEXT,                       -- Feishu message ID for in-Feishu processing
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status, priority);
CREATE INDEX IF NOT EXISTS idx_work_orders_source ON work_orders(source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_orders_assigned ON work_orders(assigned_to) WHERE status NOT IN ('resolved', 'closed');

-- Work order action log for audit trail
CREATE TABLE IF NOT EXISTS work_order_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id   UUID NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('created', 'assigned', 'in_progress', 'resolved', 'closed', 'reopened', 'commented')),
    comment         TEXT,
    performed_by    UUID REFERENCES profiles(id),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wo_actions_order ON work_order_actions(work_order_id, created_at DESC);

-- RLS
ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_order_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Work orders readable by all authenticated" ON work_orders FOR SELECT USING (true);
CREATE POLICY "Work order actions readable by all authenticated" ON work_order_actions FOR SELECT USING (true);

-- Auto-create function: generate work order from critical QA result
CREATE OR REPLACE FUNCTION auto_create_work_order(
    p_title TEXT,
    p_description TEXT,
    p_source TEXT,
    p_source_id UUID,
    p_priority TEXT,
    p_category TEXT DEFAULT 'general'
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO work_orders (title, description, source, source_id, priority, category)
    VALUES (p_title, p_description, p_source, p_source_id, p_priority, p_category)
    RETURNING id INTO v_id;

    INSERT INTO work_order_actions (work_order_id, action, metadata)
    VALUES (v_id, 'created', jsonb_build_object('auto_generated', true, 'source', p_source));

    RETURN v_id;
END;
$$;

-- >>> supabase/migration-013-payment-reminders.sql
-- ============================================================================
-- Migration 013: Smart Payment Reminder System
-- Auto-identify unpaid orders, generate personalized reminders, track conversion
-- ============================================================================

CREATE TABLE IF NOT EXISTS pending_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_order_id TEXT NOT NULL,
    platform_id     UUID REFERENCES platforms(id),
    customer_id     TEXT,
    customer_name   TEXT,
    product_name    TEXT,
    order_amount    NUMERIC(10,2),
    order_status    TEXT NOT NULL DEFAULT 'pending_payment' CHECK (order_status IN ('pending_payment', 'reminded', 'paid', 'cancelled', 'expired')),
    created_at_order TIMESTAMPTZ NOT NULL,
    expire_at       TIMESTAMPTZ,                  -- order expiry deadline
    metadata        JSONB DEFAULT '{}',           -- raw order data
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_orders_external ON pending_orders(external_order_id, platform_id);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(order_status, expire_at);

CREATE TABLE IF NOT EXISTS payment_reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES pending_orders(id) ON DELETE CASCADE,
    round           INT NOT NULL DEFAULT 1,        -- 1st, 2nd, 3rd reminder
    script          TEXT NOT NULL,                 -- LLM-generated reminder script
    channel         TEXT NOT NULL DEFAULT 'bot' CHECK (channel IN ('bot', 'sms', 'feishu', 'app_push')),
    status          TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('pending', 'sent', 'delivered', 'failed', 'converted')),
    sent_at         TIMESTAMPTZ,
    converted_at    TIMESTAMPTZ,
    response        TEXT,                          -- customer response if any
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reminders_order ON payment_reminders(order_id, round);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON payment_reminders(status, sent_at DESC);

-- RLS
ALTER TABLE pending_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reminders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Pending orders readable by all authenticated" ON pending_orders FOR SELECT USING (true);
CREATE POLICY "Payment reminders readable by all authenticated" ON payment_reminders FOR SELECT USING (true);

-- Seed: system config entries for payment reminder
INSERT INTO system_configs (config_key, config_value, value_type, description, category) VALUES
    ('payment_reminder_max_rounds', '3', 'number', 'Maximum reminder rounds per order', 'general'),
    ('payment_reminder_interval_hours', '24', 'number', 'Hours between reminder rounds', 'general'),
    ('payment_reminder_first_delay_minutes', '30', 'number', 'Minutes after order before first reminder', 'general')
ON CONFLICT (config_key) DO NOTHING;

-- >>> supabase/migration-013-personality-engine-compat.sql
-- Forward-only compatibility migration for the current system_configs schema.
-- The historical personality migration targets a different key/value schema.

ALTER TABLE public.knowledge_entries
  ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'professional';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.knowledge_entries'::regclass
      AND conname = 'knowledge_entries_tone_check'
  ) THEN
    ALTER TABLE public.knowledge_entries
      ADD CONSTRAINT knowledge_entries_tone_check
      CHECK (tone IN ('professional', 'friendly', 'concise'));
  END IF;
END
$$;

INSERT INTO public.system_configs (config_key, config_value, value_type, description, category)
VALUES
  ('style_professional', '{"name":"专业严谨","prompt_inject":"请使用正式、专业的语气回复。使用完整句子，避免口语化表达。必要时引用数据来源。","greeting":"您好，我是AI客服助手，请问有什么可以帮您？"}', 'json', '人格引擎-专业严谨风格模板', 'general'),
  ('style_friendly', '{"name":"亲切活泼","prompt_inject":"请使用亲切、温暖的语气回复。可以适当使用表情符号，让对话更自然。像朋友一样交流，但保持专业度。","greeting":"嗨～有什么可以帮你的呀？"}', 'json', '人格引擎-亲切活泼风格模板', 'general'),
  ('style_concise', '{"name":"简洁高效","prompt_inject":"请用最简洁的方式回复。直接给出答案，不添加多余解释。用短句，每条回复控制在3行以内。","greeting":"你好，请说。"}', 'json', '人格引擎-简洁高效风格模板', 'general')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    value_type = EXCLUDED.value_type,
    description = EXCLUDED.description,
    category = EXCLUDED.category;

-- >>> supabase/migration-013-real-replies.sql
-- ============================================================================
-- Migration 013: Real Reply Infrastructure
-- actual_replies table + store-level circuit breaker configs.
-- Safe to re-run: all operations are idempotent.
-- ============================================================================

-- 1. Create actual_replies table (tracks replies actually sent to platforms)
CREATE TABLE IF NOT EXISTS actual_replies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    customer_id     TEXT,
    original_text   TEXT NOT NULL,
    generated_reply TEXT NOT NULL,
    sanitized_reply TEXT NOT NULL,              -- after compliance guard (with prefix)
    reply_mode      TEXT NOT NULL DEFAULT 'gradual',  -- gradual | full
    llm_latency_ms  INTEGER,
    was_fallback    BOOLEAN DEFAULT false,
    compliance_safe BOOLEAN NOT NULL DEFAULT true,
    compliance_block_reason TEXT,
    sent_success    BOOLEAN DEFAULT false,      -- did the platform API accept it?
    sent_at         TIMESTAMPTZ,
    platform_msg_id TEXT,                       -- platform-assigned message ID
    quality_score   REAL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE actual_replies IS 'Replies actually sent to platforms via API. Separate from shadow_replies for audit dual-track.';

CREATE INDEX IF NOT EXISTS idx_actual_replies_session
    ON actual_replies(session_id);
CREATE INDEX IF NOT EXISTS idx_actual_replies_platform_date
    ON actual_replies(platform_id, created_at DESC);

-- 2. Store-level circuit breaker configs are read from system_configs / env vars.
--    Defaults (safe, fail-closed):
--      tmall_real_reply_stores = "{}" (no stores enabled)
--      tmall_require_human_approval = "true" (all replies need approval)
--      tmall_human_approval_threshold = "100"
--    If your system_configs table exists, insert these manually or via the UI.

-- >>> supabase/migration-014-production-deploy.sql
-- ============================================================================
-- Migration 014: Production Deploy — Combined Phase 1/2 Schema
-- Run this in Supabase SQL Editor to create all missing tables at once.
-- All tables use IF NOT EXISTS — safe to re-run.
-- ============================================================================

-- ============================================================================
-- PART 1: Compliance Engine (from migration-009)
-- ============================================================================

CREATE TABLE IF NOT EXISTS compliance_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_text       TEXT NOT NULL,
    pattern         TEXT NOT NULL,
    risk_level      INT NOT NULL CHECK (risk_level BETWEEN 1 AND 4),
    category        TEXT NOT NULL CHECK (category IN (
        'advertising_law', 'absolute_claim', 'false_promise',
        'platform_rule', 'competitor_mention', 'tone_violation', 'sensitive_word'
    )),
    action_type     TEXT NOT NULL DEFAULT 'block' CHECK (action_type IN ('block', 'warn', 'flag')),
    description     TEXT,
    exemption_tags  TEXT[] DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    match_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_risk ON compliance_rules(risk_level, is_active);
CREATE INDEX IF NOT EXISTS idx_compliance_category ON compliance_rules(category);

CREATE TABLE IF NOT EXISTS compliance_audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('knowledge_entry', 'bot_config', 'chat_message')),
    source_id       UUID,
    content_snippet TEXT NOT NULL,
    risk_level      INT,
    matched_rules   JSONB DEFAULT '[]',
    decision        TEXT NOT NULL CHECK (decision IN ('blocked', 'flagged', 'passed')),
    reviewed_by     UUID,
    review_notes    TEXT,
    correlation_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_logs_source ON compliance_audit_logs(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_compliance_logs_decision ON compliance_audit_logs(decision, created_at DESC);

-- Seed compliance rules (Advertising Law 34 prohibitions + platform terms)
INSERT INTO compliance_rules (rule_text, pattern, risk_level, category, action_type, description) VALUES
    ('禁止使用国家级/最高级/最佳等绝对化用语', '国家级|最高级|最佳|最优|第一品牌|独一无二|顶级|极品|全网第一|全球第一|全国第一|万能|全能', 1, 'absolute_claim', 'block', '广告法第9条'),
    ('禁止使用国家标志或暗示国家背书', '国宴|国宾|人民大会堂|国务院|中南海|中央军委|国家免检|国家推荐', 1, 'advertising_law', 'block', '广告法第9条'),
    ('禁止声称治愈率或有效率', '治愈率|有效率|根治|药到病除|永不复发|彻底治愈|无任何副作用|100%有效|纯天然无添加', 1, 'advertising_law', 'block', '广告法第16条'),
    ('禁止声称疾病预防/治疗功能（非药品）', '治疗|预防疾病|抗癌|防癌|抑制肿瘤|降血压|降血糖|降血脂|排毒|消炎|抗菌|抑菌', 1, 'advertising_law', 'block', '广告法第17条'),
    ('禁止虚假或引人误解的宣传', '假一赔万|假一赔命|假一赔十亿|绝不|永不|永久有效|终身保修|终身免费|万无一失', 1, 'false_promise', 'block', '广告法第28条'),
    ('禁止损害国家尊严或社会公共利益', '台独|港独|藏独|疆独|法轮功|邪教|分裂', 1, 'advertising_law', 'block', '广告法第9条'),
    ('禁止使用"最"字类极限用语', '(?<![不没无])最[高低大小好坏多少强弱快慢新老远近长短轻重](?!于|的|程度|范围|限度)', 1, 'absolute_claim', 'block', '广告法第9条'),
    ('禁止使用"第一"类排他性用语', '行业第一|销量第一|口碑第一|服务第一|品质第一|市场第一|中国第一|世界第一|全球首发|全国首发|独家首发', 1, 'absolute_claim', 'block', '广告法第9条'),
    ('禁止虚假承诺美容/减肥效果', '立刻见效|瞬间|立即变|马上白|秒变|一喷即白|一抹即白|永不反弹|绝不反弹|躺着瘦|不运动也能瘦', 2, 'false_promise', 'block', '禁止美容/减肥虚假承诺'),
    ('禁止虚假承诺投资理财收益', '稳赚不赔|保本保息|零风险|高收益|年化率|日息|月息|本金保障|收益翻倍|一夜暴富', 2, 'false_promise', 'block', '禁止金融产品收益承诺'),
    ('禁止虚假承诺教育培训效果', '包过|保过|包拿证|包录取|包就业|包分配|一次通过|100%通过|签证必过|政审必过', 2, 'false_promise', 'block', '禁止教育/培训效果承诺'),
    ('禁止贬低其他生产经营者', '比.*好[得多百倍千倍万倍]|远超|秒杀|吊打|完胜|碾压|甩.*几条街|别人.*不行|其他.*不如|只有我们', 2, 'competitor_mention', 'block', '广告法第13条'),
    ('禁止违规比较广告', '比.*便宜|比.*优惠|价格最低|全网最低价|历史最低|跌破底价|亏本|血亏|赔本', 2, 'platform_rule', 'warn', '禁止未经证实的比较广告'),
    ('禁止诱导点击/虚假诱导文案', '点击领取|免费领取|点击抽奖|点击有惊喜|不点就亏了|点开有惊喜|马上抢|疯狂抢购', 3, 'platform_rule', 'warn', '禁止虚假诱导点击'),
    ('禁止在非授权情况下使用平台名义', '天猫认证|京东认证|官方授权(?!书|牌|证|文件)|平台推荐(?!商品|好物)', 3, 'platform_rule', 'warn', '禁止未经授权使用平台名义'),
    ('禁止使用禁用营销词', '最后一天|仅此一天|限时抢购|秒杀(?!活动|专区|价)|清仓|倒闭|破产|跑路|老板哭了|老板疯了|挥泪|跳楼价', 3, 'platform_rule', 'flag', '平台禁用营销用语'),
    ('竞品平台提及检测', '天猫(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|优品|会员|积分|优惠|活动|双1|6|年货)|京东(?!店|店铺|旗舰|官方|客服|平台|商城|超市|国际|自营|会员|PLUS|物流|快递|优品|优惠|活动|618|年货)|拼多多(?!店|店铺|官方|客服|平台)|抖音(?!店|店铺|官方|客服|平台|商城|直播)|小红书(?!店|店铺|官方|客服|平台|商城)', 3, 'competitor_mention', 'flag', '提及竞品平台需审核'),
    ('敏感话题检测', '政治|宗教|种族|性别歧视|地域歧视|色情|暴力|赌博|毒品|枪支|弹药', 3, 'sensitive_word', 'block', '禁止敏感话题'),
    ('多处感叹号可能令客户感到压迫', '[！!]{2,}', 4, 'tone_violation', 'flag', '连续感叹号'),
    ('连续问号可能显得不耐烦', '[？?]{3,}', 4, 'tone_violation', 'flag', '连续问号'),
    ('全大写英文可能被视为咆哮', '\b[A-Z]{8,}\b', 4, 'tone_violation', 'flag', '全大写英文'),
    ('建议避免使用粗俗/不文明用语', '傻逼|脑残|废物|笨蛋|蠢|垃圾(?!分类|桶|短信|邮件|文件|清理|广告|信息|数据|内容)', 4, 'tone_violation', 'warn', '粗俗用语')
ON CONFLICT DO NOTHING;

ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_audit_logs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Compliance rules readable by all authenticated" ON compliance_rules FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE POLICY "Compliance audit logs readable by all authenticated" ON compliance_audit_logs FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 2: System Runtime Configuration (from migration-010)
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key  TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    value_type  TEXT NOT NULL DEFAULT 'string' CHECK (value_type IN ('string', 'number', 'boolean', 'json')),
    description TEXT,
    category    TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa')),
    updated_by  UUID,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_system_configs_category ON system_configs(category);

INSERT INTO system_configs (config_key, config_value, value_type, description, category) VALUES
    ('auto_publish_threshold', '0.95', 'number', 'Minimum LLM confidence for auto-publish', 'auto_publish'),
    ('auto_publish_max_change_length', '50', 'number', 'Max change description length for auto-publish', 'auto_publish'),
    ('feishu_timeout_ms', '10000', 'number', 'Feishu API timeout (ms)', 'feishu'),
    ('feishu_retry_count', '3', 'number', 'Feishu dispatch retry count', 'feishu'),
    ('feishu_night_window_start', '22', 'number', 'Night window start hour', 'feishu'),
    ('feishu_night_window_end', '8', 'number', 'Night window end hour', 'feishu'),
    ('llm_rate_limit_per_minute', '30', 'number', 'LLM API rate limit', 'llm'),
    ('llm_cache_ttl_hours', '24', 'number', 'LLM cache TTL', 'llm'),
    ('llm_max_retries', '3', 'number', 'LLM retry count', 'llm'),
    ('knowledge_gap_similarity_threshold', '0.15', 'number', 'Knowledge match similarity threshold', 'qa'),
    ('qa_kappa_alert_threshold', '0.4', 'number', 'Cohen Kappa alert threshold', 'qa'),
    ('compliance_auto_block_threshold', '2', 'number', 'Auto-block risk level threshold', 'compliance'),
    ('dedup_window_days', '7', 'number', 'Dedup window in days', 'general'),
    ('payment_reminder_max_rounds', '3', 'number', 'Max reminder rounds per order', 'general'),
    ('payment_reminder_interval_hours', '24', 'number', 'Hours between reminder rounds', 'general'),
    ('payment_reminder_first_delay_minutes', '30', 'number', 'Minutes before first reminder', 'general')
ON CONFLICT (config_key) DO NOTHING;

ALTER TABLE system_configs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "System configs readable by all authenticated" ON system_configs FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 3: Intent Accuracy Tracking (from migration-011)
-- ============================================================================

DO $$ BEGIN
    CREATE TABLE IF NOT EXISTS intent_accuracy_logs (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        platform_id     UUID,
        period_date     DATE NOT NULL,
        total_recognitions  INT NOT NULL DEFAULT 0,
        correct_recognitions INT NOT NULL DEFAULT 0,
        incorrect_recognitions INT NOT NULL DEFAULT 0,
        accuracy        NUMERIC(5,4) NOT NULL DEFAULT 0,
        coverage_rate   NUMERIC(5,4),
        target_met      BOOLEAN NOT NULL DEFAULT false,
        bad_case_ids    UUID[] DEFAULT '{}',
        notes           TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE(platform_id, period_date)
    );
EXCEPTION WHEN duplicate_table THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_intent_accuracy_date ON intent_accuracy_logs(period_date DESC);
CREATE INDEX IF NOT EXISTS idx_intent_accuracy_target ON intent_accuracy_logs(target_met, period_date DESC);

ALTER TABLE intent_accuracy_logs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Intent accuracy readable by all authenticated" ON intent_accuracy_logs FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 4: Work Orders (from migration-012)
-- ============================================================================

CREATE TABLE IF NOT EXISTS work_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('qa_evaluate', 'compliance_block', 'inspection', 'manual', 'cron')),
    source_id       UUID,
    priority        TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    category        TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'compliance', 'script_fix', 'knowledge_gap', 'customer_complaint', 'system_issue')),
    platform_id     UUID,
    assigned_to     UUID,
    resolved_by     UUID,
    resolution      TEXT,
    feishu_message_id TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status, priority);
CREATE INDEX IF NOT EXISTS idx_work_orders_source ON work_orders(source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_orders_assigned ON work_orders(assigned_to) WHERE status NOT IN ('resolved', 'closed');

CREATE TABLE IF NOT EXISTS work_order_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id   UUID NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('created', 'assigned', 'in_progress', 'resolved', 'closed', 'reopened', 'commented')),
    comment         TEXT,
    performed_by    UUID,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wo_actions_order ON work_order_actions(work_order_id, created_at DESC);

ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_order_actions ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Work orders readable by all authenticated" ON work_orders FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE POLICY "Work order actions readable by all authenticated" ON work_order_actions FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 5: Payment Reminders (from migration-013)
-- ============================================================================

CREATE TABLE IF NOT EXISTS pending_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_order_id TEXT NOT NULL,
    platform_id     UUID,
    customer_id     TEXT,
    customer_name   TEXT,
    product_name    TEXT,
    order_amount    NUMERIC(10,2),
    order_status    TEXT NOT NULL DEFAULT 'pending_payment' CHECK (order_status IN ('pending_payment', 'reminded', 'paid', 'cancelled', 'expired')),
    created_at_order TIMESTAMPTZ NOT NULL DEFAULT now(),
    expire_at       TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_orders_external ON pending_orders(external_order_id, platform_id);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(order_status, expire_at);

CREATE TABLE IF NOT EXISTS payment_reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES pending_orders(id) ON DELETE CASCADE,
    round           INT NOT NULL DEFAULT 1,
    script          TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'bot' CHECK (channel IN ('bot', 'sms', 'feishu', 'app_push')),
    status          TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('pending', 'sent', 'delivered', 'failed', 'converted')),
    sent_at         TIMESTAMPTZ,
    converted_at    TIMESTAMPTZ,
    response        TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reminders_order ON payment_reminders(order_id, round);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON payment_reminders(status, sent_at DESC);

ALTER TABLE pending_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reminders ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY "Pending orders readable by all authenticated" ON pending_orders FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE POLICY "Payment reminders readable by all authenticated" ON payment_reminders FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- Verify: List all newly created tables
-- ============================================================================
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'compliance_rules', 'compliance_audit_logs',
    'system_configs',
    'intent_accuracy_logs',
    'work_orders', 'work_order_actions',
    'pending_orders', 'payment_reminders'
  )
ORDER BY table_name;

-- >>> supabase/migration-015-unresolved-questions.sql
-- ============================================================================
-- Migration 015: Unresolved Questions — AI未解决问题闭环工作流
-- 用于记录AI客服无法处理的问题，支持导出/导入话术训练系统
-- ============================================================================

-- ── 1. 未解决问题记录表 ─────────────────────────────
CREATE TABLE IF NOT EXISTS unresolved_questions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      TEXT NOT NULL,
  platform_id     UUID REFERENCES platforms(id),
  platform_code   TEXT,                            -- feishu/tmall/jd/douyin/pdd
  user_question   TEXT NOT NULL,                   -- 客户问题原文
  ai_reply        TEXT,                            -- AI给出的回复（如果有）
  transfer_reason TEXT,                            -- 转人工原因（bot_chat_sessions.transfer_reason）
  satisfaction    TEXT CHECK (satisfaction IN ('good', 'neutral', 'bad')),
  conversation    TEXT,                            -- 完整会话上下文
  category        TEXT,                            -- 分类（由LLM聚类分析后填充）
  tags            TEXT[] NOT NULL DEFAULT '{}',
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'resolved', 'rejected', 'exported')),
  priority        INT NOT NULL DEFAULT 0,           -- 0=普通 1=优先 2=紧急
  assigned_to     TEXT,                            -- 维护者open_id或飞书user_id
  note            TEXT,                            -- 维护备注
  resolved_by     TEXT,                            -- 解决者标识
  resolved_at     TIMESTAMPTZ,                     -- 解决时间
  correlation_id  TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_unresolved_status ON unresolved_questions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_unresolved_platform ON unresolved_questions(platform_id);
CREATE INDEX IF NOT EXISTS idx_unresolved_category ON unresolved_questions(category);
CREATE INDEX IF NOT EXISTS idx_unresolved_created ON unresolved_questions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_unresolved_priority ON unresolved_questions(priority DESC, created_at DESC);

-- ── 2. unresolved_question_logs 操作日志表 ──────────────────
CREATE TABLE IF NOT EXISTS unresolved_question_logs (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  unresolved_id       UUID NOT NULL REFERENCES unresolved_questions(id) ON DELETE CASCADE,
  action              TEXT NOT NULL CHECK (action IN ('create', 'assign', 'update_status', 'export', 'import_back', 'note', 'resolve', 'reject')),
  operator            TEXT,
  detail              JSONB DEFAULT '{}',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_unresolved_logs_question ON unresolved_question_logs(unresolved_id, created_at DESC);

-- ── 3. 更新 updated_at 触发器 ───────────────────────────
CREATE OR REPLACE FUNCTION update_unresolved_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_unresolved_updated_at
  BEFORE UPDATE ON unresolved_questions
  FOR EACH ROW
  EXECUTE FUNCTION update_unresolved_updated_at();

-- ── 4. RPC: 统计未解决问题趋势 ──────────────────────────
CREATE OR REPLACE FUNCTION unresolved_question_stats(
  days_back INT DEFAULT 7
)
RETURNS TABLE(
  date_str TEXT,
  total_count BIGINT,
  pending_count BIGINT,
  resolved_count BIGINT,
  exported_count BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH dates AS (
    SELECT generate_series(
      CURRENT_DATE - (days_back - 1)::INT,
      CURRENT_DATE,
      '1 day'::INTERVAL
    )::DATE AS d
  )
  SELECT
    d::TEXT AS date_str,
    COUNT(uq.id)::BIGINT AS total_count,
    COUNT(uq.id) FILTER (WHERE uq.status = 'pending')::BIGINT AS pending_count,
    COUNT(uq.id) FILTER (WHERE uq.status = 'resolved')::BIGINT AS resolved_count,
    COUNT(uq.id) FILTER (WHERE uq.status = 'exported')::BIGINT AS exported_count
  FROM dates
  LEFT JOIN unresolved_questions uq ON uq.created_at::DATE = dates.d
  GROUP BY dates.d
  ORDER BY dates.d;
END;
$$;

-- >>> supabase/migration-016-hybrid-search-compat.sql
-- Forward-only PostgreSQL 17 compatible replacement for migration-016-hybrid-search.sql.
-- Generated tsvector expressions are not immutable on PostgreSQL 17, so a trigger
-- maintains a normal tsvector column instead.

ALTER TABLE public.knowledge_entries
  ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE OR REPLACE FUNCTION public.update_knowledge_search_vector()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.search_vector :=
    to_tsvector('simple', COALESCE(NEW.title, '')) ||
    to_tsvector('simple', COALESCE(NEW.content, '')) ||
    to_tsvector('simple', COALESCE(array_to_string(NEW.keywords, ' '), ''));
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_knowledge_search_vector ON public.knowledge_entries;
CREATE TRIGGER trg_knowledge_search_vector
  BEFORE INSERT OR UPDATE OF title, content, keywords
  ON public.knowledge_entries
  FOR EACH ROW
  EXECUTE FUNCTION public.update_knowledge_search_vector();

UPDATE public.knowledge_entries
SET search_vector =
  to_tsvector('simple', COALESCE(title, '')) ||
  to_tsvector('simple', COALESCE(content, '')) ||
  to_tsvector('simple', COALESCE(array_to_string(keywords, ' '), ''))
WHERE search_vector IS NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_search_vector
  ON public.knowledge_entries USING GIN (search_vector);

DROP FUNCTION IF EXISTS public.hybrid_search_vector(vector, integer);
DROP FUNCTION IF EXISTS public.hybrid_search_vector(vector, integer, text);
DROP FUNCTION IF EXISTS public.hybrid_search_keyword(text, integer);
DROP FUNCTION IF EXISTS public.hybrid_search_keyword(text, integer, text);

CREATE OR REPLACE FUNCTION public.hybrid_search_vector(
  query_embedding vector(1536),
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT ke.id, ke.title, ke.content, ke.category, ke.keywords,
         (1 - (ke.embedding <=> $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.embedding IS NOT NULL
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY ke.embedding <=> $1
  LIMIT $2
$$;

CREATE OR REPLACE FUNCTION public.hybrid_search_keyword(
  query_text text,
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT ke.id, ke.title, ke.content, ke.category, ke.keywords,
         ts_rank_cd(ke.search_vector, plainto_tsquery('simple', $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.search_vector @@ plainto_tsquery('simple', $1)
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY similarity DESC
  LIMIT $2
$$;

-- >>> supabase/migration-016-hybrid-search.sql
-- ============================================================================
-- Migration 016: Hybrid Search — tsvector + BM25 + RRF support
-- 为 knowledge_entries 增加全文检索能力，与 pgvector 形成双路检索
-- ============================================================================

-- ── 1. 为 knowledge_entries 增加 tsvector 列 ──────────────
ALTER TABLE knowledge_entries
  ADD COLUMN IF NOT EXISTS search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple', COALESCE(title, '')) ||
    to_tsvector('simple', COALESCE(content, '')) ||
    to_tsvector('simple', COALESCE(array_to_string(keywords, ' '), ''))
  ) STORED;

-- GIN 索引用于加速 tsquery
CREATE INDEX IF NOT EXISTS idx_knowledge_search_vector
  ON knowledge_entries
  USING GIN (search_vector);

-- ── 2. RPC: 向量检索 ──────────────────────────────────────
-- 功能同 match_knowledge_entries 但去掉 hit_count 副作用
-- 专供 hybrid_search 调用
CREATE OR REPLACE FUNCTION hybrid_search_vector(
  query_embedding vector(1536),
  match_count int DEFAULT 20
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  RETURN QUERY
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    (1 - (ke.embedding <=> query_embedding))::float AS similarity
  FROM knowledge_entries ke
  WHERE ke.status = 'published'
    AND ke.embedding IS NOT NULL
  ORDER BY ke.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── 3. RPC: 关键词检索 (tsvector) ──────────────────────────
-- 使用 plainto_tsquery 将用户自然语言转为 tsquery
-- ts_rank_cd 给出 BM25 风格的相关度分数
CREATE OR REPLACE FUNCTION hybrid_search_keyword(
  query_text text,
  match_count int DEFAULT 20
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  tsq tsquery;
BEGIN
  -- 将用户输入转为 tsquery（自动去除停用词）
  tsq := plainto_tsquery('simple', query_text);

  IF tsq IS NULL THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    ts_rank_cd(ke.search_vector, tsq)::float AS similarity
  FROM knowledge_entries ke
  WHERE ke.status = 'published'
    AND ke.search_vector @@ tsq
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$;

-- ── 4. 创建知识点时自动填充 search_vector ──────────────────
-- （GENERATED ALWAYS AS STORED 会自动维护，无需额外 trigger）

-- >>> supabase/migration-017-unresolved-fts.sql
-- Migration 017: Unresolved Questions 全文检索
-- 为 unresolved_questions 增加 tsvector 搜索支持

ALTER TABLE unresolved_questions
  ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_unresolved_search_vector
  ON unresolved_questions USING GIN (search_vector);

-- 触发器：自动从 user_question + ai_reply + conversation 更新向量
CREATE OR REPLACE FUNCTION update_unresolved_search_vector()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  conv_snippet text;
BEGIN
  conv_snippet := COALESCE(NEW.conversation, '');
  NEW.search_vector :=
    to_tsvector('simple', COALESCE(NEW.user_question, '')) ||
    to_tsvector('simple', COALESCE(NEW.ai_reply, '')) ||
    to_tsvector('simple', left(conv_snippet, 1000));
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_unresolved_search_vector
  BEFORE INSERT OR UPDATE OF user_question, ai_reply, conversation
  ON unresolved_questions
  FOR EACH ROW
  EXECUTE FUNCTION update_unresolved_search_vector();

-- 补填已有数据
UPDATE unresolved_questions
SET search_vector =
    to_tsvector('simple', COALESCE(user_question, '')) ||
    to_tsvector('simple', COALESCE(ai_reply, '')) ||
    to_tsvector('simple', left(COALESCE(conversation, ''), 1000))
WHERE search_vector IS NULL;

-- >>> supabase/migration-018-governance-foundation.sql
-- Governance foundation: role compatibility, evidence events, evaluations,
-- findings, approvals and work items. Safe to run repeatedly.

ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_role_check;
ALTER TABLE profiles ADD CONSTRAINT profiles_role_check
  CHECK (role IN ('agent', 'team_lead', 'operator', 'admin', 'viewer'));

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS tenant_id TEXT;
CREATE INDEX IF NOT EXISTS idx_profiles_tenant_team ON profiles(tenant_id, team_id);

CREATE TABLE IF NOT EXISTS evidence_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL DEFAULT '1.0',
  tenant_id TEXT NOT NULL,
  team_id TEXT,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  actor_id TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'service', 'system')),
  actor_name TEXT,
  correlation_id TEXT NOT NULL,
  payload_ref TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  processing_status TEXT NOT NULL DEFAULT 'received'
    CHECK (processing_status IN ('received', 'processing', 'processed', 'failed')),
  processing_log JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_events_tenant_time
  ON evidence_events(tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_events_correlation
  ON evidence_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_events_type
  ON evidence_events(source, event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  team_id TEXT,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  event_id UUID REFERENCES evidence_events(id),
  rule_version TEXT NOT NULL,
  model_version TEXT,
  score NUMERIC,
  risk TEXT NOT NULL CHECK (risk IN ('low', 'medium', 'high', 'critical')),
  explanations JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  decision TEXT NOT NULL DEFAULT 'review'
    CHECK (decision IN ('pass', 'review', 'block', 'override')),
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
  severity TEXT NOT NULL CHECK (severity IN ('info', 'minor', 'major', 'critical')),
  category TEXT NOT NULL,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  decision TEXT NOT NULL DEFAULT 'open'
    CHECK (decision IN ('open', 'accepted', 'rejected', 'waived')),
  review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending', 'approved', 'overturned', 'closed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  approver_id UUID REFERENCES profiles(id),
  decision TEXT NOT NULL CHECK (decision IN ('pending', 'approved', 'rejected', 'expired')),
  reason TEXT,
  expires_at TIMESTAMPTZ,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS governance_work_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  team_id TEXT,
  source_finding_id UUID REFERENCES findings(id),
  source_type TEXT NOT NULL CHECK (source_type IN ('event', 'evaluation', 'finding', 'manual')),
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  owner_id UUID REFERENCES profiles(id),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'blocked', 'resolved', 'closed')),
  sla_at TIMESTAMPTZ,
  close_evidence JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_work_items_source
  ON governance_work_items(tenant_id, source_type, source_id);

ALTER TABLE evidence_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_work_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "Governance events require matching tenant" ON evidence_events
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance evaluations require matching tenant" ON evaluations
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance findings require matching tenant" ON findings
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance approvals require matching tenant" ON approvals
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance work items require matching tenant" ON governance_work_items
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- >>> supabase/migration-019-reply-quality-loop.sql
-- Persist knowledge references used to generate automated replies.
ALTER TABLE bot_chat_sessions
  ADD COLUMN IF NOT EXISTS knowledge_refs JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_bot_sessions_knowledge_refs
  ON bot_chat_sessions USING GIN (knowledge_refs);

-- >>> supabase/migration-020-llm-call-logs.sql
-- Persisted LLM observability and cost ledger seed.
CREATE TABLE IF NOT EXISTS llm_call_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  endpoint TEXT NOT NULL,
  model TEXT NOT NULL,
  tokens_used INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
  success BOOLEAN NOT NULL DEFAULT false,
  cached BOOLEAN NOT NULL DEFAULT false,
  response_time_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_created_at
  ON llm_call_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_call_logs_model_created_at
  ON llm_call_logs(model, created_at DESC);

ALTER TABLE llm_call_logs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "LLM call logs require an authenticated user" ON llm_call_logs
    FOR SELECT USING (auth.uid() IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- >>> supabase/migration-021-cron-idempotency.sql
-- Daily reports are keyed by report type and period to make retries harmless.
CREATE UNIQUE INDEX IF NOT EXISTS idx_robot_reports_daily_period
  ON robot_reports(report_type, period_start)
  WHERE report_type = 'daily';

-- >>> supabase/migration-023-quality-loop-hardening.sql
-- Quality loop hardening. Existing governance tables are created in migration-018.
-- Keep one evaluation per report and rule version so retries cannot create duplicate
-- findings or work items for the same QA decision.
CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluations_report_rule
  ON evaluations(tenant_id, subject_type, subject_id, rule_version);

CREATE INDEX IF NOT EXISTS idx_findings_evaluation_status
  ON findings(evaluation_id, review_status);

CREATE INDEX IF NOT EXISTS idx_approvals_subject_decision
  ON approvals(tenant_id, subject_type, subject_id, decision);

-- >>> supabase/migration-024-evidence-event-contract.sql
-- EvidenceEvent v1 contract metadata and source-scoped idempotency.
-- Safe for databases created from migration-018 and for repeated execution.

ALTER TABLE evidence_events
  ADD COLUMN IF NOT EXISTS specversion TEXT NOT NULL DEFAULT '1.0',
  ADD COLUMN IF NOT EXISTS subject TEXT,
  ADD COLUMN IF NOT EXISTS traceparent TEXT,
  ADD COLUMN IF NOT EXISTS datacontenttype TEXT NOT NULL DEFAULT 'application/json',
  ADD COLUMN IF NOT EXISTS schema_ref TEXT NOT NULL DEFAULT 'schemas/events/evidence-event-v1.json',
  ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

UPDATE evidence_events
SET idempotency_key = source || ':' || event_id
WHERE idempotency_key IS NULL;

ALTER TABLE evidence_events
  ALTER COLUMN idempotency_key SET NOT NULL;

-- migration-018 declared event_id globally unique. The contract scopes
-- idempotency by source, so remove that old constraint before adding the
-- source-scoped unique index.
ALTER TABLE evidence_events
  DROP CONSTRAINT IF EXISTS evidence_events_event_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_events_source_event_id
  ON evidence_events(source, event_id);

CREATE INDEX IF NOT EXISTS idx_evidence_events_traceparent
  ON evidence_events(traceparent)
  WHERE traceparent IS NOT NULL;

-- >>> supabase/migration-025-commerce-metrics-lineage.sql
-- Sprint 3 metric snapshots and minimal Dataset -> Job -> Run lineage.
-- This migration is additive and safe to rerun after migration-024.

CREATE TABLE IF NOT EXISTS lineage_datasets (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  data_class TEXT NOT NULL DEFAULT 'internal'
    CHECK (data_class IN ('public', 'internal', 'sensitive', 'restricted')),
  owner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lineage_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL REFERENCES lineage_datasets(id),
  name TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  owner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lineage_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES lineage_jobs(id),
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'degraded', 'failed')),
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  input_count INTEGER NOT NULL DEFAULT 0,
  output_count INTEGER NOT NULL DEFAULT 0,
  error_class TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  metric_key TEXT NOT NULL,
  value NUMERIC,
  unit TEXT NOT NULL CHECK (unit IN ('count', 'currency', 'ratio')),
  definition_version TEXT NOT NULL,
  dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_dataset_id TEXT NOT NULL REFERENCES lineage_datasets(id),
  source_job_id TEXT NOT NULL REFERENCES lineage_jobs(id),
  source_run_id TEXT NOT NULL REFERENCES lineage_runs(id),
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  attribution_window TEXT NOT NULL,
  currency TEXT,
  timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  freshness_at TIMESTAMPTZ,
  quality_status TEXT NOT NULL CHECK (quality_status IN ('complete', 'stale', 'degraded', 'missing')),
  missing_reason TEXT,
  owner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_tenant_key_time
  ON metric_snapshots(tenant_id, metric_key, window_end DESC);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_lineage
  ON metric_snapshots(source_dataset_id, source_job_id, source_run_id);

ALTER TABLE lineage_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineage_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineage_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE metric_snapshots ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "Lineage datasets require matching tenant" ON lineage_datasets
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Lineage jobs require matching tenant" ON lineage_jobs
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Lineage runs require matching tenant" ON lineage_runs
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Metric snapshots require matching tenant" ON metric_snapshots
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- >>> supabase/migration-026-ai-evaluation-gate.sql
-- Sprint 4 AI evaluation cases, runs and results.
-- Results are versioned so model/prompt/rule changes remain reproducible.

CREATE TABLE IF NOT EXISTS ai_evaluation_cases (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  evaluation_set TEXT NOT NULL CHECK (evaluation_set IN ('gold', 'boundary', 'safety', 'adversarial', 'regression', 'shadow')),
  input_text TEXT NOT NULL,
  expected_category TEXT NOT NULL,
  expected_block BOOLEAN NOT NULL,
  criticality TEXT NOT NULL CHECK (criticality IN ('none', 'p1', 'p0')),
  requires_evidence BOOLEAN NOT NULL DEFAULT true,
  source_type TEXT NOT NULL DEFAULT 'fixture',
  source_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_evaluation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  evaluation_set TEXT NOT NULL DEFAULT 'all',
  evaluator_version TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('offline', 'shadow', 'canary')),
  status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'cancelled')),
  sample_count INTEGER NOT NULL DEFAULT 0,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai_evaluation_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES ai_evaluation_runs(id) ON DELETE CASCADE,
  case_id TEXT NOT NULL REFERENCES ai_evaluation_cases(id),
  predicted_category TEXT NOT NULL,
  blocked BOOLEAN NOT NULL,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_coverage NUMERIC(6, 5) NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
  raw_output_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_eval_cases_set_version
  ON ai_evaluation_cases(tenant_id, evaluation_set, dataset_version);
CREATE INDEX IF NOT EXISTS idx_ai_eval_runs_status_started
  ON ai_evaluation_runs(tenant_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_eval_results_run
  ON ai_evaluation_results(run_id, case_id);

ALTER TABLE ai_evaluation_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_evaluation_results ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "AI evaluation cases require matching tenant" ON ai_evaluation_cases
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "AI evaluation runs require matching tenant" ON ai_evaluation_runs
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "AI evaluation results require matching run tenant" ON ai_evaluation_results
    FOR SELECT USING (
      auth.uid() IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM ai_evaluation_runs runs
        WHERE runs.id = run_id
          AND runs.tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id')
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- >>> supabase/migration-027-diagnosis.sql
-- Sprint 5: Lost-deal diagnosis with reason tree, evidence layers and human review.
-- Additive migration; safe to rerun.

-- A diagnosis session groups the analysis of one or more lost conversations.
CREATE TABLE IF NOT EXISTS diagnosis_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL DEFAULT 'default',
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual', 'auto_batch', 'work_item')),
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
  conversation_ids TEXT[] NOT NULL DEFAULT '{}',
  campaign_id TEXT,
  product_id TEXT,
  time_window_start TIMESTAMPTZ,
  time_window_end TIMESTAMPTZ,
  engine_version TEXT NOT NULL DEFAULT 'diagnosis-engine-v1.0',
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES profiles(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each finding is one reason hypothesis with layered evidence.
CREATE TABLE IF NOT EXISTS diagnosis_findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES diagnosis_sessions(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  reason_category TEXT NOT NULL
    CHECK (reason_category IN (
      'traffic_quality', 'product_mismatch', 'price_objection',
      'trust_deficit', 'service_failure', 'inventory_fulfillment',
      'payment_followup', 'unknown'
    )),
  -- Layered output: fact -> inference -> confidence -> suggestion
  fact_statement TEXT NOT NULL,
  inference_statement TEXT,
  confidence TEXT NOT NULL DEFAULT 'low'
    CHECK (confidence IN ('high', 'medium', 'low', 'insufficient')),
  confidence_score NUMERIC(5,4) CHECK (confidence_score >= 0 AND confidence_score <= 1),
  counter_evidence TEXT,
  suggestion TEXT,
  suggestion_actionable BOOLEAN NOT NULL DEFAULT false,
  -- Evidence references
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  -- Link to funnel stage where drop-off detected
  funnel_stage TEXT CHECK (funnel_stage IN ('traffic', 'conversation', 'cart', 'order', 'payment')),
  -- Linked entities
  conversation_id TEXT,
  product_id TEXT,
  campaign_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human review of a diagnosis finding.
CREATE TABLE IF NOT EXISTS diagnosis_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  finding_id UUID NOT NULL REFERENCES diagnosis_findings(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  reviewer_id UUID NOT NULL REFERENCES profiles(id),
  decision TEXT NOT NULL CHECK (decision IN ('accepted', 'modified', 'rejected')),
  modified_reason TEXT,
  rejection_reason TEXT,
  feedback_note TEXT,
  -- Feedback routing: where does the correction go?
  feedback_target TEXT CHECK (feedback_target IN ('rule', 'prompt', 'knowledge', 'model', 'none')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Work items generated from accepted diagnosis findings.
CREATE TABLE IF NOT EXISTS diagnosis_work_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  finding_id UUID NOT NULL REFERENCES diagnosis_findings(id) ON DELETE CASCADE,
  session_id UUID NOT NULL REFERENCES diagnosis_sessions(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  title TEXT NOT NULL,
  description TEXT,
  assignee_id UUID REFERENCES profiles(id),
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high', 'medium', 'low')),
  sla_deadline TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  close_evidence TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_diagnosis_sessions_tenant_status
  ON diagnosis_sessions(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnosis_findings_session
  ON diagnosis_findings(session_id, reason_category);
CREATE INDEX IF NOT EXISTS idx_diagnosis_findings_tenant_category
  ON diagnosis_findings(tenant_id, reason_category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnosis_reviews_finding
  ON diagnosis_reviews(finding_id);
CREATE INDEX IF NOT EXISTS idx_diagnosis_work_items_session
  ON diagnosis_work_items(session_id, status);

-- RLS
ALTER TABLE diagnosis_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnosis_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnosis_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnosis_work_items ENABLE ROW LEVEL SECURITY;

-- >>> supabase/migration-028-feedback-release-manifests.sql
-- Contest feedback lifecycle and immutable release manifests. Additive only.
CREATE TABLE IF NOT EXISTS feedback_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  source_trace_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('captured','triaged','accepted','rejected','change_drafted','regression_running','approved','released','verified')),
  reason_code TEXT CHECK (reason_code IN ('RULE_MISSING','RULE_CONFLICT','RETRIEVAL_MISS','PROMPT_DEFECT','MODEL_JUDGMENT_ERROR','EVIDENCE_EXTRACTION_ERROR','LABEL_DISPUTE','DATA_QUALITY')),
  rejection_reason TEXT,
  owner_id UUID REFERENCES profiles(id),
  linked_dataset_items TEXT[] NOT NULL DEFAULT '{}',
  regression_passed BOOLEAN NOT NULL DEFAULT false,
  approved_by UUID REFERENCES profiles(id),
  release_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((status <> 'rejected') OR rejection_reason IS NOT NULL),
  CHECK ((status NOT IN ('approved','released','verified')) OR (regression_passed AND cardinality(linked_dataset_items) > 0)),
  CHECK ((status NOT IN ('released','verified')) OR approved_by IS NOT NULL),
  CHECK ((status <> 'verified') OR release_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS release_manifests (
  release_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  deployment_id TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  rule_set_version TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  evaluation_report TEXT NOT NULL,
  regression_passed BOOLEAN NOT NULL CHECK (regression_passed),
  approved_by UUID REFERENCES profiles(id),
  released_at TIMESTAMPTZ NOT NULL,
  integrity_hash TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE feedback_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE release_manifests ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_feedback_records_tenant_status ON feedback_records(tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS feedback_transition_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_id UUID NOT NULL REFERENCES feedback_records(id) ON DELETE CASCADE,
  from_status TEXT,
  to_status TEXT NOT NULL,
  actor_id UUID REFERENCES profiles(id),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION enforce_feedback_transition()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status <> OLD.status AND NOT (
    (OLD.status = 'captured' AND NEW.status = 'triaged') OR
    (OLD.status = 'triaged' AND NEW.status IN ('accepted', 'rejected')) OR
    (OLD.status = 'accepted' AND NEW.status = 'change_drafted') OR
    (OLD.status = 'change_drafted' AND NEW.status = 'regression_running') OR
    (OLD.status = 'regression_running' AND NEW.status = 'approved') OR
    (OLD.status = 'approved' AND NEW.status = 'released') OR
    (OLD.status = 'released' AND NEW.status = 'verified')
  ) THEN
    RAISE EXCEPTION 'invalid feedback transition: % -> %', OLD.status, NEW.status;
  END IF;
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION record_feedback_transition()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status <> OLD.status THEN
    INSERT INTO feedback_transition_history (feedback_id, from_status, to_status, actor_id)
    VALUES (NEW.id, OLD.status, NEW.status, NEW.owner_id);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS feedback_transition_guard ON feedback_records;
CREATE TRIGGER feedback_transition_guard BEFORE UPDATE ON feedback_records
  FOR EACH ROW EXECUTE FUNCTION enforce_feedback_transition();
DROP TRIGGER IF EXISTS feedback_transition_audit ON feedback_records;
CREATE TRIGGER feedback_transition_audit AFTER UPDATE ON feedback_records
  FOR EACH ROW EXECUTE FUNCTION record_feedback_transition();

CREATE OR REPLACE FUNCTION reject_release_manifest_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'release manifests are immutable; create a new manifest instead';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS release_manifest_immutable ON release_manifests;
CREATE TRIGGER release_manifest_immutable BEFORE UPDATE OR DELETE ON release_manifests
  FOR EACH ROW EXECUTE FUNCTION reject_release_manifest_mutation();

-- >>> supabase/migration-029-tenant-rls-hardening.sql
-- ============================================================================
-- Migration 029: Tenant RLS hardening for legacy QA tables
--
-- This is forward-only. Published migrations are intentionally left unchanged.
-- Service-role clients still bypass RLS by design; API routes must continue to
-- resolve a tenant and apply the same scope explicitly.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.jwt_tenant_id()
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    auth.jwt() ->> 'tenant_id',
    auth.jwt() -> 'app_metadata' ->> 'tenant_id'
  )
$$;

DO $$
DECLARE
  table_name TEXT;
  tenant_tables TEXT[] := ARRAY[
    'profiles',
    'quality_reports',
    'bad_cases',
    'bot_configs',
    'knowledge_entries',
    'bot_chat_sessions',
    'optimization_tasks',
    'robot_reports',
    'knowledge_update_logs',
    'user_roles',
    'audit_logs',
    'correction_samples',
    'compliance_rules',
    'compliance_audit_logs',
    'system_configs',
    'intent_accuracy_logs',
    'platform_credentials',
    'shadow_replies',
    'actual_replies',
    'work_orders',
    'work_order_actions',
    'pending_orders',
    'payment_reminders',
    'unresolved_questions',
    'unresolved_question_logs',
    'llm_call_logs'
  ];
BEGIN
  FOREACH table_name IN ARRAY tenant_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS tenant_id TEXT',
      table_name
    );
    EXECUTE format(
      'UPDATE public.%I SET tenant_id = ''default'' WHERE tenant_id IS NULL',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE public.%I ALTER COLUMN tenant_id SET DEFAULT ''default''',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE public.%I ALTER COLUMN tenant_id SET NOT NULL',
      table_name
    );
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON public.%I (tenant_id)',
      'idx_' || table_name || '_tenant',
      table_name
    );

    -- Keep existing role/permission policies. A restrictive policy is ANDed
    -- with every permissive policy, so legacy USING(true) cannot cross tenants
    -- and existing admin/team restrictions are not widened.
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_select', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_insert', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_update', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_delete', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_select',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_insert',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id()) WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_update',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_delete',
      table_name
    );

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

CREATE INDEX IF NOT EXISTS idx_knowledge_entries_tenant_status
  ON public.knowledge_entries (tenant_id, status);

-- Diagnosis tables already carry tenant_id but migration-027 only enabled RLS.
DO $$
DECLARE
  table_name TEXT;
  tenant_tables TEXT[] := ARRAY[
    'diagnosis_sessions',
    'diagnosis_findings',
    'diagnosis_reviews',
    'diagnosis_work_items',
    'feedback_records',
    'release_manifests',
    'release_evidences',
    'dora_metrics',
    'rollback_drills'
  ];
BEGIN
  FOREACH table_name IN ARRAY tenant_tables LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_select', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_insert', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_update', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_tenant_delete', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_select',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_insert',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id()) WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_update',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())',
      table_name || '_tenant_delete',
      table_name
    );
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

-- Legacy prompt/bot/model tables used UUID tenant columns and had no tenant
-- policy. Normalize them to the text tenant contract used by JWT claims and
-- the rest of the QA schema before enabling service-role-safe RLS.
DO $$
DECLARE
  legacy_table_name TEXT;
  column_type TEXT;
BEGIN
  FOREACH legacy_table_name IN ARRAY ARRAY['prompts', 'bots', 'model_configs', 'prompt_versions'] LOOP
    IF to_regclass(format('public.%I', legacy_table_name)) IS NULL THEN
      CONTINUE;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns AS columns
      WHERE columns.table_schema = 'public'
        AND columns.table_name = legacy_table_name
        AND columns.column_name = 'tenant_id'
    ) THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN tenant_id TEXT', legacy_table_name);
    ELSE
      SELECT format_type(a.atttypid, a.atttypmod)
        INTO column_type
      FROM pg_attribute AS a
      JOIN pg_class AS c ON c.oid = a.attrelid
      JOIN pg_namespace AS n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public'
        AND c.relname = legacy_table_name
        AND a.attname = 'tenant_id'
        AND a.attnum > 0
        AND NOT a.attisdropped;

      IF column_type <> 'text' THEN
        EXECUTE format(
          'ALTER TABLE public.%I ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text',
          legacy_table_name
        );
      END IF;
    END IF;

    EXECUTE format('UPDATE public.%I SET tenant_id = ''default'' WHERE tenant_id IS NULL', legacy_table_name);
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN tenant_id SET DEFAULT ''default''', legacy_table_name);
    EXECUTE format('ALTER TABLE public.%I ALTER COLUMN tenant_id SET NOT NULL', legacy_table_name);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON public.%I (tenant_id)',
      'idx_' || legacy_table_name || '_tenant',
      legacy_table_name
    );
  END LOOP;

  IF to_regclass('public.prompt_versions') IS NOT NULL
     AND to_regclass('public.prompts') IS NOT NULL THEN
    UPDATE public.prompt_versions AS versions
    SET tenant_id = prompts.tenant_id
    FROM public.prompts AS prompts
    WHERE versions.prompt_id = prompts.id
      AND versions.tenant_id = 'default'
      AND prompts.tenant_id <> 'default';
  END IF;
END
$$;

DO $$
BEGIN
  IF to_regclass('public.prompts') IS NOT NULL THEN
    ALTER TABLE public.prompts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.prompts FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS prompts_tenant_access ON public.prompts;
    CREATE POLICY prompts_tenant_access ON public.prompts
      AS PERMISSIVE FOR ALL TO authenticated
      USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())
      WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id());
  END IF;

  IF to_regclass('public.bots') IS NOT NULL THEN
    ALTER TABLE public.bots ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.bots FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS bots_tenant_access ON public.bots;
    CREATE POLICY bots_tenant_access ON public.bots
      AS PERMISSIVE FOR ALL TO authenticated
      USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())
      WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id());
  END IF;

  IF to_regclass('public.model_configs') IS NOT NULL THEN
    ALTER TABLE public.model_configs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.model_configs FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS model_configs_tenant_access ON public.model_configs;
    CREATE POLICY model_configs_tenant_access ON public.model_configs
      AS PERMISSIVE FOR ALL TO authenticated
      USING (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id())
      WITH CHECK (auth.uid() IS NOT NULL AND tenant_id = public.jwt_tenant_id());
  END IF;

  IF to_regclass('public.prompt_versions') IS NOT NULL THEN
    ALTER TABLE public.prompt_versions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.prompt_versions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS prompt_versions_tenant_access ON public.prompt_versions;
    CREATE POLICY prompt_versions_tenant_access ON public.prompt_versions
      AS PERMISSIVE FOR ALL TO authenticated
      USING (
        auth.uid() IS NOT NULL
        AND tenant_id = public.jwt_tenant_id()
        AND EXISTS (
          SELECT 1
          FROM public.prompts
          WHERE prompts.id = prompt_versions.prompt_id
            AND prompts.tenant_id = prompt_versions.tenant_id
        )
      )
      WITH CHECK (
        auth.uid() IS NOT NULL
        AND tenant_id = public.jwt_tenant_id()
        AND EXISTS (
          SELECT 1
          FROM public.prompts
          WHERE prompts.id = prompt_versions.prompt_id
            AND prompts.tenant_id = prompt_versions.tenant_id
        )
      );
  END IF;
END
$$;

-- Replace the old unscoped hybrid-search functions. The old signatures are
-- dropped so callers cannot accidentally keep invoking an all-tenant variant.
DROP FUNCTION IF EXISTS public.hybrid_search_vector(vector, integer);
DROP FUNCTION IF EXISTS public.hybrid_search_keyword(text, integer);

CREATE OR REPLACE FUNCTION public.hybrid_search_vector(
  query_embedding vector(1536),
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    (1 - (ke.embedding <=> $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.embedding IS NOT NULL
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY ke.embedding <=> $1
  LIMIT $2
$$;

CREATE OR REPLACE FUNCTION public.hybrid_search_keyword(
  query_text text,
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    ts_rank_cd(ke.search_vector, plainto_tsquery('simple', $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.search_vector @@ plainto_tsquery('simple', $1)
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY similarity DESC
  LIMIT $2
$$;

-- >>> supabase/migration-030-tenant-rls-verification.sql
-- Forward-only follow-up: enable RLS on the release/DORA tables and remove
-- the legacy unscoped quality-rule RPC overload.

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'diagnosis_sessions', 'diagnosis_findings', 'diagnosis_reviews',
    'diagnosis_work_items', 'feedback_records', 'release_manifests',
    'release_evidences', 'dora_metrics', 'rollback_drills'
  ] LOOP
    IF to_regclass(format('public.%I', table_name)) IS NULL THEN
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

DROP FUNCTION IF EXISTS public.match_quality_rules(vector, integer);

-- >>> supabase/migration-031-tenant-rls-force.sql
-- Forward-only tenant hardening follow-up.
-- Every table carrying tenant_id must remain protected even for table owners.
-- The dynamic query keeps this reconciliation current as tenant tables grow.

DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOR table_name IN
    SELECT DISTINCT c.table_name
    FROM information_schema.columns AS c
    JOIN information_schema.tables AS t
      ON t.table_schema = c.table_schema
     AND t.table_name = c.table_name
    WHERE c.table_schema = 'public'
      AND c.column_name = 'tenant_id'
      AND t.table_type = 'BASE TABLE'
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END
$$;

-- >>> supabase/migration-032-tenant-core-tables-columns.sql
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

-- >>> supabase/migration-033-release-evidence.sql
-- Sprint 8: Release evidence table for governed deployments.
-- The release-evidence API (/api/qa/release-evidence) referenced release_evidences
-- but no migration ever created it — this fills the gap so the panel returns
-- real rows instead of a missing-table error.
-- Additive migration; safe to rerun.
CREATE TABLE IF NOT EXISTS release_evidences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL DEFAULT 'default',
  commit_sha TEXT NOT NULL,
  build_id TEXT,
  schema_version TEXT,
  rule_version TEXT,
  prompt_version TEXT,
  model_version TEXT,
  issue_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  pr_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  adr_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  required_checks JSONB NOT NULL DEFAULT '{}'::jsonb,
  checks_passed BOOLEAN NOT NULL DEFAULT false,
  checks_failed JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending',
  feature_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  target_cohort TEXT,
  target_percentage NUMERIC(5,2) NOT NULL DEFAULT 0,
  correlation_id TEXT,
  approver_id UUID REFERENCES profiles(id),
  approver_name TEXT,
  approval_reason TEXT,
  approved_at TIMESTAMPTZ,
  canary_current_stage TEXT,
  observation_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  observation_started_at TIMESTAMPTZ,
  observation_ended_at TIMESTAMPTZ,
  rollback_triggered BOOLEAN NOT NULL DEFAULT false,
  rollback_reason TEXT,
  rollback_method TEXT,
  rollback_executed_at TIMESTAMPTZ,
  rollback_executed_by UUID,
  final_conclusion TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_release_evidences_tenant_status
  ON release_evidences(tenant_id, status, created_at DESC);
ALTER TABLE release_evidences ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
  CREATE POLICY "Release evidences readable by all authenticated"
    ON release_evidences FOR SELECT USING (auth.uid() IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$
BEGIN
  CREATE POLICY "Release evidences writable by service_role"
    ON release_evidences FOR ALL USING (auth.role() = 'service_role');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- >>> supabase/migration-rag-shadow.sql
-- ============================================================
-- 迁移: RAG 规则库 + 影子模式 + 校准端点
-- 执行方式: 在 Supabase SQL Editor 中逐段执行
-- ============================================================

-- ── 1. 启用 pgvector 扩展 ─────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ── 2. 质检规则库 (quality_rules) ──────────────────────────
CREATE TABLE IF NOT EXISTS quality_rules (
  id            BIGSERIAL PRIMARY KEY,
  category      TEXT NOT NULL,
  rule_text     TEXT NOT NULL,
  deduction_min INT NOT NULL DEFAULT 2,
  deduction_max INT NOT NULL DEFAULT 15,
  severity      TEXT NOT NULL DEFAULT 'major' CHECK (severity IN ('minor', 'major', 'critical')),
  examples      TEXT,
  embedding     vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_quality_rules_embedding
  ON quality_rules USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

-- ── 3. 向量相似度检索函数 ─────────────────────────────────
CREATE OR REPLACE FUNCTION match_quality_rules(
  query_embedding vector(1536),
  match_count int DEFAULT 5
)
RETURNS TABLE (
  id BIGINT,
  category TEXT,
  rule_text TEXT,
  deduction_min INT,
  deduction_max INT,
  severity TEXT,
  examples TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    qr.id,
    qr.category,
    qr.rule_text,
    qr.deduction_min,
    qr.deduction_max,
    qr.severity,
    qr.examples,
    1 - (qr.embedding <=> query_embedding) AS similarity
  FROM quality_rules qr
  ORDER BY qr.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── 4. 质量报告表新增字段 ─────────────────────────────────
ALTER TABLE quality_reports
  ADD COLUMN IF NOT EXISTS review_mode TEXT NOT NULL DEFAULT 'active'
    CHECK (review_mode IN ('shadow', 'active')),
  ADD COLUMN IF NOT EXISTS human_score INT
    CHECK (human_score IS NULL OR (human_score BETWEEN 0 AND 100));

-- ── 5. 校准视图 (AI vs Human 对比) ─────────────────────────
CREATE OR REPLACE VIEW alignment_view AS
SELECT
  id,
  total_score AS ai_score,
  human_score,
  risk_level AS ai_risk,
  CASE
    WHEN human_score >= 90 THEN 'low'
    WHEN human_score >= 75 THEN 'medium'
    WHEN human_score >= 60 THEN 'high'
    ELSE 'critical'
  END AS human_risk
FROM quality_reports
WHERE review_mode = 'shadow'
  AND human_score IS NOT NULL
  AND status = 'confirmed';

-- 索引
CREATE INDEX IF NOT EXISTS idx_reports_review_mode ON quality_reports(review_mode);

-- >>> seed-data.sql
-- ============================================================
-- E-Sentinel Seed Data — 50+ realistic records
-- Beauty/Skincare brand on multi-platform e-commerce
-- Uses subqueries for platform FK lookups (no hardcoded UUIDs)
-- ============================================================

-- ── Profiles (users) ────────────────────────────────────────
INSERT INTO profiles (id, name, role, team_id) VALUES
  ('a0000000-0000-0000-0000-000000000001', '张明', 'admin', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000002', '李婷', 'team_lead', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000003', '王芳', 'agent', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000004', '赵强', 'agent', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000005', '陈雪', 'team_lead', 'team_beauty')
ON CONFLICT (id) DO NOTHING;

-- ── User Roles ──────────────────────────────────────────────
INSERT INTO user_roles (profile_id, role, assigned_by) VALUES
  ('a0000000-0000-0000-0000-000000000001', 'admin', NULL),
  ('a0000000-0000-0000-0000-000000000002', 'operator', 'a0000000-0000-0000-0000-000000000001'),
  ('a0000000-0000-0000-0000-000000000003', 'agent', 'a0000000-0000-0000-0000-000000000001'),
  ('a0000000-0000-0000-0000-000000000004', 'agent', 'a0000000-0000-0000-0000-000000000001'),
  ('a0000000-0000-0000-0000-000000000005', 'operator', 'a0000000-0000-0000-0000-000000000001')
ON CONFLICT (profile_id) DO NOTHING;

-- ── Bot Chat Sessions (30 sessions across 5 platforms) ──────
-- Session 1: tmall pre-sale — converted
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000001', p.id, 'pre_sale', 'tmall-sess-001', 'cust_zhang', true, true, 'converted', 4, 'good', 8, 1200, 180000, ARRAY['美白','精华液'],
  '顾客: 你好，我想了解一下你们新出的美白精华液
机器人: 您好！感谢咨询～我们的焕白精华液含有烟酰胺+传明酸双重美白成分，适合所有肤质
顾客: 我是敏感肌，能用吗？
机器人: 完全可以用哦！我们产品通过了敏感肌测试，不含酒精、香精，pH值温和。建议第一次使用先在耳后测试
顾客: 价格呢？现在有活动吗
机器人: 618活动价179元/30ml，买2件享8折，还赠同款小样3支。现在是预售期最划算的时候
顾客: 好，那我买两瓶试试
机器人: 已为您生成订单链接，请点击查看～祝您肌肤越来越亮白✨',
  'corr-sess-001', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 2: tmall post-sale — allergy complaint (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000002', p.id, 'post_sale', 'tmall-sess-002', 'cust_li', true, false, NULL, 2, 'bad', 12, 1500, 360000, ARRAY['退货','过敏'],
  '顾客: 我用了你们的美白精华之后脸上发红发痒
机器人: 非常抱歉给您带来不好的体验！请问您使用前有做过敏测试吗？
顾客: 没有，你们说敏感肌可以用我就直接用了
机器人: 理解您的心情。我们的产品确实经过敏感肌测试，但每个人的肤质不同。建议您先停止使用，我们会为您办理退货退款
顾客: 我要退货，而且你们要承担运费
机器人: 退货是支持的，但运费需要您承担哦。我们的退换货政策是不影响二次销售的情况下支持7天无理由退货
顾客: 但是是你们的产品导致我过敏的！这不公平
机器人: 我理解您的诉求，但运费问题我这边确实无法处理，需要您联系人工客服
顾客: 真麻烦，算了退货吧',
  'corr-sess-002', NOW() - INTERVAL '27 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 3: jd pre-sale — converted
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000003', p.id, 'pre_sale', 'jd-sess-001', 'cust_wang', true, true, 'converted', 5, 'good', 6, 800, 120000, ARRAY['面霜','保湿'],
  '顾客: 推荐一款适合干皮的面霜
机器人: 推荐我们的玻尿酸保湿面霜！含有三重玻尿酸+神经酰胺，深层补水锁水，干皮救星
顾客: 和某蔻比怎么样？
机器人: 我们的面霜保湿时长实测达到48小时，成分表更干净，价格只要某蔻的三分之一哦
顾客: 油皮能用吗
机器人: 这款是针对干皮和混干的，油皮建议选择我们的清爽乳液系列～需要我推荐吗？
顾客: 行，那就先买这个面霜',
  'corr-sess-003', NOW() - INTERVAL '26 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 4: douyin pre-sale — lost
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000004', p.id, 'pre_sale', 'douyin-sess-001', 'cust_zhao', true, true, 'lost', 3, 'neutral', 10, 2000, NULL, ARRAY['口红','试色'],
  '顾客: 你们那个豆沙色口红还有货吗
机器人: 有的呢～我们的丝绒哑光唇釉#301豆沙色现货充足。需要看试色图吗？
顾客: 发来看看
机器人: [图片]这是我们模特上唇效果，黄皮也显白哦
顾客: 有没有更偏粉的
机器人: 那推荐#302蜜桃豆沙，比#301更粉嫩一点
顾客: 我不敢盲买，有没有试用装
机器人: 抱歉目前没有试用装活动呢。不过我们支持7天无理由退货
顾客: 那算了我再看看吧',
  'corr-sess-004', NOW() - INTERVAL '25 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 5: tmall post-sale — wrong item complaint (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000005', p.id, 'post_sale', 'tmall-sess-003', 'cust_chen', true, false, NULL, 1, 'bad', 9, 1000, 600000, ARRAY['投诉','发错货'],
  '顾客: 我买的面霜你们给我发成乳液了！
机器人: 非常抱歉！请提供您的订单号，我帮您核实
顾客: TM202405061234
机器人: 已查到您的订单。确实是我们仓库发错了，非常抱歉！我们马上为您补发正确的面霜，乳液无需退回
顾客: 那我要等多久？
机器人: 补发预计3-5个工作日送达。作为补偿，我们会为您发放30元优惠券
顾客: 30块？耽误我这么久就给30？
机器人: 这个...我这边只能给到30元优惠券的权限，更多补偿需要联系人工客服
顾客: 你们就是这么对待老客户的？',
  'corr-sess-005', NOW() - INTERVAL '24 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 6: pdd pre-sale — converted
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000006', p.id, 'pre_sale', 'pdd-sess-001', 'cust_sun', true, true, 'converted', 4, 'good', 5, 600, 90000, ARRAY['防晒','夏天'],
  '顾客: 有清爽不油腻的防晒吗
机器人: 推荐我们的水感防晒乳！SPF50+ PA+++，轻薄乳液质地，上脸不油腻不泛白
顾客: 多少钱
机器人: 日常价89元/50ml，现在拼团价只要59元！
顾客: 买！',
  'corr-sess-006', NOW() - INTERVAL '23 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 7: jd post-sale — logistics delay (neutral)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000007', p.id, 'post_sale', 'jd-sess-002', 'cust_zhou', true, false, NULL, 3, 'neutral', 7, 1300, 240000, ARRAY['物流','催单'],
  '顾客: 我的订单三天了还没发货
机器人: 您好，我帮您查询一下。您的订单JD202405078901，目前显示正在仓库配货中
顾客: 为什么这么慢？
机器人: 近期618大促订单量较大，仓库处理时间有所延长，请您谅解
顾客: 什么时候能发？
机器人: 预计明天内会更新物流信息。我们会为您标注加急处理
顾客: 行吧，希望别让我失望',
  'corr-sess-007', NOW() - INTERVAL '22 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 8: douyin pre-sale — sensitive skin kit (good, transferred to human for complex query)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000008', p.id, 'pre_sale', 'douyin-sess-002', 'cust_wu', false, 'complex_product_query', true, 'converted', 4, 'good', 14, 1800, 420000, ARRAY['套装','敏感肌','成分'],
  '顾客: 我是敏感肌，想找一套完整的护肤流程
机器人: 了解！我们为敏感肌专门研发了舒缓修护系列，包括氨基酸洁面+舒缓水+修护精华+屏障面霜
顾客: 成分安全吗？有没有致痘成分
机器人: 全系列不含酒精、香精、色素、矿物油，通过皮肤科测试。这是完整的成分表 [链接]
顾客: 我是学生党，预算有限
机器人: 可以试试我们的入门套装，洁面+水+面霜三件套，学生价199元
顾客: 会闷痘吗
机器人: 不会的呢，全线无致痘成分。修护精华含有积雪草提取物，反而有助于痘肌修护
顾客: 好吧我下单试试',
  'corr-sess-008', NOW() - INTERVAL '21 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 9: tmall pre-sale — eye cream (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000009', p.id, 'pre_sale', 'tmall-sess-004', 'cust_huang', true, true, 'converted', 5, 'good', 4, 700, 60000, ARRAY['眼霜','抗老'],
  '顾客: 25岁开始用眼霜早不早
机器人: 不早哦！眼部是最先显老的部位，25岁是开始抗初老的最佳时机
顾客: 推荐一下
机器人: 我们的多肽紧致眼霜，含六胜肽+咖啡因，淡化细纹、消浮肿，一涂化水不厚重
顾客: 下单了',
  'corr-sess-009', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 10: pdd post-sale — authenticity doubt (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000010', p.id, 'post_sale', 'pdd-sess-002', 'cust_liu', true, false, NULL, 2, 'bad', 8, 1400, 480000, ARRAY['质量问题','假货质疑'],
  '顾客: 你们这个洗面奶和我之前在专柜买的味道不一样
机器人: 您好，我们是品牌官方旗舰店，所有产品均为正品，请您放心
顾客: 但是闻起来就是不一样，而且泡沫也少
机器人: 不同批次的产品在气味上可能有轻微差异，这是因为我们使用的是天然植物提取成分。泡沫多少也与水质和用量有关
顾客: 你们是不是真假混卖？
机器人: 绝对没有这种情况！我们是品牌直营店，有品牌授权书。如果您不满意，可以申请退货
顾客: 退货多麻烦，我就想知道是不是正品
机器人: 我们可以提供该批次的质检报告，需要的话请留邮箱
顾客: 算了你们也证明不了什么',
  'corr-sess-010', NOW() - INTERVAL '19 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 11: jd pre-sale — mask (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000011', p.id, 'pre_sale', 'jd-sess-003', 'cust_yang', true, true, 'converted', 5, 'good', 7, 900, 150000, ARRAY['面膜','补水'],
  '顾客: 补水面膜有推荐吗
机器人: 推荐我们的玻尿酸补水面膜！每片含25ml精华液，超薄天丝膜布，敷完水润一整天
顾客: 天天敷可以吗
机器人: 建议每周2-3次即可，过度水合反而不好哦
顾客: 好的，买两盒',
  'corr-sess-011', NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 12: douyin post-sale — timeout escalation (bad, critical complaint)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000012', p.id, 'post_sale', 'douyin-sess-003', 'cust_gao', false, 'escalation_timeout', false, NULL, 1, 'bad', 15, 3000, 720000, ARRAY['投诉','客服态度'],
  '顾客: 我昨天问的问题你们还没回复
机器人: 您好，请问是什么问题呢？
顾客: 我说了我的爽肤水漏液了！你们说会处理，然后就没下文了
机器人: 非常抱歉！我没有查到之前的记录。能否重新描述一下问题？
顾客: 你们内部不沟通的吗？？每次都要我重新说一遍
机器人: 实在抱歉给您带来不便。请提供订单号和漏液照片，我马上处理
顾客: 已经发过了！DY202405102345，照片昨天就发了
机器人: 感谢您的耐心，我查到记录了一个破损补发申请，目前状态是审核中
顾客: 审核要多久？
机器人: 一般1-3个工作日
顾客: 三天了还在审核，你们效率太低了
机器人: 我帮您催促进度，预计今天内会有结果',
  'corr-sess-012', NOW() - INTERVAL '17 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 13: tmall pre-sale — price comparison (lost)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000013', p.id, 'pre_sale', 'tmall-sess-005', 'cust_ma', true, true, 'lost', 3, 'neutral', 9, 1100, NULL, ARRAY['价格','比价'],
  '顾客: 你们这个和某品牌比哪个好
机器人: 我们的产品采用的是进口原料，配方经过3年研发，效果有临床数据支撑
顾客: 但是某品牌便宜很多啊
机器人: 我们的性价比其实更高，因为有效成分浓度是同类产品的2倍
顾客: 有没有优惠券
机器人: 目前店铺券满300减30，还可叠加平台跨店满减
顾客: 还是有点贵，我再看看',
  'corr-sess-013', NOW() - INTERVAL '16 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 14: pdd pre-sale — oil control cleanser (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000014', p.id, 'pre_sale', 'pdd-sess-003', 'cust_hu', true, true, 'converted', 4, 'good', 5, 500, 80000, ARRAY['洁面','油皮'],
  '顾客: 油皮用什么洁面好
机器人: 推荐我们的水杨酸控油洁面！含水杨酸+茶树精油，深层清洁毛孔，控油不紧绷
顾客: 会不会太刺激
机器人: 水杨酸浓度0.5%，温和去角质，日常使用完全OK
顾客: 好，买一支试试',
  'corr-sess-014', NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 15: jd post-sale — shade exchange (neutral)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000015', p.id, 'post_sale', 'jd-sess-004', 'cust_lin', true, false, NULL, 3, 'neutral', 8, 1200, 300000, ARRAY['换货','色号'],
  '顾客: 买的粉底液颜色太白了
机器人: 好的，请问您购买的是哪个色号？
顾客: 自然色，但是我涂上像刷墙
机器人: 理解！自然色可能对您来说偏白了。我们可以为您更换为健康色，这个色号更适合亚洲肤色
顾客: 怎么换？
机器人: 您申请换货即可，不需退货，我们直接为您寄出健康色
顾客: 运费呢
机器人: 换货运费由我们承担，您无需支付任何费用
顾客: 行',
  'corr-sess-015', NOW() - INTERVAL '14 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 16: douyin pre-sale — cleansing oil (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000016', p.id, 'pre_sale', 'douyin-sess-004', 'cust_xu', true, false, NULL, 4, 'good', 6, 900, 100000, ARRAY['卸妆','敏感肌'],
  '顾客: 有没有敏感肌能用的卸妆油
机器人: 推荐我们的氨基酸卸妆油！以氨基酸表活为基底，温和不刺激，眼唇都可以用
顾客: 能卸防水睫毛膏吗
机器人: 可以哦，湿手湿脸也能用，乳化速度快，不会糊眼睛
顾客: 那我买一瓶',
  'corr-sess-016', NOW() - INTERVAL '13 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 17: tmall post-sale — medical complaint (bad, severe)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000017', p.id, 'post_sale', 'tmall-sess-006', 'cust_he', false, 'sensitive_issue', false, NULL, 1, 'bad', 12, 2000, 840000, ARRAY['严重过敏','医疗纠纷','投诉'],
  '顾客: 用完你们产品我脸上起了大片红疹！已经去医院了
机器人: 非常非常抱歉！您的情况我们已经记录。请问方便提供医生的诊断证明吗？
顾客: 医生说是接触性皮炎，开了药膏。你们要负责
机器人: 我们一定会负责到底。请您保存好医疗记录和费用凭证，我们会安排专人跟进
顾客: 谁来跟进？不要又是机器人回复
机器人: 这个case会转接给我们的客诉专员，48小时内会给您电话沟通。同时我们会承担合理的医疗费用
顾客: 希望你们说到做到',
  'corr-sess-017', NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 18: pdd pre-sale — lip balm (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000018', p.id, 'pre_sale', 'pdd-sess-004', 'cust_deng', true, true, 'converted', 5, 'good', 4, 400, 45000, ARRAY['唇膏','秋冬'],
  '顾客: 嘴唇干裂用什么
机器人: 推荐我们的蜂蜜修护唇膏！含蜂蜡+维生素E，深层滋润，一抹化水不粘腻
顾客: 多少钱
机器人: 29元/支，买2送1
顾客: 下单2支',
  'corr-sess-018', NOW() - INTERVAL '11 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 19: xiaohongshu pre-sale — social referral (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000019', p.id, 'pre_sale', 'xiaohongshu-sess-001', 'cust_feng', true, true, 'converted', 5, 'good', 7, 1000, 180000, ARRAY['种草','推荐'],
  '顾客: 小红书种草了你们家的精华，适合混油皮吗
机器人: 适合的！我们的焕白精华是清爽水润质地，混油皮用不会觉得油腻。小红书上的好评可以参考我们官方账号
顾客: 和博主说的一样好用吗
机器人: 保证正品！而且我们有30天无忧退换服务，不满意随时退
顾客: 好，那我也跟风入一瓶',
  'corr-sess-019', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'xiaohongshu'
ON CONFLICT (id) DO NOTHING;

-- Session 20: jd post-sale — refund progress (neutral)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000020', p.id, 'post_sale', 'jd-sess-005', 'cust_cao', true, false, NULL, 3, 'neutral', 6, 1100, 200000, ARRAY['退款进度'],
  '顾客: 我的退款什么时候到账
机器人: 您好，退款一般在我们收到退货后3-5个工作日到账
顾客: 快递显示你们已经签收3天了
机器人: 我帮您查一下。您的退款单号RF202405123456，目前状态是仓库已签收、质检中
顾客: 那还要多久
机器人: 质检通过后会立即发起退款，预计1-2个工作日内到账
顾客: 好吧',
  'corr-sess-020', NOW() - INTERVAL '9 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 21: douyin pre-sale — gift for mom (pending)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000021', p.id, 'pre_sale', 'douyin-sess-005', 'cust_wei', true, true, 'pending', 4, 'good', 8, 1200, NULL, ARRAY['礼物','送人'],
  '顾客: 想给妈妈买一套护肤品，推荐一下
机器人: 孝顺！推荐我们的逆龄紧致套装，含精华水+精华液+面霜，适合40+熟龄肌，提拉紧致效果很好
顾客: 包装好看吗？是送人的
机器人: 是的呢，我们的礼盒包装非常精致，还附带贺卡，送礼体面大方
顾客: 妈妈皮肤比较干，够滋润吗
机器人: 够的！面霜是丰润质地，特别适合干燥熟龄肌，很多顾客反馈妈妈用了很喜欢
顾客: 好的，我先看看，晚点下单',
  'corr-sess-021', NOW() - INTERVAL '8 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 22: tmall pre-sale — 618 promotion (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000022', p.id, 'pre_sale', 'tmall-sess-007', 'cust_qin', true, true, 'converted', 5, 'good', 5, 700, 70000, ARRAY['618','大促'],
  '顾客: 618有什么活动
机器人: 618年中大促即将开始！买1件享9折，买2件享8折，买3件享7折。满399还赠价值199元的大礼包！
顾客: 礼包有什么
机器人: 礼包含焕白精华7ml+保湿面霜15g+面膜2片，价值199元
顾客: 这个划算，我凑个399的单',
  'corr-sess-022', NOW() - INTERVAL '7 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 23: pdd post-sale — damaged packaging (bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000023', p.id, 'post_sale', 'pdd-sess-005', 'cust_jin', true, false, NULL, 2, 'bad', 7, 1600, 360000, ARRAY['包装破损'],
  '顾客: 收到货了，但是包装盒都压扁了
机器人: 抱歉给您带来不好的体验！是快递运输的问题。产品本身有损坏吗？
顾客: 产品看起来没事，但是盒子烂了
机器人: 非常抱歉！我们可以为您补偿10元优惠券，下次购物可用
顾客: 才10块？我是要送人的，这盒子怎么送
机器人: 如果您需要，我们可以单独为您寄一个新的包装盒
顾客: 那太麻烦了，算了。以后包装能不能好一点？
机器人: 您的建议我们已经记录，会反馈给仓库改进包装',
  'corr-sess-023', NOW() - INTERVAL '6 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 24: jd pre-sale — ingredient inquiry (lost)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000024', p.id, 'pre_sale', 'jd-sess-006', 'cust_tian', true, true, 'lost', 3, 'neutral', 11, 1400, NULL, ARRAY['成分党','配方'],
  '顾客: 你们精华的成分表能发给我吗
机器人: 当然可以！主成分：烟酰胺4%+传明酸2%+透明质酸钠。完整成分表请查看商品详情页
顾客: 有酒精吗
机器人: 不含酒精
顾客: 香精呢
机器人: 也不含香精，我们的调香来自天然植物精油
顾客: 防腐剂用的什么体系
机器人: 这个问题比较专业，我需要帮您确认一下，请稍等
顾客: 好的
机器人: 抱歉让您久等！我们使用的是多元醇防腐体系（戊二醇+己二醇），不含传统防腐剂
顾客: 嗯，不错。我再研究一下',
  'corr-sess-024', NOW() - INTERVAL '5 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 25: douyin post-sale — repurchase (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000025', p.id, 'post_sale', 'douyin-sess-006', 'cust_xia', true, false, NULL, 4, 'good', 5, 800, 120000, ARRAY['好评','回购'],
  '顾客: 用了一个月效果很好，想再买一瓶
机器人: 感谢您的认可！回购客户我们有专属优惠，输入码「老客回购」享9折
顾客: 太好了，我拉我闺蜜也来买
机器人: 太感谢了！推荐好友下单双方都可获得50积分，积分可兑换正装产品哦
顾客: 好的好的',
  'corr-sess-025', NOW() - INTERVAL '4 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 26: tmall pre-sale — pregnancy safety (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000026', p.id, 'pre_sale', 'tmall-sess-008', 'cust_han', true, true, 'converted', 4, 'good', 7, 900, 160000, ARRAY['孕妇','安全'],
  '顾客: 怀孕了能用你们的产品吗
机器人: 恭喜准妈妈！我们的产品成分安全温和，但孕期建议避开含维A醇、水杨酸的产品。推荐我们的基础保湿系列
顾客: 哪个系列？
机器人: 推荐氨基酸洁面+玻尿酸水+保湿乳的基础保湿三件套，不含孕妇慎用成分
顾客: 你确定安全吗
机器人: 是的，这三款产品无维A、无水杨酸、无酒精。但孕期体质特殊，建议使用前咨询您的产科医生
顾客: 好，那我先买这三件',
  'corr-sess-026', NOW() - INTERVAL '3 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 27: pdd pre-sale — coupon issue (lost, bad)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000027', p.id, 'pre_sale', 'pdd-sess-006', 'cust_tao', false, 'payment_issue', true, 'lost', 2, 'bad', 8, 1500, NULL, ARRAY['支付','优惠券'],
  '顾客: 为什么我领的优惠券用不了
机器人: 请问是哪个优惠券呢
顾客: 新人满200减50的
机器人: 这个券需要您的订单金额满200元才能使用，目前您的购物车金额是178元
顾客: 那我还差22块
机器人: 是的，您可以再选购一件小商品凑单哦
顾客: 我不想多买，你们就不能通融一下吗
机器人: 抱歉优惠券有使用门槛，这个我这边无法调整
顾客: 那算了不要了',
  'corr-sess-027', NOW() - INTERVAL '2 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Session 28: jd post-sale — positive feedback (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000028', p.id, 'post_sale', 'jd-sess-007', 'cust_meng', true, false, NULL, 4, 'good', 5, 700, 100000, ARRAY['好评','效果'],
  '顾客: 用了一周皮肤真的有变好
机器人: 感谢反馈！很高兴我们的产品帮到了您。坚持使用效果会更好哦
顾客: 想问下这个精华早上用还是晚上用
机器人: 美白精华建议晚上使用，白天一定要做好防晒，否则会事倍功半
顾客: 好的谢谢',
  'corr-sess-028', NOW() - INTERVAL '1 day'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Session 29: douyin pre-sale — newbie starter kit (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000029', p.id, 'pre_sale', 'douyin-sess-007', 'cust_pan', true, true, 'converted', 5, 'good', 6, 800, 110000, ARRAY['新手','入门'],
  '顾客: 完全不懂护肤，该从什么开始
机器人: 欢迎入门！基础护肤四步走：清洁→补水→保湿→防晒。推荐我们的新手入门套组
顾客: 套组包含什么
机器人: 氨基酸洁面120ml+玻尿酸爽肤水150ml+保湿乳液100ml+防晒乳50ml，一套搞定基础护肤
顾客: 加起来多少钱
机器人: 单品总价356元，套组价只要269元，相当于75折！非常划算
顾客: 好，就这个了',
  'corr-sess-029', NOW() - INTERVAL '12 hours'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Session 30: tmall post-sale — usage question (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000030', p.id, 'post_sale', 'tmall-sess-009', 'cust_shi', true, false, NULL, 4, 'good', 4, 600, 80000, ARRAY['使用方法'],
  '顾客: 这个精华用在哪一步
机器人: 精华在爽肤水之后、乳液/面霜之前使用。取2-3滴按压在面部，轻轻按摩至吸收
顾客: 早晚都用吗
机器人: 美白精华建议晚上用，保湿精华早晚都可以
顾客: 好的明白了',
  'corr-sess-030', NOW() - INTERVAL '6 hours'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Session 31: xiaohongshu pre-sale — eye mask (good)
INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, created_at)
SELECT 'b0000000-0000-0000-0000-000000000031', p.id, 'pre_sale', 'xiaohongshu-sess-002', 'cust_duan', true, true, 'converted', 5, 'good', 4, 500, 60000, ARRAY['眼膜','黑眼圈'],
  '顾客: 有什么去黑眼圈的产品
机器人: 推荐我们的咖啡因焕亮眼膜！含咖啡因+烟酰胺，针对性淡化黑眼圈，敷15分钟眼下明显提亮
顾客: 每天都能用吗
机器人: 建议每周3-4次，搭配规律作息效果最好
顾客: 下单试试',
  'corr-sess-031', NOW() - INTERVAL '3 hours'
FROM platforms p WHERE p.code = 'xiaohongshu'
ON CONFLICT (id) DO NOTHING;

-- ── Quality Reports (25 reports) ───────────────────────────
-- Report 1: tmall pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000001', 'tmall-sess-001', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 你好，我想了解一下你们新出的美白精华液...', 'pre_sale_product_inquiry',
  4, 92, '[]', 'low', 'confirmed', 'corr-eval-001', 'active', true,
  'b0000000-0000-0000-0000-000000000001', p.id, NOW() - INTERVAL '27 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 2: tmall post-sale — allergy complaint (high risk, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000002', 'tmall-sess-002', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 我用了你们的美白精华之后脸上发红发痒...', 'post_sale_complaint',
  2, 45, '[{"rule":"未主动安抚客户情绪","deduction":15,"source_quote":"我理解您的诉求，但运费问题我这边确实无法处理","severity":"critical"},{"rule":"退换货政策说明不清晰","deduction":10,"source_quote":"退货是支持的，但运费需要您承担哦","severity":"major"},{"rule":"未提供升级路径","deduction":5,"source_quote":"需要您联系人工客服","severity":"minor"}]',
  'high', 'pending_review', 'corr-eval-002', 'active', true,
  'b0000000-0000-0000-0000-000000000002', p.id, NOW() - INTERVAL '27 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 3: jd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000003', 'jd-sess-001', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 推荐一款适合干皮的面霜...', 'pre_sale_product_inquiry',
  5, 96, '[]', 'low', 'confirmed', 'corr-eval-003', 'active', true,
  'b0000000-0000-0000-0000-000000000003', p.id, NOW() - INTERVAL '26 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 4: douyin pre-sale — lost sale (medium risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000004', 'douyin-sess-001', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 你们那个豆沙色口红还有货吗...', 'pre_sale_product_inquiry',
  3, 78, '[{"rule":"未主动挽留流失客户","deduction":10,"source_quote":"抱歉目前没有试用装活动呢","severity":"major"},{"rule":"缺少主动转化引导","deduction":8,"source_quote":"那算了我再看看吧","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-004', 'active', true,
  'b0000000-0000-0000-0000-000000000004', p.id, NOW() - INTERVAL '25 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 5: tmall post-sale — critical complaint (critical, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000005', 'tmall-sess-003', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 我买的面霜你们给我发成乳液了！...', 'post_sale_complaint',
  1, 35, '[{"rule":"补偿方案不足","deduction":15,"source_quote":"更多补偿需要联系人工客服","severity":"critical"},{"rule":"未主动道歉安抚","deduction":10,"source_quote":"确实是我们仓库发错了","severity":"major"},{"rule":"未提供升级路径","deduction":5,"source_quote":"需要联系人工客服","severity":"minor"}]',
  'critical', 'confirmed', 'corr-eval-005', 'active', true,
  'b0000000-0000-0000-0000-000000000005', p.id, NOW() - INTERVAL '24 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 6: pdd pre-sale — minor issue (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000006', 'pdd-sess-001', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 有清爽不油腻的防晒吗...', 'pre_sale_product_inquiry',
  4, 90, '[{"rule":"产品介绍过于简短","deduction":5,"severity":"minor"}]',
  'low', 'confirmed', 'corr-eval-006', 'active', true,
  'b0000000-0000-0000-0000-000000000006', p.id, NOW() - INTERVAL '23 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 7: jd post-sale — logistics (medium risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000007', 'jd-sess-002', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 我的订单三天了还没发货...', 'post_sale_logistics',
  3, 82, '[{"rule":"缺少主动补偿","deduction":10,"source_quote":"我们会为您标注加急处理","severity":"major"},{"rule":"话术过于模板化","deduction":8,"source_quote":"近期618大促订单量较大","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-007', 'active', true,
  'b0000000-0000-0000-0000-000000000007', p.id, NOW() - INTERVAL '22 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 8: douyin pre-sale — human transfer (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000008', 'douyin-sess-002', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 我是敏感肌，想找一套完整的护肤流程...', 'pre_sale_recommend',
  4, 88, '[{"rule":"转人工后响应时间长","deduction":12,"severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-008', 'active', true,
  'b0000000-0000-0000-0000-000000000008', p.id, NOW() - INTERVAL '21 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 9: tmall pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000009', 'tmall-sess-004', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 25岁开始用眼霜早不早...', 'pre_sale_product_inquiry',
  5, 94, '[]', 'low', 'confirmed', 'corr-eval-009', 'active', true,
  'b0000000-0000-0000-0000-000000000009', p.id, NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 10: pdd post-sale — authenticity doubt (high risk, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000010', 'pdd-sess-002', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 你们这个洗面奶和我之前在专柜买的味道不一样...', 'post_sale_quality_doubt',
  2, 52, '[{"rule":"未有效消除客户疑虑","deduction":15,"source_quote":"不同批次的产品在气味上可能有轻微差异","severity":"critical"},{"rule":"语气过于被动防御","deduction":10,"source_quote":"绝对没有这种情况","severity":"major"},{"rule":"未主动提供解决方案","deduction":8,"source_quote":"如果您不满意，可以申请退货","severity":"major"}]',
  'high', 'pending_review', 'corr-eval-010', 'active', true,
  'b0000000-0000-0000-0000-000000000010', p.id, NOW() - INTERVAL '19 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 11: jd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000011', 'jd-sess-003', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 补水面膜有推荐吗...', 'pre_sale_product_inquiry',
  5, 95, '[]', 'low', 'confirmed', 'corr-eval-011', 'active', true,
  'b0000000-0000-0000-0000-000000000011', p.id, NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 12: douyin post-sale — critical complaint (critical, 3 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000012', 'douyin-sess-003', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 我昨天问的问题你们还没回复...', 'post_sale_complaint',
  1, 28, '[{"rule":"多客服信息不共享","deduction":15,"source_quote":"我没有查到之前的记录","severity":"critical"},{"rule":"响应时间过长","deduction":10,"source_quote":"审核中","severity":"major"},{"rule":"反复要求客户重复信息","deduction":8,"source_quote":"请提供订单号和漏液照片","severity":"major"}]',
  'critical', 'confirmed', 'corr-eval-012', 'active', true,
  'b0000000-0000-0000-0000-000000000012', p.id, NOW() - INTERVAL '17 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 13: tmall pre-sale — price compare lost (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000013', 'tmall-sess-005', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 你们这个和某品牌比哪个好...', 'pre_sale_price_compare',
  3, 80, '[{"rule":"比价场景缺乏说服力","deduction":10,"source_quote":"我们的产品采用的是进口原料","severity":"major"},{"rule":"未转化价格敏感客户","deduction":8,"source_quote":"还是有点贵，我再看看","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-013', 'active', true,
  'b0000000-0000-0000-0000-000000000013', p.id, NOW() - INTERVAL '16 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 14: pdd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000014', 'pdd-sess-003', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 油皮用什么洁面好...', 'pre_sale_product_inquiry',
  4, 92, '[]', 'low', 'confirmed', 'corr-eval-014', 'active', true,
  'b0000000-0000-0000-0000-000000000014', p.id, NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 15: jd post-sale — shade exchange (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000015', 'jd-sess-004', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 买的粉底液颜色太白了...', 'post_sale_exchange',
  3, 88, '[]', 'low', 'confirmed', 'corr-eval-015', 'active', true,
  'b0000000-0000-0000-0000-000000000015', p.id, NOW() - INTERVAL '14 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 16: douyin pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000016', 'douyin-sess-004', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 有没有敏感肌能用的卸妆油...', 'pre_sale_product_inquiry',
  4, 91, '[]', 'low', 'confirmed', 'corr-eval-016', 'active', true,
  'b0000000-0000-0000-0000-000000000016', p.id, NOW() - INTERVAL '13 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 17: tmall post-sale — medical complaint (critical)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000017', 'tmall-sess-006', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 用完你们产品我脸上起了大片红疹...', 'post_sale_medical_complaint',
  1, 40, '[{"rule":"医疗投诉处理流程需完善","deduction":20,"source_quote":"这个case会转接给我们的客诉专员","severity":"critical"},{"rule":"首次响应缺少同理心","deduction":10,"source_quote":"请问方便提供医生的诊断证明吗","severity":"major"}]',
  'critical', 'pending_review', 'corr-eval-017', 'active', true,
  'b0000000-0000-0000-0000-000000000017', p.id, NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- Report 18: pdd pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000018', 'pdd-sess-004', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 嘴唇干裂用什么...', 'pre_sale_product_inquiry',
  5, 96, '[]', 'low', 'confirmed', 'corr-eval-018', 'active', true,
  'b0000000-0000-0000-0000-000000000018', p.id, NOW() - INTERVAL '11 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 19: xiaohongshu pre-sale — clean (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000019', 'xiaohongshu-sess-001', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 小红书种草了你们家的精华...', 'pre_sale_social_referral',
  5, 93, '[]', 'low', 'confirmed', 'corr-eval-019', 'active', true,
  'b0000000-0000-0000-0000-000000000019', p.id, NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'xiaohongshu'
ON CONFLICT (id) DO NOTHING;

-- Report 20: jd post-sale — refund progress (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000020', 'jd-sess-005', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 我的退款什么时候到账...', 'post_sale_refund',
  3, 86, '[{"rule":"退款进度话术可优化","deduction":8,"source_quote":"质检通过后会立即发起退款","severity":"major"}]',
  'medium', 'confirmed', 'corr-eval-020', 'active', true,
  'b0000000-0000-0000-0000-000000000020', p.id, NOW() - INTERVAL '9 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 21: pdd post-sale — packaging (high risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000021', 'pdd-sess-005', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 收到货了，但是包装盒都压扁了...', 'post_sale_packaging',
  2, 68, '[{"rule":"补偿力度不足","deduction":15,"source_quote":"我们可以为您补偿10元优惠券","severity":"critical"},{"rule":"未考虑送礼场景","deduction":10,"source_quote":"如果您需要，我们可以单独为您寄一个新的包装盒","severity":"major"}]',
  'high', 'confirmed', 'corr-eval-021', 'active', true,
  'b0000000-0000-0000-0000-000000000023', p.id, NOW() - INTERVAL '6 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 22: jd pre-sale — ingredient inquiry (medium risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000022', 'jd-sess-006', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 你们精华的成分表能发给我吗...', 'pre_sale_ingredient_inquiry',
  3, 85, '[{"rule":"成分查询响应慢","deduction":10,"source_quote":"这个问题比较专业，我需要帮您确认一下","severity":"major"},{"rule":"未转化专业型客户","deduction":5,"source_quote":"我再研究一下","severity":"minor"}]',
  'medium', 'confirmed', 'corr-eval-022', 'active', true,
  'b0000000-0000-0000-0000-000000000024', p.id, NOW() - INTERVAL '5 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

-- Report 23: pdd pre-sale — coupon issue (high risk, 2 violations)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000023', 'pdd-sess-006', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 为什么我领的优惠券用不了...', 'pre_sale_coupon_issue',
  2, 72, '[{"rule":"未挽留因券流失客户","deduction":12,"source_quote":"抱歉优惠券有使用门槛","severity":"critical"},{"rule":"缺少灵活应对方案","deduction":10,"source_quote":"这个我这边无法调整","severity":"major"}]',
  'high', 'pending_review', 'corr-eval-023', 'active', true,
  'b0000000-0000-0000-0000-000000000027', p.id, NOW() - INTERVAL '2 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

-- Report 24: douyin pre-sale — newbie guide (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000024', 'douyin-sess-007', 'a0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000005',
  '顾客: 完全不懂护肤，该从什么开始...', 'pre_sale_newbie_guide',
  5, 94, '[]', 'low', 'confirmed', 'corr-eval-024', 'active', true,
  'b0000000-0000-0000-0000-000000000029', p.id, NOW() - INTERVAL '12 hours'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

-- Report 25: tmall pre-sale — 618 promotion (low risk)
INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, created_at)
SELECT 'c0000000-0000-0000-0000-000000000025', 'tmall-sess-007', 'a0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000002',
  '顾客: 618有什么活动...', 'pre_sale_promotion_inquiry',
  5, 92, '[]', 'low', 'confirmed', 'corr-eval-025', 'active', true,
  'b0000000-0000-0000-0000-000000000022', p.id, NOW() - INTERVAL '7 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- ── Bot Configs (10 configs) ─────────────────────────────────
INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000001', p.id, 'pre_sale', 'greeting_template', '{"greeting":"您好！欢迎光临{{brand}}官方旗舰店～请问有什么可以帮您的？","time_greeting":{"morning":"早上好☀️","afternoon":"下午好🌤","evening":"晚上好🌙"}}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000002', p.id, 'pre_sale', 'product_recommend', '{"strategy":"肤质优先","flow":["询问肤质→确认需求→推荐产品→提供链接"],"upsell":"推荐搭配使用效果更好"}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000003', p.id, 'post_sale', 'return_policy', '{"policy_text":"支持7天无理由退换货，不影响二次销售即可。过敏包退，需提供照片。退货地址：广东省广州市...","auto_approve":true,"auto_approve_amount":200}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000004', p.id, 'post_sale', 'compensation_tiers', '{"tier_1":{"condition":"发货延迟1-3天","compensation":"5元优惠券"},"tier_2":{"condition":"发错货/少发货","compensation":"30元优惠券+补发"},"tier_3":{"condition":"过敏/质量问题","compensation":"全额退款+医疗费(需凭证)"}}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000005', p.id, 'pre_sale', 'live_stream_script', '{"hook":"直播间专属福利来啦！","pain_point":"是不是总觉得自己皮肤暗沉？","solution":"今天给大家带来的是我们的明星产品...","urgency":"库存不多，先到先得！"}', 1, 'draft', 'a0000000-0000-0000-0000-000000000005', '初始版本', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000006', p.id, 'post_sale', 'douyin_after_sales', '{"support_hours":"09:00-22:00","response_sla_minutes":5,"escalation":"3次无解→转人工","satisfaction_survey":true}', 1, 'active', 'a0000000-0000-0000-0000-000000000005', '初始版本', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000007', p.id, 'pre_sale', 'jd_price_match', '{"enable":false,"reason":"品牌控价策略，不参与比价","redirect_msg":"我们的产品品质和效果值得这个价格哦"}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'jd'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000008', p.id, 'pre_sale', 'pdd_low_price_strategy', '{"low_price_tactics":["拼团价","限时秒杀","新人专享"],"upsell_threshold":99,"free_shipping_threshold":29}', 1, 'active', 'a0000000-0000-0000-0000-000000000005', '初始版本', NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'pdd'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000009', p.id, 'pre_sale', 'objection_handling', '{"common_objections":[{"obj":"太贵了","reply":"我们的性价比其实更高，因为有效成分浓度是同类产品的2倍"},{"obj":"会过敏吗","reply":"产品通过敏感肌测试，但建议首次使用先做耳后测试"},{"obj":"和XX比怎么样","reply":"我们的配方更安全，不添加酒精香精，您可以对比成分表"}]}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, created_at, updated_at)
SELECT 'd0000000-0000-0000-0000-000000000010', p.id, 'post_sale', 'complaint_escalation', '{"levels":["初级客服→安抚+记录","中台→48h电话回访","客诉专员→处理医疗投诉"],"sensitive_keywords":["过敏","毁容","医院","12315","投诉","律师","媒体"]}', 1, 'active', 'a0000000-0000-0000-0000-000000000002', '初始版本', NOW() - INTERVAL '8 days', NOW() - INTERVAL '8 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- ── Knowledge Entries (15 entries) ──────────────────────────
INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000001', 'product', p.id, '焕白精华液产品说明',
  '产品名称：焕白精华液 规格：30ml 主要成分：烟酰胺4%+传明酸2%+透明质酸钠 功效：美白淡斑、提亮肤色 适用肤质：所有肤质（含敏感肌） 使用建议：每晚使用，取2-3滴按压吸收 注意事项：白天使用需搭配防晒',
  ARRAY['美白','精华','烟酰胺','淡斑'], ARRAY['明星产品','核心单品'], 10, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000002', 'product', p.id, '玻尿酸保湿面霜产品说明',
  '产品名称：玻尿酸保湿面霜 规格：50g 主要成分：三重玻尿酸+神经酰胺+角鲨烷 功效：深层补水、锁水保湿、修护屏障 适用肤质：干皮、混干 使用建议：早晚使用，取适量均匀涂抹',
  ARRAY['面霜','保湿','玻尿酸','干皮'], ARRAY['明星产品'], 9, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000003', 'faq', p.id, '常见问题：敏感肌能用吗',
  '我们的产品全线经过敏感肌测试，不含酒精、香精、色素、矿物油。但每个人的过敏原不同，建议首次使用前在耳后或手腕内侧做24小时过敏测试。如果出现不适，请立即停用并联系我们。',
  ARRAY['敏感肌','过敏','安全','测试'], ARRAY['FAQ','高频问题'], 8, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000004', 'faq', p.id, '常见问题：孕妇能用吗',
  '孕期建议避开含维A醇（视黄醇）、水杨酸、果酸的产品。我们推荐的基础保湿三件套（氨基酸洁面+玻尿酸水+保湿乳）不含上述成分，适合孕期使用。但因孕期体质特殊，建议使用前咨询产科医生。',
  ARRAY['孕妇','怀孕','安全','成分'], ARRAY['FAQ','安全类'], 8, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000005', 'after_sales_policy', p.id, '退换货政策',
  '1. 7天无理由退货：不影响二次销售即可（未拆封、未使用） 2. 过敏退货：提供过敏照片+停止使用，全额退款 3. 发错货：免费补发正确商品，错误商品无需退回 4. 质量问题：提供照片/视频证明，全额退款或换货 5. 退货地址：广东省广州市白云区XX产业园XX栋 6. 退款时效：收到退货后3-5个工作日内到账',
  ARRAY['退货','退款','换货','政策','售后'], ARRAY['售后政策','重要'], 9, 'published', 2, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '25 days', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000006', 'product', p.id, '水感防晒乳产品说明',
  '产品名称：水感防晒乳 规格：50ml SPF值：SPF50+ PA+++ 主要成分：物理+化学双重防晒 功效：防晒、清爽不油腻 适用肤质：所有肤质 使用建议：出门前20分钟涂抹，每2-3小时补涂',
  ARRAY['防晒','清爽','SPF50','夏天'], ARRAY['夏季热销'], 7, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '22 days', NOW() - INTERVAL '22 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000007', 'campaign', p.id, '618年中大促活动规则',
  '活动时间：6月1日-6月20日 优惠力度：买1件9折/买2件8折/买3件7折 满赠：满399元赠价值199元大礼包（精华7ml+面霜15g+面膜2片） 叠加：可叠加平台跨店满减 老客专属：输入暗号「老客回购」额外9折 积分翻倍：活动期间购买享双倍积分',
  ARRAY['618','大促','优惠','满减','折扣'], ARRAY['大促活动','促销'], 10, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000008', 'product', p.id, '多肽紧致眼霜产品说明',
  '产品名称：多肽紧致眼霜 规格：15g 主要成分：六胜肽+咖啡因+透明质酸 功效：淡化细纹、消除浮肿、紧致眼周 适用肤质：所有肤质 使用建议：早晚使用，取米粒大小点涂在眼周，轻拍至吸收',
  ARRAY['眼霜','抗老','细纹','黑眼圈'], ARRAY['明星产品'], 7, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000009', 'faq', p.id, '常见问题：使用顺序',
  '基础护肤使用顺序（日间）：洁面→爽肤水→精华→眼霜→乳液/面霜→防晒 基础护肤使用顺序（夜间）：卸妆→洁面→爽肤水→精华→眼霜→乳液/面霜 美白精华建议夜间使用，保湿精华早晚均可',
  ARRAY['使用顺序','步骤','护肤流程'], ARRAY['FAQ','使用指南'], 6, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000010', 'product', p.id, '丝绒哑光唇釉产品说明',
  '产品名称：丝绒哑光唇釉 规格：4.5g 色号：#301豆沙色、#302蜜桃豆沙、#303复古红、#304珊瑚橘 质地：丝绒哑光，上嘴轻薄不拔干 特色：食品级安全配方，持色8小时',
  ARRAY['口红','唇釉','哑光','豆沙色'], ARRAY['彩妆','爆款'], 6, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'
FROM platforms p WHERE p.code = 'douyin'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000011', 'greeting', p.id, '天猫旗舰店欢迎语',
  '{{time_greeting}}欢迎光临{{brand}}官方旗舰店～ 我们主营温和高效的护肤产品，全线通过敏感肌测试。618大促进行中，买3件享7折！ 有任何护肤问题都可以问我哦 💕',
  ARRAY['欢迎','问候','618'], ARRAY['欢迎语','天猫'], 5, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000012', 'after_sales_policy', p.id, '物流与配送政策',
  '发货时效：正常订单48小时内发货，大促期间72小时内 快递合作：顺丰/中通（随机） 包邮政策：满99元包邮，不满99元运费8元 偏远地区：新疆、西藏、内蒙古加收15元 物流查询：提供订单号即可查询实时物流',
  ARRAY['物流','快递','发货','包邮'], ARRAY['售后政策'], 5, 'published', 1, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '12 days', NOW() - INTERVAL '12 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000013', 'campaign', p.id, '新客专享活动',
  '新客首单礼：注册即领满200减50新人券（有效期30天） 首单赠品：下单即赠焕白精华7ml试用装 邀请有礼：邀请好友下单双方各获50积分（积分可兑换正装） 会员体系：消费1元=1积分，积分商城定期上新',
  ARRAY['新人','首单','优惠券','积分'], ARRAY['拉新活动'], 8, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000014', 'product', p.id, '氨基酸洁面产品说明',
  '产品名称：氨基酸洁面乳 规格：120ml 主要成分：氨基酸表活+甘油+积雪草提取物 功效：温和清洁、不紧绷、修护屏障 适用肤质：所有肤质，尤其推荐敏感肌 起泡方式：湿手揉搓或搭配起泡网',
  ARRAY['洁面','氨基酸','温和','敏感肌'], ARRAY['基础护肤'], 6, 'published', 1, 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '25 days', NOW() - INTERVAL '25 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, version, updated_by, created_at, updated_at)
SELECT 'e0000000-0000-0000-0000-000000000015', 'faq', p.id, '常见问题：真假辨别',
  '辨别正品方法：1. 扫描包装二维码可跳转官网验证 2. 正品包装有激光防伪标签 3. 正品瓶身底部有生产批号（可通过官网查询） 4. 我们每个批次都有质检报告，可联系客服索取 温馨提示：请认准官方旗舰店和授权店，非授权渠道无法保证正品',
  ARRAY['正品','真假','辨别','防伪'], ARRAY['FAQ','信任类'], 9, 'published', 2, 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '20 days', NOW() - INTERVAL '5 days'
FROM platforms p WHERE p.code = 'tmall'
ON CONFLICT (id) DO NOTHING;

-- ── Optimization Tasks (10 tasks) ──────────────────────────
INSERT INTO optimization_tasks (id, source, category, title, description, priority, status, platform_id, related_chat_id, related_knowledge_id, assigned_to, impact_estimate, created_by, created_at) VALUES
('f0000000-0000-0000-0000-000000000001', 'chat_inspection', '话术优化', '过敏投诉场景增加主动安抚话术', '质检发现多起过敏投诉中机器人回复缺少同理心，直接进入退换货流程。需要在首次回应中增加情绪安抚模板', 'critical', 'open', (SELECT id FROM platforms WHERE code='tmall'), 'b0000000-0000-0000-0000-000000000002', NULL, 'a0000000-0000-0000-0000-000000000005', '预计减少差评30%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '26 days'),
('f0000000-0000-0000-0000-000000000002', 'chat_inspection', '流程优化', '客服信息同步机制建立', '多客服转接时信息不共享导致客户重复描述问题。需要建立会话上下文传递机制', 'critical', 'in_progress', (SELECT id FROM platforms WHERE code='douyin'), 'b0000000-0000-0000-0000-000000000012', NULL, 'a0000000-0000-0000-0000-000000000005', '预计减少客户重复沟通时间50%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '17 days'),
('f0000000-0000-0000-0000-000000000003', 'inquiry_loss', '话术优化', '比价场景增加价值证明话术', '用户因价格疑虑流失。需要在比价回复中补充成分浓度对比、临床数据、用户口碑等价值证明', 'high', 'open', (SELECT id FROM platforms WHERE code='jd'), 'b0000000-0000-0000-0000-000000000024', NULL, 'a0000000-0000-0000-0000-000000000003', '预计提升转化率5%', 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '5 days'),
('f0000000-0000-0000-0000-000000000004', 'chat_inspection', '知识库更新', '补充防腐剂体系专业知识', '成分党客户询问防腐剂体系时机器人无法即时回答。需将各产品线的防腐体系加入知识库', 'medium', 'resolved', (SELECT id FROM platforms WHERE code='jd'), 'b0000000-0000-0000-0000-000000000024', 'e0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000005', '预计减少转人工率3%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '4 days'),
('f0000000-0000-0000-0000-000000000005', 'satisfaction', '流程优化', '差评补偿体系优化', '包装破损和发错货的补偿力度不足导致差评。建议将发错货补偿从30元提升至50元优惠券+免邮', 'high', 'open', (SELECT id FROM platforms WHERE code='pdd'), 'b0000000-0000-0000-0000-000000000023', NULL, 'a0000000-0000-0000-0000-000000000002', '预计减少差评率10%', 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '6 days'),
('f0000000-0000-0000-0000-000000000006', 'chat_inspection', '话术优化', '试用装缺失场景增加替代方案', '因无试用装导致客户流失。建议增加"可购买旅行装体验"或"建议先购买30ml小规格"的替代转化话术', 'high', 'open', (SELECT id FROM platforms WHERE code='douyin'), 'b0000000-0000-0000-0000-000000000004', NULL, 'a0000000-0000-0000-0000-000000000003', '预计减少流失率8%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '24 days'),
('f0000000-0000-0000-0000-000000000007', 'knowledge_gap', '知识库更新', '增加各肤质推荐产品矩阵', '多个会话中客户同时询问多个肤质适用性。建议建立"肤质×产品"推荐矩阵知识条目', 'medium', 'open', (SELECT id FROM platforms WHERE code='tmall'), NULL, NULL, 'a0000000-0000-0000-0000-000000000005', '预计减少会话轮次2-3轮', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '7 days'),
('f0000000-0000-0000-0000-000000000008', 'manual', '流程优化', '抖音直播话术脚本定稿', '抖音直播带货脚本目前仍是draft状态。需要运营团队审核定稿并在下次直播中AB测试', 'medium', 'open', (SELECT id FROM platforms WHERE code='douyin'), NULL, 'e0000000-0000-0000-0000-000000000010', 'a0000000-0000-0000-0000-000000000004', '提升抖音渠道转化率', 'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '3 days'),
('f0000000-0000-0000-0000-000000000009', 'satisfaction', '流程优化', '真假质疑场景增加信任背书', '客户质疑正品时机器人回复过于被动防御。需要增加品牌授权书展示、质检报告链接、防伪查询指引', 'high', 'in_progress', (SELECT id FROM platforms WHERE code='pdd'), 'b0000000-0000-0000-0000-000000000010', 'e0000000-0000-0000-0000-000000000015', 'a0000000-0000-0000-0000-000000000003', '预计减少信任类流失20%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '18 days'),
('f0000000-0000-0000-0000-000000000010', 'chat_inspection', '话术优化', '逾期未回复客户增加进度通知', '客户等待3天未收到回复导致严重投诉。建议增加自动"处理进度通知"卡片', 'critical', 'open', (SELECT id FROM platforms WHERE code='douyin'), 'b0000000-0000-0000-0000-000000000012', NULL, 'a0000000-0000-0000-0000-000000000003', '预计减少投诉升级率40%', 'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '17 days')
ON CONFLICT (id) DO NOTHING;

-- ── Robot Reports (5 reports) ──────────────────────────────
INSERT INTO robot_reports (id, report_type, period_start, period_end, platform_id, summary_md, metrics, optimization_plan, generated_by, created_at) VALUES
('77777777-0000-0000-0000-000000000001', 'daily', '2026-05-13', '2026-05-13', NULL,
  '# 每日机器人运营报告\n\n## 核心指标\n- 总会话数: 31\n- 机器人处理率: 87%\n- 平均首响时间: 1.2s\n- 客户满意度: 4.1/5',
  '{"total_sessions":31,"bot_handle_rate":0.87,"avg_first_response_ms":1200,"satisfaction_avg":4.1,"conversion_rate":0.65,"complaint_count":3}',
  '1. 本周完成过敏安抚话术A/B测试 2. 与仓库确认包装加固方案', 'auto', NOW() - INTERVAL '1 day'),
('77777777-0000-0000-0000-000000000002', 'daily', '2026-05-12', '2026-05-12', NULL,
  '# 每日机器人运营报告\n\n## 核心指标\n- 总会话数: 28\n- 机器人处理率: 85%\n- 客户满意度: 4.0/5\n\n## 预警\n- 抖音渠道2起投诉升级',
  '{"total_sessions":28,"bot_handle_rate":0.85,"avg_first_response_ms":1400,"satisfaction_avg":4.0,"conversion_rate":0.60,"complaint_count":5}',
  '1. 优化退款进度自动推送 2. 检查抖音售后SLA是否达标', 'auto', NOW() - INTERVAL '2 days'),
('77777777-0000-0000-0000-000000000003', 'daily', '2026-05-11', '2026-05-11', NULL,
  '# 每日机器人运营报告\n\n## 核心指标\n- 总会话数: 25\n- 机器人处理率: 88%\n- 客户满意度: 4.2/5\n\n## 亮点\n- 拼多多渠道转化率创新高达75%',
  '{"total_sessions":25,"bot_handle_rate":0.88,"avg_first_response_ms":1100,"satisfaction_avg":4.2,"conversion_rate":0.68,"complaint_count":2}',
  '继续推广老客专属优惠码', 'auto', NOW() - INTERVAL '3 days'),
('77777777-0000-0000-0000-000000000004', 'weekly', '2026-05-04', '2026-05-10', NULL,
  '# 周报 (W19)\n\n## 概览\n- 总会话数: 187\n- 机器人处理率: 86%\n- 客户满意度: 4.0/5\n- 转化率: 62%\n\n## 渠道对比\n| 渠道 | 满意度 | 转化率 |\n|------|--------|--------|\n| 天猫 | 4.1 | 65% |\n| 京东 | 4.2 | 60% |\n| 抖音 | 3.8 | 55% |\n| 拼多多 | 3.9 | 72% |\n| 小红书 | 4.5 | 70% |',
  '{"total_sessions":187,"bot_handle_rate":0.86,"satisfaction_avg":4.0,"conversion_rate":0.62}',
  '1. 过敏安抚话术A/B测试 2. 物流催款自动推送 3. 比价场景价值证明', 'auto', NOW() - INTERVAL '4 days'),
('77777777-0000-0000-0000-000000000005', 'monthly', '2026-04-01', '2026-04-30', NULL,
  '# 月报 (2026年4月)\n\n## 月度概览\n- 总会话数: 742\n- 机器人处理率: 85%\n- 客户满意度: 4.0/5\n- 转化率: 61%\n\n## 行业对标\n| 指标 | 我们 | 行业平均 | 行业Top |\n|------|------|----------|--------|\n| 满意度 | 4.0 | 3.8 | 4.5 |\n| 首响时间 | 1.2s | 3.0s | 1.0s |',
  '{"total_sessions":742,"bot_handle_rate":0.85,"satisfaction_avg":4.0,"conversion_rate":0.61,"transfer_rate":0.15}',
  '5月重点：过敏安抚话术+抖音售后SLA+跨客服信息同步', 'auto', NOW() - INTERVAL '14 days')
ON CONFLICT (id) DO NOTHING;

-- ── Knowledge Update Logs (8 logs) ─────────────────────────
INSERT INTO knowledge_update_logs (id, knowledge_id, update_type, field_changed, old_value, new_value, updated_by, correlation_id, created_at) VALUES
('99999999-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000005', 'update', 'content', '退换货政策v1', '退换货政策v2（增加发错货和补偿细则）', 'a0000000-0000-0000-0000-000000000002', 'corr-update-001', NOW() - INTERVAL '10 days'),
('99999999-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-000000000015', 'update', 'content', '真假辨别v1', '真假辨别v2（增加激光防伪标签和质检报告说明）', 'a0000000-0000-0000-0000-000000000005', 'corr-update-002', NOW() - INTERVAL '5 days'),
('99999999-0000-0000-0000-000000000003', 'e0000000-0000-0000-0000-000000000007', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000002', 'corr-create-003', NOW() - INTERVAL '15 days'),
('99999999-0000-0000-0000-000000000004', 'e0000000-0000-0000-0000-000000000011', 'publish', NULL, 'draft', 'published', 'a0000000-0000-0000-0000-000000000002', 'corr-publish-004', NOW() - INTERVAL '10 days'),
('99999999-0000-0000-0000-000000000005', 'e0000000-0000-0000-0000-000000000013', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000002', 'corr-create-005', NOW() - INTERVAL '14 days'),
('99999999-0000-0000-0000-000000000006', 'e0000000-0000-0000-0000-000000000009', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000005', 'corr-create-006', NOW() - INTERVAL '18 days'),
('99999999-0000-0000-0000-000000000007', 'e0000000-0000-0000-0000-000000000008', 'create', NULL, NULL, NULL, 'a0000000-0000-0000-0000-000000000002', 'corr-create-007', NOW() - INTERVAL '20 days'),
('99999999-0000-0000-0000-000000000008', 'e0000000-0000-0000-0000-000000000012', 'publish', NULL, 'draft', 'published', 'a0000000-0000-0000-0000-000000000005', 'corr-publish-008', NOW() - INTERVAL '12 days')
ON CONFLICT (id) DO NOTHING;

-- ── Audit Logs (12 logs) ──────────────────────────────────
INSERT INTO audit_logs (id, action, user_id, user_name, resource_type, resource_id, detail, correlation_id, created_at) VALUES
('88888888-0000-0000-0000-000000000001', 'evaluate', 'a0000000-0000-0000-0000-000000000003', '王芳', 'quality_report', 'c0000000-0000-0000-0000-000000000001', '{"score":92,"risk":"low","violations":0}', 'corr-audit-001', NOW() - INTERVAL '27 days'),
('88888888-0000-0000-0000-000000000002', 'evaluate', 'a0000000-0000-0000-0000-000000000004', '赵强', 'quality_report', 'c0000000-0000-0000-0000-000000000002', '{"score":45,"risk":"high","violations":3}', 'corr-audit-002', NOW() - INTERVAL '27 days'),
('88888888-0000-0000-0000-000000000003', 'knowledge_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'knowledge_entry', 'e0000000-0000-0000-0000-000000000007', '{"category":"campaign","title":"618年中大促活动规则"}', 'corr-audit-003', NOW() - INTERVAL '15 days'),
('88888888-0000-0000-0000-000000000004', 'knowledge_update', 'a0000000-0000-0000-0000-000000000005', '陈雪', 'knowledge_entry', 'e0000000-0000-0000-0000-000000000015', '{"field":"content","reason":"增加防伪信息"}', 'corr-audit-004', NOW() - INTERVAL '5 days'),
('88888888-0000-0000-0000-000000000005', 'optimization_task_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'optimization_task', 'f0000000-0000-0000-0000-000000000001', '{"source":"chat_inspection","priority":"critical"}', 'corr-audit-005', NOW() - INTERVAL '26 days'),
('88888888-0000-0000-0000-000000000006', 'optimization_task_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'optimization_task', 'f0000000-0000-0000-0000-000000000002', '{"source":"chat_inspection","priority":"critical"}', 'corr-audit-006', NOW() - INTERVAL '17 days'),
('88888888-0000-0000-0000-000000000007', 'bot_config_create', 'a0000000-0000-0000-0000-000000000002', '李婷', 'bot_config', 'd0000000-0000-0000-0000-000000000003', '{"config_type":"post_sale","key":"return_policy"}', 'corr-audit-007', NOW() - INTERVAL '30 days'),
('88888888-0000-0000-0000-000000000008', 'bot_config_activate', 'a0000000-0000-0000-0000-000000000002', '李婷', 'bot_config', 'd0000000-0000-0000-0000-000000000001', '{"config_type":"pre_sale","key":"greeting_template"}', 'corr-audit-008', NOW() - INTERVAL '30 days'),
('88888888-0000-0000-0000-000000000009', 'report_generate', NULL, 'system', 'robot_report', '77777777-0000-0000-0000-000000000001', '{"report_type":"daily","period":"2026-05-13"}', 'corr-audit-009', NOW() - INTERVAL '1 day'),
('88888888-0000-0000-0000-000000000010', 'report_generate', NULL, 'system', 'robot_report', '77777777-0000-0000-0000-000000000004', '{"report_type":"weekly","period":"2026-W19"}', 'corr-audit-010', NOW() - INTERVAL '4 days'),
('88888888-0000-0000-0000-000000000011', 'login', 'a0000000-0000-0000-0000-000000000001', '张明', NULL, NULL, NULL, 'corr-audit-011', NOW() - INTERVAL '1 day'),
('88888888-0000-0000-0000-000000000012', 'evaluate', 'a0000000-0000-0000-0000-000000000003', '王芳', 'quality_report', 'c0000000-0000-0000-0000-000000000017', '{"score":40,"risk":"critical","violations":2}', 'corr-audit-012', NOW() - INTERVAL '12 days')
ON CONFLICT (id) DO NOTHING;

-- ── Bad Cases (3 cases for overturned reports) ────────────
INSERT INTO bad_cases (id, quality_report_id, original_judgment, corrected_judgment, overturn_reason, corrected_by, created_at) VALUES
('55555555-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000005',
  '{"score":35,"violations":[{"rule":"补偿方案不足","deduction":15},{"rule":"未主动道歉安抚","deduction":10},{"rule":"未提供升级路径","deduction":5}],"risk_level":"critical"}',
  '{"score":45,"violations":[{"rule":"补偿方案不足","deduction":15},{"rule":"未提供升级路径","deduction":5}],"risk_level":"high"}',
  '客户发错货场景中机器人已进行了道歉（"确实是我们仓库发错了，非常抱歉！"），"未主动道歉安抚"扣分不合理',
  'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '23 days'),
('55555555-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000010',
  '{"score":52,"violations":[{"rule":"未有效消除客户疑虑","deduction":15},{"rule":"语气过于被动防御","deduction":10},{"rule":"未主动提供解决方案","deduction":8}],"risk_level":"high"}',
  '{"score":62,"violations":[{"rule":"未有效消除客户疑虑","deduction":15},{"rule":"语气过于被动防御","deduction":10}],"risk_level":"medium"}',
  '机器人已提供退货方案和质检报告获取方式，"未主动提供解决方案"不成立',
  'a0000000-0000-0000-0000-000000000005', NOW() - INTERVAL '18 days'),
('55555555-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000023',
  '{"score":72,"violations":[{"rule":"未挽留因券流失客户","deduction":12},{"rule":"缺少灵活应对方案","deduction":10}],"risk_level":"high"}',
  '{"score":82,"violations":[{"rule":"缺少灵活应对方案","deduction":10}],"risk_level":"medium"}',
  '新人券有固定使用门槛，机器人已清楚解释规则并给出凑单建议。在平台规则硬性约束下，"未挽留"不应视为机器人问题',
  'a0000000-0000-0000-0000-000000000002', NOW() - INTERVAL '1 day')
ON CONFLICT (id) DO NOTHING;

-- >>> seed-phase-1-2-data.sql
-- ============================================================================
-- Seed Data for Phase 1/2 Panels
-- Run AFTER migration-014 in Supabase SQL Editor.
-- ============================================================================

-- 1. Seed Work Orders (for 工单管理)
INSERT INTO work_orders (title, description, source, priority, status, category, metadata) VALUES
    ('客服态度恶劣需整改 — 质检红灯', '质检报告发现客服在对话中使用粗俗用语，客户情绪升至5级。对话内容涉及退货纠纷。需立即约谈并整改。', 'qa_evaluate', 'critical', 'open', 'customer_complaint', '{"report_id": "seed-001", "score": 45}'),
    ('退款政策话术疑似违规', '自动话术"不满意全额退"被合规引擎标记为虚假承诺嫌疑（风险等级2）。需人工审核修改措辞。', 'compliance_block', 'high', 'open', 'compliance', '{"rule_id": "false_promise", "risk": 2}'),
    ('物流查询流程缺少快递100+平台适配', '质检发现抖音和拼多多平台的物流查询话术未做平台适配，导致客户在正确输入订单号后仍转人工。', 'inspection', 'medium', 'in_progress', 'script_fix', '{"platforms": ["pdd", "douyin"]}'),
    ('孕妇可用护肤品知识条目缺失', '连续3天出现"孕妇可以用吗"类问题未命中知识库。需要审核并创建相关条目。', 'cron', 'medium', 'open', 'knowledge_gap', '{"gap_count": 12, "cluster": "孕产护肤"}'),
    ('系统自动催付功能未按预期触发', 'payment_reminders cron 任务报错：pending_orders 关联查询超时。需优化查询或增加索引。', 'manual', 'high', 'in_progress', 'system_issue', '{"error": "timeout", "endpoint": "/api/qa/payment-reminders"}'),
    ('批量导入商品材质说明更新', '运营团队需要一次性更新50个商品的材质说明话术。需要批量导入接口支持。', 'manual', 'low', 'resolved', 'general', '{"batch_size": 50, "status": "done"}'),
    ('化妆品备案号缺失导致合规拦截', '某护肤品牌在话术中声称"医学级"但未提供备案号，合规引擎拦截。需补充备案号或修改措辞。', 'compliance_block', 'critical', 'open', 'compliance', '{"brand": "sample-brand", "term": "医学级"}')
ON CONFLICT DO NOTHING;

-- Add some work order actions for the in_progress orders
INSERT INTO work_order_actions (work_order_id, action, comment, metadata)
SELECT id, 'created', '系统自动生成', '{"auto_generated": true}'::jsonb
FROM work_orders
WHERE NOT EXISTS (SELECT 1 FROM work_order_actions WHERE work_order_actions.work_order_id = work_orders.id);

-- 2. Seed Pending Orders (for 智能催付)
INSERT INTO pending_orders (external_order_id, customer_name, product_name, order_amount, order_status, created_at_order, expire_at) VALUES
    ('ORD-20260501-001', '张*丽', '兰蔻持妆粉底液 PO-01 30ml', 459.00, 'pending_payment', '2026-05-15 14:30:00+08', '2026-05-16 14:30:00+08'),
    ('ORD-20260502-002', '王*明', 'Apple AirPods Pro 2 无线耳机', 1388.00, 'pending_payment', '2026-05-16 09:15:00+08', '2026-05-17 09:15:00+08'),
    ('ORD-20260502-003', '李*芳', '三只松鼠坚果大礼包 1888g', 128.00, 'reminded', '2026-05-15 20:00:00+08', '2026-05-16 20:00:00+08'),
    ('ORD-20260503-004', '赵*', '海尔冰箱 BCD-500 智能变频', 3299.00, 'pending_payment', '2026-05-16 11:00:00+08', '2026-05-18 11:00:00+08'),
    ('ORD-20260503-005', '刘*婷', 'SK-II 神仙水 230ml 限量版', 1590.00, 'reminded', '2026-05-16 15:45:00+08', '2026-05-17 15:45:00+08'),
    ('ORD-20260501-006', '陈*', '小米13 Ultra 12+256G 黑色', 4999.00, 'paid', '2026-05-15 10:00:00+08', '2026-05-16 10:00:00+08'),
    ('ORD-20260501-007', '孙*华', '耐克 Air Max 270 男款跑步鞋 42码', 739.00, 'paid', '2026-05-15 12:30:00+08', '2026-05-16 12:30:00+08'),
    ('ORD-20260430-008', '周*杰', '戴森 V15 无线吸尘器 2024款', 4399.00, 'expired', '2026-04-30 16:00:00+08', '2026-05-01 16:00:00+08'),
    ('ORD-20260428-009', '吴*', '海底捞火锅底料 麻辣 200g*5', 49.90, 'cancelled', '2026-04-28 10:00:00+08', '2026-04-29 10:00:00+08'),
    ('ORD-20260503-010', '黄*强', 'PS5 主机 光驱版 国行', 3499.00, 'pending_payment', '2026-05-16 18:30:00+08', '2026-05-17 18:30:00+08')
ON CONFLICT DO NOTHING;

-- Add sample reminders for reminded/paid orders
INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at)
SELECT id, 1, '亲爱的顾客，您的订单已生成，请及时完成支付哦～', 'bot', 'sent', created_at_order + interval '30 minutes'
FROM pending_orders WHERE order_status IN ('reminded', 'paid')
ON CONFLICT DO NOTHING;

INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at, converted_at)
SELECT id, 1, '亲爱的顾客，您的订单已生成，请及时完成支付哦～', 'bot', 'converted', created_at_order + interval '30 minutes', created_at_order + interval '2 hours'
FROM pending_orders WHERE order_status = 'paid'
ON CONFLICT DO NOTHING;

-- 3. Seed Intent Accuracy Logs (for 意图准确率)
-- Generates 30 days of trending data
INSERT INTO intent_accuracy_logs (period_date, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, target_met)
SELECT
    today::date - (n || ' days')::interval,
    150 + floor(random() * 200)::int,
    (150 + floor(random() * 200)::int) - floor(random() * 5)::int,
    floor(random() * 5)::int,
    CASE
        WHEN n <= 5 THEN 0.996 + random() * 0.003  -- recent: high accuracy
        WHEN n <= 15 THEN 0.993 + random() * 0.005 -- mid: around alert line
        ELSE 0.988 + random() * 0.010              -- older: some dips
    END,
    CASE WHEN n <= 5 THEN true ELSE random() > 0.3 END
FROM generate_series(0, 29) AS n,
     (SELECT current_date AS today) AS d
WHERE NOT EXISTS (SELECT 1 FROM intent_accuracy_logs WHERE period_date = today::date - (n || ' days')::interval);

-- 4. Verify seed data
SELECT 'work_orders' AS table_name, count(*) AS rows FROM work_orders
UNION ALL SELECT 'work_order_actions', count(*) FROM work_order_actions
UNION ALL SELECT 'pending_orders', count(*) FROM pending_orders
UNION ALL SELECT 'payment_reminders', count(*) FROM payment_reminders
UNION ALL SELECT 'intent_accuracy_logs', count(*) FROM intent_accuracy_logs
UNION ALL SELECT 'system_configs', count(*) FROM system_configs
UNION ALL SELECT 'compliance_rules', count(*) FROM compliance_rules
ORDER BY table_name;

-- >>> seed-system-ops.sql
-- ============================================================================
-- 系统运维面板综合种子数据
-- 覆盖: 审计日志 · 坐席绩效 · 合规审核 · 工单管理 · 智能催付 · 效果对比
-- 安全重复运行 (ON CONFLICT DO NOTHING / NOT EXISTS guards)
-- ============================================================================

-- ============================================================================
-- PART 1: 确保坐席 Profiles 存在 (AgentPerformancePanel 数据源)
-- ============================================================================
INSERT INTO profiles (id, name, role, team_id) VALUES
  ('a0000000-0000-0000-0000-000000000003', '王芳', 'agent', 'team_beauty'),
  ('a0000000-0000-0000-0000-000000000004', '赵强', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000101', '周敏', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000102', '刘洋', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000103', '陈丽华', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000104', '黄伟', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000105', '林小红', 'agent', 'team_beauty'),
  ('00000000-0000-0000-0000-000000000106', '吴建国', 'agent', 'team_beauty')
ON CONFLICT (id) DO NOTHING;

-- Ensure agents have user_roles entries
INSERT INTO user_roles (profile_id, role, assigned_by)
SELECT id, 'agent', 'a0000000-0000-0000-0000-000000000001'
FROM profiles
WHERE role = 'agent'
ON CONFLICT (profile_id) DO NOTHING;

-- ============================================================================
-- PART 2: 坐席质检报告 (AgentPerformancePanel 排行数据)
-- 为每个坐席生成近 30 天、不同分数和风险等级的质检记录
-- ============================================================================
DO $$
DECLARE
    agent_list UUID[] := ARRAY[
        'a0000000-0000-0000-0000-000000000003'::UUID,
        'a0000000-0000-0000-0000-000000000004'::UUID,
        '00000000-0000-0000-0000-000000000101'::UUID,
        '00000000-0000-0000-0000-000000000102'::UUID,
        '00000000-0000-0000-0000-000000000103'::UUID,
        '00000000-0000-0000-0000-000000000104'::UUID,
        '00000000-0000-0000-0000-000000000105'::UUID,
        '00000000-0000-0000-0000-000000000106'::UUID
    ];
    ag_name TEXT[] := ARRAY['王芳','赵强','周敏','刘洋','陈丽华','黄伟','林小红','吴建国'];
    ag_profile JSONB[] := ARRAY[
        '{"scores":[92,88,95,78,91,85,97,89,83,90,94,87,91,86,93,79,88,92,85,90,96,84,89,91],"violations":[{"category":"语气不当","desc":"连续使用感叹号"},{"category":"流程遗漏","desc":"未确认客户身份"}]}'::JSONB,
        '{"scores":[75,82,79,88,71,84,76,83,80,77,85,73,81,79,86,74,82,78,80,76,83,75,79,82],"violations":[{"category":"虚假承诺","desc":"声称产品保证效果"},{"category":"竞品提及","desc":"与其他品牌比较"},{"category":"敏感词","desc":"涉及医疗术语"}]}'::JSONB,
        '{"scores":[96,93,98,91,95,97,92,94,99,90,96,93,97,95,91,98,94,92,96,93,99,95,91,97],"violations":[{"category":"语气不当","desc":"回复过于简短"}]}'::JSONB,
        '{"scores":[88,85,91,84,87,90,83,86,89,82,85,88,84,91,86,83,90,87,85,89,82,86,88,84],"violations":[{"category":"流程遗漏","desc":"未发送满意度调查"}]}'::JSONB,
        '{"scores":[70,68,73,65,71,76,62,69,74,67,72,64,70,75,66,71,63,69,73,68,65,72,70,67],"violations":[{"category":"态度问题","desc":"语气生硬不耐烦"},{"category":"知识错误","desc":"产品成分描述有误"},{"category":"虚假承诺","desc":"声称适合所有肤质"},{"category":"敏感词","desc":"使用禁用营销词"}]}'::JSONB,
        '{"scores":[85,82,88,90,83,86,89,81,87,84,90,83,86,88,82,85,89,84,87,90,83,86,88,85],"violations":[{"category":"竞品提及","desc":"主动推荐其他平台"},{"category":"流程遗漏","desc":"未记录客户诉求"}]}'::JSONB,
        '{"scores":[78,81,75,83,79,76,82,80,77,84,81,78,75,82,79,76,83,80,77,84,81,78,75,82],"violations":[{"category":"语气不当","desc":"使用连续感叹号"},{"category":"知识错误","desc":"会员权益描述有误"}]}'::JSONB,
        '{"scores":[91,94,88,92,95,89,93,90,96,87,92,94,91,88,95,89,93,90,96,87,92,94,91,88],"violations":[{"category":"语气不当","desc":"回复格式不规范"}]}'::JSONB
    ];
    ag_reviewer UUID := 'a0000000-0000-0000-0000-000000000001'::UUID;
    i INT;
    d INT;
    score_val INT;
    risk TEXT;
    base_time TIMESTAMPTZ := now();
BEGIN
    FOR i IN 1..8 LOOP
        FOR d IN 0..23 LOOP
            score_val := (ag_profile[i]->'scores'->d)::INT;
            IF score_val >= 90 THEN risk := 'low';
            ELSIF score_val >= 75 THEN risk := 'medium';
            ELSIF score_val >= 60 THEN risk := 'high';
            ELSE risk := 'critical';
            END IF;

            INSERT INTO quality_reports (
                id, ticket_id, agent_id, reviewer_id, conversation,
                intent, sentiment_score, total_score, violations, risk_level,
                status, correlation_id, review_mode, created_at
            ) VALUES (
                gen_random_uuid(),
                'TKT-' || to_char(base_time - (d || ' days')::INTERVAL, 'YYMMDD') || '-' || lpad(i::TEXT, 3, '0'),
                agent_list[i],
                ag_reviewer,
                '顾客: ' || ag_name[i] || '处理的客服对话记录 #' || d,
                'consultation',
                round((score_val::NUMERIC / 100 * 4 + 1)::NUMERIC, 1),
                score_val,
                CASE WHEN score_val < 85 THEN ag_profile[i]->'violations' ELSE '[]'::JSONB END,
                risk,
                'confirmed',
                'corr-agent-' || i::TEXT || '-' || d::TEXT,
                'active',
                base_time - (d || ' days')::INTERVAL
            )
            ON CONFLICT DO NOTHING;
        END LOOP;
    END LOOP;
END $$;

-- ============================================================================
-- PART 3: 全链路审计日志 (AuditPanel 数据源)
-- 覆盖全部 19 种审计事件类型，时间分散于近 30 天
-- ============================================================================
DO $$
DECLARE
    admin_id UUID := 'a0000000-0000-0000-0000-000000000001'::UUID;
    agent_ids UUID[] := ARRAY['a0000000-0000-0000-0000-000000000003','a0000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000101']::UUID[];
    trace_id TEXT;
    idx INT;
    action_list TEXT[] := ARRAY[
        'login','logout','llm_call','evaluate','overturn',
        'dispatch_feishu','feishu_event_receive','report_generate',
        'knowledge_create','knowledge_update','knowledge_delete','knowledge_publish','knowledge_reject',
        'bot_config_create','bot_config_activate','bot_config_archive','bot_config_publish','bot_config_reject',
        'optimization_task_create','optimization_task_update',
        'campaign_import','rule_create','rule_delete',
        'auto_evaluate_failed','compliance_warn'
    ];
    detail_json JSONB;
    action_now TEXT;
    time_offset INTERVAL;
BEGIN
    FOR idx IN 1..80 LOOP
        action_now := action_list[1 + (idx % array_length(action_list, 1))];
        time_offset := (idx * 180 + (random() * 360)::INT) * '1 minute'::INTERVAL;

        -- Build realistic detail per action type
        CASE action_now
            WHEN 'login' THEN
                detail_json := jsonb_build_object('ip', '192.168.' || (1 + random() * 254)::INT || '.' || (1 + random() * 254)::INT, 'user_agent', 'Mozilla/5.0');
            WHEN 'logout' THEN
                detail_json := jsonb_build_object('session_duration_min', (5 + random() * 480)::INT);
            WHEN 'llm_call' THEN
                detail_json := jsonb_build_object(
                    'model', (CASE WHEN random() > 0.5 THEN 'moonshot-v1-8k' ELSE 'kimi-latest' END),
                    'prompt_type', (CASE WHEN random() > 0.6 THEN 'evaluate' WHEN random() > 0.3 THEN 'generate_knowledge' ELSE 'compliance_check' END),
                    'latency_ms', (800 + random() * 15000)::INT,
                    'cached', random() > 0.7,
                    'tokens', (200 + random() * 3000)::INT,
                    'was_fallback', random() > 0.9
                );
            WHEN 'evaluate' THEN
                detail_json := jsonb_build_object(
                    'score', (60 + random() * 40)::INT,
                    'risk_level', (CASE WHEN random() > 0.8 THEN 'critical' WHEN random() > 0.5 THEN 'high' ELSE 'medium' END),
                    'violations_count', (0 + random() * 8)::INT,
                    'review_mode', (CASE WHEN random() > 0.5 THEN 'auto' ELSE 'manual' END)
                );
            WHEN 'dispatch_feishu' THEN
                detail_json := jsonb_build_object(
                    'route', (CASE WHEN random() > 0.6 THEN 'direct_message' WHEN random() > 0.3 THEN 'group_webhook' ELSE 'global_webhook' END),
                    'target', (CASE WHEN random() > 0.5 THEN 'team_beauty' ELSE 'agent_wangfang' END),
                    'priority', (CASE WHEN random() > 0.8 THEN 'critical' ELSE 'normal' END)
                );
            WHEN 'feishu_event_receive' THEN
                detail_json := jsonb_build_object(
                    'event_type', (CASE WHEN random() > 0.5 THEN 'im.message.receive_v1' ELSE 'im.message.reaction.created_v1' END),
                    'chat_id', 'oc_' || md5(random()::TEXT),
                    'sender_open_id', 'ou_' || md5(random()::TEXT)
                );
            WHEN 'report_generate' THEN
                detail_json := jsonb_build_object('report_type', (CASE WHEN random() > 0.5 THEN 'daily' WHEN random() > 0.3 THEN 'weekly' ELSE 'agent_performance' END));
            WHEN 'knowledge_create','knowledge_update' THEN
                detail_json := jsonb_build_object('title', (CASE
                    WHEN random() > 0.8 THEN '美白精华液成分说明'
                    WHEN random() > 0.6 THEN '防晒霜SPF值科普'
                    WHEN random() > 0.4 THEN '退换货政策FAQ'
                    WHEN random() > 0.2 THEN '敏感肌护肤指南'
                    ELSE '618活动规则解读'
                END));
            WHEN 'knowledge_delete' THEN
                detail_json := jsonb_build_object('title', '过期话术模板-2024版', 'reason', '内容已过时');
            WHEN 'bot_config_create','bot_config_activate' THEN
                detail_json := jsonb_build_object('config_key', (CASE
                    WHEN random() > 0.7 THEN 'skincare_consult'
                    WHEN random() > 0.4 THEN 'order_inquiry_reply'
                    ELSE 'after_sale_return'
                END));
            WHEN 'bot_config_archive' THEN
                detail_json := jsonb_build_object('config_key', 'old_promo_script_Q1', 'reason', '促销活动已结束');
            WHEN 'campaign_import' THEN
                detail_json := jsonb_build_object('count', (10 + random() * 200)::INT, 'source', 'tmall_campaign_api');
            WHEN 'rule_create' THEN
                detail_json := jsonb_build_object('rule_text', '绝对化用语检测增强', 'risk_level', 1);
            WHEN 'rule_delete' THEN
                detail_json := jsonb_build_object('rule_text', '旧版营销词检测', 'reason', '已合并至新规则');
            WHEN 'overturn' THEN
                detail_json := jsonb_build_object('original_score', (60 + random() * 30)::INT, 'new_risk', 'medium', 'reason', '该对话属于正常产品咨询，不构成违规');
            WHEN 'auto_evaluate_failed' THEN
                detail_json := jsonb_build_object('error', (CASE WHEN random() > 0.5 THEN 'LLM timeout after 30s' ELSE 'JSON parse error in evaluation result' END), 'conversation_preview', '顾客: 你好，请问这款产品适合油性皮肤吗...');
            WHEN 'compliance_warn' THEN
                detail_json := jsonb_build_object('resource_type', 'knowledge_entries', 'action', (CASE WHEN random() > 0.5 THEN 'blocked' ELSE 'flagged' END), 'risk_level', (1 + random() * 3)::INT);
            ELSE
                detail_json := jsonb_build_object('note', '系统自动操作');
        END CASE;

        trace_id := 'trace-' || to_char(now() - time_offset, 'YYMMDD') || '-' || lpad(idx::TEXT, 4, '0');

        INSERT INTO audit_logs (
            id, action, user_id, user_name, resource_type, resource_id,
            detail, correlation_id, created_at
        ) VALUES (
            gen_random_uuid(),
            action_now,
            CASE WHEN action_now IN ('login','logout','llm_call','evaluate','rule_create','rule_delete')
                 THEN agent_ids[1 + (idx % 3)]
                 WHEN action_now IN ('knowledge_create','knowledge_update','knowledge_delete','knowledge_publish','knowledge_reject',
                                     'bot_config_create','bot_config_activate','bot_config_archive','bot_config_publish','bot_config_reject',
                                     'report_generate','campaign_import','overturn','compliance_warn')
                 THEN admin_id
                 ELSE NULL
            END,
            CASE WHEN action_now IN ('login','logout','llm_call','evaluate','rule_create','rule_delete')
                 THEN (SELECT name FROM profiles WHERE id = agent_ids[1 + (idx % 3)])
                 WHEN action_now IN ('knowledge_create','knowledge_update','knowledge_delete','knowledge_publish','knowledge_reject',
                                     'bot_config_create','bot_config_activate','bot_config_archive','bot_config_publish','bot_config_reject',
                                     'report_generate','campaign_import','overturn','compliance_warn')
                 THEN (SELECT name FROM profiles WHERE id = admin_id)
                 ELSE NULL
            END,
            CASE
                WHEN action_now LIKE 'knowledge_%' THEN 'knowledge_entries'
                WHEN action_now LIKE 'bot_config_%' THEN 'bot_configs'
                WHEN action_now IN ('evaluate','auto_evaluate_failed') THEN 'quality_reports'
                WHEN action_now = 'llm_call' THEN 'llm'
                WHEN action_now = 'dispatch_feishu' THEN 'feishu_dispatch'
                WHEN action_now = 'feishu_event_receive' THEN 'feishu_event'
                WHEN action_now = 'report_generate' THEN 'quality_reports'
                WHEN action_now IN ('rule_create','rule_delete') THEN 'compliance_rules'
                WHEN action_now IN ('login','logout') THEN 'auth'
                WHEN action_now = 'overturn' THEN 'quality_reports'
                WHEN action_now = 'campaign_import' THEN 'campaigns'
                WHEN action_now = 'compliance_warn' THEN 'compliance_rules'
                ELSE 'system'
            END,
            gen_random_uuid(),
            detail_json,
            trace_id,
            now() - time_offset
        );
    END LOOP;
END $$;

-- ============================================================================
-- PART 4: 合规审计日志 (CompliancePanel 历史记录)
-- 模拟 30 次合规扫描事件
-- ============================================================================
INSERT INTO compliance_audit_logs (source_type, source_id, content_snippet, risk_level, matched_rules, decision, correlation_id, created_at)
SELECT
    (CASE WHEN n % 3 = 0 THEN 'knowledge_entry' WHEN n % 3 = 1 THEN 'bot_config' ELSE 'chat_message' END),
    gen_random_uuid(),
    (CASE
        WHEN n % 8 = 0 THEN '我们产品是最顶级的，效果秒杀市面所有其他品牌'
        WHEN n % 8 = 1 THEN '这款面霜含有天然植物精华，有效改善肌肤'
        WHEN n % 8 = 2 THEN '国家免检产品，100%有效，永不复发'
        WHEN n % 8 = 3 THEN '天猫认证正品，比其他平台便宜很多'
        WHEN n % 8 = 4 THEN '本产品由国家级实验室研发，品质有保障'
        WHEN n % 8 = 5 THEN '亲爱的顾客您好，感谢您的咨询，请问有什么可以帮您？'
        WHEN n % 8 = 6 THEN '活动最后一天！！不买就亏了！！赶紧下单！！'
        WHEN n % 8 = 7 THEN '建议您搭配我们的精华液一起使用效果更好哦'
    END),
    (CASE
        WHEN n % 8 = 0 THEN 1 WHEN n % 8 = 1 THEN 4
        WHEN n % 8 = 2 THEN 1 WHEN n % 8 = 3 THEN 2
        WHEN n % 8 = 4 THEN 1 WHEN n % 8 = 5 THEN NULL
        WHEN n % 8 = 6 THEN 3 WHEN n % 8 = 7 THEN NULL
    END),
    (CASE
        WHEN n % 8 = 0 THEN '[{"rule":"绝对化用语","risk":1}]'::JSONB
        WHEN n % 8 = 1 THEN '[]'::JSONB
        WHEN n % 8 = 2 THEN '[{"rule":"禁止承诺有效率","risk":1},{"rule":"禁止使用国家标志","risk":1}]'::JSONB
        WHEN n % 8 = 3 THEN '[{"rule":"禁止未经授权使用平台名义","risk":3},{"rule":"禁止违规比较广告","risk":2}]'::JSONB
        WHEN n % 8 = 4 THEN '[{"rule":"禁止使用国家标志","risk":1}]'::JSONB
        WHEN n % 8 = 5 THEN '[]'::JSONB
        WHEN n % 8 = 6 THEN '[{"rule":"连续感叹号","risk":4},{"rule":"禁止使用禁用营销词","risk":3}]'::JSONB
        WHEN n % 8 = 7 THEN '[]'::JSONB
    END),
    (CASE
        WHEN n % 8 = 0 THEN 'blocked' WHEN n % 8 = 1 THEN 'passed'
        WHEN n % 8 = 2 THEN 'blocked' WHEN n % 8 = 3 THEN 'flagged'
        WHEN n % 8 = 4 THEN 'blocked' WHEN n % 8 = 5 THEN 'passed'
        WHEN n % 8 = 6 THEN 'flagged' WHEN n % 8 = 7 THEN 'passed'
    END),
    'compliance-' || lpad(n::TEXT, 3, '0'),
    now() - (n * 12 || ' hours')::INTERVAL
FROM generate_series(1, 30) AS n
WHERE NOT EXISTS (SELECT 1 FROM compliance_audit_logs LIMIT 1);

-- ============================================================================
-- PART 5: 工单 (WorkOrderPanel)
-- 补充更多真实工单场景
-- ============================================================================
INSERT INTO work_orders (title, description, source, priority, status, category, metadata, created_at)
VALUES
  ('抖音直播间话术违规 — 质检红灯',
   '直播中主播使用了"全网最低价""最有效美白"等声称，合规引擎标记致命级违规。需审核话术脚本并修改。',
   'compliance_block', 'critical', 'open', 'compliance',
   '{"platform":"douyin","rule_ids":["absolute_claim_001","false_promise_005"]}',
   now() - '2 hours'::INTERVAL),

  ('客户投诉退货流程超过72小时未处理',
   '客户购买护肤套装后因过敏申请退货，系统流程卡在审核环节超过3天，客户在微博公开投诉。',
   'manual', 'critical', 'open', 'customer_complaint',
   '{"order_id":"ORD-20260515-889","platform":"tmall","escalated":true}',
   now() - '5 hours'::INTERVAL),

  ('小红书平台回复话术缺少产品备案号',
   '质检发现小红书平台的自动回复中提及"美白""祛斑"等特殊功效但未引用备案号/批准文号格式，不符合药监局要求。',
   'inspection', 'high', 'open', 'compliance',
   '{"platform":"xiaohongshu","config_key":"whitening_faq"}',
   now() - '1 day'::INTERVAL),

  ('拼多多店铺话术模板批量过期',
   'Q1促销活动已结束，但拼多多平台的欢迎语和催付话术仍包含"女神节特惠"等过期内容，需要批量归档并生成新话术。',
   'cron', 'high', 'in_progress', 'script_fix',
   '{"platform":"pdd","expired_configs":4,"campaign":"Q1_womens_day"}',
   now() - '1 day'::INTERVAL),

  ('坐席王芳客户满意度连续下降',
   '绩效系统检测到坐席王芳近两周的好评率从92%降至78%，可能存在工作状态问题，需团队负责人约谈。',
   'qa_evaluate', 'medium', 'in_progress', 'general',
   '{"agent_id":"a0000000-0000-0000-0000-000000000003","trend":"declining","period":"14d"}',
   now() - '2 days'::INTERVAL),

  ('知识库"防晒"类目覆盖不足',
   '连续5天检测到高频率未命中问题："物理防晒和化学防晒区别""孕妇可用防晒霜吗""SPF值怎么选"。建议创建知识条目。',
   'cron', 'medium', 'open', 'knowledge_gap',
   '{"cluster":"sun_protection","gap_count":23,"priority_score":0.87}',
   now() - '2 days'::INTERVAL),

  ('618大促活动话术上线审批',
   '运营团队提交了618活动话术模板，包括限时折扣、满减优惠、赠品策略等内容，需要合规扫描后发布到全部8个平台。',
   'manual', 'medium', 'in_progress', 'script_fix',
   '{"campaign":"618","platforms":["tmall","jd","pdd","douyin"],"config_count":12}',
   now() - '3 days'::INTERVAL),

  ('飞书告警通道降级测试',
   '凌晨3点检测到飞书个人Webhook超时，系统按四级降级路由切换至群聊Webhook成功。需确认夜间告警策略是否正常。',
   'manual', 'low', 'resolved', 'system_issue',
   '{"route":"direct->group","downgrade_time_ms":3200,"night_window":true}',
   now() - '4 days'::INTERVAL),

  ('自动质检模型对美妆类对话误判率高',
   '运营反馈美妆行业的专业术语（如烟酰胺、A醇、刷酸等）经常被误判为敏感词或违规内容，需要添加行业豁免词表。',
   'manual', 'medium', 'open', 'system_issue',
   '{"industry":"beauty","false_positive_rate":0.12,"affected_terms":["烟酰胺","刷酸","A醇","果酸"]}',
   now() - '5 days'::INTERVAL),

  ('批量导入竞品分析话术',
   '市场部完成竞品调研，需要批量导入50+条竞品对比话术，内容涵盖产品成分、价格、功效等多维度对比。',
   'manual', 'low', 'resolved', 'general',
   '{"batch_size":52,"imported_by":"a0000000-0000-0000-0000-000000000002"}',
   now() - '7 days'::INTERVAL)

ON CONFLICT DO NOTHING;

-- ============================================================================
-- PART 6: 智能催付订单补充 (PaymentReminderPanel)
-- ============================================================================
INSERT INTO pending_orders (external_order_id, customer_name, product_name, order_amount, order_status, created_at_order, expire_at) VALUES
  ('ORD-20260517-101', '郑*怡', '雅诗兰黛小棕瓶精华 50ml', 890.00, 'pending_payment', '2026-05-17 10:15:00+08', '2026-05-18 10:15:00+08'),
  ('ORD-20260517-102', '林*豪', '戴森吹风机 Supersonic HD15', 3190.00, 'pending_payment', '2026-05-17 14:30:00+08', '2026-05-18 14:30:00+08'),
  ('ORD-20260517-103', '杨*婷', '兰芝睡眠面膜 70ml*2', 185.00, 'reminded', '2026-05-17 09:00:00+08', '2026-05-19 09:00:00+08'),
  ('ORD-20260518-104', '马*军', '华为Mate 70 Pro 12+512G', 6499.00, 'pending_payment', '2026-05-18 08:45:00+08', '2026-05-19 08:45:00+08'),
  ('ORD-20260518-105', '胡*', '完美日记小细跟口红礼盒 6支', 299.00, 'pending_payment', '2026-05-18 11:20:00+08', '2026-05-19 11:20:00+08'),
  ('ORD-20260516-106', '何*雯', '科沃斯扫拖机器人 X5 PRO', 4599.00, 'paid', '2026-05-16 15:00:00+08', '2026-05-17 15:00:00+08'),
  ('ORD-20260516-107', '高*', '花西子空气蜜粉 01号色', 159.00, 'paid', '2026-05-16 20:30:00+08', '2026-05-17 20:30:00+08'),
  ('ORD-20260515-108', '罗*华', '飞利浦电动牙刷 HX9352', 699.00, 'reminded', '2026-05-15 13:00:00+08', '2026-05-17 13:00:00+08'),
  ('ORD-20260514-109', '梁*欣', 'OLAY 抗糖小白瓶 30ml', 239.00, 'expired', '2026-05-14 16:00:00+08', '2026-05-15 16:00:00+08'),
  ('ORD-20260513-110', '谢*锋', '北面冲锋衣 1996经典款', 1899.00, 'cancelled', '2026-05-13 10:00:00+08', '2026-05-14 10:00:00+08'),
  ('ORD-20260518-111', '潘*玲', '芙丽芳丝净润洗面奶 100g*3', 297.00, 'pending_payment', '2026-05-18 13:10:00+08', '2026-05-19 13:10:00+08'),
  ('ORD-20260518-112', '范*伟', '联想ThinkPad X1 Carbon i7', 9999.00, 'pending_payment', '2026-05-18 14:55:00+08', '2026-05-19 14:55:00+08')
ON CONFLICT DO NOTHING;

-- Add payment reminders (only for orders that don't have them)
DO $$
BEGIN
    INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at)
    SELECT o.id, 1,
        '亲爱的' || COALESCE(o.customer_name, '顾客') || '，您选购的' || COALESCE(o.product_name, '商品') || '还未支付哦～库存有限，请尽快完成支付',
        'bot', 'sent', o.created_at_order + '30 minutes'::INTERVAL
    FROM pending_orders o
    WHERE o.order_status IN ('reminded', 'paid')
      AND NOT EXISTS (SELECT 1 FROM payment_reminders r WHERE r.order_id = o.id);

    INSERT INTO payment_reminders (order_id, round, script, channel, status, sent_at, converted_at)
    SELECT o.id, 1,
        '亲爱的' || COALESCE(o.customer_name, '顾客') || '，您的订单已为您保留，现在支付即享优先发货～',
        'bot', 'converted', o.created_at_order + '30 minutes'::INTERVAL, o.created_at_order + '2 hours'::INTERVAL
    FROM pending_orders o
    WHERE o.order_status = 'paid'
      AND NOT EXISTS (SELECT 1 FROM payment_reminders r WHERE r.order_id = o.id AND r.status = 'converted');
END $$;

-- ============================================================================
-- PART 7: Effect Metrics (EffectComparePanel — 发布前后对比)
-- 安全执行：仅在对应列存在时更新
-- ============================================================================
DO $$
BEGIN
    -- bot_configs.effect_metrics (from migration-007)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'bot_configs' AND column_name = 'effect_metrics'
    ) THEN
        EXECUTE '
            UPDATE bot_configs
            SET effect_metrics = jsonb_build_object(
                ''pre_publish_satisfaction'', round((0.82 + random() * 0.1)::NUMERIC, 3),
                ''pre_publish_handled_rate'', round((0.75 + random() * 0.15)::NUMERIC, 3),
                ''pre_publish_avg_response_ms'', (1500 + random() * 3000)::INT,
                ''snapshot_date'', to_char(now() - ''14 days''::INTERVAL, ''YYYY-MM-DD'')
            )
            WHERE status = ''active''
              AND effect_metrics IS NULL
              AND effect_metrics = ''{}''::jsonb';
    END IF;

    -- knowledge_entries.effect_metrics (from migration-008)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'knowledge_entries' AND column_name = 'effect_metrics'
    ) THEN
        EXECUTE '
            UPDATE knowledge_entries
            SET effect_metrics = jsonb_build_object(
                ''pre_update_hit_rate'', round((0.6 + random() * 0.25)::NUMERIC, 3),
                ''pre_update_avg_relevance'', round((0.7 + random() * 0.2)::NUMERIC, 3),
                ''gap_reduction_pct'', round((0.15 + random() * 0.4)::NUMERIC, 3),
                ''snapshot_date'', to_char(now() - ''14 days''::INTERVAL, ''YYYY-MM-DD'')
            )
            WHERE status = ''published''
              AND effect_metrics IS NULL
              AND effect_metrics = ''{}''::jsonb';
    END IF;
END $$;

-- ============================================================================
-- PART 8: 意图准确率日志补充 (IntentAccuracyPanel)
-- 确保近 30 天每天有数据
-- ============================================================================
INSERT INTO intent_accuracy_logs (period_date, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, target_met)
SELECT
    current_date - (n || ' days')::INTERVAL,
    200 + floor(random() * 300)::INT,
    (200 + floor(random() * 300)::INT) - (1 + floor(random() * 8))::INT,
    (1 + floor(random() * 8))::INT,
    CASE
        WHEN n <= 3 THEN 0.997 + random() * 0.002
        WHEN n <= 10 THEN 0.994 + random() * 0.004
        WHEN n <= 20 THEN 0.992 + random() * 0.005
        ELSE 0.989 + random() * 0.008
    END,
    CASE WHEN n <= 8 THEN true ELSE random() > 0.25 END
FROM generate_series(0, 29) AS n
WHERE NOT EXISTS (
    SELECT 1 FROM intent_accuracy_logs WHERE period_date = current_date - (n || ' days')::INTERVAL
);

-- ============================================================================
-- 验证：输出所有表行数
-- ============================================================================
SELECT 'profiles (agents)' AS tbl, count(*) AS rows FROM profiles WHERE role = 'agent'
UNION ALL SELECT 'quality_reports', count(*) FROM quality_reports
UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs
UNION ALL SELECT 'compliance_rules', count(*) FROM compliance_rules
UNION ALL SELECT 'compliance_audit_logs', count(*) FROM compliance_audit_logs
UNION ALL SELECT 'work_orders', count(*) FROM work_orders
UNION ALL SELECT 'pending_orders', count(*) FROM pending_orders
UNION ALL SELECT 'payment_reminders', count(*) FROM payment_reminders
UNION ALL SELECT 'intent_accuracy_logs', count(*) FROM intent_accuracy_logs
UNION ALL SELECT 'system_configs', count(*) FROM system_configs
ORDER BY tbl;

-- >>> seed-cross-panel-demo.sql
-- E-Sentinel cross-panel demo data
-- Run after all migrations and the existing seed-data.sql files.
-- Safe to re-run: demo rows use stable IDs and conflict guards.
-- The same session/report/correlation IDs intentionally appear in multiple tables
-- so the dashboard can be checked across panels.

BEGIN;

-- Local projects may not have the optional observability migration applied yet.
-- Keep the demo script self-contained without changing the production schema contract.
CREATE TABLE IF NOT EXISTS llm_call_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  endpoint TEXT NOT NULL,
  model TEXT NOT NULL,
  tokens_used INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
  success BOOLEAN NOT NULL DEFAULT false,
  cached BOOLEAN NOT NULL DEFAULT false,
  response_time_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_demo_llm_call_logs_created_at ON llm_call_logs(created_at DESC);

-- Stable IDs used by the demo dataset.
DO $$
BEGIN
  INSERT INTO model_configs (id, name, provider, model_name, temperature, max_tokens, top_p, is_default, is_active, priority)
  VALUES
    ('d1000000-0000-0000-0000-000000000001', '演示-DeepSeek 主模型', 'deepseek', 'deepseek-chat', 0.70, 4096, 1.00, true, true, 1),
    ('d1000000-0000-0000-0000-000000000002', '演示-Kimi 兜底模型', 'kimi', 'moonshot-v1-8k', 0.60, 2048, 0.95, false, true, 2),
    ('d1000000-0000-0000-0000-000000000003', '演示-轻量分类模型', 'qwen', 'qwen-turbo', 0.20, 1024, 1.00, false, true, 3)
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO prompts (id, name, scene, system_prompt, variables, temperature, max_tokens, version, status, is_active)
  VALUES
    ('d2000000-0000-0000-0000-000000000001', '演示-售前转化助手', 'pre_sale', '你是美妆品牌售前顾问。先识别肤质和需求，再给出可验证的产品建议，不承诺绝对效果。', '[{"name":"shop_name","required":true},{"name":"customer_question","required":true}]'::jsonb, 0.65, 2048, 3, 'published', true),
    ('d2000000-0000-0000-0000-000000000002', '演示-售后安抚助手', 'after_sale', '你是售后服务专员。先确认订单和问题，再说明处理时效与升级路径，涉及过敏和医疗问题必须转人工。', '[{"name":"order_id","required":true},{"name":"issue","required":true}]'::jsonb, 0.45, 2048, 2, 'published', true),
    ('d2000000-0000-0000-0000-000000000003', '演示-物流查询助手', 'logistics', '你是物流查询客服。只引用已查到的物流状态，无法确认时明确说明并提供人工跟进方式。', '[{"name":"order_id","required":true}]'::jsonb, 0.35, 1024, 2, 'published', true),
    ('d2000000-0000-0000-0000-000000000004', '演示-合规回复审校', 'general', '审查客服回复中的绝对化用语、虚假承诺、平台比较和敏感表达，并给出可直接替换的合规版本。', '[{"name":"draft_reply","required":true}]'::jsonb, 0.15, 1536, 4, 'draft', false)
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO prompt_versions (id, prompt_id, version, system_prompt, variables, temperature, max_tokens, created_by)
  VALUES
    ('d2100000-0000-0000-0000-000000000001', 'd2000000-0000-0000-0000-000000000001', 1, '你是美妆品牌售前顾问。根据客户需求推荐商品。', '[]'::jsonb, 0.70, 1536, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000002', 'd2000000-0000-0000-0000-000000000001', 2, '你是美妆品牌售前顾问。先识别肤质和需求，再给出可验证的产品建议。', '[]'::jsonb, 0.65, 2048, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000003', 'd2000000-0000-0000-0000-000000000001', 3, '你是美妆品牌售前顾问。先识别肤质和需求，再给出可验证的产品建议，不承诺绝对效果。', '[{"name":"shop_name","required":true}]'::jsonb, 0.65, 2048, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000004', 'd2000000-0000-0000-0000-000000000002', 1, '你是售后服务专员。先安抚，再核实订单，最后给出处理路径。', '[]'::jsonb, 0.50, 1536, 'demo-seed'),
    ('d2100000-0000-0000-0000-000000000005', 'd2000000-0000-0000-0000-000000000002', 2, '你是售后服务专员。涉及过敏和医疗问题必须转人工。', '[]'::jsonb, 0.45, 2048, 'demo-seed')
  ON CONFLICT (id) DO NOTHING;

  INSERT INTO bots (id, name, welcome_message, prompt_id, model_config_id, platform, working_hours, transfer_keywords, is_active)
  VALUES
    ('d3000000-0000-0000-0000-000000000001', '演示-天猫美妆客服', '您好，欢迎来到品牌旗舰店，我可以帮您查询商品、活动和订单。', 'd2000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'tmall', '{"start":"09:00","end":"23:00","timezone":"Asia/Shanghai"}'::jsonb, '["人工","投诉","过敏","医疗"]'::jsonb, true),
    ('d3000000-0000-0000-0000-000000000002', '演示-抖音售后助手', '您好，我来帮您跟进订单和售后问题，请提供订单号。', 'd2000000-0000-0000-0000-000000000002', 'd1000000-0000-0000-0000-000000000002', 'douyin', '{"start":"10:00","end":"22:00","timezone":"Asia/Shanghai"}'::jsonb, '["人工","退款","投诉","过敏"]'::jsonb, true),
    ('d3000000-0000-0000-0000-000000000003', '演示-京东物流助手', '您好，我可以帮您查询物流进度和预计送达时间。', 'd2000000-0000-0000-0000-000000000003', 'd1000000-0000-0000-0000-000000000003', 'jd', '{"start":"08:00","end":"22:00","timezone":"Asia/Shanghai"}'::jsonb, '["人工","延误","投诉"]'::jsonb, true)
  ON CONFLICT (id) DO NOTHING;
END $$;

-- Make the existing knowledge base useful for effect and hit-rate panels.
UPDATE knowledge_entries
SET hit_count = CASE category
  WHEN 'product' THEN 96
  WHEN 'faq' THEN 72
  WHEN 'after_sales_policy' THEN 58
  WHEN 'campaign' THEN 44
  ELSE 31
END,
  last_hit_at = now() - interval '12 hours',
effect_metrics = jsonb_build_object(
  'pre_update_hit_rate', 0.68,
  'post_update_hit_rate', 0.89,
  'gap_reduction_pct', 0.37,
  'sample_count', 128,
  'snapshot_date', current_date::text
)
WHERE status = 'published';

-- Additional knowledge entries used by the current sessions and work orders.
INSERT INTO knowledge_entries (id, category, platform_id, title, content, keywords, tags, priority, status, source, updated_by, version, tone, hit_count, gap_source_count, last_hit_at, effect_metrics)
SELECT v.id, v.category, p.id, v.title, v.content, v.keywords, v.tags, v.priority, v.status, 'demo-cross-panel', 'a0000000-0000-0000-0000-000000000002'::uuid, v.version, v.tone, v.hit_count, v.gap_source_count, now() - (v.hours_ago * interval '1 hour'), v.effect_metrics::jsonb
FROM (VALUES
  ('d4000000-0000-0000-0000-000000000001'::uuid, 'product', 'tmall', '神经酰胺屏障修护面霜', '含神经酰胺和泛醇，适合干燥及敏感肌日常修护。首次使用建议先做局部测试。', ARRAY['神经酰胺','屏障','敏感肌'], ARRAY['产品','敏感肌'], 8, 'published', 3, 'friendly', 84, 2, 6, '{"pre_update_hit_rate":0.63,"post_update_hit_rate":0.91,"gap_reduction_pct":0.45}'),
  ('d4000000-0000-0000-0000-000000000002'::uuid, 'faq', 'jd', 'SPF 与 PA 如何选择', '通勤可选择 SPF30 以上且 PA+++ 的产品；户外长时间活动需要按说明补涂。', ARRAY['SPF','PA','防晒'], ARRAY['FAQ','防晒'], 7, 'published', 2, 'concise', 67, 4, 12, '{"pre_update_hit_rate":0.59,"post_update_hit_rate":0.86,"gap_reduction_pct":0.38}'),
  ('d4000000-0000-0000-0000-000000000003'::uuid, 'after_sales_policy', 'douyin', '破损和漏液售后处理', '请保留外包装、订单号和商品照片。核实后可按平台规则安排补发、退款或其他处理。', ARRAY['破损','漏液','补发','退款'], ARRAY['售后','高频'], 10, 'published', 1, 'professional', 73, 5, 4, '{"pre_update_hit_rate":0.55,"post_update_hit_rate":0.88,"gap_reduction_pct":0.52}'),
  ('d4000000-0000-0000-0000-000000000004'::uuid, 'campaign', 'tmall', '夏季满减活动规则', '单笔满399元可享赠品，优惠以结算页实际展示为准，不同平台活动可能不同。', ARRAY['满减','赠品','夏季活动'], ARRAY['活动','需实时更新'], 9, 'draft', 1, 'friendly', 0, 12, 96, '{"pre_update_hit_rate":0.42,"post_update_hit_rate":0.74,"gap_reduction_pct":0.29}'),
  ('d4000000-0000-0000-0000-000000000005'::uuid, 'faq', 'pdd', '孕期护肤咨询边界', '客服只能提供产品成分和使用信息，孕期、疾病或过敏相关问题建议咨询医生，并转人工服务。', ARRAY['孕期','成分','过敏','医生'], ARRAY['FAQ','敏感问题'], 10, 'published', 0, 'professional', 52, 9, 18, '{"pre_update_hit_rate":0.48,"post_update_hit_rate":0.82,"gap_reduction_pct":0.61}')
) AS v(id, category, platform_code, title, content, keywords, tags, priority, status, version, tone, hit_count, gap_source_count, hours_ago, effect_metrics)
JOIN platforms p ON p.code = v.platform_code
ON CONFLICT (id) DO NOTHING;

-- More bot configurations with effect snapshots, linked to the same platforms.
INSERT INTO bot_configs (id, platform_id, config_type, config_key, config_value, version, status, updated_by, change_summary, source_type, source_session_ids, effect_metrics, created_at, updated_at)
SELECT v.id, p.id, v.config_type, v.config_key, v.config_value::jsonb, v.version, v.status, 'a0000000-0000-0000-0000-000000000002'::uuid, v.change_summary, v.source_type, ARRAY['b1000000-0000-0000-0000-' || lpad(v.session_no::text, 12, '0')]::uuid[], v.effect_metrics::jsonb, now() - (v.days_ago * interval '1 day'), now() - (v.days_ago * interval '1 day')
FROM (VALUES
  ('d5000000-0000-0000-0000-000000000001'::uuid, 'tmall', 'pre_sale', 'demo_product_recommend', '{"greeting":"您好，我可以根据肤质和预算推荐产品。","max_rounds":6}', 3, 'active', '基于售前询单样本优化推荐顺序', 'inspect_script', 1, '{"pre_publish_satisfaction":0.81,"post_publish_satisfaction":0.91,"post_publish_handled_rate":0.88}', 2),
  ('d5000000-0000-0000-0000-000000000002'::uuid, 'tmall', 'post_sale', 'demo_allergy_escalation', '{"trigger_keywords":["过敏","红疹","就医"],"action":"transfer_human"}', 2, 'active', '增加敏感问题人工升级', 'knowledge_loop', 2, '{"pre_publish_satisfaction":0.63,"post_publish_satisfaction":0.86,"post_publish_handled_rate":0.72}', 3),
  ('d5000000-0000-0000-0000-000000000003'::uuid, 'jd', 'pre_sale', 'demo_sunscreen_faq', '{"knowledge_title":"SPF 与 PA 如何选择","fallback":"转人工"}', 2, 'active', '补充防晒高频问答', 'inspect_script', 3, '{"pre_publish_satisfaction":0.78,"post_publish_satisfaction":0.89,"post_publish_handled_rate":0.84}', 4),
  ('d5000000-0000-0000-0000-000000000004'::uuid, 'douyin', 'post_sale', 'demo_damage_claim', '{"required_fields":["订单号","照片"],"sla_hours":24}', 2, 'draft', '等待合规复核后发布', 'llm_suggest', 4, '{"pre_publish_satisfaction":0.71,"post_publish_satisfaction":0.79,"post_publish_handled_rate":0.67}', 1),
  ('d5000000-0000-0000-0000-000000000005'::uuid, 'pdd', 'pre_sale', 'demo_coupon_explain', '{"coupon_rules":["满199减20","不可与部分券叠加"],"avoid_claims":["全网最低"]}', 2, 'active', '修正优惠券解释和合规措辞', 'manual', 5, '{"pre_publish_satisfaction":0.74,"post_publish_satisfaction":0.84,"post_publish_handled_rate":0.79}', 5),
  ('d5000000-0000-0000-0000-000000000006'::uuid, 'xiaohongshu', 'pre_sale', 'demo_content_referral', '{"source":"官方笔记","disclaimer":"以商品详情页为准"}', 1, 'active', '增加内容种草来源说明', 'manual', 6, '{"pre_publish_satisfaction":0.80,"post_publish_satisfaction":0.88,"post_publish_handled_rate":0.82}', 6)
) AS v(id, platform_code, config_type, config_key, config_value, version, status, change_summary, source_type, session_no, effect_metrics, days_ago)
JOIN platforms p ON p.code = v.platform_code
ON CONFLICT (id) DO NOTHING;

-- 60 recent sessions across five platforms. The corresponding fixed report IDs,
-- shadow replies, unresolved questions, and correlation IDs are derived from n.
DO $$
DECLARE
  n integer;
  platform_code text;
  session_type text;
  inquiry_result text;
  satisfaction text;
  bot_handled boolean;
  bot_id uuid;
  session_id uuid;
  agent_id uuid;
  created_at_value timestamptz;
BEGIN
  FOR n IN 1..60 LOOP
    platform_code := (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1];
    session_type := CASE WHEN n % 3 = 0 THEN 'post_sale' ELSE 'pre_sale' END;
    inquiry_result := CASE WHEN session_type = 'post_sale' THEN NULL WHEN n % 7 = 0 THEN 'lost' WHEN n % 11 = 0 THEN 'pending' ELSE 'converted' END;
    satisfaction := CASE WHEN n % 9 = 0 THEN 'bad' WHEN n % 4 = 0 THEN 'neutral' ELSE 'good' END;
    bot_handled := n % 8 <> 0;
    bot_id := CASE platform_code WHEN 'tmall' THEN 'd3000000-0000-0000-0000-000000000001'::uuid WHEN 'douyin' THEN 'd3000000-0000-0000-0000-000000000002'::uuid ELSE 'd3000000-0000-0000-0000-000000000003'::uuid END;
    session_id := ('b1000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid;
    agent_id := CASE (n % 5) WHEN 0 THEN 'a0000000-0000-0000-0000-000000000003'::uuid WHEN 1 THEN 'a0000000-0000-0000-0000-000000000004'::uuid WHEN 2 THEN '00000000-0000-0000-0000-000000000101'::uuid WHEN 3 THEN '00000000-0000-0000-0000-000000000102'::uuid ELSE '00000000-0000-0000-0000-000000000103'::uuid END;
    created_at_value := CASE WHEN n <= 12 THEN now() - (n * interval '2 hours') ELSE now() - ((n % 30 + 1) * interval '1 day') END;

    INSERT INTO bot_chat_sessions (id, platform_id, session_type, external_session_id, customer_id, bot_handled, transfer_reason, is_inquiry, inquiry_result, sentiment_score, satisfaction, total_messages, first_response_ms, resolution_ms, tags, conversation, correlation_id, bot_id, tenant_id, created_at)
    SELECT session_id, p.id, session_type, 'demo-' || platform_code || '-' || lpad(n::text, 3, '0'), 'demo-customer-' || lpad(n::text, 3, '0'), bot_handled,
      CASE WHEN bot_handled THEN NULL WHEN n % 3 = 0 THEN 'sensitive_issue' ELSE 'complex_product_query' END,
      session_type = 'pre_sale', inquiry_result, CASE WHEN satisfaction = 'bad' THEN 1 WHEN satisfaction = 'neutral' THEN 3 ELSE 5 END, satisfaction,
      4 + (n % 12), 450 + (n % 8) * 180, CASE WHEN satisfaction = 'bad' THEN 480000 ELSE 60000 + (n % 8) * 30000 END,
      CASE WHEN n % 5 = 0 THEN ARRAY['敏感肌','成分'] ELSE ARRAY['产品咨询','demo'] END,
      CASE WHEN session_type = 'pre_sale' THEN '顾客: 这款产品适合敏感肌吗？\n机器人: 建议先查看成分并做局部测试，我可以继续帮您匹配。\n顾客: 还有优惠活动吗？\n机器人: 当前活动以结算页展示为准。' ELSE '顾客: 我的订单需要查询售后进度。\n机器人: 请提供订单号和问题照片，我会先核实状态。\n顾客: 已经提交过了，什么时候能处理？' END,
      'corr-demo-' || lpad(n::text, 3, '0'), bot_id, 'default', created_at_value
    FROM platforms p WHERE p.code = platform_code
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO quality_reports (id, ticket_id, agent_id, reviewer_id, conversation, intent, sentiment_score, total_score, violations, risk_level, status, correlation_id, review_mode, is_bot_session, bot_session_id, platform_id, tenant_id, created_at)
    SELECT ('c1000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, 'demo-' || platform_code || '-' || lpad(n::text, 3, '0'), agent_id,
      'a0000000-0000-0000-0000-000000000002'::uuid, '顾客咨询与客服回复的演示质检记录', CASE WHEN session_type = 'pre_sale' THEN '产品咨询' ELSE '售后进度' END,
      CASE WHEN satisfaction = 'bad' THEN 1 WHEN satisfaction = 'neutral' THEN 3 ELSE 5 END,
      CASE WHEN satisfaction = 'bad' THEN 48 + (n % 12) WHEN satisfaction = 'neutral' THEN 72 + (n % 10) ELSE 88 + (n % 10) END,
      CASE WHEN satisfaction = 'bad' THEN '[{"rule":"未明确说明升级路径","category":"服务质量","deduction":15,"severity":"major"},{"rule":"未确认客户已提交材料","category":"响应效率","deduction":10,"severity":"medium"}]'::jsonb WHEN n % 6 = 0 THEN '[{"rule":"活动规则引用不完整","category":"准确性","deduction":8,"severity":"minor"}]'::jsonb ELSE '[]'::jsonb END,
      CASE WHEN satisfaction = 'bad' THEN 'high' WHEN n % 10 = 0 THEN 'medium' ELSE 'low' END,
      CASE WHEN n % 10 = 0 THEN 'pending_review' WHEN n % 13 = 0 THEN 'overturned' ELSE 'confirmed' END,
      'corr-demo-' || lpad(n::text, 3, '0'), CASE WHEN n % 4 = 0 THEN 'shadow' ELSE 'active' END, true, session_id, p.id, 'default', created_at_value + interval '5 minutes'
    FROM platforms p WHERE p.code = platform_code
    ON CONFLICT (id) DO NOTHING;
  END LOOP;
END $$;

-- Recent shadow and actual replies feed quality monitoring and shadow approval.
DO $$
DECLARE
  n integer;
  code text;
BEGIN
  FOR n IN 1..72 LOOP
    code := (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1];
    INSERT INTO shadow_replies (id, platform_id, session_id, message_id, customer_id, original_text, generated_reply, reply_mode, llm_latency_ms, was_fallback, cached, gate_reason, gate_tier, quality_score, metadata, created_at)
    VALUES (
      ('d6000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, code, 'demo-session-' || code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), 'demo-msg-shadow-' || n, 'demo-customer-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'),
      CASE WHEN n % 3 = 0 THEN '我的订单什么时候发货？' WHEN n % 3 = 1 THEN '敏感肌可以用吗？' ELSE '现在有什么优惠？' END,
      CASE WHEN n % 3 = 0 THEN '我先帮您查询物流状态，确认后给出预计发货时间。' WHEN n % 3 = 1 THEN '建议先查看完整成分表并做局部测试，涉及过敏问题可转人工。' ELSE '活动和优惠以当前商品结算页展示为准。' END,
      CASE WHEN n % 4 = 0 THEN 'gradual' ELSE 'shadow' END, 380 + (n % 9) * 210, n % 17 = 0, n % 5 = 0,
      CASE WHEN n % 4 = 0 THEN 'simple_question_match' ELSE 'whitelist_match' END, CASE WHEN n % 4 = 0 THEN 'simple_questions' ELSE 'whitelist' END,
      CASE WHEN n % 17 = 0 THEN 0.62 ELSE 0.86 + (n % 10) / 100.0 END,
      jsonb_build_object('store_nick', code || '_demo_store', 'correlation_id', 'corr-demo-' || lpad(((n - 1) % 60 + 1)::text, 3, '0')), now() - (n * interval '18 minutes')
    ) ON CONFLICT (id) DO NOTHING;

    IF n <= 36 THEN
      INSERT INTO actual_replies (id, platform_id, session_id, message_id, customer_id, original_text, generated_reply, sanitized_reply, reply_mode, llm_latency_ms, was_fallback, compliance_safe, compliance_block_reason, sent_success, sent_at, platform_msg_id, quality_score, metadata, created_at)
      VALUES (
        ('d6100000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, code, 'demo-session-' || code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), 'demo-msg-actual-' || n, 'demo-customer-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'),
        '我想确认一下这个订单和产品信息。', '您好，我来帮您核实订单和商品信息。', '您好，我来帮您核实订单和商品信息。', CASE WHEN n % 3 = 0 THEN 'full' ELSE 'gradual' END, 420 + (n % 7) * 240, n % 19 = 0,
        n % 11 <> 0, CASE WHEN n % 11 = 0 THEN '命中敏感问题，需要人工复核' ELSE NULL END, n % 4 <> 0, CASE WHEN n % 4 <> 0 THEN now() - (n * interval '25 minutes') ELSE NULL END,
        CASE WHEN n % 4 <> 0 THEN 'platform-msg-' || n ELSE NULL END, CASE WHEN n % 11 = 0 THEN 0.58 ELSE 0.82 + (n % 12) / 100.0 END,
        jsonb_build_object('approved', n % 4 <> 0, 'reviewed_by', CASE WHEN n % 4 <> 0 THEN 'demo-operator' ELSE NULL END, 'correlation_id', 'corr-demo-' || lpad(((n - 1) % 60 + 1)::text, 3, '0')), now() - (n * interval '25 minutes')
      ) ON CONFLICT (id) DO NOTHING;
    END IF;
  END LOOP;
END $$;

-- LLM ledger rows are persisted so the observability panel is populated after a restart.
INSERT INTO llm_call_logs (id, endpoint, model, tokens_used, cost_estimate, success, cached, response_time_ms, created_at)
SELECT ('d6200000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 5 WHEN 0 THEN '/api/qa/evaluate' WHEN 1 THEN '/api/qa/satisfaction/analyze' WHEN 2 THEN '/api/qa/knowledge/search' WHEN 3 THEN '/api/qa/payment-reminders' ELSE '/api/qa/prompts/generate' END,
  CASE n % 3 WHEN 0 THEN 'deepseek-chat' WHEN 1 THEN 'moonshot-v1-8k' ELSE 'qwen-turbo' END,
  320 + (n % 15) * 47, round((0.002 + (n % 8) * 0.0007)::numeric, 6), n % 13 <> 0, n % 5 = 0, 620 + (n % 18) * 310,
  now() - (n * interval '4 minutes')
FROM generate_series(1, 120) AS n
ON CONFLICT (id) DO NOTHING;

-- Unresolved questions mirror the transferred or low-satisfaction sessions.
INSERT INTO unresolved_questions (id, session_id, platform_id, platform_code, user_question, ai_reply, transfer_reason, satisfaction, conversation, category, tags, status, priority, assigned_to, note, resolved_by, resolved_at, correlation_id, created_at, updated_at)
SELECT ('d6300000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  'demo-session-' || p.code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), p.id, p.code,
  CASE n % 5 WHEN 0 THEN '孕期可以使用这款产品吗？' WHEN 1 THEN '商品漏液了，已经提交照片，什么时候处理？' WHEN 2 THEN '这个成分和我正在使用的药会冲突吗？' WHEN 3 THEN '订单一直没有物流更新怎么办？' ELSE '活动优惠和直播间券可以一起使用吗？' END,
  '这个问题需要进一步核实，我先为您转接人工客服。', CASE n % 3 WHEN 0 THEN 'sensitive_issue' WHEN 1 THEN 'policy_unclear' ELSE 'complex_product_query' END,
  CASE n % 4 WHEN 0 THEN 'bad' WHEN 1 THEN 'neutral' ELSE 'good' END,
  '顾客: 需要确认一个复杂问题。\n机器人: 已记录问题，但当前需要人工核实。\n顾客: 请尽快给我明确答复。',
  CASE n % 4 WHEN 0 THEN '敏感问题' WHEN 1 THEN '售后政策' WHEN 2 THEN '物流查询' ELSE '活动规则' END,
  ARRAY['demo','需人工核实'], CASE n % 5 WHEN 0 THEN 'resolved' WHEN 1 THEN 'processing' WHEN 2 THEN 'exported' ELSE 'pending' END,
  CASE WHEN n % 5 = 0 THEN 2 WHEN n % 3 = 0 THEN 1 ELSE 0 END, CASE WHEN n % 5 = 0 THEN 'ou_demo_001' ELSE NULL END,
  CASE WHEN n % 5 = 0 THEN '已补充知识库条目并回访客户' ELSE NULL END, CASE WHEN n % 5 = 0 THEN 'demo-operator' ELSE NULL END,
  CASE WHEN n % 5 = 0 THEN now() - ((n % 16 + 1) * interval '1 hour') ELSE NULL END,
  'corr-demo-' || lpad(((n - 1) % 60 + 1)::text, 3, '0'), now() - ((n % 7 + 1) * interval '1 day'), now()
FROM generate_series(1, 24) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

INSERT INTO unresolved_question_logs (id, unresolved_id, action, operator, detail, created_at)
SELECT ('d6400000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, ('d6300000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE WHEN n % 3 = 0 THEN 'resolve' WHEN n % 3 = 1 THEN 'assign' ELSE 'create' END, 'demo-operator', jsonb_build_object('source','cross-panel-demo','step',n), now() - (n * interval '20 hours')
FROM generate_series(1, 24) AS n
ON CONFLICT (id) DO NOTHING;

-- Intent accuracy: one row per platform/day for a 30-day trend with a few alert days.
INSERT INTO intent_accuracy_logs (id, platform_id, period_date, total_recognitions, correct_recognitions, incorrect_recognitions, accuracy, coverage_rate, target_met, bad_case_ids, notes, created_at)
SELECT ('d6500000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, p.id, current_date - ((n - 1) % 30),
  420 + (n % 9) * 23, 420 + (n % 9) * 23 - CASE WHEN n % 17 = 0 THEN 7 ELSE (n % 3) END, CASE WHEN n % 17 = 0 THEN 7 ELSE (n % 3) END,
  round(((420 + (n % 9) * 23 - CASE WHEN n % 17 = 0 THEN 7 ELSE (n % 3) END)::numeric / (420 + (n % 9) * 23))::numeric, 4),
  round((0.95 + (n % 5) * 0.01)::numeric, 4), n % 17 <> 0 AND n % 11 <> 0, ARRAY[]::uuid[], CASE WHEN n % 17 = 0 THEN '演示告警日：需复核低置信度意图' ELSE '每日抽样复核' END, now() - (n * interval '10 hours')
FROM generate_series(1, 150) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu','vip','kuaishou','weibo'])[((n - 1) % 8) + 1]
ON CONFLICT (platform_id, period_date) DO NOTHING;

-- Work orders and action history cover every status and priority branch.
INSERT INTO work_orders (id, title, description, source, source_id, priority, status, category, platform_id, assigned_to, metadata, created_at, resolved_at, closed_at)
SELECT ('d6600000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 5 WHEN 0 THEN '敏感问题升级路径需要补充' WHEN 1 THEN '物流延迟话术需要平台适配' WHEN 2 THEN '活动优惠规则需要重新发布' WHEN 3 THEN '漏液售后知识条目需要复核' ELSE '机器人回复质量抽样复盘' END,
  '演示工单：由质检、合规、知识库或监控面板产生，关联同一批演示会话。',
  CASE n % 5 WHEN 0 THEN 'compliance_block' WHEN 1 THEN 'qa_evaluate' WHEN 2 THEN 'cron' WHEN 3 THEN 'inspection' ELSE 'manual' END,
  ('c1000000-0000-0000-0000-' || lpad((n % 60 + 1)::text, 12, '0'))::uuid,
  CASE n % 4 WHEN 0 THEN 'critical' WHEN 1 THEN 'high' WHEN 2 THEN 'medium' ELSE 'low' END,
  CASE n % 4 WHEN 0 THEN 'open' WHEN 1 THEN 'in_progress' WHEN 2 THEN 'resolved' ELSE 'closed' END,
  CASE n % 5 WHEN 0 THEN 'compliance' WHEN 1 THEN 'script_fix' WHEN 2 THEN 'knowledge_gap' WHEN 3 THEN 'customer_complaint' ELSE 'system_issue' END,
  p.id, CASE n % 3 WHEN 0 THEN 'a0000000-0000-0000-0000-000000000003'::uuid WHEN 1 THEN 'a0000000-0000-0000-0000-000000000004'::uuid ELSE '00000000-0000-0000-0000-000000000101'::uuid END,
  jsonb_build_object('source_panel', CASE n % 4 WHEN 0 THEN '合规审核' WHEN 1 THEN '质检中枢' WHEN 2 THEN '知识库' ELSE '回复质量监控' END, 'demo', true),
  now() - (n * interval '9 hours'), CASE WHEN n % 4 >= 2 THEN now() - (n * interval '4 hours') ELSE NULL END, CASE WHEN n % 4 = 3 THEN now() - (n * interval '3 hours') ELSE NULL END
FROM generate_series(1, 24) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

INSERT INTO work_order_actions (id, work_order_id, action, comment, performed_by, metadata, created_at)
SELECT ('d6700000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, ('d6600000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 4 WHEN 0 THEN 'created' WHEN 1 THEN 'assigned' WHEN 2 THEN 'in_progress' ELSE 'commented' END,
  CASE n % 4 WHEN 0 THEN '系统自动创建' WHEN 1 THEN '已分配给坐席' WHEN 2 THEN '负责人开始处理' ELSE '补充了关联会话和证据' END,
  'a0000000-0000-0000-0000-000000000002'::uuid, jsonb_build_object('demo', true, 'correlation_id', 'corr-demo-' || lpad(n::text, 3, '0')), now() - (n * interval '7 hours')
FROM generate_series(1, 24) AS n
ON CONFLICT (id) DO NOTHING;

-- Payment reminders include pending, reminded, paid, expired and cancelled orders.
INSERT INTO pending_orders (id, external_order_id, platform_id, customer_id, customer_name, product_name, order_amount, order_status, created_at_order, expire_at, metadata, created_at, updated_at)
SELECT ('d6800000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, 'DEMO-ORDER-' || lpad(n::text, 4, '0'), p.id, 'demo-customer-' || n, '演示客户' || n,
  CASE n % 4 WHEN 0 THEN '舒缓修护套装' WHEN 1 THEN '神经酰胺面霜' WHEN 2 THEN '玻尿酸补水面膜' ELSE '防晒乳 SPF50+' END,
  (129 + n * 17.5)::numeric(10,2), CASE n % 5 WHEN 0 THEN 'pending_payment' WHEN 1 THEN 'reminded' WHEN 2 THEN 'paid' WHEN 3 THEN 'expired' ELSE 'cancelled' END,
  now() - (n * interval '5 hours'), now() + ((24 - n) * interval '1 hour'), jsonb_build_object('source','demo-cross-panel','session_id','demo-session-' || p.code || '-' || lpad(((n - 1) % 60 + 1)::text, 3, '0')),
  now() - (n * interval '4 hours'), now() - (n * interval '2 hours')
FROM generate_series(1, 20) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

INSERT INTO payment_reminders (id, order_id, round, script, channel, status, sent_at, converted_at, response, metadata, created_at)
SELECT ('d6900000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid, ('d6800000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE WHEN n % 6 = 0 THEN 2 ELSE 1 END, '温馨提醒：您的订单还未支付，活动库存会随时变化，请及时完成支付。', CASE n % 3 WHEN 0 THEN 'bot' WHEN 1 THEN 'app_push' ELSE 'feishu' END,
  CASE n % 5 WHEN 0 THEN 'pending' WHEN 1 THEN 'sent' WHEN 2 THEN 'converted' WHEN 3 THEN 'delivered' ELSE 'failed' END,
  now() - (n * interval '2 hours'), CASE WHEN n % 5 = 2 THEN now() - (n * interval '1 hour') ELSE NULL END,
  CASE WHEN n % 5 = 2 THEN '已完成支付，谢谢提醒' ELSE NULL END, jsonb_build_object('demo', true, 'round_label', '第' || CASE WHEN n % 6 = 0 THEN 2 ELSE 1 END || '轮'), now() - (n * interval '2 hours')
FROM generate_series(1, 20) AS n
ON CONFLICT (id) DO NOTHING;

-- Compliance history provides passed, flagged and blocked examples.
INSERT INTO compliance_audit_logs (id, source_type, source_id, content_snippet, risk_level, matched_rules, decision, reviewed_by, review_notes, correlation_id, created_at)
SELECT ('d7000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 3 WHEN 0 THEN 'knowledge_entry' WHEN 1 THEN 'bot_config' ELSE 'chat_message' END,
  ('d4000000-0000-0000-0000-' || lpad((n % 5 + 1)::text, 12, '0'))::uuid,
  CASE n % 4 WHEN 0 THEN '本产品全网第一，马上见效' WHEN 1 THEN '您好，建议先查看成分表并做局部测试' WHEN 2 THEN '活动最后一天，点击领取优惠' ELSE '您的订单已进入仓库配货流程' END,
  CASE n % 4 WHEN 0 THEN 1 WHEN 1 THEN NULL WHEN 2 THEN 3 ELSE NULL END,
  CASE n % 4 WHEN 0 THEN '[{"rule_text":"绝对化用语","category":"absolute_claim","action":"blocked"}]'::jsonb WHEN 2 THEN '[{"rule_text":"诱导点击","category":"platform_rule","action":"flagged"}]'::jsonb ELSE '[]'::jsonb END,
  CASE n % 4 WHEN 0 THEN 'blocked' WHEN 2 THEN 'flagged' ELSE 'passed' END,
  CASE WHEN n % 4 = 1 THEN NULL ELSE 'a0000000-0000-0000-0000-000000000002'::uuid END,
  CASE WHEN n % 4 = 0 THEN '已拦截并生成工单' WHEN n % 4 = 2 THEN '待运营确认活动上下文' ELSE NULL END,
  'corr-demo-compliance-' || lpad(n::text, 3, '0'), now() - (n * interval '6 hours')
FROM generate_series(1, 48) AS n
ON CONFLICT (id) DO NOTHING;

-- Audit rows tie panel operations back to the same reports/configs/knowledge.
INSERT INTO audit_logs (id, action, user_id, user_name, resource_type, resource_id, detail, correlation_id, created_at)
SELECT ('d7100000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 8 WHEN 0 THEN 'evaluate' WHEN 1 THEN 'knowledge_update' WHEN 2 THEN 'bot_config_activate' WHEN 3 THEN 'compliance_warn' WHEN 4 THEN 'work_order_create' WHEN 5 THEN 'llm_call' WHEN 6 THEN 'report_generate' ELSE 'unresolved_questions_create' END,
  CASE WHEN n % 4 = 0 THEN NULL ELSE 'a0000000-0000-0000-0000-000000000002'::uuid END, CASE WHEN n % 4 = 0 THEN 'system' ELSE '李婷' END,
  CASE n % 8 WHEN 0 THEN 'quality_report' WHEN 1 THEN 'knowledge_entry' WHEN 2 THEN 'bot_config' WHEN 3 THEN 'compliance_rules' WHEN 4 THEN 'work_orders' WHEN 5 THEN 'llm' WHEN 6 THEN 'robot_report' ELSE 'unresolved_questions' END,
  CASE n % 8 WHEN 0 THEN 'c1000000-0000-0000-0000-' || lpad((n % 60 + 1)::text, 12, '0') WHEN 1 THEN 'd4000000-0000-0000-0000-' || lpad((n % 5 + 1)::text, 12, '0') WHEN 2 THEN 'd5000000-0000-0000-0000-' || lpad((n % 6 + 1)::text, 12, '0') WHEN 4 THEN 'd6600000-0000-0000-0000-' || lpad((n % 24 + 1)::text, 12, '0') ELSE NULL END,
  jsonb_build_object('demo', true, 'panel', CASE n % 8 WHEN 0 THEN 'qa' WHEN 1 THEN 'knowledge-base' WHEN 2 THEN 'bot-config' WHEN 3 THEN 'compliance' WHEN 4 THEN 'work-orders' WHEN 5 THEN 'llm-metrics' WHEN 6 THEN 'reports' ELSE 'unresolved' END),
  CASE WHEN n % 8 IN (0, 4) THEN 'corr-demo-' || lpad((n % 60 + 1)::text, 3, '0') ELSE 'corr-demo-audit-' || lpad(n::text, 3, '0') END, now() - (n * interval '5 hours')
FROM generate_series(1, 80) AS n
ON CONFLICT (id) DO NOTHING;

-- Daily/weekly/monthly reports cover the data center's three report types.
INSERT INTO robot_reports (id, report_type, period_start, period_end, platform_id, summary_md, metrics, optimization_plan, industry_compare, generated_by, created_at)
SELECT ('d7200000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE WHEN n % 3 = 0 THEN 'daily' WHEN n % 3 = 1 THEN 'weekly' ELSE 'monthly' END,
  current_date - CASE WHEN n % 3 = 0 THEN (n / 3) ELSE CASE WHEN n % 3 = 1 THEN (n / 3 + 1) * 7 ELSE (n / 3 + 1) * 30 END END,
  current_date - CASE WHEN n % 3 = 0 THEN (n / 3) ELSE CASE WHEN n % 3 = 1 THEN (n / 3 + 1) * 7 - 6 ELSE (n / 3 + 1) * 30 - 29 END END,
  p.id,
  '# 演示运营报告\n\n本报告关联客服会话、质检报告、知识命中和合规扫描数据。\n\n- 建议优先处理高风险售后与活动规则话术。',
  jsonb_build_object('sessions', 36 + n * 2, 'qa_reports', 28 + n, 'satisfaction_rate', 0.82 + (n % 6) / 100.0, 'conversion_rate', 0.18 + (n % 5) / 100.0, 'critical_count', n % 4),
  '1. 补齐敏感问题知识库；\n2. 对高风险回复启用人工审批；\n3. 每日复核流失原因。',
  jsonb_build_object('industry_avg_conversion', 0.12, 'industry_top_conversion', 0.22, 'sample_period', '2026'), 'demo-seed', now() - (n * interval '1 day')
FROM generate_series(1, 18) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu','vip'])[((n - 1) % 6) + 1]
ON CONFLICT (id) DO NOTHING;

-- Optimization tasks connect inquiry loss, satisfaction, chats and knowledge gaps.
INSERT INTO optimization_tasks (id, source, category, title, description, priority, status, platform_id, related_chat_id, related_knowledge_id, assigned_to, resolution, impact_estimate, created_by, created_at, resolved_at)
SELECT ('d7300000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid,
  CASE n % 5 WHEN 0 THEN 'inquiry_loss' WHEN 1 THEN 'satisfaction' WHEN 2 THEN 'chat_inspection' WHEN 3 THEN 'knowledge_gap' ELSE 'campaign' END,
  CASE n % 4 WHEN 0 THEN '转化' WHEN 1 THEN '服务质量' WHEN 2 THEN '物流' ELSE '知识库' END,
  CASE n % 4 WHEN 0 THEN '优化优惠券解释，减少询单流失' WHEN 1 THEN '补充敏感肌售后升级话术' WHEN 2 THEN '完善物流延迟预计时间回复' ELSE '建立防晒和孕期咨询知识条目' END,
  '演示优化任务，来源于面板中的会话、评分、知识命中和活动数据。', CASE n % 4 WHEN 0 THEN 'high' WHEN 1 THEN 'critical' WHEN 2 THEN 'medium' ELSE 'low' END,
  CASE n % 4 WHEN 0 THEN 'open' WHEN 1 THEN 'in_progress' WHEN 2 THEN 'resolved' ELSE 'wont_fix' END, p.id,
  ('b1000000-0000-0000-0000-' || lpad((n % 60 + 1)::text, 12, '0'))::uuid, ('d4000000-0000-0000-0000-' || lpad((n % 5 + 1)::text, 12, '0'))::uuid,
  CASE n % 2 WHEN 0 THEN 'a0000000-0000-0000-0000-000000000003'::uuid ELSE 'a0000000-0000-0000-0000-000000000004'::uuid END,
  CASE WHEN n % 4 >= 2 THEN '已更新对应话术并观察7天' ELSE NULL END, CASE n % 4 WHEN 0 THEN '预计询单转化率 +3%' WHEN 1 THEN '预计差评率 -5%' ELSE '预计命中率 +8%' END,
  'a0000000-0000-0000-0000-000000000002'::uuid, now() - (n * interval '11 hours'), CASE WHEN n % 4 >= 2 THEN now() - (n * interval '5 hours') ELSE NULL END
FROM generate_series(1, 20) AS n
JOIN platforms p ON p.code = (ARRAY['tmall','jd','douyin','pdd','xiaohongshu'])[((n - 1) % 5) + 1]
ON CONFLICT (id) DO NOTHING;

-- Runtime values keep monitoring and panels readable in the local demo.
INSERT INTO system_configs (config_key, config_value, value_type, description, category, updated_by)
VALUES
  ('tmall_auto_throttle_enabled', 'true', 'boolean', '演示：启用自动降级', 'qa', 'a0000000-0000-0000-0000-000000000001'::uuid),
  ('tmall_alert_auto_dispatch', 'false', 'boolean', '演示：告警只展示不外发', 'qa', 'a0000000-0000-0000-0000-000000000001'::uuid),
  ('tmall_shadow_daily_quota', '1000', 'number', '演示：影子回复每日配额', 'platform', 'a0000000-0000-0000-0000-000000000001'::uuid)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, value_type = EXCLUDED.value_type, description = EXCLUDED.description, category = EXCLUDED.category, updated_by = EXCLUDED.updated_by, updated_at = now();

-- Cross-panel verification: all result sets should be non-zero and key links should be intact.
SELECT 'sessions' AS table_name, count(*) AS demo_rows FROM bot_chat_sessions WHERE correlation_id LIKE 'corr-demo-%'
UNION ALL SELECT 'quality_reports', count(*) FROM quality_reports WHERE correlation_id LIKE 'corr-demo-%'
UNION ALL SELECT 'shadow_replies', count(*) FROM shadow_replies WHERE metadata->>'correlation_id' LIKE 'corr-demo-%'
UNION ALL SELECT 'actual_replies', count(*) FROM actual_replies WHERE metadata->>'correlation_id' LIKE 'corr-demo-%'
UNION ALL SELECT 'unresolved_questions', count(*) FROM unresolved_questions WHERE correlation_id LIKE 'corr-demo-%'
UNION ALL SELECT 'work_orders', count(*) FROM work_orders WHERE metadata->>'demo' = 'true'
UNION ALL SELECT 'pending_orders', count(*) FROM pending_orders WHERE metadata->>'source' = 'demo-cross-panel'
UNION ALL SELECT 'llm_call_logs', count(*) FROM llm_call_logs WHERE id::text LIKE 'd6200000-%'
ORDER BY table_name;

SELECT 'orphan_quality_reports' AS check_name, count(*) AS failures
FROM quality_reports r
LEFT JOIN bot_chat_sessions s ON s.id = r.bot_session_id
WHERE r.correlation_id LIKE 'corr-demo-%' AND s.id IS NULL
UNION ALL
SELECT 'orphan_optimization_tasks', count(*)
FROM optimization_tasks t
LEFT JOIN bot_chat_sessions s ON s.id = t.related_chat_id
WHERE t.id::text LIKE 'd7300000-%' AND s.id IS NULL;

COMMIT;

-- >>> seed-dashboard-gaps.sql
-- E-Sentinel seed data for previously-empty dashboard panels.
-- Fills: Release-evidence panel (release_evidences) + Lost-deal diagnosis panel
--        (diagnosis_sessions / diagnosis_findings / diagnosis_reviews).
-- Safe to rerun: stable IDs with ON CONFLICT DO NOTHING.
BEGIN;

-- ── Release evidence (release-evidence panel) ────────────────
INSERT INTO release_evidences (
  id, tenant_id, commit_sha, build_id, schema_version, rule_version, prompt_version,
  model_version, issue_ids, pr_ids, adr_refs, required_checks, checks_passed,
  checks_failed, status, feature_flags, target_cohort, target_percentage,
  correlation_id, approver_id, approver_name, approval_reason, approved_at,
  canary_current_stage, observation_metrics, rollback_triggered, rollback_reason,
  rollback_method, rollback_executed_at, rollback_executed_by, final_conclusion,
  created_at, updated_at
) VALUES
  -- 1) Pending: quality rule v2.1 awaiting approval
  ('f2000000-0000-0000-0000-000000000001', 'default',
   '9f2c4b7a1e8d3f6a5b2c9d0e1f8a7b6c5d4e3f2a',
   'build-20260805-01', 'schema-1.0', 'rules-v2.1', 'prompt-qa-v3', 'qwen3-8b-fp16',
   '["QA-113"]'::jsonb, '["PR-42"]'::jsonb, '["ADR-0004"]'::jsonb,
   '{"goldset-105": true, "stability-3x": true}'::jsonb, true,
   '[]'::jsonb, 'pending', '["agent_qa_new"]'::jsonb, NULL, 0,
   'rel_corr_001', NULL, NULL, NULL, NULL, NULL, '{}'::jsonb,
   false, NULL, NULL, NULL, NULL, NULL,
   NOW() - INTERVAL '2 hours', NOW() - INTERVAL '2 hours'),
  -- 2) Approved + canary in observation
  ('f2000000-0000-0000-0000-000000000002', 'default',
   '1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d',
   'build-20260803-02', 'schema-1.0', 'rules-v2.0', 'prompt-tone-v4', 'qwen3-8b-fp16',
   '["QA-089"]'::jsonb, '["PR-38"]'::jsonb, '[]'::jsonb,
   '{"human-gold-105": true}'::jsonb, true,
   '[]'::jsonb, 'approved', '["tone_policy"]'::jsonb, '5%', 5,
   'rel_corr_002',
   'a0000000-0000-0000-0000-000000000001', '张明', '话术模板更新，黄金集回放通过', NOW() - INTERVAL '2 days',
   'started', '{"conversation_count": 320, "compliance_violations": 1}'::jsonb,
   false, NULL, NULL, NULL, NULL, '观察中',
   NOW() - INTERVAL '2 days', NOW() - INTERVAL '1 day'),
  -- 3) Rolled back
  ('f2000000-0000-0000-0000-000000000003', 'default',
   '7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e',
   'build-20260728-09', 'schema-0.9', 'rules-v1.9', 'prompt-qa-v2', 'qwen3-8b-fp16',
   '["QA-061"]'::jsonb, '["PR-30"]'::jsonb, '["ADR-0003"]'::jsonb,
   '{"leak-test": true}'::jsonb, false,
   '["stable-v2-regression"]'::jsonb, 'rolled_back', '["old_rule_engine"]'::jsonb,
   '100%', 100, 'rel_corr_003',
   'a0000000-0000-0000-0000-000000000001', '张明', '发布 6h 后 FPR 上升 12%',
   NOW() - INTERVAL '8 days', NULL, '{}'::jsonb,
   true, 'FPR 上升 12%，触发回滚阈值', 'feature_flag',
   NOW() - INTERVAL '7 days', 'a0000000-0000-0000-0000-000000000001', '已回滚并冻结旧规则',
   NOW() - INTERVAL '8 days', NOW() - INTERVAL '7 days')
ON CONFLICT (id) DO NOTHING;

-- ── Lost-deal diagnosis (diagnosis panel) ───────────────────
INSERT INTO diagnosis_sessions (
  id, tenant_id, trigger_type, status, conversation_ids, campaign_id, product_id,
  time_window_start, time_window_end, engine_version, summary,
  created_by, started_at, finished_at, created_at
) VALUES (
  'e2000000-0000-0000-0000-000000000001', 'default', 'auto_batch', 'completed',
  ARRAY['sess-006', 'pdd-sess-008']::TEXT[], '618_promotion', 'Gemini-335',
  NOW() - INTERVAL '3 days', NOW() - INTERVAL '1 day', 'diagnosis-engine-v1.0',
  '{"loss_count": 14, "top_category": "price_objection", "revenue_impact": 8600}'::jsonb,
  'a0000000-0000-0000-0000-000000000001', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO diagnosis_findings (
  id, session_id, tenant_id, reason_category, fact_statement, inference_statement,
  confidence, confidence_score, counter_evidence, suggestion, suggestion_actionable,
  evidence_refs, funnel_stage, conversation_id, product_id, campaign_id, created_at
) VALUES
  ('e2000000-0000-0000-0000-000000000011', 'e2000000-0000-0000-0000-000000000001', 'default',
   'price_objection',
   '会话 pdd-sess-006 中客户因优惠券使用门槛明确表示放弃下单（原文："抱歉优惠券有使用门槛"）。',
   '618 大促优惠券设置过高的门槛，直接拦截了价格敏感客户。',
   'high', 0.82, '部分客户仍正常下单', '将优惠券门槛从满 999 降至满 299，覆盖价格敏感人群。', true,
   '[{"type": "quote", "ref": "pdd-sess-006", "text": "抱歉优惠券有使用门槛"}]'::jsonb,
   'cart', 'pdd-sess-006', 'Gemini-335', '618_promotion', NOW() - INTERVAL '2 days'),
  ('e2000000-0000-0000-0000-000000000012', 'e2000000-0000-0000-0000-000000000001', 'default',
   'service_failure',
   '会话 sess-008 中客服在客户询问物流时效时仅回复"请您耐心等待"且未给出预计到达时间。',
   '客服未提供确定性信息，削弱客户信任导致流失。',
   'medium', 0.61, '该客服整体满意度仍高于团队均值', '为物流查询配置确定性时效话术并加入质检规则。', true,
   '[{"type": "quote", "ref": "sess-008", "text": "请您耐心等待"}]'::jsonb,
   'conversation', 'sess-008', 'Gemini-335', '618_promotion', NOW() - INTERVAL '2 days')
ON CONFLICT (id) DO NOTHING;

INSERT INTO diagnosis_reviews (
  id, finding_id, tenant_id, reviewer_id, decision, modified_reason, feedback_note,
  feedback_target, created_at
) VALUES (
  'e2000000-0000-0000-0000-000000000021', 'e2000000-0000-0000-0000-000000000011',
  'default', 'a0000000-0000-0000-0000-000000000001', 'accepted', NULL,
  '价格敏感客户占比确认，门槛调整建议合理。', 'rule', NOW() - INTERVAL '1 day'
) ON CONFLICT (id) DO NOTHING;

COMMIT;

-- >>> GRANTS (Supabase standard perms for app roles)
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated, service_role;
