-- Union Multi-Agent System MVP initial PostgreSQL schema.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE agents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    agent_type text NOT NULL CHECK (
        agent_type IN ('claude_code', 'codex', 'reasonix', 'codewhile', 'opencode', 'generic')
    ),
    host_id text NOT NULL,
    status text NOT NULL DEFAULT 'online' CHECK (
        status IN ('online', 'offline', 'draining', 'disabled')
    ),
    os text CHECK (os IN ('windows', 'linux', 'darwin', 'unknown')),
    shell text,
    python_version text,
    workspace_root text,
    available_commands jsonb NOT NULL DEFAULT '[]'::jsonb,
    capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    network_capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_policy text,
    max_concurrency integer NOT NULL DEFAULT 1 CHECK (max_concurrency > 0),
    last_heartbeat_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (host_id, name)
);

CREATE TABLE tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_task_id uuid REFERENCES tasks(id) ON DELETE SET NULL,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    task_type text NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN (
            'queued',
            'leased',
            'running',
            'blocked_permission',
            'blocked_auth',
            'blocked_rate_limit',
            'blocked_env',
            'timeout_silent',
            'cancelled',
            'failed_retryable',
            'failed_final',
            'needs_review',
            'done'
        )
    ),
    priority integer NOT NULL DEFAULT 100,
    dependencies jsonb NOT NULL DEFAULT '[]'::jsonb,
    required_capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    acceptance_check jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    lease_owner uuid REFERENCES agents(id) ON DELETE SET NULL,
    lease_expires_at timestamptz,
    blocked_until timestamptz,
    created_by text NOT NULL DEFAULT 'system',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CHECK (
        (status IN ('leased', 'running') AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status NOT IN ('leased', 'running')
    ),
    CHECK (
        (status = 'blocked_rate_limit' AND blocked_until IS NOT NULL)
        OR status <> 'blocked_rate_limit'
    )
);

CREATE TABLE task_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    status text NOT NULL CHECK (
        status IN (
            'leased',
            'running',
            'blocked_permission',
            'blocked_auth',
            'blocked_rate_limit',
            'blocked_env',
            'timeout_silent',
            'cancelled',
            'failed_retryable',
            'failed_final',
            'needs_review',
            'done'
        )
    ),
    exit_code integer,
    error_type text CHECK (
        error_type IS NULL OR error_type IN (
            'blocked_permission',
            'blocked_auth',
            'blocked_rate_limit',
            'blocked_env',
            'timeout_silent',
            'retryable',
            'unrecoverable',
            'acceptance_failed',
            'needs_review'
        )
    ),
    error_message text,
    blocked_until timestamptz,
    summary text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id, attempt_no)
);

CREATE TABLE artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_id uuid REFERENCES task_attempts(id) ON DELETE SET NULL,
    artifact_type text NOT NULL CHECK (
        artifact_type IN ('patch', 'log', 'test_result', 'screenshot', 'report', 'workspace_snapshot', 'other')
    ),
    uri text NOT NULL,
    sha256 text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_id uuid REFERENCES task_attempts(id) ON DELETE SET NULL,
    agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
    event_type text NOT NULL,
    message text NOT NULL DEFAULT '',
    level text NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warn', 'error')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_agents_type_status ON agents(agent_type, status);
CREATE INDEX idx_agents_last_heartbeat ON agents(last_heartbeat_at);

CREATE INDEX idx_tasks_status_priority ON tasks(status, priority, created_at);
CREATE INDEX idx_tasks_lease_expires ON tasks(lease_expires_at) WHERE status IN ('leased', 'running');
CREATE INDEX idx_tasks_blocked_until ON tasks(blocked_until) WHERE status = 'blocked_rate_limit';
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);

CREATE INDEX idx_task_attempts_task ON task_attempts(task_id, attempt_no DESC);
CREATE INDEX idx_task_attempts_agent ON task_attempts(agent_id, status);
CREATE INDEX idx_task_attempts_lease_expires ON task_attempts(lease_expires_at)
    WHERE status IN ('leased', 'running');

CREATE INDEX idx_artifacts_task ON artifacts(task_id, created_at);
CREATE INDEX idx_artifacts_attempt ON artifacts(attempt_id);
CREATE INDEX idx_events_task_created ON events(task_id, created_at);
CREATE INDEX idx_events_attempt_created ON events(attempt_id, created_at);
