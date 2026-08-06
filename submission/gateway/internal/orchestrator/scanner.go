package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	ScanIntervalSeconds             = 60
	AgentOfflineAfterSeconds        = 180
	AgentDegradedAfterSeconds       = 60
	NeedsReviewTimeoutHours         = 72
	ReassignAfterAgentOfflineSeconds = 1800
	ArchiveTerminalAfterHours       = 24
	AutoAcceptReviewAfterHours      = 1
	StuckQueuedAlertMinutes         = 30
	ExhaustedGraceMinutes           = 5
	TaskHeartbeatLeaseSeconds       = 60  // task heartbeat must be within 60s to keep lease alive
	DeadLetterAfterHours            = 1   // move failed_final to dead_letter after 1h
)

// ScanStep is a named scan function.
type ScanStep struct {
	Name string
	Fn   func(ctx context.Context, pool *pgxpool.Pool)
}

// ScanSteps is the ordered list of all scanner operations.
var ScanSteps = []ScanStep{
	{"agent_health", scanAgentHealth},
	{"expired_leases", scanExpiredLeases},
	{"unblock_rate_limited", scanUnblockRateLimited},
	{"failed_retryable", scanFailedRetryable},
	{"offline_agents", scanOfflineAgents},
	{"degraded_agents", scanDegradedAgents},
	{"completion_consistency", scanCompletionConsistency},
	// Phase 2.5: evaluate handoff BEFORE timeout_silent_resume so a
	// handoff-able task is redirected to another agent rather than
	// blindly re-queued onto the same pool.
	{"timeout_handoff_evaluate", scanTimeoutHandoffEvaluate},
	{"timeout_silent_resume", scanTimeoutSilentResume},
	{"handoff_requeue", scanHandoffRequeue},
	{"redispatch_queued", scanRedispatchQueued},
	{"needs_review_timeout", scanNeedsReviewTimeout},
	{"reassign_offline_agent_tasks", scanReassignOfflineAgentTasks},
	{"dead_agent_reclaim", scanDeadAgentReclaim},
	{"dead_letter_move", scanDeadLetterMove},
	{"archive_terminal", scanArchiveTerminal},
	{"auto_accept_review", scanAutoAcceptReview},
	{"stuck_tasks", scanStuckTasks},
	// Phase 2.6: role phase-change. Single step handles pending set,
	// grace expiry + condition recheck, and stale pending cleanup.
	{"phase_change_evaluate", scanPhaseChangeEvaluate},
}

// scanAgentHealth is the new unified health grading step (replaces raw status polling).
func scanAgentHealth(ctx context.Context, pool *pgxpool.Pool) {
	UpdateAgentHealth(ctx, pool)
}

// RunScanLoop runs all scan steps in order every ScanIntervalSeconds.
func RunScanLoop(ctx context.Context, pool *pgxpool.Pool) {
	ticker := time.NewTicker(ScanIntervalSeconds * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			runScanCycle(ctx, pool)
		}
	}
}

func runScanCycle(ctx context.Context, pool *pgxpool.Pool) {
	for _, step := range ScanSteps {
		func() {
			defer func() {
				if r := recover(); r != nil {
					slog.Error("scanner step panicked", "step", step.Name, "panic", r)
				}
			}()
			step.Fn(ctx, pool)
		}()
	}
}

// ── step 1: expired leases → timeout_silent ──────────────────────────

func scanExpiredLeases(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	heartbeatCutoff := now.Add(-TaskHeartbeatLeaseSeconds * time.Second)

	// Two conditions expire a lease:
	// 1. lease_expires_at < now (traditional time-based expiry)
	// 2. task_attempts.heartbeat_at < heartbeatCutoff (task heartbeat stale — agent working but forgot to heartbeat)
	rows, err := pool.Query(ctx,
		`SELECT t.id FROM tasks t
		 LEFT JOIN LATERAL (
			 SELECT ta.heartbeat_at FROM task_attempts ta
			 WHERE ta.task_id = t.id AND ta.status IN ('leased','running')
			 ORDER BY ta.attempt_no DESC LIMIT 1
		 ) latest ON true
		 WHERE t.status IN ('leased', 'running')
		   AND (
			 t.lease_expires_at < $1
			 OR (latest.heartbeat_at IS NOT NULL AND latest.heartbeat_at < $2)
			 OR (latest.heartbeat_at IS NULL AND t.updated_at < $2)
		   )
		 FOR UPDATE OF t SKIP LOCKED`, now, heartbeatCutoff)
	if err != nil {
		slog.Error("scanner expired_leases query", "err", err)
		return
	}
	defer rows.Close()

	var taskIDs []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			slog.Error("scanner expired_leases scan", "err", err)
			continue
		}
		taskIDs = append(taskIDs, id)
	}

	for _, taskID := range taskIDs {
		if _, err := pool.Exec(ctx,
			`UPDATE tasks SET status = 'timeout_silent', lease_owner = NULL,
			 lease_expires_at = NULL, updated_at = $1 WHERE id = $2`,
			now, taskID); err != nil {
			slog.Error("scanner expired_leases update task", "task", taskID, "err", err)
			continue
		}
		if _, err := pool.Exec(ctx,
			`UPDATE task_attempts SET status = 'timeout_silent',
			 finished_at = $1, updated_at = $1
			 WHERE task_id = $2 AND status IN ('leased', 'running')`,
			now, taskID); err != nil {
			slog.Error("scanner expired_leases update attempt", "task", taskID, "err", err)
		}
		reason := "lease_expired"
		payload, _ := json.Marshal(map[string]string{"scanned_at": now.Format(time.RFC3339), "reason": reason})
		if _, err := pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.timeout_silent', 'Lease expired — marked timeout_silent.', 'warn', $2)`,
			taskID, payload); err != nil {
			slog.Error("scanner expired_leases event", "task", taskID, "err", err)
		}
		slog.Info("scanner expired_leases", "task", taskID, "action", "→ timeout_silent", "reason", reason)
	}
}

