-- Migration 014: Prompt, Bot, Model, Knowledge management tables

-- 1. prompts table
CREATE TABLE IF NOT EXISTS prompts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID,  -- for future multi-tenant (nullable for now)
  name TEXT NOT NULL,
  scene TEXT NOT NULL,  -- 'pre_sale','after_sale','logistics','complaint','general'
  system_prompt TEXT NOT NULL,
  variables JSONB DEFAULT '[]',  -- [{name:"user_name",required:true}]
  temperature NUMERIC(3,2) DEFAULT 0.7,
  max_tokens INTEGER DEFAULT 1024,
  version INTEGER DEFAULT 1,
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. prompt_versions table (history)
CREATE TABLE IF NOT EXISTS prompt_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prompt_id UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  system_prompt TEXT NOT NULL,
  variables JSONB DEFAULT '[]',
  temperature NUMERIC(3,2) DEFAULT 0.7,
  max_tokens INTEGER DEFAULT 1024,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. bots table
CREATE TABLE IF NOT EXISTS bots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID,
  name TEXT NOT NULL,
  avatar TEXT,  -- URL to avatar image
  welcome_message TEXT DEFAULT '您好，我是AI客服助手，请问有什么可以帮您？',
  prompt_id UUID REFERENCES prompts(id) ON DELETE SET NULL,
  model_config_id UUID,  -- will reference model_configs after creation
  platform TEXT DEFAULT 'feishu',  -- 'feishu','tmall','jd','pdd','web'
  working_hours JSONB DEFAULT '{"start":"09:00","end":"22:00","timezone":"Asia/Shanghai"}',
  -- GoFly uses substring matching; a bare "人工" causes false handoffs.
  transfer_keywords JSONB DEFAULT '["转人工"]',
  is_active BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 4. model_configs table
CREATE TABLE IF NOT EXISTS model_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID,
  name TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('deepseek','kimi','moonshot','openai','zhipu','qwen')),
  model_name TEXT NOT NULL,  -- e.g. 'deepseek-chat','moonshot-v1-8k'
  api_key TEXT,  -- encrypted or reference to vault
  api_url TEXT,
  temperature NUMERIC(3,2) DEFAULT 0.7,
  max_tokens INTEGER DEFAULT 2048,
  top_p NUMERIC(3,2) DEFAULT 1.0,
  is_default BOOLEAN DEFAULT false,
  is_active BOOLEAN DEFAULT true,
  priority INTEGER DEFAULT 1,  -- lower = higher priority for fallback chain
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Extend knowledge_entries if not already done
-- Add tags and hit_count columns
ALTER TABLE knowledge_entries
ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS hit_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS tone TEXT DEFAULT 'professional' CHECK (tone IN ('professional','friendly','concise'));

-- 6. Create indexes
CREATE INDEX IF NOT EXISTS idx_prompts_scene ON prompts(scene);
CREATE INDEX IF NOT EXISTS idx_prompts_status ON prompts(status);
CREATE INDEX IF NOT EXISTS idx_bots_platform ON bots(platform);
CREATE INDEX IF NOT EXISTS idx_bots_active ON bots(is_active);
CREATE INDEX IF NOT EXISTS idx_model_configs_provider ON model_configs(provider);
CREATE INDEX IF NOT EXISTS idx_model_configs_default ON model_configs(is_default);
-- Tags index skipped (GIN on text[] requires extension; tags queried via ANY() which works fine without index for <10K rows)
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_tone ON knowledge_entries(tone);

-- 7. Insert default model configs
INSERT INTO model_configs (name, provider, model_name, temperature, max_tokens, is_default, priority) VALUES
  ('DeepSeek 标准版', 'deepseek', 'deepseek-chat', 0.7, 2048, true, 1),
  ('Kimi 标准版', 'kimi', 'moonshot-v1-8k', 0.7, 2048, false, 2),
  ('DeepSeek 轻量版', 'deepseek', 'deepseek-chat', 0.3, 1024, false, 3)
ON CONFLICT DO NOTHING;

-- 8. Insert default prompts
INSERT INTO prompts (name, scene, system_prompt, status) VALUES
  ('售前咨询', 'pre_sale', '你是{shop_name}的客服专家。用亲切专业的语气回答产品咨询，主动推荐适合的产品，引导客户下单。', 'published'),
  ('售后服务', 'after_sale', '你是{shop_name}的售后客服。耐心处理客户投诉和退换货请求，先安抚情绪再解决问题，严格按照售后政策执行。', 'published'),
  ('物流查询', 'logistics', '你是{shop_name}的物流客服。准确查询订单物流状态，对延迟情况主动致歉并给出预计到达时间。', 'published'),
  ('通用客服', 'general', '你是{shop_name}的全能客服。对不确定的问题如实告知需要核实，不承诺无法兑现的内容。', 'published')
ON CONFLICT DO NOTHING;

-- 9. Add bot_id to bot_chat_sessions (optional, for tracking which bot handled the session)
ALTER TABLE bot_chat_sessions
ADD COLUMN IF NOT EXISTS bot_id UUID REFERENCES bots(id) ON DELETE SET NULL;
