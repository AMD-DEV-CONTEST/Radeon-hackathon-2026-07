-- UnionAgents Phase 3 hub memory and machine registry.

CREATE TABLE IF NOT EXISTS hub_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    objective text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    model_policy text,
    owner text NOT NULL DEFAULT 'system',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_hub_sessions_status ON hub_sessions(status);

CREATE TABLE IF NOT EXISTS hub_context_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_session_id uuid NOT NULL REFERENCES hub_sessions(id) ON DELETE CASCADE,
    summary text NOT NULL DEFAULT '',
    task_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    token_estimate integer NOT NULL DEFAULT 0 CHECK (token_estimate >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hub_context_snapshots_session_created
    ON hub_context_snapshots(hub_session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS machines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    host text NOT NULL,
    launcher_port integer NOT NULL DEFAULT 9001 CHECK (launcher_port > 0),
    status text NOT NULL DEFAULT 'offline'
        CHECK (status IN ('online', 'offline', 'draining')),
    os text,
    capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_machines_status ON machines(status);
CREATE INDEX IF NOT EXISTS idx_machines_last_seen ON machines(last_seen_at);

CREATE TABLE IF NOT EXISTS machine_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id uuid NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    task_id uuid REFERENCES tasks(id) ON DELETE SET NULL,
    agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
    session_id text NOT NULL UNIQUE,
    agent_type text NOT NULL,
    command jsonb NOT NULL DEFAULT '[]'::jsonb,
    cwd text,
    status text NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'running', 'exited', 'failed', 'cancelled')),
    pid integer,
    exit_code integer,
    log_uri text,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_machine_sessions_machine_status
    ON machine_sessions(machine_id, status);

CREATE INDEX IF NOT EXISTS idx_machine_sessions_task
    ON machine_sessions(task_id);