// ── step 2: unblock rate-limited tasks ───────────────────────────────

func scanUnblockRateLimited(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	rows, err := pool.Query(ctx,
		`SELECT id FROM tasks
		 WHERE status = 'blocked_rate_limit'
		   AND blocked_until IS NOT NULL
		   AND blocked_until < $1
		 FOR UPDATE SKIP LOCKED`, now)
	if err != nil {
		slog.Error("scanner unblock_rate_limited query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var taskID string
		if err := rows.Scan(&taskID); err != nil {
			slog.Error("scanner unblock_rate_limited scan", "err", err)
			continue
		}
		if _, err := pool.Exec(ctx,
			`UPDATE tasks SET status = 'queued', blocked_until = NULL, updated_at = $1 WHERE id = $2`,
			now, taskID); err != nil {
			slog.Error("scanner unblock_rate_limited update", "task", taskID, "err", err)
			continue
		}
		payload, _ := json.Marshal(map[string]string{"scanned_at": now.Format(time.RFC3339)})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.unblocked', 'Rate-limit block expired — re-queued.', 'info', $2)`,
			taskID, payload)
		slog.Info("scanner unblock", "task", taskID, "action", "blocked_rate_limit → queued")
	}
}

// ── step 3: failed_retryable → queued (exponential backoff) ──────────

func scanFailedRetryable(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	rows, err := pool.Query(ctx,
		`SELECT t.id,
		        COALESCE((SELECT max(ta.attempt_no) FROM task_attempts ta WHERE ta.task_id = t.id), 0) AS last_attempt_no,
		        t.updated_at,
		        (SELECT ta2.error_type FROM task_attempts ta2
		         WHERE ta2.task_id = t.id ORDER BY ta2.attempt_no DESC LIMIT 1) AS last_error_type
		 FROM tasks t
		 WHERE t.status = 'failed_retryable'
		 FOR UPDATE SKIP LOCKED`)
	if err != nil {
		slog.Error("scanner failed_retryable query", "err", err)
		return
	}
	defer rows.Close()

	type retryRow struct {
		ID            string
		LastAttemptNo int
		UpdatedAt     time.Time
		LastErrorType *string
	}

	for rows.Next() {
		var r retryRow
		if err := rows.Scan(&r.ID, &r.LastAttemptNo, &r.UpdatedAt, &r.LastErrorType); err != nil {
			slog.Error("scanner failed_retryable scan", "err", err)
			continue
		}

		// P2-6: permanent errors must not retry → route to needs_review
		if r.LastErrorType != nil && (*r.LastErrorType == "permanent" || *r.LastErrorType == "auth") {
			if _, err := pool.Exec(ctx,
				`UPDATE tasks SET status = 'needs_review', updated_at = $1 WHERE id = $2`,
				now, r.ID); err != nil {
				slog.Error("scanner failed_retryable permanent", "task", r.ID, "err", err)
				continue
			}
			payload, _ := json.Marshal(map[string]interface{}{
				"scanned_at": now.Format(time.RFC3339),
				"error_type": *r.LastErrorType,
				"reason":     "permanent error, not retrying",
			})
			pool.Exec(ctx,
				`INSERT INTO events (task_id, event_type, message, level, payload)
				 VALUES ($1, 'task.permanent_failure', $2, 'error', $3)`,
				r.ID,
				fmt.Sprintf("Permanent error (%s) — moved to needs_review without retry.", *r.LastErrorType),
				payload)
			slog.Warn("scanner permanent failure", "task", r.ID, "error_type", *r.LastErrorType)
			continue
		}
		backoffSeconds := int(math.Min(math.Pow(2, float64(r.LastAttemptNo)), 3600))
		eligibleAt := r.UpdatedAt.Add(time.Duration(backoffSeconds) * time.Second)
		if eligibleAt.After(now) {
			continue
		}

		if _, err := pool.Exec(ctx,
			`UPDATE tasks SET status = 'queued', updated_at = $1 WHERE id = $2`,
			now, r.ID); err != nil {
			slog.Error("scanner failed_retryable update", "task", r.ID, "err", err)
			continue
		}
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":      now.Format(time.RFC3339),
			"backoff_seconds": backoffSeconds,
			"attempt_no":      r.LastAttemptNo,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.retry_queued', $2, 'info', $3)`,
			r.ID, fmt.Sprintf("failed_retryable re-queued after %ds backoff (attempt %d).", backoffSeconds, r.LastAttemptNo), payload)
		slog.Info("scanner retry", "task", r.ID, "backoff_s", backoffSeconds)
	}
}

