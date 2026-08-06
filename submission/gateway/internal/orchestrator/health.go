package orchestrator

import (
	"context"
	"encoding/json"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ── Agent Health States ──────────────────────────────────────────────

const (
	HealthHealthy   = "healthy"   // heartbeat < 60s, poll < 120s
	HealthDegraded  = "degraded"  // heartbeat < 180s, poll stale or never
	HealthUnhealthy = "unhealthy" // heartbeat 180s-600s
	HealthDead      = "dead"      // heartbeat > 600s
)

const (
	CircuitMaxConsecutiveFailures = 3
	CircuitMaxTotalFailures       = 10
	CircuitPauseMinutes           = 5
)

// ── Health grading ───────────────────────────────────────────────────

// GradeAgentHealth computes the health state for a single agent.
// Returns: new state, reason string.
func GradeAgentHealth(lastHeartbeat, lastPoll *time.Time) (string, string) {
	now := time.Now().UTC()

	if lastHeartbeat == nil {
		return HealthDead, "never heartbeated"
	}

	hbAge := now.Sub(*lastHeartbeat)

	if hbAge > 600*time.Second {
		return HealthDead, "heartbeat >10min stale"
	}
	if hbAge > 180*time.Second {
		return HealthUnhealthy, "heartbeat 3-10min stale"
	}
	if lastPoll == nil {
		return HealthDegraded, "heartbeat OK but never polled"
	}

	pollAge := now.Sub(*lastPoll)
	if pollAge > 120*time.Second {
		return HealthDegraded, "heartbeat OK but poll >2min stale"
	}

	return HealthHealthy, ""
}

// UpdateAgentHealth scans all agents and updates their health state.
func UpdateAgentHealth(ctx context.Context, pool *pgxpool.Pool) {
	now := time.Now().UTC()

	rows, err := pool.Query(ctx,
		`SELECT id, name, last_heartbeat_at, last_poll_at, status, 
		 consecutive_failures, total_failures
		 FROM agents WHERE status != 'disabled'`)
	if err != nil {
		slog.Error("health scan query", "err", err)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var id, name, currentStatus string
		var lastHB, lastPoll *time.Time
		var consecFails, totalFails int

		if err := rows.Scan(&id, &name, &lastHB, &lastPoll,
			&currentStatus, &consecFails, &totalFails); err != nil {
			slog.Error("health scan row", "err", err)
			continue
		}

		newState, reason := GradeAgentHealth(lastHB, lastPoll)

		// Only update if state changed
		if newState != currentStatus {
			_, err := pool.Exec(ctx,
				`UPDATE agents SET status = $1, updated_at = $2 WHERE id = $3`,
				newState, now, id)
			if err != nil {
				slog.Error("health update", "agent", id, "err", err)
				continue
			}

			// Log event
			payload, _ := json.Marshal(map[string]string{
				"previous": currentStatus, "new": newState, "reason": reason,
			})
			pool.Exec(ctx,
				`INSERT INTO events (agent_id, event_type, message, level, payload)
				 VALUES ($1, 'agent.health_change',
				 'Agent health changed: ' || $2 || ' → ' || $3 || ' (' || $4 || ')',
				 CASE WHEN $3 IN ('dead','unhealthy') THEN 'error'
				      WHEN $3 = 'degraded' THEN 'warn'
				      ELSE 'info' END,
				 $5)`,
				id, currentStatus, newState, reason, payload)

			slog.Info("agent health change",
				"agent", name, "from", currentStatus, "to", newState, "reason", reason)

			// ── Feishu alert ─────────────────────────────────
			AlertAgentStatus(id, name, currentStatus, newState, reason)
		}

		// ── Circuit breaker logic ────────────────────────────
		// Check if agent should be paused due to failures
		if newState == HealthHealthy && consecFails >= CircuitMaxConsecutiveFailures {
			// Pause agent for N minutes (set status to degraded temporarily)
			_, err := pool.Exec(ctx,
				`UPDATE agents SET status = 'degraded', updated_at = $1
				 WHERE id = $2 AND status = 'healthy'`, now, id)
			if err == nil {
				payload, _ := json.Marshal(map[string]interface{}{
					"consecutive_failures": consecFails,
					"circuit_open_until":   now.Add(CircuitPauseMinutes * time.Minute).Format(time.RFC3339),
				})
				pool.Exec(ctx,
					`INSERT INTO events (agent_id, event_type, message, level, payload)
					 VALUES ($1, 'agent.circuit_open',
					 'Circuit breaker opened: ' || $2 || ' consecutive failures → pausing ' || $3 || 'min',
					 'warn', $4)`,
					id, consecFails, CircuitPauseMinutes, payload)
				slog.Warn("circuit breaker open",
					"agent", name, "consecutive_failures", consecFails)
				AlertCircuitBreaker(id, name, consecFails, totalFails)
			}
		}

		// Auto-disable agent with too many total failures
		if totalFails >= CircuitMaxTotalFailures && currentStatus != "disabled" {
			_, err := pool.Exec(ctx,
				`UPDATE agents SET status = 'disabled', updated_at = $1 WHERE id = $2`,
				now, id)
			if err == nil {
				payload, _ := json.Marshal(map[string]int{
					"total_failures":         totalFails,
					"consecutive_failures":   consecFails,
				})
				pool.Exec(ctx,
					`INSERT INTO events (agent_id, event_type, message, level, payload)
					 VALUES ($1, 'agent.disabled',
					 'Agent auto-disabled: ' || $2 || ' total failures (circuit breaker threshold)',
					 'error', $3)`,
					id, totalFails, payload)
				slog.Error("agent auto-disabled",
					"agent", name, "total_failures", totalFails)
				AlertAgentDisabled(id, name, totalFails)
			}
		}
	}
}

// ── Circuit breaker task guard ───────────────────────────────────────

// ShouldDispatchTask checks whether a task should be dispatched to an agent.
// Returns false if agent is unhealthy/dead/disabled or circuit breaker is open.
func ShouldDispatchTask(ctx context.Context, pool *pgxpool.Pool, agentID string) (bool, string) {
	var status string
	var consecFails, totalFails int

	err := pool.QueryRow(ctx,
		`SELECT status, COALESCE(consecutive_failures,0), COALESCE(total_failures,0)
		 FROM agents WHERE id = $1`, agentID,
	).Scan(&status, &consecFails, &totalFails)
	if err != nil {
		return false, "agent not found"
	}

	if status == "disabled" {
		return false, "agent disabled"
	}
	if status == "dead" || status == "unhealthy" {
		return false, "agent " + status
	}
	if status == "degraded" && consecFails >= CircuitMaxConsecutiveFailures {
		return false, "circuit breaker open (consecutive failures)"
	}
	if totalFails >= CircuitMaxTotalFailures {
		return false, "circuit breaker open (total failures)"
	}

	return true, ""
}

// RecordTaskFailure increments failure counters for an agent.
func RecordTaskFailure(ctx context.Context, pool *pgxpool.Pool, agentID string) {
	pool.Exec(ctx,
		`UPDATE agents SET
		 consecutive_failures = COALESCE(consecutive_failures,0) + 1,
		 total_failures = COALESCE(total_failures,0) + 1,
		 updated_at = $1
		 WHERE id = $2`, time.Now().UTC(), agentID)
}

// RecordTaskSuccess resets consecutive failures for an agent.
func RecordTaskSuccess(ctx context.Context, pool *pgxpool.Pool, agentID string) {
	pool.Exec(ctx,
		`UPDATE agents SET
		 consecutive_failures = 0,
		 updated_at = $1
		 WHERE id = $2`, time.Now().UTC(), agentID)
}
