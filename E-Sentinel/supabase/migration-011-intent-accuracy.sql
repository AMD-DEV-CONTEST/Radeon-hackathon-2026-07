-- ============================================================================
-- Migration 011: Intent Recognition Accuracy Tracking
-- Enables monitoring of intent recognition accuracy with 99.8% target
-- ============================================================================

CREATE TABLE IF NOT EXISTS intent_accuracy_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_id     UUID REFERENCES platforms(id),
    period_date     DATE NOT NULL,
    total_recognitions  INT NOT NULL DEFAULT 0,
    correct_recognitions INT NOT NULL DEFAULT 0,
    incorrect_recognitions INT NOT NULL DEFAULT 0,
    accuracy        NUMERIC(5,4) NOT NULL DEFAULT 0, -- e.g. 0.9980 = 99.80%
    coverage_rate   NUMERIC(5,4),  -- % of user questions matched to an intent
    target_met      BOOLEAN NOT NULL DEFAULT false, -- accuracy >= 0.998
    bad_case_ids    UUID[] DEFAULT '{}',
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, period_date)
);

CREATE INDEX IF NOT EXISTS idx_intent_accuracy_date ON intent_accuracy_logs(period_date DESC);
CREATE INDEX IF NOT EXISTS idx_intent_accuracy_target ON intent_accuracy_logs(target_met, period_date DESC);

-- Alert threshold config: accuracy < 0.99 triggers Feishu alert (stored in system_configs)
ALTER TABLE intent_accuracy_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Intent accuracy readable by all authenticated" ON intent_accuracy_logs FOR SELECT USING (true);
