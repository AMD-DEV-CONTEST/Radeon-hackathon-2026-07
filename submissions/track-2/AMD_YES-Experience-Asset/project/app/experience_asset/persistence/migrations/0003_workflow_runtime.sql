PRAGMA foreign_keys = ON;

ALTER TABLE runs ADD COLUMN workflow_version TEXT;
ALTER TABLE runs ADD COLUMN topology_hash TEXT;
ALTER TABLE runs ADD COLUMN base_version_id TEXT;
ALTER TABLE runs ADD COLUMN command_id TEXT;

CREATE TABLE IF NOT EXISTS workflow_run_contexts (
    run_id TEXT PRIMARY KEY,
    user_goal TEXT NOT NULL,
    allow_current_source_search INTEGER NOT NULL,
    server_base_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workflow_effects (
    effect_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    node_attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error_class TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    UNIQUE (run_id, node_name, node_attempt)
);

CREATE TABLE IF NOT EXISTS workflow_traces (
    trace_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    topology_hash TEXT NOT NULL,
    node_name TEXT NOT NULL,
    node_attempt INTEGER NOT NULL,
    selected_edge TEXT,
    input_refs_json TEXT NOT NULL,
    output_refs_json TEXT NOT NULL,
    policy_outcome TEXT,
    tool_execution_status TEXT,
    verification_outcome TEXT,
    checkpoint_id TEXT,
    terminal_state TEXT,
    finding_codes_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    UNIQUE (run_id, node_name, node_attempt)
);

CREATE INDEX IF NOT EXISTS idx_workflow_effects_run
ON workflow_effects(run_id, node_name, node_attempt);

CREATE INDEX IF NOT EXISTS idx_workflow_traces_run
ON workflow_traces(run_id, started_at);
