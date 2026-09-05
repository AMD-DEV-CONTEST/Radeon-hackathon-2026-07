PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS run_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    phase TEXT NOT NULL,
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    UNIQUE (run_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_sequence
ON run_checkpoints(run_id, sequence DESC);
