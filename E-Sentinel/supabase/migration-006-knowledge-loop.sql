-- ============================================================================
-- Migration 006: Knowledge Loop — effect tracking + review workflow
-- Adds gap_source_count, last_hit_at, hit_count to knowledge_entries
-- ============================================================================

-- 1. Add effect tracking columns to knowledge_entries
ALTER TABLE knowledge_entries
  ADD COLUMN IF NOT EXISTS gap_source_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS hit_count INT NOT NULL DEFAULT 0;

-- 2. Index for pending review queries
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_status ON knowledge_entries(status, created_at DESC);

-- 3. Update the match_knowledge_entries RPC to increment hit counters
--    (drop old version first to avoid overload conflict)
DROP FUNCTION IF EXISTS match_knowledge_entries(vector(1536), int);

CREATE OR REPLACE FUNCTION match_knowledge_entries(
  query_embedding vector(1536),
  match_count int DEFAULT 5
)
RETURNS TABLE(
  id uuid,
  category text,
  title text,
  content text,
  keywords text[],
  priority int,
  status text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  -- Increment hit counters for matched entries
  UPDATE knowledge_entries
  SET hit_count = COALESCE(hit_count, 0) + 1,
      last_hit_at = NOW()
  WHERE id IN (
    SELECT ke.id
    FROM knowledge_entries ke
    WHERE ke.status = 'published' AND ke.embedding IS NOT NULL
    ORDER BY ke.embedding <=> query_embedding
    LIMIT match_count
  );

  RETURN QUERY
  SELECT ke.id, ke.category, ke.title, ke.content, ke.keywords, ke.priority, ke.status,
         (1 - (ke.embedding <=> query_embedding))::float AS similarity
  FROM knowledge_entries ke
  WHERE ke.status = 'published' AND ke.embedding IS NOT NULL
  ORDER BY ke.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
