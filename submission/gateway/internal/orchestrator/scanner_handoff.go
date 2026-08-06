package orchestrator

import (
	"context"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// handoffCandidate is a normalized agent view used by the timeout-handoff
// evaluator. It flattens local (from DB) and remote (from peer cache) agents
// into one shape. PeerURL empty == local; non-empty == remote base.
//
// AgentType is intentionally absent: the caller (scanTimeoutHandoffEvaluate)
// already filters candidates by the task's required type when building this
// list (the discover view groups by type), so re-filtering here would be
// redundant. selectHandoffTarget only needs identity + locality + health.
type handoffCandidate struct {
	ID      string
	PeerURL string // "" = local base
	Online  bool
}

// shouldAttemptHandoff reports whether a task with the given handoff_count
// is still eligible for handoff. The cap is 1: a task may be handed off at
// most once. A second timeout after a handoff goes straight to failed_final,
// no recursion — handing a task around an infinite ring of failing agents
// would be worse than failing fast.
func shouldAttemptHandoff(handoffCount int) bool {
	return handoffCount < 1
}

// selectHandoffTarget picks the best candidate to receive a handed-off task.
// Rules, in priority order:
//  1. Exclude the timed-out agent (would hand back to the failure).
//  2. Exclude offline agents.
//  3. Prefer a local agent (PeerURL == "") — lower latency, no cross-base hop.
//  4. Fall back to a remote agent if no local one qualifies.
//  5. Return nil if nothing qualifies — caller falls back to the original
//     timeout_silent_resume path.
func selectHandoffTarget(candidates []handoffCandidate, timedOutAgentID string) *handoffCandidate {
	// First pass: best local candidate.
	for i := range candidates {
		c := &candidates[i]
		if c.ID == timedOutAgentID || !c.Online || c.PeerURL != "" {
			continue
		}
		return c
	}
	// Second pass: best remote candidate.
	for i := range candidates {
		c := &candidates[i]
		if c.ID == timedOutAgentID || !c.Online || c.PeerURL == "" {
			continue
		}
		return c
	}
	return nil
}

// scanTimeoutHandoffEvaluate is the scanner step that, for each
// timeout_silent task still eligible for handoff (handoff_count < 1),
// looks for another agent — local first, then remote (Phase 2.4 peer
// cache) — capable of taking it over. If found, transitions the task to
// handoff_pending and records the handoff metadata. If not found, the
// task is left in timeout_silent for the existing timeout_silent_resume
// step to retry or fail.
//
// Runs BEFORE scanTimeoutSilentResume so that a handoff-able task is
// redirected rather than blindly re-queued onto the same (possibly dead)
// agent pool.
func scanTimeoutHandoffEvaluate(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()

	rows, err := pool.Query(ctx, `
		SELECT t.id, t.target_agent_id, t.task_type, t.handoff_count
		FROM tasks t
		WHERE t.status = 'timeout_silent'
		  AND t.handoff_count < 1
		FOR UPDATE OF t SKIP LOCKED`)
	if err != nil {
		slog.Error("scanner timeout_handoff_evaluate query", "err", err)
		return
	}
	defer rows.Close()

	type timeoutTask struct {
		ID             string
		TargetAgentID  *string
		TaskType       string
		HandoffCount   int
	}
	var tasks []timeoutTask
	for rows.Next() {
		var t timeoutTask
		if err := rows.Scan(&t.ID, &t.TargetAgentID, &t.TaskType, &t.HandoffCount); err != nil {
			continue
		}
		tasks = append(tasks, t)
	}

	for _, t := range tasks {
		candidates := buildHandoffCandidates(ctx, pool, t.TaskType, now)
		timedOutID := ""
		if t.TargetAgentID != nil {
			timedOutID = *t.TargetAgentID
		}
		target := selectHandoffTarget(candidates, timedOutID)
		if target == nil {
			// No viable handoff target — leave for timeout_silent_resume.
			continue
		}

		// Transition timeout_silent → handoff_pending via the FSM, then
		// stamp the handoff metadata. We do NOT go straight to pending
		// because handoff_requeue (next scan cycle) needs to see the
		// intermediate state to know the handoff already happened.
		err := TransitionWithAudit(ctx, pool, t.ID, StateTimeoutSilent, StateHandoffPending,
			"handoff_eval", map[string]interface{}{
				"new_target":      target.ID,
				"new_target_base": targetBaseLabel(target),
			})
		if err != nil {
			slog.Warn("scanner timeout_handoff_evaluate transition", "task", t.ID, "err", err)
			continue
		}

		// Record handoff metadata: new target, incremented count, prior agent.
		_, err = pool.Exec(ctx, `
			UPDATE tasks SET
				target_agent_id = $1,
				handoff_count = handoff_count + 1,
				handoff_from_agent = $2,
				lease_owner = NULL,
				lease_expires_at = NULL,
				updated_at = $3
			WHERE id = $4`,
			target.ID, timedOutID, now, t.ID)
		if err != nil {
			slog.Error("scanner timeout_handoff_evaluate update", "task", t.ID, "err", err)
			continue
		}
		slog.Info("scanner timeout_handoff_evaluate",
			"task", t.ID, "from", timedOutID, "to", target.ID, "base", targetBaseLabel(target))
	}
}

// buildHandoffCandidates assembles the local + remote agent list for a
// given task_type. Local comes from the DB (online agents of that type);
// remote comes from the peer cache (Phase 2.4). The caller filters by
// excluding the timed-out agent and preferring local in selectHandoffTarget.
func buildHandoffCandidates(ctx context.Context, pool *pgxpool.Pool, taskType string, now time.Time) []handoffCandidate {
	var candidates []handoffCandidate

	// Local: online agents matching the task's type. An empty task_type
	// means "any agent" — we don't filter by type in that case.
	q := `SELECT id FROM agents WHERE status = 'online'`
	args := []interface{}{}
	if taskType != "" {
		q += ` AND agent_type = $1`
		args = append(args, taskType)
	}
	rows, err := pool.Query(ctx, q, args...)
	if err == nil {
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err == nil {
				candidates = append(candidates, handoffCandidate{ID: id, PeerURL: "", Online: true})
			}
		}
		rows.Close()
	}

	// Remote: peer-discovered online agents of the matching type.
	for _, pa := range globalPeerCache.allRemote(now) {
		if pa.Status != "online" {
			continue
		}
		if taskType != "" && pa.AgentType != taskType {
			continue
		}
		candidates = append(candidates, handoffCandidate{
			ID: pa.ID, PeerURL: pa.PeerURL, Online: true,
		})
	}
	return candidates
}

