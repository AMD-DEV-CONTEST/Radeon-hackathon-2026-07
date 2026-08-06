-- P6: artifacts table — tracks deliverable evidence for each task.
-- done transition soft-warns if no artifact is registered.

CREATE TABLE IF NOT EXISTS artifacts (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       uuid        NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_id    uuid        REFERENCES task_attempts(id) ON DELETE SET NULL,
    artifact_type text        NOT NULL DEFAULT 'other',
    uri           text        NOT NULL,
    sha256        text,
    metadata      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_attempt ON artifacts(attempt_id) WHERE attempt_id IS NOT NULL;
