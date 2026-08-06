package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Phase 2.6 role phase-change. Two transitions:
//   - keeper → worker (promote): all workers busy, high-priority task
//     stuck, an idle keeper can pick up the slack.
//   - worker → keeper (demote): no online keeper, an idle worker can
//     take the vacant keeper role.
//
// The scanner sets pending_role + pending_until on the agent. On the
// next tick, if the grace period elapsed AND the trigger conditions
// still hold, the role change applies directly (tx: update agent_type
// + write audit event). If conditions cleared, the pending state is
// silently dropped. No request/confirm table, no manual confirm API.

// promoteThreshold is how long a high-priority task must wait before a
// keeper→worker promotion is considered. Tuned to avoid flapping on
// brief load spikes.
const promoteThreshold = 2 * time.Minute

// demoteIdleThreshold is how long a worker must be idle before it's
// eligible to be promoted to keeper (when the keeper role is vacant).
const demoteIdleThreshold = 5 * time.Minute

// pendingGrace is the delay between setting pending_role and applying
// the change. Prevents flapping on transient signal blips.
const pendingGrace = 60 * time.Second

// phaseChangeSignals is the normalized input to the two decision
// functions. The scanner step gathers these from the DB + queue state
// and hands them in as plain values so the decision logic is testable
// without a database.
type phaseChangeSignals struct {
	// Promote (keeper→worker) signals.
	AllWorkersRunning      bool          // every worker agent has a running task
	HighPriorityWaitingFor time.Duration // how long a high-priority task has sat queued
	IdleKeeperAvailable    bool          // an idle keeper-type agent exists locally

	// Demote (worker→keeper) signals.
	OnlineKeeperExists  bool          // any online keeper-type agent on this base
	IdleWorkerAvailable bool          // an idle worker-type agent exists locally
	IdleWorkerIdleFor   time.Duration // how long that worker has been idle
}

// shouldPromoteKeeperToWorker: promote when workers are saturated, a
// high-priority task has been waiting past the threshold, and an idle
// keeper is available to take it on. All three must hold — promoting
// without an idle keeper, or on a brief spike, just moves the
// bottleneck.
func shouldPromoteKeeperToWorker(sig phaseChangeSignals, threshold time.Duration) bool {
	return sig.AllWorkersRunning &&
		sig.HighPriorityWaitingFor >= threshold &&
		sig.IdleKeeperAvailable
}

// shouldDemoteWorkerToKeeper: demote (promote a worker into the keeper
// role) only when the keeper role is genuinely vacant (no online
// keeper) AND a worker has been idle long enough that pulling it off
// worker duty won't strand a running task.
func shouldDemoteWorkerToKeeper(sig phaseChangeSignals, idleThreshold time.Duration) bool {
	return !sig.OnlineKeeperExists &&
		sig.IdleWorkerAvailable &&
		sig.IdleWorkerIdleFor >= idleThreshold
}

// shouldApplyPending: a pending role change whose grace period has
// elapsed is eligible to apply.
func shouldApplyPending(pendingUntil time.Time, now time.Time) bool {
	return !pendingUntil.IsZero() && now.After(pendingUntil)
}

// ── scanner steps ──────────────────────────────────────────────────────

