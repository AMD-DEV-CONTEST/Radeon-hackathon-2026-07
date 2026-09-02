-- EvidenceEvent v1 contract metadata and source-scoped idempotency.
-- Safe for databases created from migration-018 and for repeated execution.

ALTER TABLE evidence_events
  ADD COLUMN IF NOT EXISTS specversion TEXT NOT NULL DEFAULT '1.0',
  ADD COLUMN IF NOT EXISTS subject TEXT,
  ADD COLUMN IF NOT EXISTS traceparent TEXT,
  ADD COLUMN IF NOT EXISTS datacontenttype TEXT NOT NULL DEFAULT 'application/json',
  ADD COLUMN IF NOT EXISTS schema_ref TEXT NOT NULL DEFAULT 'schemas/events/evidence-event-v1.json',
  ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

UPDATE evidence_events
SET idempotency_key = source || ':' || event_id
WHERE idempotency_key IS NULL;

ALTER TABLE evidence_events
  ALTER COLUMN idempotency_key SET NOT NULL;

-- migration-018 declared event_id globally unique. The contract scopes
-- idempotency by source, so remove that old constraint before adding the
-- source-scoped unique index.
ALTER TABLE evidence_events
  DROP CONSTRAINT IF EXISTS evidence_events_event_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_events_source_event_id
  ON evidence_events(source, event_id);

CREATE INDEX IF NOT EXISTS idx_evidence_events_traceparent
  ON evidence_events(traceparent)
  WHERE traceparent IS NOT NULL;
