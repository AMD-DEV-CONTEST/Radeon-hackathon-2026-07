-- Forward-only PostgreSQL 17 compatible replacement for migration-016-hybrid-search.sql.
-- Generated tsvector expressions are not immutable on PostgreSQL 17, so a trigger
-- maintains a normal tsvector column instead.

ALTER TABLE public.knowledge_entries
  ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE OR REPLACE FUNCTION public.update_knowledge_search_vector()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.search_vector :=
    to_tsvector('simple', COALESCE(NEW.title, '')) ||
    to_tsvector('simple', COALESCE(NEW.content, '')) ||
    to_tsvector('simple', COALESCE(array_to_string(NEW.keywords, ' '), ''));
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_knowledge_search_vector ON public.knowledge_entries;
CREATE TRIGGER trg_knowledge_search_vector
  BEFORE INSERT OR UPDATE OF title, content, keywords
  ON public.knowledge_entries
  FOR EACH ROW
  EXECUTE FUNCTION public.update_knowledge_search_vector();

UPDATE public.knowledge_entries
SET search_vector =
  to_tsvector('simple', COALESCE(title, '')) ||
  to_tsvector('simple', COALESCE(content, '')) ||
  to_tsvector('simple', COALESCE(array_to_string(keywords, ' '), ''))
WHERE search_vector IS NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_search_vector
  ON public.knowledge_entries USING GIN (search_vector);

DROP FUNCTION IF EXISTS public.hybrid_search_vector(vector, integer);
DROP FUNCTION IF EXISTS public.hybrid_search_vector(vector, integer, text);
DROP FUNCTION IF EXISTS public.hybrid_search_keyword(text, integer);
DROP FUNCTION IF EXISTS public.hybrid_search_keyword(text, integer, text);

CREATE OR REPLACE FUNCTION public.hybrid_search_vector(
  query_embedding vector(1536),
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT ke.id, ke.title, ke.content, ke.category, ke.keywords,
         (1 - (ke.embedding <=> $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.embedding IS NOT NULL
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY ke.embedding <=> $1
  LIMIT $2
$$;

CREATE OR REPLACE FUNCTION public.hybrid_search_keyword(
  query_text text,
  match_count integer DEFAULT 20,
  tenant_id text DEFAULT NULL
)
RETURNS TABLE(
  id uuid,
  title text,
  content text,
  category text,
  keywords text[],
  similarity float
)
LANGUAGE sql
STABLE
AS $$
  SELECT ke.id, ke.title, ke.content, ke.category, ke.keywords,
         ts_rank_cd(ke.search_vector, plainto_tsquery('simple', $1))::float AS similarity
  FROM public.knowledge_entries AS ke
  WHERE ke.status = 'published'
    AND ke.search_vector @@ plainto_tsquery('simple', $1)
    AND $3 IS NOT NULL
    AND ke.tenant_id = $3
  ORDER BY similarity DESC
  LIMIT $2
$$;
