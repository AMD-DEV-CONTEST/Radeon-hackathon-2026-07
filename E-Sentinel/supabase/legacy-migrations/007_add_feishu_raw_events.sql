-- ============================================================
-- Migration: 007 — FeishuFlow Pro: raw events + idempotency
-- ============================================================

CREATE TABLE IF NOT EXISTS feishu_raw_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id TEXT NOT NULL,
  event_type TEXT,
  app_id TEXT,
  operator_id TEXT,
  raw_body JSONB NOT NULL,
  processed BOOLEAN DEFAULT false,
  processing_errors TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_feishu_raw_events_event_id ON feishu_raw_events(event_id);
CREATE INDEX IF NOT EXISTS idx_feishu_raw_events_processed ON feishu_raw_events(processed, created_at);

COMMENT ON TABLE feishu_raw_events IS '飞书原始事件持久化 — 幂等写入 + 事件溯源';
COMMENT ON COLUMN feishu_raw_events.event_id IS '飞书事件唯一ID，UNIQUE约束实现静默幂等';
