-- Add Feishu push configuration columns to team_members.
-- Run this in Supabase SQL Editor.
ALTER TABLE team_members ADD COLUMN IF NOT EXISTS feishu_open_id TEXT;
ALTER TABLE team_members ADD COLUMN IF NOT EXISTS feishu_webhook_url TEXT;
ALTER TABLE team_members ADD COLUMN IF NOT EXISTS notification_preference TEXT DEFAULT 'private';
