-- ============================================================
-- Migration: 013 — Personality Engine
-- Adds tone/style awareness to AI replies so the bot matches
-- the brand's communication style.
-- Note: system_configs table already exists from migration 194.
--       Column is `key` (not config_key), no `category` column.
-- ============================================================

-- 1. Add tone column to knowledge_entries (primary source of truth)
ALTER TABLE knowledge_entries
ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'professional'
CHECK (tone IN ('professional', 'friendly', 'concise'));

-- 2. Insert personality style templates into existing system_configs table
INSERT INTO system_configs (key, value, description) VALUES
  ('style_professional', '{"name":"专业严谨","prompt_inject":"请使用正式、专业的语气回复。使用完整句子，避免口语化表达。必要时引用数据来源。","greeting":"您好，我是AI客服助手，请问有什么可以帮您？"}', '人格引擎-专业严谨风格模板'),
  ('style_friendly', '{"name":"亲切活泼","prompt_inject":"请使用亲切、温暖的语气回复。可以适当使用表情符号，让对话更自然。像朋友一样交流，但保持专业度。","greeting":"嗨～有什么可以帮你的呀？😊"}', '人格引擎-亲切活泼风格模板'),
  ('style_concise', '{"name":"简洁高效","prompt_inject":"请用最简洁的方式回复。直接给出答案，不添加多余解释。用短句，每条回复控制在3行以内。","greeting":"你好，请说。"}', '人格引擎-简洁高效风格模板')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, description = EXCLUDED.description;
