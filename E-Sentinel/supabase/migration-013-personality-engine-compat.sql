-- Forward-only compatibility migration for the current system_configs schema.
-- The historical personality migration targets a different key/value schema.

ALTER TABLE public.knowledge_entries
  ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'professional';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.knowledge_entries'::regclass
      AND conname = 'knowledge_entries_tone_check'
  ) THEN
    ALTER TABLE public.knowledge_entries
      ADD CONSTRAINT knowledge_entries_tone_check
      CHECK (tone IN ('professional', 'friendly', 'concise'));
  END IF;
END
$$;

INSERT INTO public.system_configs (config_key, config_value, value_type, description, category)
VALUES
  ('style_professional', '{"name":"专业严谨","prompt_inject":"请使用正式、专业的语气回复。使用完整句子，避免口语化表达。必要时引用数据来源。","greeting":"您好，我是AI客服助手，请问有什么可以帮您？"}', 'json', '人格引擎-专业严谨风格模板', 'general'),
  ('style_friendly', '{"name":"亲切活泼","prompt_inject":"请使用亲切、温暖的语气回复。可以适当使用表情符号，让对话更自然。像朋友一样交流，但保持专业度。","greeting":"嗨～有什么可以帮你的呀？"}', 'json', '人格引擎-亲切活泼风格模板', 'general'),
  ('style_concise', '{"name":"简洁高效","prompt_inject":"请用最简洁的方式回复。直接给出答案，不添加多余解释。用短句，每条回复控制在3行以内。","greeting":"你好，请说。"}', 'json', '人格引擎-简洁高效风格模板', 'general')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    value_type = EXCLUDED.value_type,
    description = EXCLUDED.description,
    category = EXCLUDED.category;
