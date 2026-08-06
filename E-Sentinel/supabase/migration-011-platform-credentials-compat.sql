-- Forward-only PostgreSQL 17 compatible replacement for migration-011-platform-credentials.sql.
-- The published migration used BIGINT for platform_id although platforms.id is UUID.

ALTER TABLE public.platforms
  ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}';

CREATE TABLE IF NOT EXISTS public.platform_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform_id UUID NOT NULL REFERENCES public.platforms(id) ON DELETE CASCADE,
  credential_key TEXT NOT NULL,
  credential_value TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(platform_id, credential_key)
);

CREATE INDEX IF NOT EXISTS idx_platform_creds_lookup
  ON public.platform_credentials(platform_id, credential_key);

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'oauth2',
  'auth_url', 'https://oauth.taobao.com/authorize',
  'token_url', 'https://oauth.taobao.com/token',
  'api_base_url', 'https://eco.taobao.com/router/rest',
  'webhook_verify_method', 'md5',
  'timeout_ms', 5000,
  'rate_limit_per_minute', 60
) WHERE code = 'tmall';

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'oauth2',
  'timeout_ms', 5000,
  'webhook_verify_method', 'sha256'
) WHERE code = 'jd';

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'oauth2',
  'timeout_ms', 2000,
  'webhook_verify_method', 'md5'
) WHERE code = 'douyin';

UPDATE public.platforms SET config = jsonb_build_object(
  'auth_type', 'websocket',
  'timeout_ms', 10000,
  'webhook_verify_method', 'hmac'
) WHERE code = 'pdd';

ALTER TABLE public.system_configs DROP CONSTRAINT IF EXISTS system_configs_category_check;
ALTER TABLE public.system_configs ADD CONSTRAINT system_configs_category_check
  CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa', 'platform'));

INSERT INTO public.system_configs (config_key, config_value, value_type, description, category)
VALUES
  ('tmall_reply_enabled', 'false', 'boolean', 'Enable real reply dispatch to Tmall', 'platform'),
  ('tmall_reply_ratio', '0.1', 'number', 'Tmall reply traffic ratio (0-1)', 'platform'),
  ('tmall_circuit_error_rate', '0.05', 'number', 'Tmall circuit breaker error rate threshold', 'platform'),
  ('tmall_circuit_cooldown_seconds', '300', 'number', 'Tmall circuit breaker cooldown in seconds', 'platform')
ON CONFLICT (config_key) DO NOTHING;
