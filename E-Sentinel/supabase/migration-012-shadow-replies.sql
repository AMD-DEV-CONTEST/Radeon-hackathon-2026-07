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
