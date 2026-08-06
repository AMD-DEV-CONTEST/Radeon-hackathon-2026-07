-- ============================================================================
-- Migration 003: E-Commerce Customer Service Bot Operations Platform
-- Extends E-Sentinel to cover 7 job responsibilities:
--   1. Multi-platform bot script/config optimization
--   2. Daily chat QA & problem extraction
--   3. Knowledge base optimization
--   4. Campaign/product KB sync
--   5. Inquiry loss analysis → conversion rate
--   6. Satisfaction analysis (good/bad reviews)
--   7. Daily/weekly/monthly reports + industry benchmarking
-- ============================================================================

-- Ensure pgvector extension is available (reuses migration-rag-shadow.sql setup)
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ============================================================================
-- Table: platforms — 8 e-commerce platforms
-- ============================================================================
CREATE TABLE IF NOT EXISTS platforms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    code        TEXT NOT NULL UNIQUE,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    bot_type    TEXT NOT NULL DEFAULT 'third_party' CHECK (bot_type IN ('third_party', 'native', 'hybrid')),
    api_endpoint TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Table: bot_configs — pre-sale / post-sale script configuration per platform
-- Responsibility 1 core table. Versioned for audit trail.
-- ============================================================================
CREATE TABLE IF NOT EXISTS bot_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     UUID NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
    config_type     TEXT NOT NULL CHECK (config_type IN ('pre_sale', 'post_sale')),
    config_key      TEXT NOT NULL,
    config_value    JSONB NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    updated_by      UUID REFERENCES profiles(id),
    change_summary  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, config_type, config_key, version)
);
CREATE INDEX IF NOT EXISTS idx_bot_configs_platform ON bot_configs(platform_id, config_type, status);
CREATE INDEX IF NOT EXISTS idx_bot_configs_active ON bot_configs(platform_id, config_type, config_key) WHERE status = 'active';

