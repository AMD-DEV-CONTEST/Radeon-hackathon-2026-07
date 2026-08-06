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
