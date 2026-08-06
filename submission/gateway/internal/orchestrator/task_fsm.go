package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// TaskState is the FSM-layer task status enum. It exists to give the
// orchestrator a single, checked place where status transitions are
// validated, instead of the bare-string `UPDATE tasks SET status=...`
// scattered across scanner.go (16 steps) and intake.go.
//
// The DB column `tasks.status` still holds the bare strings — we do NOT
// migrate the schema. The mapping is fixed and bidirectional via
// ToDBString / FromDBString. The non-obvious entry is StateDispatched,
// which maps to the DB string "leased": the existing SQL hardcodes
// "leased" in ~20 places, and renaming the DB value is out of scope for
// Phase 2.1. The FSM name "Dispatched" is the honest label for what
// that state means (a task has been leased out to an agent).
type TaskState int

const (
	StateUnknown TaskState = iota
	StatePending          // DB: "queued"
	StateDispatched       // DB: "leased"   ← name/value mismatch is intentional, see doc
	StateRunning          // DB: "running"
	StateDone             // DB: "done"
	StateFailedFinal      // DB: "failed_final"
	StateArchived         // DB: "archived"
	StateCancelled        // DB: "cancelled"
	StateNeedsReview      // DB: "needs_review"
	StateTimeoutSilent    // DB: "timeout_silent"
	StateFailedRetryable  // DB: "failed_retryable"
	StateBlockedRateLimit // DB: "blocked_rate_limit"
	StateHandoffPending   // DB: "handoff_pending" — Phase 2.5: task handed off to a new agent after timeout
)

// ToDBString maps a TaskState to the bare string stored in tasks.status.
// StateUnknown maps to "" (callers should never persist it).
func ToDBString(s TaskState) string {
	switch s {
	case StatePending:
		return "queued"
	case StateDispatched:
		return "leased"
	case StateRunning:
		return "running"
	case StateDone:
		return "done"
	case StateFailedFinal:
		return "failed_final"
	case StateArchived:
		return "archived"
	case StateCancelled:
		return "cancelled"
	case StateNeedsReview:
		return "needs_review"
	case StateTimeoutSilent:
		return "timeout_silent"
	case StateFailedRetryable:
		return "failed_retryable"
	case StateBlockedRateLimit:
		return "blocked_rate_limit"
	case StateHandoffPending:
		return "handoff_pending"
	default:
		return ""
	}
}

// FromDBString maps a bare DB status string back to a TaskState. Any
// unrecognized string returns StateUnknown rather than panicking — the
// FSM must tolerate a DB row that has drifted (manual fix, forward
// migration) rather than crash a scan cycle.
func FromDBString(db string) TaskState {
	switch db {
	case "queued":
		return StatePending
	case "leased":
		return StateDispatched
	case "running":
		return StateRunning
	case "done":
		return StateDone
	case "failed_final":
		return StateFailedFinal
	case "archived":
		return StateArchived
	case "cancelled":
		return StateCancelled
	case "needs_review":
		return StateNeedsReview
	case "timeout_silent":
		return StateTimeoutSilent
	case "failed_retryable":
		return StateFailedRetryable
	case "blocked_rate_limit":
		return StateBlockedRateLimit
	case "handoff_pending":
		return StateHandoffPending
	default:
		return StateUnknown
	}
}

// legalTransitions is the allow-list of (from → to) pairs the FSM
// accepts. It is the union of every transition the scanner steps and
// intake handlers actually perform today (sourced from scanner.go
// ScanSteps and intake.go CreateTask/PollTask/CompleteTask), plus the
// reserved user-cancel path. Anything not in this set is rejected.
//
// Self-transitions (X→X) are intentionally absent: a no-op status write
// is a caller bug we want to surface as ErrNoChange, not silently accept.
var legalTransitions = map[TaskState]map[TaskState]bool{
	StatePending: {
		StateDispatched: true, // PollTask: queued → leased
		StateCancelled:  true, // user cancel from queue
	},
	StateDispatched: {
		StateRunning:      true, // worker marks running
		StateDone:         true, // CompleteTask short-circuit
		StateFailedFinal:  true, // CompleteTask short-circuit
		StateTimeoutSilent: true, // scanner expired_leases
	},
	StateRunning: {
		StateDone:         true, // CompleteTask success
		StateFailedFinal:  true, // CompleteTask failure
		StateNeedsReview:  true, // CompleteTask permanent error
		StateTimeoutSilent: true, // scanner expired_leases
	},
	StateTimeoutSilent: {
		StatePending:        true, // scanner timeout_silent_resume (retry)
		StateFailedFinal:    true, // scanner timeout_silent_resume (max attempts)
		StateHandoffPending: true, // Phase 2.5: scanner found a handoff target
	},
	StateHandoffPending: {
		StatePending:      true, // re-queued with new target_agent_id (handoff_requeue)
		StateFailedFinal:  true, // no target, or already handed off once
	},
	StateFailedRetryable: {
		StatePending:     true, // scanner failed_retryable backoff
		StateNeedsReview: true, // scanner permanent error
	},
	StateBlockedRateLimit: {
		StatePending: true, // scanner unblock_rate_limited
	},
	StateNeedsReview: {
		StateDone:        true, // scanner auto_accept_review
		StateFailedFinal: true, // scanner needs_review_timeout
	},
	StateDone: {
		StateArchived: true, // scanner archive_terminal
	},
	StateFailedFinal: {
		StateArchived: true, // scanner archive_terminal / dead_letter_move
	},
	StateCancelled: {
		StateArchived: true, // scanner archive_terminal
	},
	StateArchived: {
		// Archived is terminal but idempotent-stable: a re-scan touching
		// an already-archived row is a no-op, not an error.
		StateArchived: true,
	},
}

