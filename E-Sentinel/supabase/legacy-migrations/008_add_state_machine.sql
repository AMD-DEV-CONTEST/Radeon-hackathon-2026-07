-- ============================================================
-- Migration: 008 — FeishuFlow Pro: state machine + HITL
-- ============================================================

-- ── execution_steps: per-step audit trail + structured output ────────────────
CREATE TABLE IF NOT EXISTS execution_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_job_id UUID REFERENCES pipeline_jobs(id) ON DELETE CASCADE,
  step_name TEXT NOT NULL,
  step_order INT NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'PENDING',       -- PENDING | RUNNING | SUCCEEDED | FAILED | SUSPENDED_ASR | SUSPENDED_HITL
  suspend_reason TEXT,                -- 'asr_retry_exhausted' | 'hitl_confidence_low' | 'hitl_personnel_ambiguous' | null
  step_input JSONB,
  step_output JSONB,                  -- Structured output for downstream variable resolution
  resume_token TEXT,                  -- Token to resume from suspension (e.g. card message_id for HITL)
  error TEXT,
  timeout_at TIMESTAMPTZ,             -- Suspension timeout deadline
  retry_count INT DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_steps_job ON execution_steps(pipeline_job_id, step_order);
CREATE INDEX IF NOT EXISTS idx_execution_steps_status ON execution_steps(status, timeout_at);
CREATE INDEX IF NOT EXISTS idx_execution_steps_suspend ON execution_steps(suspend_reason, timeout_at)
  WHERE status IN ('SUSPENDED_ASR', 'SUSPENDED_HITL');

COMMENT ON TABLE execution_steps IS '每步骤的执行轨迹 — step_output 供下游变量解析引擎读取';
COMMENT ON COLUMN execution_steps.timeout_at IS 'HITL: 30min; ASR: 5min (3次重试后→dead)';

-- ── Update pipeline_jobs to support finer states ────────────────────────────
ALTER TABLE pipeline_jobs
  ADD COLUMN IF NOT EXISTS current_step_id UUID REFERENCES execution_steps(id),
  ADD COLUMN IF NOT EXISTS suspend_reason TEXT,
  ADD COLUMN IF NOT EXISTS timeout_at TIMESTAMPTZ;

COMMENT ON COLUMN pipeline_jobs.current_step_id IS '当前正在执行的步骤（重入时直接从此步恢复）';
COMMENT ON COLUMN pipeline_jobs.suspend_reason IS 'asr_retry_exhausted | hitl_confidence_low | hitl_personnel_ambiguous';

-- ── feishu_messages: track all sent cards for HITL lifecycle ─────────────────
CREATE TABLE IF NOT EXISTS feishu_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id TEXT NOT NULL,
  chat_id TEXT,
  message_type TEXT DEFAULT 'interactive',
  content JSONB,
  related_task_id UUID,
  related_step_id UUID REFERENCES execution_steps(id),
  status TEXT DEFAULT 'sent',          -- sent | updated | failed | expired
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_feishu_messages_task ON feishu_messages(related_task_id);
CREATE INDEX IF NOT EXISTS idx_feishu_messages_step ON feishu_messages(related_step_id);

-- ── pg_cron: scan for timed-out suspended steps ─────────────────────────────
-- NOTE: Run in Supabase SQL Editor to enable pg_cron extension first:
--   CREATE EXTENSION IF NOT EXISTS pg_cron;
-- Then schedule:
--   SELECT cron.schedule(
--     'feishuflow-scan-suspended',
--     '*/2 * * * *',
--     $$
--     SELECT feishuflow_scan_suspended();
--     $$
--   );

CREATE OR REPLACE FUNCTION feishuflow_scan_suspended()
RETURNS TABLE (
  step_id UUID,
  action_taken TEXT,
  job_id UUID
) AS $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT es.id, es.status, es.suspend_reason, es.pipeline_job_id, es.retry_count, es.timeout_at
    FROM execution_steps es
    WHERE es.status IN ('SUSPENDED_ASR', 'SUSPENDED_HITL')
      AND es.timeout_at IS NOT NULL
      AND es.timeout_at <= NOW()
    ORDER BY es.timeout_at ASC
    LIMIT 50
  LOOP
    IF rec.status = 'SUSPENDED_ASR' AND rec.retry_count < 3 THEN
      -- Retry: reset to PENDING for re-pickup
      UPDATE execution_steps
      SET status = 'PENDING', retry_count = rec.retry_count + 1, timeout_at = NOW() + INTERVAL '5 minutes'
      WHERE id = rec.id;

      UPDATE pipeline_jobs
      SET status = 'PROCESSING', suspend_reason = NULL, timeout_at = NULL
      WHERE id = rec.pipeline_job_id;

      RETURN QUERY SELECT rec.id, 'retry_asr'::TEXT, rec.pipeline_job_id;

    ELSIF rec.status = 'SUSPENDED_ASR' AND rec.retry_count >= 3 THEN
      -- ASR exhausted → dead
      UPDATE execution_steps
      SET status = 'FAILED', error = 'ASR retry exhausted after 3 attempts', completed_at = NOW()
      WHERE id = rec.id;

      UPDATE pipeline_jobs
      SET status = 'FAILED', error = 'ASR retry exhausted', updated_at = NOW()
      WHERE id = rec.pipeline_job_id;

      RETURN QUERY SELECT rec.id, 'mark_dead_asr'::TEXT, rec.pipeline_job_id;

    ELSIF rec.status = 'SUSPENDED_HITL' THEN
      -- HITL timeout → failed + needs Feishu card notification (handled by app layer)
      UPDATE execution_steps
      SET status = 'FAILED', error = 'HITL timeout (30min)', completed_at = NOW()
      WHERE id = rec.id;

      UPDATE pipeline_jobs
      SET status = 'FAILED', error = 'HITL timeout', suspend_reason = 'hitl_timeout', updated_at = NOW()
      WHERE id = rec.pipeline_job_id;

      RETURN QUERY SELECT rec.id, 'mark_failed_hitl'::TEXT, rec.pipeline_job_id;
    END IF;
  END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION feishuflow_scan_suspended() IS 'pg_cron 每2分钟扫描超时的 SUSPENDED_ASR/HITL 步骤，执行重试或标记失败';
