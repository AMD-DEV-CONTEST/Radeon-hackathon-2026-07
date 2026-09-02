-- ============================================================================
-- Migration 013: Smart Payment Reminder System
-- Auto-identify unpaid orders, generate personalized reminders, track conversion
-- ============================================================================

CREATE TABLE IF NOT EXISTS pending_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_order_id TEXT NOT NULL,
    platform_id     UUID REFERENCES platforms(id),
    customer_id     TEXT,
    customer_name   TEXT,
    product_name    TEXT,
    order_amount    NUMERIC(10,2),
    order_status    TEXT NOT NULL DEFAULT 'pending_payment' CHECK (order_status IN ('pending_payment', 'reminded', 'paid', 'cancelled', 'expired')),
    created_at_order TIMESTAMPTZ NOT NULL,
    expire_at       TIMESTAMPTZ,                  -- order expiry deadline
    metadata        JSONB DEFAULT '{}',           -- raw order data
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_orders_external ON pending_orders(external_order_id, platform_id);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(order_status, expire_at);

CREATE TABLE IF NOT EXISTS payment_reminders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES pending_orders(id) ON DELETE CASCADE,
    round           INT NOT NULL DEFAULT 1,        -- 1st, 2nd, 3rd reminder
    script          TEXT NOT NULL,                 -- LLM-generated reminder script
    channel         TEXT NOT NULL DEFAULT 'bot' CHECK (channel IN ('bot', 'sms', 'feishu', 'app_push')),
    status          TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('pending', 'sent', 'delivered', 'failed', 'converted')),
    sent_at         TIMESTAMPTZ,
    converted_at    TIMESTAMPTZ,
    response        TEXT,                          -- customer response if any
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reminders_order ON payment_reminders(order_id, round);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON payment_reminders(status, sent_at DESC);

-- RLS
ALTER TABLE pending_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_reminders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Pending orders readable by all authenticated" ON pending_orders FOR SELECT USING (true);
CREATE POLICY "Payment reminders readable by all authenticated" ON payment_reminders FOR SELECT USING (true);

-- Seed: system config entries for payment reminder
INSERT INTO system_configs (config_key, config_value, value_type, description, category) VALUES
    ('payment_reminder_max_rounds', '3', 'number', 'Maximum reminder rounds per order', 'general'),
    ('payment_reminder_interval_hours', '24', 'number', 'Hours between reminder rounds', 'general'),
    ('payment_reminder_first_delay_minutes', '30', 'number', 'Minutes after order before first reminder', 'general')
ON CONFLICT (config_key) DO NOTHING;