// scanHandoffRequeue transitions handoff_pending tasks back to pending
// (queued) so the normal poll/dispatch path picks them up with the new
// target_agent_id set by scanTimeoutHandoffEvaluate. This runs as a
// separate step on the next cycle, keeping the handoff observable:
// a task sits in handoff_pending for one scan interval, not silently
// jumping timeout_silent → queued.
func scanHandoffRequeue(ctx context.Context, pool *pgxpool.Pool) {
	rows, err := pool.Query(ctx, `
		SELECT id FROM tasks
		WHERE status = 'handoff_pending'
		FOR UPDATE SKIP LOCKED`)
	if err != nil {
		slog.Error("scanner handoff_requeue query", "err", err)
		return
	}
	defer rows.Close()

	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err == nil {
			ids = append(ids, id)
		}
	}
	for _, id := range ids {
		if err := TransitionWithAudit(ctx, pool, id, StateHandoffPending, StatePending,
			"handoff_requeue", nil); err != nil {
			slog.Warn("scanner handoff_requeue transition", "task", id, "err", err)
			continue
		}
		slog.Info("scanner handoff_requeue", "task", id, "action", "handoff_pending → queued")
	}
}

// targetBaseLabel is a human-readable label for log lines: "local" or
// the peer URL.
func targetBaseLabel(t *handoffCandidate) string {
	if t.PeerURL == "" {
		return "local"
	}
	return t.PeerURL
}
