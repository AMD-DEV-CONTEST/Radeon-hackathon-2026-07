-- ============================================================
-- Migration: 006 — Pipeline 状态持久化表
-- 替代 FC 内存 Map，Serverless 实例回收也不丢数据
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id TEXT,
  status TEXT DEFAULT 'PENDING',       -- PENDING | PROCESSING | SUCCEEDED | FAILED
  transcript TEXT,
  segments JSONB,
  result JSONB,                        -- { tasks, new_members, errors }
  error TEXT,
  source_channel TEXT DEFAULT 'WEB_APP',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status);
