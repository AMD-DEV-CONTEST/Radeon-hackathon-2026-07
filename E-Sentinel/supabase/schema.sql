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