// ── step 4: stale agent heartbeats → offline ─────────────────────────

func scanOfflineAgents(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-AgentOfflineAfterSeconds * time.Second)
	rows, err := pool.Query(ctx,
		`UPDATE agents
		 SET status = 'offline', updated_at = $1
		 WHERE status = 'online'
		   AND last_heartbeat_at IS NOT NULL
		   AND last_heartbeat_at < $2
		 RETURNING id, name, host_id, last_heartbeat_at`,
		now, cutoff)
	if err != nil {
		slog.Error("scanner offline_agents query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id, name, hostID string
		var lastHB *time.Time
		if err := rows.Scan(&id, &name, &hostID, &lastHB); err != nil {
			slog.Error("scanner offline_agents scan", "err", err)
			continue
		}
		var lastHBs string
		if lastHB != nil {
			lastHBs = lastHB.Format(time.RFC3339)
		}
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":            now.Format(time.RFC3339),
			"offline_after_seconds": AgentOfflineAfterSeconds,
			"last_heartbeat_at":     lastHBs,
			"name":                  name,
			"host_id":               hostID,
		})
		pool.Exec(ctx,
			`INSERT INTO events (agent_id, event_type, message, level, payload)
			 VALUES ($1, 'agent.offline', 'Agent heartbeat stale - marked offline.', 'warn', $2)`,
			id, payload)
		slog.Info("scanner agent offline", "agent", id, "name", name)
	}
}

// ── step 5: degraded agents (heartbeat OK, no poll) ──────────────────

func scanDegradedAgents(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	pollCutoff := now.Add(-AgentDegradedAfterSeconds * time.Second)
	heartbeatCutoff := now.Add(-AgentOfflineAfterSeconds * time.Second)

	// Agents that have NEVER polled
	rowsNull, err := pool.Query(ctx,
		`UPDATE agents SET status = 'degraded', updated_at = $1
		 WHERE status = 'online'
		   AND last_heartbeat_at IS NOT NULL
		   AND last_heartbeat_at >= $2
		   AND last_poll_at IS NULL
		 RETURNING id, name, host_id`,
		now, heartbeatCutoff)
	if err != nil {
		slog.Error("scanner degraded_agents null query", "err", err)
	} else {
		for rowsNull.Next() {
			var id, name, hostID string
			rowsNull.Scan(&id, &name, &hostID)
			payload, _ := json.Marshal(map[string]string{"reason": "never_polled", "name": name, "host_id": hostID})
			pool.Exec(ctx,
				`INSERT INTO events (agent_id, event_type, message, level, payload)
				 VALUES ($1, 'agent.degraded', 'Agent has never polled — marking degraded.', 'warn', $2)`,
				id, payload)
			slog.Info("scanner agent degraded (never polled)", "agent", id, "name", name)
		}
		rowsNull.Close()
	}

	// Agents that polled but stopped
	rowsStale, err := pool.Query(ctx,
		`UPDATE agents SET status = 'degraded', updated_at = $1
		 WHERE status = 'online'
		   AND last_heartbeat_at IS NOT NULL
		   AND last_heartbeat_at >= $2
		   AND last_poll_at IS NOT NULL
		   AND last_poll_at < $3
		 RETURNING id, name, host_id, last_poll_at`,
		now, heartbeatCutoff, pollCutoff)
	if err != nil {
		slog.Error("scanner degraded_agents stale query", "err", err)
	} else {
		for rowsStale.Next() {
			var id, name, hostID string
			var lastPoll *time.Time
			rowsStale.Scan(&id, &name, &hostID, &lastPoll)
			var lastPollS string
			if lastPoll != nil {
				lastPollS = lastPoll.Format(time.RFC3339)
			}
			payload, _ := json.Marshal(map[string]interface{}{
				"reason":       "poll_stale",
				"name":         name,
				"host_id":      hostID,
				"last_poll_at": lastPollS,
			})
			pool.Exec(ctx,
				`INSERT INTO events (agent_id, event_type, message, level, payload)
				 VALUES ($1, 'agent.degraded', $2, 'warn', $3)`,
				id, fmt.Sprintf("Agent poll stale (%ds) — marking degraded.", AgentDegradedAfterSeconds), payload)
			slog.Info("scanner agent degraded", "agent", id, "name", name, "last_poll", lastPollS)
		}
		rowsStale.Close()
	}

	// Recover: agents that were degraded but now polling again
	rowsRecover, err := pool.Query(ctx,
		`UPDATE agents SET status = 'online', updated_at = $1
		 WHERE status = 'degraded'
		   AND last_poll_at IS NOT NULL
		   AND last_poll_at >= $2
		 RETURNING id, name`,
		now, pollCutoff)
	if err != nil {
		slog.Error("scanner degraded_agents recover query", "err", err)
	} else {
		for rowsRecover.Next() {
			var id, name string
			rowsRecover.Scan(&id, &name)
			payload, _ := json.Marshal(map[string]string{"name": name})
			pool.Exec(ctx,
				`INSERT INTO events (agent_id, event_type, message, level, payload)
				 VALUES ($1, 'agent.recovered', 'Agent poll recovered — marked online.', 'info', $2)`,
				id, payload)
			slog.Info("scanner agent recovered", "agent", id, "name", name)
		}
		rowsRecover.Close()
	}
}

