-- ============================================================================
-- Migration 012: Work Orders — auto-generated from QA + Feishu integration
-- Critical QA findings → actionable work orders with status tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS work_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('qa_evaluate', 'compliance_block', 'inspection', 'manual', 'cron')),
    source_id       UUID,                        -- e.g. quality_report id, compliance_audit_log id
    priority        TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    category        TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general', 'compliance', 'script_fix', 'knowledge_gap', 'customer_complaint', 'system_issue')),
    platform_id     UUID REFERENCES platforms(id),
    assigned_to     UUID REFERENCES profiles(id),
    resolved_by     UUID REFERENCES profiles(id),
    resolution      TEXT,
    feishu_message_id TEXT,                       -- Feishu message ID for in-Feishu processing
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status, priority);
CREATE INDEX IF NOT EXISTS idx_work_orders_source ON work_orders(source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_orders_assigned ON work_orders(assigned_to) WHERE status NOT IN ('resolved', 'closed');

-- Work order action log for audit trail
CREATE TABLE IF NOT EXISTS work_order_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id   UUID NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('created', 'assigned', 'in_progress', 'resolved', 'closed', 'reopened', 'commented')),
    comment         TEXT,
    performed_by    UUID REFERENCES profiles(id),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wo_actions_order ON work_order_actions(work_order_id, created_at DESC);

-- RLS
ALTER TABLE work_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_order_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Work orders readable by all authenticated" ON work_orders FOR SELECT USING (true);
CREATE POLICY "Work order actions readable by all authenticated" ON work_order_actions FOR SELECT USING (true);

-- Auto-create function: generate work order from critical QA result
CREATE OR REPLACE FUNCTION auto_create_work_order(
    p_title TEXT,
    p_description TEXT,
    p_source TEXT,
    p_source_id UUID,
    p_priority TEXT,
    p_category TEXT DEFAULT 'general'
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO work_orders (title, description, source, source_id, priority, category)
    VALUES (p_title, p_description, p_source, p_source_id, p_priority, p_category)
    RETURNING id INTO v_id;

    INSERT INTO work_order_actions (work_order_id, action, metadata)
    VALUES (v_id, 'created', jsonb_build_object('auto_generated', true, 'source', p_source));

    RETURN v_id;
END;
$$;
