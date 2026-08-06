-- Solo Worker OS — Auth Migration
-- Run this in Supabase SQL Editor AFTER schema.sql and poc_schema.sql.
-- Adds user_id to all tables and tightens RLS policies.
--
-- NOTE: The app server uses the service-role key (bypasses RLS) for all writes.
-- These RLS policies protect against direct anon-key API access from the browser.

-- ── 1. Add user_id columns (nullable to avoid breaking existing rows) ────────

ALTER TABLE projects       ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE messages       ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE agent_actions  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE knowledge_docs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE notifications  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- ── 2. Indexes on user_id ────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_projects_user       ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_user       ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_user  ON agent_actions(user_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_user ON knowledge_docs(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user  ON notifications(user_id);

-- ── 3. Enable RLS on tables that didn't have it ──────────────────────────────

ALTER TABLE IF EXISTS notifications  ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS workflow_steps ENABLE ROW LEVEL SECURITY;

-- ── 4. Drop old permissive anon policies ─────────────────────────────────────

DROP POLICY IF EXISTS "projects_anon_all"      ON projects;
DROP POLICY IF EXISTS "messages_anon_all"      ON messages;
DROP POLICY IF EXISTS "agent_actions_anon_all" ON agent_actions;
DROP POLICY IF EXISTS "knowledge_docs_anon_all" ON knowledge_docs;

-- ── 5. Create user-scoped policies ───────────────────────────────────────────
-- These apply when using the anon key + a user JWT (browser client).
-- Service-role key bypasses all of these — that's intentional and safe
-- because the service role is never exposed to the browser.

CREATE POLICY "projects_own" ON projects
  FOR ALL USING (user_id IS NULL OR user_id = auth.uid()) WITH CHECK (user_id IS NULL OR user_id = auth.uid());

CREATE POLICY "messages_own" ON messages
  FOR ALL USING (user_id IS NULL OR user_id = auth.uid()) WITH CHECK (user_id IS NULL OR user_id = auth.uid());

CREATE POLICY "agent_actions_own" ON agent_actions
  FOR ALL USING (user_id IS NULL OR user_id = auth.uid()) WITH CHECK (user_id IS NULL OR user_id = auth.uid());

CREATE POLICY "knowledge_docs_own" ON knowledge_docs
  FOR ALL USING (user_id IS NULL OR user_id = auth.uid()) WITH CHECK (user_id IS NULL OR user_id = auth.uid());

CREATE POLICY "notifications_own" ON notifications
  FOR ALL USING (user_id IS NULL OR user_id = auth.uid()) WITH CHECK (user_id IS NULL OR user_id = auth.uid());

-- workflow_steps has no user_id — it's linked to projects via project_id.
-- Access is gated via the project ownership check in app code.
CREATE POLICY "workflow_steps_via_project" ON workflow_steps
  FOR ALL USING (
    project_id IN (
      SELECT id FROM projects WHERE user_id IS NULL OR user_id = auth.uid()
    )
  );
