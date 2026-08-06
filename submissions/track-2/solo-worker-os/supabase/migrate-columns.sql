-- Solo Worker OS — Column migration (run once in Supabase SQL Editor)
-- Adds columns that may be missing from tables created by an older schema version.
-- Safe to re-run: every statement uses IF NOT EXISTS.

-- projects
ALTER TABLE projects ADD COLUMN IF NOT EXISTS casper_address text;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'CNY';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS deadline date NOT NULL DEFAULT CURRENT_DATE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';

-- poc tables
ALTER TABLE IF EXISTS notifications  ADD COLUMN IF NOT EXISTS read BOOLEAN DEFAULT FALSE;
ALTER TABLE IF EXISTS workflow_steps ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