-- ============================================================================
-- Table: knowledge_entries — custom knowledge base
-- Core table for responsibilities 1, 3, 4. pgvector RAG enabled.
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category    TEXT NOT NULL CHECK (category IN ('product', 'faq', 'after_sales_policy', 'campaign', 'greeting')),
    platform_id UUID REFERENCES platforms(id),
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    keywords    TEXT[] NOT NULL DEFAULT '{}',
    tags        TEXT[] NOT NULL DEFAULT '{}',
    priority    INT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    source      TEXT,
    embedding   vector(1536),
    updated_by  UUID REFERENCES profiles(id),
    version     INT NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_entries(category, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_platform ON knowledge_entries(platform_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON knowledge_entries
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- RPC: match_knowledge_entries — same pattern as match_quality_rules
CREATE OR REPLACE FUNCTION match_knowledge_entries(
    query_embedding vector(1536),
    match_count int DEFAULT 5
)
RETURNS TABLE(
    id UUID,
    category TEXT,
    title TEXT,
    content TEXT,
    keywords TEXT[],
    tags TEXT[],
    priority INT,
    status TEXT,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ke.id,
        ke.category,
        ke.title,
        ke.content,
        ke.keywords,
        ke.tags,
        ke.priority,
        ke.status,
        (1 - (ke.embedding <=> query_embedding))::float AS similarity
    FROM knowledge_entries ke
    WHERE ke.status = 'published'
      AND ke.embedding IS NOT NULL
    ORDER BY ke.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================================
-- Table: bot_chat_sessions — bot chat logs
-- Responsibility 2 core data. Separate from quality_reports for scale.
-- ============================================================================
CREATE TABLE IF NOT EXISTS bot_chat_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id         UUID NOT NULL REFERENCES platforms(id),
    session_type        TEXT NOT NULL CHECK (session_type IN ('pre_sale', 'post_sale')),
    external_session_id TEXT,
    customer_id         TEXT,
    bot_handled         BOOLEAN NOT NULL DEFAULT true,
    transfer_reason     TEXT,
    is_inquiry          BOOLEAN NOT NULL DEFAULT false,
    inquiry_result      TEXT CHECK (inquiry_result IN ('converted', 'lost', 'pending', null)),
    sentiment_score     INT CHECK (sentiment_score BETWEEN 1 AND 5),
    satisfaction        TEXT CHECK (satisfaction IN ('good', 'neutral', 'bad', null)),
    total_messages      INT NOT NULL DEFAULT 0,
    first_response_ms   INT,
    resolution_ms       INT,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    conversation        TEXT NOT NULL,
    correlation_id      TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_platform ON bot_chat_sessions(platform_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_type ON bot_chat_sessions(session_type, satisfaction);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_inquiry ON bot_chat_sessions(is_inquiry, inquiry_result);
CREATE INDEX IF NOT EXISTS idx_bot_sessions_created ON bot_chat_sessions(created_at DESC);

-- ============================================================================
-- Table: optimization_tasks — tracked optimization items
-- Responsibilities 2, 3, 5, 6. Bridges analysis to actionable tasks.
-- ============================================================================
CREATE TABLE IF NOT EXISTS optimization_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source              TEXT NOT NULL CHECK (source IN ('chat_inspection', 'inquiry_loss', 'satisfaction', 'campaign', 'manual', 'knowledge_gap')),
    category            TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    priority            TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'wont_fix')),
    platform_id         UUID REFERENCES platforms(id),
    related_chat_id     UUID REFERENCES bot_chat_sessions(id),
    related_knowledge_id UUID REFERENCES knowledge_entries(id),
    assigned_to         UUID REFERENCES profiles(id),
    resolution          TEXT,
    impact_estimate     TEXT,
    created_by          UUID REFERENCES profiles(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_opt_tasks_status ON optimization_tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_opt_tasks_source ON optimization_tasks(source);
CREATE INDEX IF NOT EXISTS idx_opt_tasks_assigned ON optimization_tasks(assigned_to) WHERE status != 'resolved';

-- ============================================================================
-- Table: robot_reports — daily/weekly/monthly reports
-- Responsibility 7. LLM-generated structured reports.
-- ============================================================================
CREATE TABLE IF NOT EXISTS robot_reports (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type       TEXT NOT NULL CHECK (report_type IN ('daily', 'weekly', 'monthly')),
    period_start      DATE NOT NULL,
    period_end        DATE NOT NULL,
    platform_id       UUID REFERENCES platforms(id),
    summary_md        TEXT NOT NULL,
    metrics           JSONB NOT NULL,
    optimization_plan TEXT,
    industry_compare  JSONB,
    generated_by      TEXT NOT NULL DEFAULT 'auto',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(report_type, period_start, platform_id)
);
CREATE INDEX IF NOT EXISTS idx_robot_reports_period ON robot_reports(report_type, period_start DESC);

-- ============================================================================
-- Table: industry_benchmarks — reference data for responsibility 7
-- ============================================================================
CREATE TABLE IF NOT EXISTS industry_benchmarks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name   TEXT NOT NULL,
    industry_avg  NUMERIC NOT NULL,
    industry_top  NUMERIC,
    category      TEXT,
    period        TEXT NOT NULL DEFAULT '2025',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Table: knowledge_update_logs — audit trail for responsibility 3
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_update_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_id    UUID REFERENCES knowledge_entries(id) ON DELETE SET NULL,
    update_type     TEXT NOT NULL CHECK (update_type IN ('create', 'update', 'publish', 'archive', 'batch_import')),
    field_changed   TEXT,
    old_value       TEXT,
    new_value       TEXT,
    updated_by      UUID REFERENCES profiles(id),
    correlation_id  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_logs_entry ON knowledge_update_logs(knowledge_id, created_at DESC);

-- ============================================================================
-- Extend quality_reports with bot session and platform references
-- ============================================================================
ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS is_bot_session BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS bot_session_id UUID REFERENCES bot_chat_sessions(id);
ALTER TABLE quality_reports ADD COLUMN IF NOT EXISTS platform_id UUID REFERENCES platforms(id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_bot_session ON quality_reports(bot_session_id) WHERE is_bot_session = true;

-- ============================================================================
-- Seed data: 8 e-commerce platforms
-- ============================================================================
INSERT INTO platforms (name, code, bot_type) VALUES
    ('天猫', 'tmall', 'third_party'),
    ('京东', 'jd', 'third_party'),
    ('唯品会', 'vip', 'third_party'),
    ('抖音', 'douyin', 'third_party'),
    ('拼多多', 'pdd', 'third_party'),
    ('快手', 'kuaishou', 'third_party'),
    ('小红书', 'xiaohongshu', 'native'),
    ('官微', 'weibo', 'hybrid')
ON CONFLICT (code) DO NOTHING;

-- ============================================================================
-- Seed data: industry benchmarks
-- ============================================================================
INSERT INTO industry_benchmarks (metric_name, industry_avg, industry_top, category, period) VALUES
    ('independent_reception_rate', 65, 85, '全品类', '2025'),
    ('conversion_rate', 12, 22, '全品类', '2025'),
    ('satisfaction_rate', 78, 92, '全品类', '2025'),
    ('avg_resolution_time_sec', 180, 90, '全品类', '2025'),
    ('transfer_to_human_rate', 35, 12, '全品类', '2025'),
    ('first_response_time_sec', 15, 5, '全品类', '2025'),
    ('independent_reception_rate', 58, 80, '美妆', '2025'),
    ('independent_reception_rate', 70, 88, '3C', '2025'),
    ('independent_reception_rate', 62, 83, '服饰', '2025'),
    ('independent_reception_rate', 67, 85, '食品', '2025')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- RLS: Enable on new tables where applicable
-- ============================================================================
ALTER TABLE platforms ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE optimization_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE robot_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_update_logs ENABLE ROW LEVEL SECURITY;

-- Public read for reference tables
CREATE POLICY "Platforms are publicly readable" ON platforms FOR SELECT USING (true);
CREATE POLICY "Industry benchmarks are publicly readable" ON industry_benchmarks FOR SELECT USING (true);

-- Authenticated read/write for operational tables (UI uses supabaseAdmin which bypasses RLS;
-- these policies provide defense-in-depth for any client-side queries)
CREATE POLICY "Bot configs readable by all authenticated users" ON bot_configs FOR SELECT USING (true);
CREATE POLICY "Knowledge entries readable by all authenticated users" ON knowledge_entries FOR SELECT USING (true);
CREATE POLICY "Chat sessions readable by all authenticated users" ON bot_chat_sessions FOR SELECT USING (true);
CREATE POLICY "Optimization tasks readable by all authenticated users" ON optimization_tasks FOR SELECT USING (true);
CREATE POLICY "Robot reports readable by all authenticated users" ON robot_reports FOR SELECT USING (true);
CREATE POLICY "Knowledge logs readable by all authenticated users" ON knowledge_update_logs FOR SELECT USING (true);
