-- M4 run bookkeeping.
--
-- Migration 0008 froze the M4 artifact tables but not the run-side tables the
-- M3 slice got in 0006: the per-attempt model proposal, the run-to-artifact
-- commit binding, and the run-context columns a resumed graph compares its
-- cursor against. Without them an M4 run has nowhere to record the proposal it
-- is validating, nothing to make its commit idempotent across a restart, and no
-- durable copy of the context bound its acceptance criteria require to be
-- recorded next to the model-call budget.

CREATE TABLE IF NOT EXISTS m4_model_proposals (
    run_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    proposal_hash TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    server_kind TEXT NOT NULL DEFAULT 'unknown',
    server_base_url TEXT NOT NULL DEFAULT 'unknown',
    model_id TEXT NOT NULL DEFAULT 'unknown',
    response_id TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    received_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
    PRIMARY KEY (run_id, attempt),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- One run commits at most one artifact/version pair. The graph re-reads this
-- row on resume instead of persisting again: a second persist would append a
-- second artifact for work the first attempt already durably completed, and the
-- readiness and relation bindings downstream would then name a version the user
-- never saw.
CREATE TABLE IF NOT EXISTS m4_run_commits (
    run_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    canonical_version_id TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES m4_artifacts(artifact_id) ON DELETE CASCADE,
    FOREIGN KEY (canonical_version_id) REFERENCES asset_versions(version_id) ON DELETE CASCADE
);

-- A resumed run must reach the same decision identity it reached before the
-- restart. Re-evaluating would mint a new decision_id for a proposal already
-- judged, and the workflow trace would then carry two policy references for one
-- node — indistinguishable from the policy having run twice on real input.
CREATE TABLE IF NOT EXISTS m4_policy_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    proposal_attempt INTEGER NOT NULL,
    proposal_id TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, proposal_attempt, proposal_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_m4_policy_decisions_run
ON m4_policy_decisions(run_id, proposal_attempt);

ALTER TABLE workflow_run_contexts ADD COLUMN base_m3_artifact_id TEXT;
ALTER TABLE workflow_run_contexts ADD COLUMN m4_regenerate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workflow_run_contexts ADD COLUMN expected_invalidated_m4_artifact_id TEXT;

-- The bound placed on the canonical context handed to the model, recorded with
-- the run rather than derived at read time. E4's first blocker was an oversized
-- pre-injected payload returning 422 or timing out; a truncated context yields a
-- proposal citing records the model never saw, which then fails validation for
-- reasons that read as model quality rather than payload size. Storing what was
-- actually sent is what keeps the two distinguishable afterwards.
ALTER TABLE workflow_run_contexts ADD COLUMN m4_context_bound_json TEXT;
