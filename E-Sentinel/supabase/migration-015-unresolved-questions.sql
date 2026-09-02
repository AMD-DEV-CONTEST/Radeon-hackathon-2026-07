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