// ── step 6: completion consistency ───────────────────────────────────

func scanCompletionConsistency(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	rows, err := pool.Query(ctx,
		`SELECT id, updated_at FROM tasks
		 WHERE status = 'done' AND finished_at IS NULL
		 FOR UPDATE SKIP LOCKED`)
	if err != nil {
		slog.Error("scanner completion_consistency query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id string
		var updatedAt time.Time
		if err := rows.Scan(&id, &updatedAt); err != nil {
			continue
		}
		if _, err := pool.Exec(ctx,
			`UPDATE tasks SET finished_at = updated_at, updated_at = $1 WHERE id = $2`,
			now, id); err != nil {
			slog.Error("scanner completion_consistency update", "task", id, "err", err)
		}
		slog.Info("scanner completion repaired", "task", id)
	}
}

// ── step 7: timeout_silent resume (re-queue with next attempt) ────────

func scanTimeoutSilentResume(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	rows, err := pool.Query(ctx,
		`SELECT id FROM tasks
		 WHERE status = 'timeout_silent'
		 FOR UPDATE SKIP LOCKED`)
	if err != nil {
		slog.Error("scanner timeout_silent_resume query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var taskID string
		if err := rows.Scan(&taskID); err != nil {
			continue
		}

		// Count attempts
		var attemptCount int
		if err := pool.QueryRow(ctx,
			`SELECT COUNT(*) FROM task_attempts WHERE task_id = $1`, taskID).Scan(&attemptCount); err != nil {
			continue
		}

		var maxAttempts int
		if err := pool.QueryRow(ctx,
			`SELECT max_attempts FROM tasks WHERE id = $1`, taskID).Scan(&maxAttempts); err != nil {
			continue
		}

		if attemptCount >= maxAttempts {
			pool.Exec(ctx,
				`UPDATE tasks SET status = 'failed_final', finished_at = $1, updated_at = $1 WHERE id = $2`,
				now, taskID)
			payload, _ := json.Marshal(map[string]interface{}{"scanned_at": now.Format(time.RFC3339), "attempt_count": attemptCount, "max_attempts": maxAttempts})
			pool.Exec(ctx,
				`INSERT INTO events (task_id, event_type, message, level, payload)
				 VALUES ($1, 'task.failed_final', 'Max attempts exhausted after timeout_silent.', 'error', $2)`,
				taskID, payload)
			slog.Info("scanner timeout_silent → failed_final", "task", taskID, "attempts", fmt.Sprintf("%d/%d", attemptCount, maxAttempts))
		} else {
			pool.Exec(ctx,
				`UPDATE tasks SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL, updated_at = $1 WHERE id = $2`,
				now, taskID)
			payload, _ := json.Marshal(map[string]interface{}{"scanned_at": now.Format(time.RFC3339), "attempt_count": attemptCount, "max_attempts": maxAttempts})
			pool.Exec(ctx,
				`INSERT INTO events (task_id, event_type, message, level, payload)
				 VALUES ($1, 'task.retry_queued', $2, 'info', $3)`,
				taskID, fmt.Sprintf("timeout_silent re-queued (attempt %d/%d).", attemptCount+1, maxAttempts), payload)
			slog.Info("scanner timeout_silent → queued", "task", taskID, "attempt", fmt.Sprintf("%d/%d", attemptCount+1, maxAttempts))
		}
	}
}

// ── step 8: redispatch stale queued tasks ────────────────────────────

func scanRedispatchQueued(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-2 * time.Minute) // tasks queued >2 min without dispatch

	rows, err := pool.Query(ctx,
		`SELECT id, title, description, task_type, priority, payload, required_capabilities, target_agent_id
		 FROM tasks
		 WHERE status = 'queued'
		   AND lease_owner IS NULL
		   AND created_at < $1
		 ORDER BY priority DESC, created_at
		 LIMIT 20`, cutoff)
	if err != nil {
		slog.Error("scanner redispatch_queued query", "err", err)
		return
	}
	defer rows.Close()

	type queuedTask struct {
		ID                   string
		Title                string
		Description          string
		TaskType             string
		Priority             int
		Payload              []byte
		RequiredCapabilities []byte
		TargetAgentID        *string
	}

	for rows.Next() {
		var t queuedTask
		if err := rows.Scan(&t.ID, &t.Title, &t.Description, &t.TaskType, &t.Priority, &t.Payload, &t.RequiredCapabilities, &t.TargetAgentID); err != nil {
			continue
		}

		// Dispatch via gateway HTTP
		gatewayURL := os.Getenv("GATEWAY_URL")
		if gatewayURL == "" {
			gatewayURL = "http://127.0.0.1:8001"
		}

		payload, _ := json.Marshal(map[string]interface{}{
			"task_id":         t.ID,
			"target_agent_id": t.TargetAgentID,
			"task": map[string]interface{}{
				"id":        t.ID,
				"title":     t.Title,
				"task_type": t.TaskType,
			},
		})

		client := &http.Client{Timeout: 5 * time.Second}
		resp, err := client.Post(gatewayURL+"/tasks/dispatch", "application/json", bytes.NewReader(payload))
		if err != nil {
			slog.Error("scanner redispatch http fail", "task", t.ID, "err", err)
			continue
		}
		resp.Body.Close()

		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			slog.Info("scanner redispatched", "task", t.ID, "title", truncate(t.Title, 40))
			// Log event
			evtPayload, _ := json.Marshal(map[string]string{
				"scanned_at": now.Format(time.RFC3339),
				"method":     "gateway_post",
			})
			pool.Exec(ctx,
				`INSERT INTO events (task_id, event_type, message, level, payload)
				 VALUES ($1, 'task.redispatched', 'Re-dispatched via gateway', 'info', $2)`,
				t.ID, evtPayload)
		} else {
			slog.Warn("scanner redispatch http status", "task", t.ID, "status", resp.StatusCode)
		}
	}
}

