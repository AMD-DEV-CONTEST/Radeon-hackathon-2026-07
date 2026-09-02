-- Migration 017: Unresolved Questions 全文检索
-- 为 unresolved_questions 增加 tsvector 搜索支持

ALTER TABLE unresolved_questions
  ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_unresolved_search_vector
  ON unresolved_questions USING GIN (search_vector);

-- 触发器：自动从 user_question + ai_reply + conversation 更新向量
CREATE OR REPLACE FUNCTION update_unresolved_search_vector()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  conv_snippet text;
BEGIN
  conv_snippet := COALESCE(NEW.conversation, '');
  NEW.search_vector :=
    to_tsvector('simple', COALESCE(NEW.user_question, '')) ||
    to_tsvector('simple', COALESCE(NEW.ai_reply, '')) ||
    to_tsvector('simple', left(conv_snippet, 1000));
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_unresolved_search_vector
  BEFORE INSERT OR UPDATE OF user_question, ai_reply, conversation
  ON unresolved_questions
  FOR EACH ROW
  EXECUTE FUNCTION update_unresolved_search_vector();

-- 补填已有数据
UPDATE unresolved_questions
SET search_vector =
    to_tsvector('simple', COALESCE(user_question, '')) ||
    to_tsvector('simple', COALESCE(ai_reply, '')) ||
    to_tsvector('simple', left(COALESCE(conversation, ''), 1000))
WHERE search_vector IS NULL;
