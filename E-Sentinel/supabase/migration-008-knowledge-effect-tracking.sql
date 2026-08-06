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
