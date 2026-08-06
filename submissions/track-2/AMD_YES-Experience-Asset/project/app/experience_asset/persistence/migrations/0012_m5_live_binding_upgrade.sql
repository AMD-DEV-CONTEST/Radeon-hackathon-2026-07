-- PR #52 initially wrote a route-draft content hash into draft_id. Keep those
-- immutable audit records but make their inability to authorize export explicit.
UPDATE m5_approvals
SET stale_since = COALESCE(stale_since, CURRENT_TIMESTAMP),
    stale_reason = COALESCE(
        stale_reason,
        'Legacy approval has no exact persisted RouteDraft identity; re-approval required'
    )
WHERE length(draft_id) = 64
  AND draft_id NOT LIKE '%-%';

CREATE TABLE IF NOT EXISTS m5_workflow_commands (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE RESTRICT,
    command_kind TEXT NOT NULL CHECK(command_kind IN ('EVALUATE', 'RESOLVE', 'APPROVE')),
    finding_id TEXT,
    privacy_action TEXT,
    route_draft_id TEXT,
    user_action TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (command_kind='EVALUATE' AND finding_id IS NULL AND route_draft_id IS NULL)
        OR (command_kind='RESOLVE' AND finding_id IS NOT NULL AND privacy_action IS NOT NULL)
        OR (command_kind='APPROVE' AND route_draft_id IS NOT NULL AND user_action IS NOT NULL AND idempotency_key IS NOT NULL)
    )
);
