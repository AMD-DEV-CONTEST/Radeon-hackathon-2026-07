-- ILS v2.2: Ownership Registry
-- Tracks which agent owns which module/resource to prevent conflict (ILS-G004).

CREATE TABLE IF NOT EXISTS ownership_registry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id text NOT NULL UNIQUE,
    owner_agent_id text NOT NULL,
    scope text NOT NULL DEFAULT '',
    lease_duration_seconds integer,
    claimed_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ownership_module ON ownership_registry(module_id);
CREATE INDEX IF NOT EXISTS idx_ownership_agent ON ownership_registry(owner_agent_id);
CREATE INDEX IF NOT EXISTS idx_ownership_active ON ownership_registry(module_id) WHERE released_at IS NULL;

-- Intent audit log for ILS v2.2 lifecycle events
CREATE TABLE IF NOT EXISTS ils_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type text NOT NULL,
    task_id text,
    gate_id text,
    failure_code text,
    blocked boolean NOT NULL DEFAULT false,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    ils_version text NOT NULL DEFAULT '2.2',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_task ON ils_audit_log(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON ils_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_created ON ils_audit_log(created_at DESC);
