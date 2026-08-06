-- ============================================================================
-- Migration 011: Platform Credentials & Multi-Platform Adapter Support
-- Supabase SQL Editor compatible (no DO $$ blocks)
-- Safe to re-run: all operations are idempotent
-- ============================================================================

-- 1. Add config JSONB column to platforms (stores platform-specific settings)
ALTER TABLE platforms ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}';

-- 2. Create platform_credentials table for OAuth tokens / API keys
CREATE TABLE IF NOT EXISTS platform_credentials (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id      BIGINT NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
    credential_key   TEXT NOT NULL,
    credential_value TEXT NOT NULL,
    expires_at       TIMESTAMPTZ,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, credential_key)
);

COMMENT ON TABLE platform_credentials IS 'OAuth tokens and API keys per platform. credential_value should be encrypted at rest in production.';
COMMENT ON COLUMN platform_credentials.credential_key IS 'e.g. access_token, refresh_token, app_key, app_secret, sign_key';
COMMENT ON COLUMN platform_credentials.metadata IS 'Extra fields: seller_nick, shop_id, scope, etc.';

-- Index for fast token lookup by platform + key
CREATE INDEX IF NOT EXISTS idx_platform_creds_lookup
    ON platform_credentials(platform_id, credential_key);

-- 3. Seed platform configs for e-commerce platforms
UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'oauth2',
    'auth_url', 'https://oauth.taobao.com/authorize',
    'token_url', 'https://oauth.taobao.com/token',
    'api_base_url', 'https://eco.taobao.com/router/rest',
    'webhook_verify_method', 'md5',
    'timeout_ms', 5000,
    'rate_limit_per_minute', 60
) WHERE code = 'tmall';

UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'oauth2',
    'timeout_ms', 5000,
    'webhook_verify_method', 'sha256'
) WHERE code = 'jd';

UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'oauth2',
    'timeout_ms', 2000,
    'webhook_verify_method', 'md5'
) WHERE code = 'douyin';

UPDATE platforms SET config = jsonb_build_object(
    'auth_type', 'websocket',
    'timeout_ms', 10000,
    'webhook_verify_method', 'hmac'
) WHERE code = 'pdd';

-- 4. Add platform category to system_configs CHECK constraint
ALTER TABLE system_configs DROP CONSTRAINT IF EXISTS system_configs_category_check;
ALTER TABLE system_configs ADD CONSTRAINT system_configs_category_check
    CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa', 'platform'));

-- 5. Seed platform-specific system_configs for traffic gating
INSERT INTO system_configs (config_key, config_value, value_type, description, category)
VALUES
    ('tmall_reply_enabled', 'false', 'boolean', 'Enable real reply dispatch to Tmall', 'platform'),
    ('tmall_reply_ratio', '0.1', 'number', 'Tmall reply traffic ratio (0-1)', 'platform'),
    ('tmall_circuit_error_rate', '0.05', 'number', 'Tmall circuit breaker error rate threshold', 'platform'),
    ('tmall_circuit_cooldown_seconds', '300', 'number', 'Tmall circuit breaker cooldown in seconds', 'platform')
ON CONFLICT (config_key) DO NOTHING;
