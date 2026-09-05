PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS m2_artifacts (
    artifact_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    parent_artifact_id TEXT,
    base_m1_version_id TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_artifact_id) REFERENCES m2_artifacts(artifact_id),
    FOREIGN KEY (base_m1_version_id) REFERENCES asset_versions(version_id)
);

CREATE TABLE IF NOT EXISTS m2_current (
    asset_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES m2_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_m2_artifacts_asset_created
ON m2_artifacts(asset_id, created_at);
