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
