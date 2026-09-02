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