// ── step 9: needs_review timeout → failed_final ──────────────────────

func scanNeedsReviewTimeout(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-NeedsReviewTimeoutHours * time.Hour)
	rows, err := pool.Query(ctx,
		`SELECT id, title, updated_at FROM tasks
		 WHERE status = 'needs_review'
		   AND updated_at < $1
		 FOR UPDATE SKIP LOCKED`, cutoff)
	if err != nil {
		slog.Error("scanner needs_review_timeout query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id, title string
		var updatedAt time.Time
		if err := rows.Scan(&id, &title, &updatedAt); err != nil {
			continue
		}
		hoursStuck := now.Sub(updatedAt).Hours()
		pool.Exec(ctx,
			`UPDATE tasks SET status = 'failed_final', updated_at = $1, finished_at = COALESCE(finished_at, $1) WHERE id = $2`,
			now, id)
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":    now.Format(time.RFC3339),
			"hours_stuck":   fmt.Sprintf("%.1f", hoursStuck),
			"timeout_hours": NeedsReviewTimeoutHours,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.needs_review_timeout', $2, 'error', $3)`,
			id, fmt.Sprintf("needs_review timed out after %.1fh — moved to failed_final.", hoursStuck), payload)
		slog.Info("scanner needs_review → failed_final", "task", id, "title", truncate(title, 40), "hours", fmt.Sprintf("%.1f", hoursStuck))
	}
}

// ── step 10: reassign tasks stuck on offline agents ──────────────────

func scanReassignOfflineAgentTasks(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-ReassignAfterAgentOfflineSeconds * time.Second)

	offlineRows, err := pool.Query(ctx,
		`SELECT id, name FROM agents WHERE status = 'offline' AND updated_at < $1`, cutoff)
	if err != nil {
		slog.Error("scanner reassign query agents", "err", err)
		return
	}
	defer offlineRows.Close()

	var offlineIDs []string
	for offlineRows.Next() {
		var id, name string
		offlineRows.Scan(&id, &name)
		offlineIDs = append(offlineIDs, id)
	}
	if len(offlineIDs) == 0 {
		return
	}

	taskRows, err := pool.Query(ctx,
		`SELECT id, title, status, target_agent_id FROM tasks
		 WHERE target_agent_id = ANY($1)
		   AND status IN ('queued', 'leased')
		 FOR UPDATE SKIP LOCKED`, offlineIDs)
	if err != nil {
		slog.Error("scanner reassign query tasks", "err", err)
		return
	}
	defer taskRows.Close()

	for taskRows.Next() {
		var taskID, title, status, oldAgent string
		taskRows.Scan(&taskID, &title, &status, &oldAgent)
		pool.Exec(ctx,
			`UPDATE tasks SET target_agent_id = NULL, updated_at = $1 WHERE id = $2`, now, taskID)
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":             now.Format(time.RFC3339),
			"old_target_agent_id":    oldAgent,
			"reassign_after_seconds": ReassignAfterAgentOfflineSeconds,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.reassigned', 'Reassigned — target agent has been offline >30 min.', 'warn', $2)`,
			taskID, payload)
		slog.Info("scanner task reassigned", "task", taskID, "title", truncate(title, 40), "old_agent", oldAgent)
	}
}