// scanPhaseChangeEvaluate looks at local base state and either:
//   - sets pending_role on an agent when trigger conditions first fire, or
//   - applies the change if pending_role was set last tick and the
//     grace period elapsed and conditions still hold, or
//   - clears a stale pending_role if conditions no longer hold.
func scanPhaseChangeEvaluate(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()

	var workerCount, runningWorkers, idleWorkers int
	var keepersOnline int
	var oldestHighQueuedAge time.Duration

	err := pool.QueryRow(ctx, `
		SELECT
			(SELECT count(*) FROM agents WHERE agent_type = 'worker' AND status = 'online') AS workers,
			(SELECT count(*) FROM agents a WHERE a.agent_type = 'worker' AND a.status = 'online'
			 AND EXISTS (SELECT 1 FROM tasks t WHERE t.lease_owner = a.id AND t.status IN ('leased','running'))) AS running_workers,
			(SELECT count(*) FROM agents a WHERE a.agent_type = 'worker' AND a.status = 'online'
			 AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.lease_owner = a.id AND t.status IN ('leased','running'))) AS idle_workers,
			(SELECT count(*) FROM agents WHERE agent_type = 'keeper' AND status = 'online') AS keepers_online`,
	).Scan(&workerCount, &runningWorkers, &idleWorkers, &keepersOnline)
	if err != nil {
		slog.Error("scanner phase_change_evaluate signals", "err", err)
		return
	}

	var oldestHighQueued *time.Time
	pool.QueryRow(ctx, `
		SELECT created_at FROM tasks
		WHERE status = 'queued' AND lease_owner IS NULL AND priority >= $1
		ORDER BY created_at LIMIT 1`, PriorityToInt(PriorityHigh)).Scan(&oldestHighQueued)
	if oldestHighQueued != nil {
		oldestHighQueuedAge = now.Sub(*oldestHighQueued)
	}

	var idleKeeperAvailable bool
	var idleKeeperID string
	pool.QueryRow(ctx, `
		SELECT id FROM agents
		WHERE agent_type = 'keeper' AND status = 'online'
		AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.lease_owner = agents.id AND t.status IN ('leased','running'))
		LIMIT 1`).Scan(&idleKeeperID)
	if idleKeeperID != "" {
		idleKeeperAvailable = true
	}

	var idleWorkerID string
	var idleWorkerSince *time.Time
	pool.QueryRow(ctx, `
		SELECT a.id, COALESCE(MAX(t.finished_at), a.updated_at)
		FROM agents a
		LEFT JOIN tasks t ON t.lease_owner = a.id
		WHERE a.agent_type = 'worker' AND a.status = 'online'
		AND NOT EXISTS (SELECT 1 FROM tasks t2 WHERE t2.lease_owner = a.id AND t2.status IN ('leased','running'))
		GROUP BY a.id, a.updated_at
		ORDER BY MAX(t.finished_at) ASC NULLS FIRST
		LIMIT 1`).Scan(&idleWorkerID, &idleWorkerSince)

	var idleWorkerIdleFor time.Duration
	if idleWorkerSince != nil {
		idleWorkerIdleFor = now.Sub(*idleWorkerSince)
	}

	sig := phaseChangeSignals{
		AllWorkersRunning:      workerCount > 0 && runningWorkers == workerCount,
		HighPriorityWaitingFor: oldestHighQueuedAge,
		IdleKeeperAvailable:    idleKeeperAvailable,
		OnlineKeeperExists:     keepersOnline > 0,
		IdleWorkerAvailable:    idleWorkerID != "",
		IdleWorkerIdleFor:      idleWorkerIdleFor,
	}

	// Promote path: keeper → worker.
	if shouldPromoteKeeperToWorker(sig, promoteThreshold) && idleKeeperID != "" {
		handlePendingAgent(ctx, pool, idleKeeperID, "keeper", "worker",
			fmt.Sprintf("all %d workers running, high-priority task waiting %s", workerCount, oldestHighQueuedAge),
			now)
	}

	// Demote path: worker → keeper.
	if shouldDemoteWorkerToKeeper(sig, demoteIdleThreshold) && idleWorkerID != "" {
		handlePendingAgent(ctx, pool, idleWorkerID, "worker", "keeper",
			fmt.Sprintf("no online keeper, idle worker available (idle %s)", idleWorkerIdleFor),
			now)
	}

	// Clear stale pending_role on agents whose trigger conditions no
	// longer hold. This covers the case where a pending was set last
	// tick but the situation resolved itself before the grace elapsed.
	clearStalePending(ctx, pool, idleKeeperID, idleWorkerID, sig, now)
}

