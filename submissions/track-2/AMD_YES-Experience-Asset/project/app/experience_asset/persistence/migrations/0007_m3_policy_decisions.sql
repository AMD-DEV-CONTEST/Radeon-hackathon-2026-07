PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS m3_policy_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    proposal_attempt INTEGER NOT NULL,
    proposal_id TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, proposal_attempt, proposal_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_m3_policy_decisions_run
ON m3_policy_decisions(run_id, proposal_attempt);

-- Retain only bounded, sanitized model identity and timing. Raw prompts and
-- responses remain forbidden and are never written to the application DB.
ALTER TABLE m3_model_proposals ADD COLUMN server_kind TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE m3_model_proposals ADD COLUMN server_base_url TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE m3_model_proposals ADD COLUMN model_id TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE m3_model_proposals ADD COLUMN response_id TEXT;
ALTER TABLE m3_model_proposals ADD COLUMN prompt_tokens INTEGER;
ALTER TABLE m3_model_proposals ADD COLUMN completion_tokens INTEGER;
ALTER TABLE m3_model_proposals ADD COLUMN elapsed_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE m3_model_proposals ADD COLUMN received_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00';