// ── step 11: archive terminal tasks ──────────────────────────────────

func scanArchiveTerminal(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-ArchiveTerminalAfterHours * time.Hour)
	rows, err := pool.Query(ctx,
		`SELECT id, title, status, updated_at FROM tasks
		 WHERE status IN ('done', 'failed_final', 'cancelled')
		   AND updated_at < $1
		 LIMIT 100
		 FOR UPDATE SKIP LOCKED`, cutoff)
	if err != nil {
		slog.Error("scanner archive_terminal query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id, title, status string
		var updatedAt time.Time
		if err := rows.Scan(&id, &title, &status, &updatedAt); err != nil {
			continue
		}
		hoursTerminal := now.Sub(updatedAt).Hours()
		pool.Exec(ctx,
			`UPDATE tasks SET status = 'archived', updated_at = $1 WHERE id = $2`, now, id)
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":          now.Format(time.RFC3339),
			"previous_status":     status,
			"hours_terminal":      fmt.Sprintf("%.1f", hoursTerminal),
			"archive_after_hours": ArchiveTerminalAfterHours,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.archived', $2, 'info', $3)`,
			id, fmt.Sprintf("Terminal task archived after %.1fh.", hoursTerminal), payload)
		slog.Info("scanner archived", "task", id, "title", truncate(title, 40), "prev_status", status, "hours", fmt.Sprintf("%.1f", hoursTerminal))
	}
}

// ── step 12: auto-accept review-chain completed reviews ──────────────

func scanAutoAcceptReview(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-AutoAcceptReviewAfterHours * time.Hour)
	rows, err := pool.Query(ctx,
		`SELECT id, title, updated_at FROM tasks
		 WHERE status = 'needs_review'
		   AND updated_at < $1
		   AND payload->>'review_chain_completed' = 'true'
		 FOR UPDATE SKIP LOCKED`, cutoff)
	if err != nil {
		slog.Error("scanner auto_accept_review query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id, title string
		var updatedAt time.Time
		if err := rows.Scan(&id, &title, &updatedAt); err != nil {
			continue
		}
		hoursWaiting := now.Sub(updatedAt).Hours()
		pool.Exec(ctx,
			`UPDATE tasks SET status = 'done', finished_at = $1, updated_at = $1 WHERE id = $2`, now, id)
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":              now.Format(time.RFC3339),
			"hours_waiting":           fmt.Sprintf("%.1f", hoursWaiting),
			"auto_accept_after_hours": AutoAcceptReviewAfterHours,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.auto_accepted', $2, 'info', $3)`,
			id, fmt.Sprintf("Review auto-accepted after %.1fh without human response.", hoursWaiting), payload)
		slog.Info("scanner auto-accepted", "task", id, "title", truncate(title, 40), "hours", fmt.Sprintf("%.1f", hoursWaiting))
	}
}

// ── step 13: stuck tasks watchdog ────────────────────────────────────