// handlePendingAgent either applies a pending change whose grace
// elapsed, or sets the pending state if this is the first tick the
// conditions fired.
func handlePendingAgent(ctx context.Context, pool *pgxpool.Pool, agentID, fromRole, toRole, reason string, now time.Time) {
	var pendingRole *string
	var pendingUntil *time.Time
	pool.QueryRow(ctx, `SELECT pending_role, pending_until FROM agents WHERE id = $1`, agentID).Scan(&pendingRole, &pendingUntil)

	// Already pending for this role transition — check if grace elapsed.
	if pendingRole != nil && *pendingRole == toRole && pendingUntil != nil {
		if shouldApplyPending(*pendingUntil, now) {
			applyPhaseChange(ctx, pool, agentID, toRole, reason, now)
		}
		return
	}

	// First tick: set pending state.
	_, err := pool.Exec(ctx, `
		UPDATE agents SET pending_role = $1, pending_until = $2, updated_at = $2 WHERE id = $3`,
		toRole, now.Add(pendingGrace), agentID)
	if err != nil {
		slog.Error("phase_change set pending", "agent", agentID, "err", err)
		return
	}
	slog.Info("phase_change pending set",
		"agent", agentID, "to_role", toRole, "reason", reason, "grace", pendingGrace)
}

// clearStalePending removes pending_role from agents that had a
// pending transition but whose conditions no longer hold. This is the
// "circuit breaker" — if the load spike passed or a keeper came back
// online, the pending is abandoned.
func clearStalePending(ctx context.Context, pool *pgxpool.Pool, idleKeeperID, idleWorkerID string, sig phaseChangeSignals, now time.Time) {
	// Clear pending on idle keeper if promote conditions no longer hold.
	if idleKeeperID != "" && !shouldPromoteKeeperToWorker(sig, promoteThreshold) {
		clearPendingIfSet(ctx, pool, idleKeeperID)
	}
	// Clear pending on idle worker if demote conditions no longer hold.
	if idleWorkerID != "" && !shouldDemoteWorkerToKeeper(sig, demoteIdleThreshold) {
		clearPendingIfSet(ctx, pool, idleWorkerID)
	}
}

func clearPendingIfSet(ctx context.Context, pool *pgxpool.Pool, agentID string) {
	_, err := pool.Exec(ctx, `
		UPDATE agents SET pending_role = NULL, pending_until = NULL, updated_at = now()
		WHERE id = $1 AND pending_role IS NOT NULL`, agentID)
	if err != nil {
		slog.Error("phase_change clear pending", "agent", agentID, "err", err)
	}
}

// applyPhaseChange finalizes the role change: updates the agent's
// agent_type, clears pending fields, and writes an audit event.
func applyPhaseChange(ctx context.Context, pool *pgxpool.Pool, agentID, toRole, reason string, now time.Time) {
	tx, err := pool.Begin(ctx)
	if err != nil {
		slog.Error("phase_change apply begin", "agent", agentID, "err", err)
		return
	}
	defer tx.Rollback(ctx)

	_, err = tx.Exec(ctx, `
		UPDATE agents SET agent_type = $1, pending_role = NULL, pending_until = NULL, updated_at = $2
		WHERE id = $3`,
		toRole, now, agentID)
	if err != nil {
		slog.Error("phase_change apply update agent", "agent", agentID, "err", err)
		return
	}

	payload, _ := json.Marshal(map[string]interface{}{
		"agent_id": agentID,
		"to_role":  toRole,
		"reason":   reason,
	})
	_, err = tx.Exec(ctx, `
		INSERT INTO events (agent_id, event_type, message, level, payload)
		VALUES ($1, 'agent.phase_change', $2, 'info', $3)`,
		agentID, fmt.Sprintf("Phase change → %s (%s)", toRole, reason), payload)
	if err != nil {
		slog.Error("phase_change apply audit", "agent", agentID, "err", err)
		return
	}

	if err := tx.Commit(ctx); err != nil {
		slog.Error("phase_change apply commit", "agent", agentID, "err", err)
		return
	}
	slog.Info("phase_change applied", "agent", agentID, "to", toRole, "reason", reason)
	go broadcastToGateway("agent:phase_change", agentID, map[string]interface{}{
		"to_role": toRole, "reason": reason,
	})
}
