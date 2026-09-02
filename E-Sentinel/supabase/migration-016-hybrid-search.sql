-- ============================================================================
-- Migration 016: Hybrid Search — tsvector + BM25 + RRF support
-- 为 knowledge_entries 增加全文检索能力，与 pgvector 形成双路检索
-- ============================================================================

-- ── 1. 为 knowledge_entries 增加 tsvector 列 ──────────────
ALTER TABLE knowledge_entries
  ADD COLUMN IF NOT EXISTS search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('simple', COALESCE(title, '')) ||
    to_tsvector('simple', COALESCE(content, '')) ||
    to_tsvector('simple', COALESCE(array_to_string(keywords, ' '), ''))
  ) STORED;

-- GIN 索引用于加速 tsquery
CREATE INDEX IF NOT EXISTS idx_knowledge_search_vector
  ON knowledge_entries
  USING GIN (search_vector);

-- ── 2. RPC: 向量检索 ──────────────────────────────────────
-- 功能同 match_knowledge_entries 但去掉 hit_count 副作用
-- 专供 hybrid_search 调用
CREATE OR REPLACE FUNCTION hybrid_search_vector(
  query_embedding vector(1536),
  match_count int DEFAULT 20
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  RETURN QUERY
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    (1 - (ke.embedding <=> query_embedding))::float AS similarity
  FROM knowledge_entries ke
  WHERE ke.status = 'published'
    AND ke.embedding IS NOT NULL
  ORDER BY ke.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── 3. RPC: 关键词检索 (tsvector) ──────────────────────────
-- 使用 plainto_tsquery 将用户自然语言转为 tsquery
-- ts_rank_cd 给出 BM25 风格的相关度分数
CREATE OR REPLACE FUNCTION hybrid_search_keyword(
  query_text text,
  match_count int DEFAULT 20
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  tsq tsquery;
BEGIN
  -- 将用户输入转为 tsquery（自动去除停用词）
  tsq := plainto_tsquery('simple', query_text);

  IF tsq IS NULL THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT
    ke.id,
    ke.title,
    ke.content,
    ke.category,
    ke.keywords,
    ts_rank_cd(ke.search_vector, tsq)::float AS similarity
  FROM knowledge_entries ke
  WHERE ke.status = 'published'
    AND ke.search_vector @@ tsq
  ORDER BY similarity DESC
  LIMIT match_count;
END;
$$;

-- ── 4. 创建知识点时自动填充 search_vector ──────────────────
-- （GENERATED ALWAYS AS STORED 会自动维护，无需额外 trigger）
