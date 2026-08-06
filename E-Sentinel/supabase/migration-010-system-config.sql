-- ============================================================================
-- Migration 010: System Runtime Configuration
-- Enables online adjustment of key thresholds without redeployment
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_configs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key  TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    value_type  TEXT NOT NULL DEFAULT 'string' CHECK (value_type IN ('string', 'number', 'boolean', 'json')),
    description TEXT,
    category    TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'auto_publish', 'feishu', 'llm', 'compliance', 'qa')),
    updated_by  UUID REFERENCES profiles(id),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_system_configs_category ON system_configs(category);

-- Seed data: current hardcoded defaults
INSERT INTO system_configs (config_key, config_value, value_type, description, category) VALUES
    ('auto_publish_threshold', '0.95', 'number', 'Minimum LLM confidence for auto-publish (0-1)', 'auto_publish'),
    ('auto_publish_max_change_length', '50', 'number', 'Maximum change description length for auto-publish', 'auto_publish'),
    ('feishu_timeout_ms', '10000', 'number', 'Feishu API request timeout in milliseconds', 'feishu'),
    ('feishu_retry_count', '3', 'number', 'Number of retries for Feishu dispatch', 'feishu'),
    ('feishu_night_window_start', '22', 'number', 'Night window start hour (0-23), suppress non-critical alerts', 'feishu'),
    ('feishu_night_window_end', '8', 'number', 'Night window end hour (0-23)', 'feishu'),
    ('llm_rate_limit_per_minute', '30', 'number', 'LLM API rate limit (calls per minute)', 'llm'),
    ('llm_cache_ttl_hours', '24', 'number', 'LLM result cache TTL in hours', 'llm'),
    ('llm_max_retries', '3', 'number', 'LLM API retry count', 'llm'),
    ('knowledge_gap_similarity_threshold', '0.15', 'number', 'Minimum similarity to consider a knowledge match (0-1)', 'qa'),
    ('qa_kappa_alert_threshold', '0.4', 'number', 'Cohen Kappa below this triggers alert', 'qa'),
    ('compliance_auto_block_threshold', '2', 'number', 'Auto-block when compliance risk level <= this value', 'compliance'),
    ('dedup_window_days', '7', 'number', 'Deduplication window in days for auto-generated content', 'general')
ON CONFLICT (config_key) DO NOTHING;

-- RLS
ALTER TABLE system_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "System configs readable by all authenticated" ON system_configs FOR SELECT USING (true);