// CanTransition reports whether from → to is an FSM-legal transition.
// Self-transitions return false except for the archived idempotency case.
func CanTransition(from, to TaskState) bool {
	dests, ok := legalTransitions[from]
	if !ok {
		return false
	}
	return dests[to]
}

// Sentinel errors returned by TransitionWithAudit. Callers may match
// with errors.Is to distinguish "you asked for something illegal" from
// "someone else moved the row first" from "you asked for a no-op".
var (
	// ErrIllegalTransition: the from→to pair is not in legalTransitions.
	ErrIllegalTransition = errors.New("uasclient: illegal task state transition")
	// ErrConcurrentModification: the row's current status no longer
	// matches `from` — another writer (or a scan step) moved it between
	// the caller's read and this transition.
	ErrConcurrentModification = errors.New("uasclient: task status changed concurrently")
	// ErrNoChange: from == to (and from is not the archived idempotency
	// case). The caller asked for a no-op write, which is a bug.
	ErrNoChange = errors.New("uasclient: task state unchanged (no-op transition)")
	// ErrUnknownState: a DB status string did not map to any TaskState.
	ErrUnknownState = errors.New("uasclient: unknown task state")
)

// TransitionWithAudit is the single side-effecting entry point for
// changing a task's status. It validates the transition, then in one
// PG transaction: (1) optimistically updates the row only if its
// current status equals `from`, and (2) writes an audit event to the
// events table. It does NOT broadcast to the Gateway — that is the
// intake handler's responsibility, not the FSM's.
//
// pool may be nil only for the pre-SQL guard path (illegal/no-change),
// which lets callers cheaply validate intent without a DB. Any legal
// transition requires a real pool.
func TransitionWithAudit(ctx context.Context, pool *pgxpool.Pool, taskID string, from, to TaskState, reason string, extra map[string]interface{}) error {
	if from == to && from != StateArchived {
		return ErrNoChange
	}
	if !CanTransition(from, to) {
		return fmt.Errorf("%w: %s → %s (reason=%s)", ErrIllegalTransition, ToDBString(from), ToDBString(to), reason)
	}
	if pool == nil {
		// Legal transition but no pool: this is a programming error in
		// the caller (they passed nil for a real transition). Surface it
		// explicitly rather than nil-deref.
		return errors.New("uasclient: TransitionWithAudit requires a non-nil pool for legal transitions")
	}

	tx, err := pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("fsm begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	// Optimistic lock: only update if the current status is still `from`.
	// RowsAffected == 0 means the row moved under us.
	tag, err := tx.Exec(ctx, `
		UPDATE tasks SET status = $1, updated_at = now()
		WHERE id = $2 AND status = $3`,
		ToDBString(to), taskID, ToDBString(from),
	)
	if err != nil {
		return fmt.Errorf("fsm update: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrConcurrentModification
	}

	// Audit event. payload is a small JSON blob; `extra` is merged in
	// as-is so callers can attach agent_id, attempt_no, etc.
	payload := map[string]interface{}{
		"from":       ToDBString(from),
		"to":         ToDBString(to),
		"reason":     reason,
		"scanned_at": time.Now().UTC().Format(time.RFC3339),
	}
	for k, v := range extra {
		payload[k] = v
	}
	payloadJSON, _ := json.Marshal(payload)
	if _, err := tx.Exec(ctx, `
		INSERT INTO events (task_id, event_type, message, level, payload)
		VALUES ($1, 'task.fsm_transition', $2, 'info', $3)`,
		taskID,
		fmt.Sprintf("FSM %s → %s: %s", ToDBString(from), ToDBString(to), reason),
		payloadJSON,
	); err != nil {
		// Audit write failure is logged but does not roll back the
		// status change — the transition is the source of truth, the
		// audit is observability. Match the pattern in CompleteTask.
		slog.Warn("fsm audit event insert failed", "task", taskID, "err", err)
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("fsm commit: %w", err)
	}
	return nil
}
