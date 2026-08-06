-- ============================================================
--  Solo Worker OS — POC Feature Tables
--  Run this in Supabase SQL Editor AFTER schema.sql and BEFORE auth-migration.sql
-- ============================================================

-- ── 1. Notifications (auto-trigger output) ───────────────────
CREATE TABLE IF NOT EXISTS notifications (
  id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  type        TEXT        NOT NULL,   -- deadline_reminder | weekly_report | custom
  title       TEXT        NOT NULL,
  body        TEXT        NOT NULL,
  project_id  UUID        REFERENCES projects(id) ON DELETE SET NULL,
  read        BOOLEAN     DEFAULT FALSE,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notifications_read_idx ON notifications(read, created_at DESC);

ALTER TABLE IF EXISTS notifications ADD COLUMN IF NOT EXISTS read BOOLEAN DEFAULT FALSE;

-- ── 2. Workflow State (per project) ──────────────────────────
CREATE TABLE IF NOT EXISTS workflow_steps (
  project_id  UUID        REFERENCES projects(id) ON DELETE CASCADE PRIMARY KEY,
  stage       TEXT        NOT NULL DEFAULT 'kickoff',
  checks      JSONB       NOT NULL DEFAULT '{}',
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE IF EXISTS workflow_steps ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
