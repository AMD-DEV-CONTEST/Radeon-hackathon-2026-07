-- ============================================================
-- Migration: 010 — pgvector + quality_rules + correction_samples
-- ============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ── quality_rules: AI 质检规则库 (semantic search) ─────────
CREATE TABLE IF NOT EXISTS quality_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'general',
  severity TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  embedding vector(1536),
  version INT NOT NULL DEFAULT 1,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quality_rules_embedding
  ON quality_rules USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_quality_rules_category ON quality_rules(category);
CREATE INDEX IF NOT EXISTS idx_quality_rules_active ON quality_rules(is_active);

-- ── correction_samples: 人工纠正样本 (Few-Shot learning) ──
CREATE TABLE IF NOT EXISTS correction_samples (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id TEXT,
  conversation TEXT NOT NULL,
  conversation_hash TEXT NOT NULL,
  ai_prediction JSONB NOT NULL DEFAULT '{}',
  human_correction JSONB NOT NULL DEFAULT '{}',
  correction_type TEXT NOT NULL DEFAULT 'risk_level' CHECK (correction_type IN ('risk_level', 'violation', 'score', 'other')),
  embedding vector(1536),
  is_active BOOLEAN NOT NULL DEFAULT true,
  used_count INT NOT NULL DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '30 days'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correction_samples_embedding
  ON correction_samples USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_correction_samples_active ON correction_samples(is_active);
CREATE INDEX IF NOT EXISTS idx_correction_samples_type ON correction_samples(correction_type);

-- ── Semantic match RPC: quality_rules ───────────────────────
CREATE OR REPLACE FUNCTION match_quality_rules(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.7,
  match_count int DEFAULT 5
)
RETURNS TABLE (
  id UUID,
  content TEXT,
  category TEXT,
  severity TEXT,
  similarity float
)
LANGUAGE plpgsql STABLE
AS $$
BEGIN
  RETURN QUERY
  SELECT
    qr.id,
    qr.content,
    qr.category,
    qr.severity,
    1 - (qr.embedding <=> query_embedding) AS similarity
  FROM quality_rules qr
  WHERE qr.is_active = true
    AND qr.embedding IS NOT NULL
    AND 1 - (qr.embedding <=> query_embedding) > match_threshold
  ORDER BY qr.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── Semantic match RPC: correction_samples ──────────────────
CREATE OR REPLACE FUNCTION match_correction_samples(
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.65,
  match_count int DEFAULT 5
)
RETURNS TABLE (
  id UUID,
  conversation TEXT,
  ai_prediction JSONB,
  human_correction JSONB,
  correction_type TEXT,
  similarity float
)
LANGUAGE plpgsql STABLE
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
  WHERE cs.is_active = true
    AND cs.embedding IS NOT NULL
    AND cs.expires_at > now()
    AND 1 - (cs.embedding <=> query_embedding) > match_threshold
  ORDER BY cs.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- ── Seed: basic quality rules ────────────────────────────────
INSERT INTO quality_rules (content, category, severity) VALUES
  ('客户明确表示要投诉或向监管部门举报', 'compliance', 'critical'),
  ('客服使用辱骂、讽刺、歧视性语言', 'professionalism', 'critical'),
  ('客户问题超过30分钟未得到实质回复', 'response_efficiency', 'high'),
  ('客服提供了错误的商品信息或政策说明', 'accuracy', 'high'),
  ('客户询问退款流程但客服未给出明确指引', 'service_quality', 'medium'),
  ('客服主动引导客户取消订单或离开平台', 'compliance', 'critical'),
  ('涉及食品安全或产品质量安全投诉', 'compliance', 'critical'),
  ('客户多次表达不满但客服未进行情绪安抚', 'service_quality', 'medium'),
  ('物流问题导致客户强烈不满', 'logistics', 'high'),
  ('客服承诺的处理时效未兑现', 'service_quality', 'high'),
  ('促销活动规则解释不清导致客户误解', 'accuracy', 'medium'),
  ('客户要求升级处理但客服未响应', 'service_quality', 'high'),
  ('退换货流程沟通存在明显障碍', 'logistics', 'medium'),
  ('客服未核实客户身份就处理敏感操作', 'compliance', 'high'),
  ('涉及大额退款或赔付的争议', 'compliance', 'high')
ON CONFLICT DO NOTHING;
