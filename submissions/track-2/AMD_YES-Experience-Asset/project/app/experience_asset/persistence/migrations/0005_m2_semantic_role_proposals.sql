PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS m2_semantic_role_proposals (
    run_id TEXT PRIMARY KEY,
    proposal_hash TEXT NOT NULL,
    content_json TEXT NOT NULL,
    model_id TEXT NOT NULL,
    server_base_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);
