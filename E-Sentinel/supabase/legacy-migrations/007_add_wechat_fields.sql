-- ============================================================
-- Migration: 007 — 微信通道字段
-- ============================================================

ALTER TABLE team_members ADD COLUMN IF NOT EXISTS wechat_user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_team_members_wechat ON team_members(wechat_user_id) WHERE wechat_user_id IS NOT NULL;
