-- P61-L4: Participants schema + dynamic role derivation
-- Creates the task_participants table for persisting task participant assignments.

CREATE TABLE IF NOT EXISTS task_participants (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL,
    derivation_source TEXT NOT NULL DEFAULT 'explicit',
    assigned_by     TEXT,
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT task_participants_unique UNIQUE (task_id, agent_id, role)
);

CREATE INDEX IF NOT EXISTS idx_task_participants_task_id ON task_participants(task_id);
CREATE INDEX IF NOT EXISTS idx_task_participants_agent_id ON task_participants(agent_id);
CREATE INDEX IF NOT EXISTS idx_task_participants_role ON task_participants(role);

COMMENT ON TABLE task_participants IS 'P61-L4: Tracks which agents are involved in a task and their roles.';
COMMENT ON COLUMN task_participants.derivation_source IS 'How the role was determined: explicit, requester, target_agent, intent_type, policy';
