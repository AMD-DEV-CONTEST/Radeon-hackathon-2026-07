-- ============================================================
-- Migration: 005 — Pipeline 提交限流表
-- 用于 /api/pipeline/trigger 的轻量防刷
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_submissions (
  id SERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_submissions_user_time 
ON pipeline_submissions(user_id, created_at DESC);