func scanStuckTasks(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()

	// Force failed_final for tasks that exhausted attempts
	rows, err := pool.Query(ctx,
		`SELECT t.id, t.title, t.max_attempts, t.status,
		        COALESCE(ta.max_attempt, 0) AS attempt_no
		 FROM tasks t
		 LEFT JOIN (
		     SELECT task_id, MAX(attempt_no) AS max_attempt
		     FROM task_attempts
		     GROUP BY task_id
		 ) ta ON ta.task_id = t.id
		 WHERE t.status NOT IN ('done','failed_final','archived','cancelled','needs_review')
		   AND COALESCE(ta.max_attempt, 0) >= t.max_attempts
		   AND t.max_attempts > 0
		   AND t.updated_at < $1
		 FOR UPDATE OF t SKIP LOCKED`,
		now.Add(-ExhaustedGraceMinutes*time.Minute))
	if err != nil {
		slog.Error("scanner stuck_tasks query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id, title, status string
		var maxAttempts, attemptNo int
		if err := rows.Scan(&id, &title, &maxAttempts, &status, &attemptNo); err != nil {
			continue
		}
		pool.Exec(ctx,
			`UPDATE tasks SET status='failed_final', finished_at=$1, updated_at=$1 WHERE id=$2`, now, id)
		payload, _ := json.Marshal(map[string]interface{}{
			"previous_status": status,
			"scanned_at":      now.Format(time.RFC3339),
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.forced_final', $2, 'warn', $3)`,
			id, fmt.Sprintf("Watchdog: attempt_no=%d>=%d forced failed_final", attemptNo, maxAttempts), payload)
		slog.Warn("scanner watchdog forced final", "task", id, "prev_status", status)
	}

	// Warn about long-queued tasks
	staleRows, err := pool.Query(ctx,
		`SELECT id, title, created_at, target_agent_id FROM tasks
		 WHERE status = 'queued' AND lease_owner IS NULL AND created_at < $1`,
		now.Add(-StuckQueuedAlertMinutes*time.Minute))
	if err == nil {
		defer staleRows.Close()
		for staleRows.Next() {
			var id, title string
			var createdAt time.Time
			var targetAgentID *string
			if err := staleRows.Scan(&id, &title, &createdAt, &targetAgentID); err != nil {
				continue
			}
			ageMin := now.Sub(createdAt).Minutes()
			slog.Warn("scanner watchdog queued stale", "task", id, "title", truncate(title, 40), "age_min", ageMin, "target", targetAgentID)
		}
	}
}

// ── step 13: dead agent task reclaim ──────────────────────────────────
// Reclaims all leased/running tasks from dead agents and re-queues them.

func scanDeadAgentReclaim(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()

	// Find all dead agents
	deadRows, err := pool.Query(ctx,
		`SELECT id, name FROM agents WHERE status = 'dead'`)
	if err != nil {
		slog.Error("scanner dead_agent_reclaim query agents", "err", err)
		return
	}
	defer deadRows.Close()

	type deadAgent struct {
		ID   string
		Name string
	}
	var deadAgents []deadAgent
	for deadRows.Next() {
		var a deadAgent
		if err := deadRows.Scan(&a.ID, &a.Name); err != nil {
			continue
		}
		deadAgents = append(deadAgents, a)
	}
	if len(deadAgents) == 0 {
		return
	}

	// Collect dead agent IDs for the query
	deadIDs := make([]string, len(deadAgents))
	deadNameMap := make(map[string]string, len(deadAgents))
	for i, a := range deadAgents {
		deadIDs[i] = a.ID
		deadNameMap[a.ID] = a.Name
	}

	// Find all tasks leased by dead agents
	taskRows, err := pool.Query(ctx,
		`SELECT id, title, status, lease_owner FROM tasks
		 WHERE lease_owner = ANY($1)
		   AND status IN ('leased', 'running')
		 FOR UPDATE SKIP LOCKED`, deadIDs)
	if err != nil {
		slog.Error("scanner dead_agent_reclaim query tasks", "err", err)
		return
	}
	defer taskRows.Close()

	type reclaimedTask struct {
		ID         string
		Title      string
		Status     string
		LeaseOwner string
	}
	var tasks []reclaimedTask
	for taskRows.Next() {
		var t reclaimedTask
		if err := taskRows.Scan(&t.ID, &t.Title, &t.Status, &t.LeaseOwner); err != nil {
			continue
		}
		tasks = append(tasks, t)
	}

	// Reclaim each task: release lease, re-queue
	perAgentCount := make(map[string]int)
	for _, t := range tasks {
		// Release lease and re-queue
		if _, err := pool.Exec(ctx,
			`UPDATE tasks SET
			 status = 'queued',
			 lease_owner = NULL,
			 lease_expires_at = NULL,
			 updated_at = $1
			 WHERE id = $2`, now, t.ID); err != nil {
			slog.Error("scanner dead_agent_reclaim update task", "task", t.ID, "err", err)
			continue
		}

		// Mark affected attempts
		pool.Exec(ctx,
			`UPDATE task_attempts SET status = 'timeout_silent', finished_at = $1, updated_at = $1
			 WHERE task_id = $2 AND status IN ('leased', 'running')`,
			now, t.ID)

		// Event log
		agentName := deadNameMap[t.LeaseOwner]
		payload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":    now.Format(time.RFC3339),
			"dead_agent_id": t.LeaseOwner,
			"agent_name":    agentName,
			"prev_status":   t.Status,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.reclaimed_dead', $2, 'warn', $3)`,
			t.ID,
			fmt.Sprintf("Reclaimed from dead agent %s — re-queued.", agentName),
			payload)

		perAgentCount[t.LeaseOwner]++
		slog.Info("scanner dead_agent_reclaim",
			"task", t.ID, "title", truncate(t.Title, 40),
			"dead_agent", agentName, "prev_status", t.Status)
	}

	// Alert per agent
	for agentID, count := range perAgentCount {
		if name, ok := deadNameMap[agentID]; ok {
			AlertTaskDeadAgentReclaim(agentID, name, count)
		}
	}
}

// ── step 14: dead letter move ────────────────────────────────────────
// Moves failed_final tasks older than DeadLetterAfterHours into the dead_letter table,
// preserving full context. Then marks the original task as 'archived'.

func scanDeadLetterMove(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()
	cutoff := now.Add(-DeadLetterAfterHours * time.Hour)

	rows, err := pool.Query(ctx,
		`SELECT id, title, description, task_type, priority, max_attempts,
		 payload, required_capabilities, acceptance_check, created_by,
		 target_agent_id, status, lease_owner, created_at, updated_at
		 FROM tasks
		 WHERE status = 'failed_final'
		   AND finished_at IS NOT NULL
		   AND finished_at < $1
		 LIMIT 50
		 FOR UPDATE SKIP LOCKED`, cutoff)
	if err != nil {
		slog.Error("scanner dead_letter_move query", "err", err)
		return
	}
	defer rows.Close()

	type taskRow struct {
		ID                   string
		Title                string
		Description          string
		TaskType             string
		Priority             int
		MaxAttempts          int
		Payload              []byte
		RequiredCapabilities []byte
		AcceptanceCheck      []byte
		CreatedBy            string
		TargetAgentID        *string
		Status               string
		LeaseOwner           *string
		CreatedAt            time.Time
		UpdatedAt            time.Time
	}

	for rows.Next() {
		var t taskRow
		if err := rows.Scan(&t.ID, &t.Title, &t.Description, &t.TaskType,
			&t.Priority, &t.MaxAttempts, &t.Payload, &t.RequiredCapabilities,
			&t.AcceptanceCheck, &t.CreatedBy, &t.TargetAgentID, &t.Status,
			&t.LeaseOwner, &t.CreatedAt, &t.UpdatedAt); err != nil {
			slog.Error("scanner dead_letter_move scan", "err", err)
			continue
		}

		// Count attempts
		var attemptCount int
		pool.QueryRow(ctx,
			`SELECT COUNT(*) FROM task_attempts WHERE task_id = $1`, t.ID).Scan(&attemptCount)

		// Collect events summary (last 5 error/warn events)
		var eventsSummary []byte
		eventsSummary = []byte("[]")
		evtRows, evtErr := pool.Query(ctx,
			`SELECT event_type, message, level, created_at FROM events
			 WHERE task_id = $1 AND level IN ('error','warn')
			 ORDER BY created_at DESC LIMIT 5`, t.ID)
		if evtErr == nil {
			type evtSummary struct {
				Type    string `json:"type"`
				Message string `json:"message"`
				Level   string `json:"level"`
				Time    string `json:"time"`
			}
			var evts []evtSummary
			for evtRows.Next() {
				var e evtSummary
				var ts time.Time
				evtRows.Scan(&e.Type, &e.Message, &e.Level, &ts)
				e.Time = ts.Format(time.RFC3339)
				evts = append(evts, e)
			}
			evtRows.Close()
			eventsSummary, _ = json.Marshal(evts)
		}

		// Get failure summary from last attempt
		var failureReason, failureSummary *string
		pool.QueryRow(ctx,
			`SELECT error_type, error_message FROM task_attempts
			 WHERE task_id = $1 AND status = 'failed_final'
			 ORDER BY attempt_no DESC LIMIT 1`, t.ID).Scan(&failureReason, &failureSummary)

		// Insert into dead_letter
		if _, err := pool.Exec(ctx,
			`INSERT INTO dead_letter (
			 original_task_id, title, description, task_type, priority,
			 max_attempts, payload, required_capabilities, acceptance_check,
			 created_by, target_agent_id, last_status, last_lease_owner,
			 failure_reason, failure_summary, attempt_count, events_summary,
			 original_created_at, original_updated_at, archived_at
		 ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`,
			t.ID, t.Title, t.Description, t.TaskType, t.Priority,
			t.MaxAttempts, t.Payload, t.RequiredCapabilities, t.AcceptanceCheck,
			t.CreatedBy, t.TargetAgentID, t.Status, t.LeaseOwner,
			failureReason, failureSummary, attemptCount, eventsSummary,
			t.CreatedAt, t.UpdatedAt, now); err != nil {
			slog.Error("scanner dead_letter_move insert", "task", t.ID, "err", err)
			continue
		}

		// Archive original task
		pool.Exec(ctx,
			`UPDATE tasks SET status = 'archived', updated_at = $1 WHERE id = $2`, now, t.ID)

		// Event log
		dlPayload, _ := json.Marshal(map[string]interface{}{
			"scanned_at":     now.Format(time.RFC3339),
			"previous_status": t.Status,
			"attempt_count":  attemptCount,
		})
		pool.Exec(ctx,
			`INSERT INTO events (task_id, event_type, message, level, payload)
			 VALUES ($1, 'task.dead_letter', $2, 'info', $3)`,
			t.ID,
			fmt.Sprintf("Moved to dead_letter queue — %d attempts, preserved for analysis.", attemptCount),
			dlPayload)

		slog.Info("scanner dead_letter_move",
			"task", t.ID,
			"title", truncate(t.Title, 40),
			"attempts", attemptCount)
	}
}

func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen]
}
