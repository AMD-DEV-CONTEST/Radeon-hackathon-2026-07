-- Persist knowledge references used to generate automated replies.
ALTER TABLE bot_chat_sessions
  ADD COLUMN IF NOT EXISTS knowledge_refs JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_bot_sessions_knowledge_refs
  ON bot_chat_sessions USING GIN (knowledge_refs);
