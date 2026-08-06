-- P5: target_agent_id — lock a task to a specific agent identity.
-- NULL = any capable agent may claim; non-NULL = only the named agent may claim.
-- Backward compatible: existing tasks have NULL and behave as before.

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS target_agent_id uuid REFERENCES agents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_target_agent
    ON tasks(target_agent_id)
    WHERE target_agent_id IS NOT NULL;
