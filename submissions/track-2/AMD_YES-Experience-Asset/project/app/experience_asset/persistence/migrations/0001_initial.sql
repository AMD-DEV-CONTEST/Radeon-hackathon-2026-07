PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    lifecycle TEXT NOT NULL,
    current_version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (current_version_id) REFERENCES asset_versions(version_id)
);

CREATE TABLE IF NOT EXISTS asset_versions (
    version_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    parent_version_id TEXT,
    schema_version TEXT NOT NULL,
    change_kind TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_version_id) REFERENCES asset_versions(version_id)
);

CREATE INDEX IF NOT EXISTS idx_asset_versions_asset_created
ON asset_versions(asset_id, created_at);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    asset_id TEXT,
    command TEXT NOT NULL,
    model_id TEXT,
    model_config_hash TEXT,
    code_commit TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    terminal_state TEXT,
    last_durable_version_id TEXT,
    retryable INTEGER,
    safe_user_message TEXT,
    internal_error_class TEXT,
    elapsed_ms INTEGER,
    model_call_count INTEGER NOT NULL DEFAULT 0,
    recovery_action TEXT,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL,
    FOREIGN KEY (last_durable_version_id) REFERENCES asset_versions(version_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id) REFERENCES asset_versions(version_id)
);

CREATE TABLE IF NOT EXISTS exports (
    export_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE,
    FOREIGN KEY (version_id) REFERENCES asset_versions(version_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    asset_id TEXT,
    run_id TEXT,
    event_type TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS deletion_requests (
    request_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    challenge_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    confirmed_at TEXT,
    state TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
);
