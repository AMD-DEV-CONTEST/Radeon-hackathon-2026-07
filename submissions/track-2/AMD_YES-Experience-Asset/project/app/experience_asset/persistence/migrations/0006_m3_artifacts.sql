PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS m3_artifacts (
    artifact_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    parent_artifact_id TEXT,
    base_m2_artifact_id TEXT NOT NULL,
    base_canonical_version_id TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_artifact_id) REFERENCES m3_artifacts(artifact_id),
    FOREIGN KEY (base_m2_artifact_id) REFERENCES m2_artifacts(artifact_id),
    FOREIGN KEY (base_canonical_version_id) REFERENCES asset_versions(version_id)
);

CREATE TABLE IF NOT EXISTS m3_current (
    asset_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES m3_artifacts(artifact_id)
);

CREATE TABLE IF NOT EXISTS m3_model_proposals (
    run_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    proposal_hash TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, attempt),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- M3's accepted upstream identity is durable run context, not checkpoint-only state.
ALTER TABLE workflow_run_contexts ADD COLUMN base_m2_artifact_id TEXT;
ALTER TABLE workflow_run_contexts ADD COLUMN m3_regenerate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE workflow_run_contexts ADD COLUMN expected_invalidated_m3_artifact_id TEXT;

ALTER TABLE runs ADD COLUMN structured_repair_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN replan_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN finding_codes_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS m3_run_commits (
    run_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL UNIQUE,
    canonical_version_id TEXT NOT NULL UNIQUE,
    committed_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES m3_artifacts(artifact_id),
    FOREIGN KEY (canonical_version_id) REFERENCES asset_versions(version_id)
);

CREATE INDEX IF NOT EXISTS idx_m3_artifacts_asset_created
ON m3_artifacts(asset_id, created_at);
