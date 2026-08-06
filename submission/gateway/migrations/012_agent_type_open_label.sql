-- Allow current and future Agent runtime labels without schema churn.
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_agent_type_check;

ALTER TABLE agents
  ADD CONSTRAINT agents_agent_type_check
  CHECK (agent_type ~ '^[a-z0-9_-]{1,64}$');

