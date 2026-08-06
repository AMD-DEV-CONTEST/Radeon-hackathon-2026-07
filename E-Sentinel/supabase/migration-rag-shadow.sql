-- ============================================================
-- 迁移: RAG 规则库 + 影子模式 + 校准端点
-- 执行方式: 在 Supabase SQL Editor 中逐段执行
-- ============================================================

-- ── 1. 启用 pgvector 扩展 ─────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ── 2. 质检规则库 (quality_rules) ──────────────────────────
CREATE TABLE IF NOT EXISTS quality_rules (
  id            BIGSERIAL PRIMARY KEY,
  category      TEXT NOT NULL,
  rule_text     TEXT NOT NULL,
  deduction_min INT NOT NULL DEFAULT 2,
  deduction_max INT NOT NULL DEFAULT 15,
  severity      TEXT NOT NULL DEFAULT 'major' CHECK (severity IN ('minor', 'major', 'critical')),
  examples      TEXT,
  embedding     vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_quality_rules_embedding
  ON quality_rules USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);

-- ── 3. 向量相似度检索函数 ─────────────────────────────────
CREATE OR REPLACE FUNCTION match_quality_rules(
  query_embedding vector(1536),
  match_count int DEFAULT 5
)
RETURNS TABLE (
  id BIGINT,
  category TEXT,
  rule_text TEXT,
  deduction_min INT,
  deduction_max INT,
  severity TEXT,
  examples TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    qr.id,
    qr.category,
    qr.rule_text,
    qr.deduction_min,
    qr.deduction_max,
    qr.severity,
    qr.examples,
    1 - (qr.embedding <=> query_embedding) AS similarity
  FROM quality_rules qr
  ORDER BY qr.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── 4. 质量报告表新增字段 ─────────────────────────────────
ALTER TABLE quality_reports
  ADD COLUMN IF NOT EXISTS review_mode TEXT NOT NULL DEFAULT 'active'
    CHECK (review_mode IN ('shadow', 'active')),
  ADD COLUMN IF NOT EXISTS human_score INT
    CHECK (human_score IS NULL OR (human_score BETWEEN 0 AND 100));

-- ── 5. 校准视图 (AI vs Human 对比) ─────────────────────────
CREATE OR REPLACE VIEW alignment_view AS
SELECT
  id,
  total_score AS ai_score,
  human_score,
  risk_level AS ai_risk,
  CASE
    WHEN human_score >= 90 THEN 'low'
    WHEN human_score >= 75 THEN 'medium'
    WHEN human_score >= 60 THEN 'high'
    ELSE 'critical'
  END AS human_risk
FROM quality_reports
WHERE review_mode = 'shadow'
  AND human_score IS NOT NULL
  AND status = 'confirmed';

-- 索引
CREATE INDEX IF NOT EXISTS idx_reports_review_mode ON quality_reports(review_mode);
