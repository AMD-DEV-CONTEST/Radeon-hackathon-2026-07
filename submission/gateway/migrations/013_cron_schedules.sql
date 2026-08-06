-- Cron schedules table for cron-expression-based task dispatch (T2).
-- Each row defines a named schedule with a 5-field cron expression and a
-- task template to use when dispatching.
CREATE TABLE IF NOT EXISTS cron_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    cron_expr       TEXT NOT NULL,                              -- standard 5-field cron
    task_template   JSONB NOT NULL DEFAULT '{}'::JSONB,        -- template for task creation
    enabled         BOOLEAN NOT NULL DEFAULT true,
    last_triggered_at TIMESTAMPTZ,
    created_by      TEXT NOT NULL DEFAULT 'unknown',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(name)
);

-- Cron events audit trail: one row per cron-triggered dispatch.
CREATE TABLE IF NOT EXISTS cron_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id     UUID NOT NULL REFERENCES cron_schedules(id) ON DELETE CASCADE,
    schedule_name   TEXT NOT NULL,
    cron_expr       TEXT NOT NULL,
    task_id         UUID REFERENCES tasks(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'dispatched',         -- dispatched | skipped | failed
    message         TEXT NOT NULL DEFAULT '',
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cron_events_schedule_id ON cron_events(schedule_id);
CREATE INDEX IF NOT EXISTS idx_cron_events_triggered_at ON cron_events(triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_cron_schedules_enabled ON cron_schedules(enabled) WHERE enabled = true;
