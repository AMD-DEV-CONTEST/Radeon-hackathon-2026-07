-- ============================================================
-- Migration 005: Correction Samples + Few-Shot RPC
-- Enables dynamic Few-Shot learning: human corrections →
-- embedding → semantic retrieval → LLM prompt injection.
-- ============================================================

-- ── 1. 人工纠错样本库 (correction_samples) ──────────────────
CREATE TABLE IF NOT EXISTS correction_samples (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       UUID,
  conversation     TEXT NOT NULL,
  conversation_hash TEXT NOT NULL,
  ai_prediction    JSONB NOT NULL DEFAULT '{}',
  human_correction JSONB NOT NULL DEFAULT '{}',
  correction_type  TEXT NOT NULL DEFAULT 'risk_level',
  embedding        vector(1536),
  used_count       INT NOT NULL DEFAULT 0,
  last_used_at     TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correction_samples_hash ON correction_samples(conversation_hash);
CREATE INDEX IF NOT EXISTS idx_correction_samples_embedding
  ON correction_samples USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 10);
CREATE INDEX IF NOT EXISTS idx_correction_samples_type ON correction_samples(correction_type);

-- ── 2. RPC: 语义检索相似纠错案例 ────────────────────────────
CREATE OR REPLACE FUNCTION match_correction_samples(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.65,
  match_count int DEFAULT 3
)
RETURNS TABLE (
  id UUID,
  conversation TEXT,
  ai_prediction JSONB,
  human_correction JSONB,
  correction_type TEXT,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    cs.id,
    cs.conversation,
    cs.ai_prediction,
    cs.human_correction,
    cs.correction_type,
    1 - (cs.embedding <=> query_embedding) AS similarity
  FROM correction_samples cs
  WHERE 1 - (cs.embedding <=> query_embedding) >= match_threshold
  ORDER BY cs.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── 3. 更新 match_quality_rules 增加 threshold 过滤 ─────────
-- Drop old 2-param version to avoid overload ambiguity
DROP FUNCTION IF EXISTS match_quality_rules(vector(1536), int);
CREATE OR REPLACE FUNCTION match_quality_rules(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.6,
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
  WHERE 1 - (qr.embedding <=> query_embedding) >= match_threshold
  ORDER BY qr.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
