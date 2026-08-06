package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// TestDBStringRoundTrip: every defined TaskState must survive a
// ToDBString → FromDBString round-trip, and the DB strings must match
// the bare strings the existing SQL (scanner.go, intake.go) hardcodes.
// This is the contract that lets the FSM layer sit on top of an
// unchanged DB schema.
func TestDBStringRoundTrip(t *testing.T) {
	cases := []struct {
		state TaskState
		db    string
	}{
		{StatePending, "queued"},
		{StateDispatched, "leased"}, // ← key mapping, DB value unchanged
		{StateRunning, "running"},
		{StateDone, "done"},
		{StateFailedFinal, "failed_final"},
		{StateArchived, "archived"},
		{StateCancelled, "cancelled"},
		{StateNeedsReview, "needs_review"},
		{StateTimeoutSilent, "timeout_silent"},
		{StateFailedRetryable, "failed_retryable"},
		{StateBlockedRateLimit, "blocked_rate_limit"},
		{StateHandoffPending, "handoff_pending"}, // Phase 2.5
	}
	for _, c := range cases {
		if got := ToDBString(c.state); got != c.db {
			t.Fatalf("ToDBString(%v) = %q, want %q", c.state, got, c.db)
		}
		if got := FromDBString(c.db); got != c.state {
			t.Fatalf("FromDBString(%q) = %v, want %v", c.db, got, c.state)
		}
	}
	// Unknown DB string → StateUnknown, no panic.
	if got := FromDBString("nonsense_state"); got != StateUnknown {
		t.Fatalf("FromDBString(unknown) = %v, want StateUnknown", got)
	}
	if got := ToDBString(StateUnknown); got != "" {
		t.Fatalf("ToDBString(StateUnknown) = %q, want empty", got)
	}
}

// TestCanTransition_AllLegalPaths: each transition the scanner and
// intake handlers actually perform must be legal. If any of these
// return false, the FSM would block an existing code path — a
// regression. Sourced from scanner.go ScanSteps + intake.go handlers.
func TestCanTransition_AllLegalPaths(t *testing.T) {
	legal := []struct {
		from, to TaskState
	}{
		// PollTask: queued → leased
		{StatePending, StateDispatched},
		// worker starts: leased → running (not currently used by code,
		// but a legal worker-side transition we must allow)
		{StateDispatched, StateRunning},
		// scanner expired_leases: leased/running → timeout_silent
		{StateDispatched, StateTimeoutSilent},
		{StateRunning, StateTimeoutSilent},
		// CompleteTask: → done / failed_final / needs_review
		{StateRunning, StateDone},
		{StateRunning, StateFailedFinal},
		{StateRunning, StateNeedsReview},
		// CompleteTask short-circuit from leased (no running seen)
		{StateDispatched, StateDone},
		{StateDispatched, StateFailedFinal},
		// scanner timeout_silent_resume: → queued (retry) or failed_final
		{StateTimeoutSilent, StatePending},
		{StateTimeoutSilent, StateFailedFinal},
		// scanner failed_retryable: → queued (backoff) or needs_review (permanent)
		{StateFailedRetryable, StatePending},
		{StateFailedRetryable, StateNeedsReview},
		// scanner unblock_rate_limited: → queued
		{StateBlockedRateLimit, StatePending},
		// user cancel from queued
		{StatePending, StateCancelled},
		// terminal convergence → archived
		{StateDone, StateArchived},
		{StateFailedFinal, StateArchived},
		{StateCancelled, StateArchived},
		{StateArchived, StateArchived}, // archived is idempotent-stable
		// needs_review resolution
		{StateNeedsReview, StateDone},         // auto_accept
		{StateNeedsReview, StateFailedFinal},  // timeout
		// Phase 2.5: timeout handoff
		{StateTimeoutSilent, StateHandoffPending},  // scanner found a handoff target
		{StateHandoffPending, StatePending},        // re-queued with new target_agent_id
		{StateHandoffPending, StateFailedFinal},    // no target, or already handed off once
	}
	for _, c := range legal {
		if !CanTransition(c.from, c.to) {
			t.Fatalf("CanTransition(%v → %v) = false, want true (legal scanner/intake path)", c.from, c.to)
		}
	}
}

// TestCanTransition_IllegalPaths: transitions that must never happen.
// These guard against accidentally widening the FSM.
func TestCanTransition_IllegalPaths(t *testing.T) {
	illegal := []struct {
		from, to TaskState
	}{
		// No resurrection from terminal states (except archived→archived).
		{StateDone, StatePending},
		{StateDone, StateRunning},
		{StateFailedFinal, StatePending},
		{StateCancelled, StateRunning},
		{StateArchived, StateRunning},
		// Self-reflection is rejected (use ErrNoChange via TransitionWithAudit).
		{StatePending, StatePending},
		{StateRunning, StateRunning},
		{StateDone, StateDone},
		// Can't dispatch an already-dispatched task again.
		{StateDispatched, StateDispatched},
		// Pending skips straight to done only via Dispatched/Running.
		{StatePending, StateDone},
		{StatePending, StateFailedFinal},
		// Handoff cannot recurse back to timeout_silent (would loop).
		{StateHandoffPending, StateTimeoutSilent},
		// Unknown is not a valid endpoint.
		{StatePending, StateUnknown},
		{StateUnknown, StatePending},
	}
	for _, c := range illegal {
		if CanTransition(c.from, c.to) {
			t.Fatalf("CanTransition(%v → %v) = true, want false (illegal path)", c.from, c.to)
		}
	}
}

// TestTransitionWithAudit_IllegalRejected: an illegal transition must
// return ErrIllegalTransition and write nothing to the DB. We don't
// need a real PG for this — the guard fires before any SQL.
func TestTransitionWithAudit_IllegalRejected(t *testing.T) {
	err := TransitionWithAudit(context.Background(), nil, "fake-task", StateDone, StatePending, "test", nil)
	if !errors.Is(err, ErrIllegalTransition) {
		t.Fatalf("illegal transition err = %v, want ErrIllegalTransition", err)
	}
}

// TestTransitionWithAudit_NoChangeRejected: a self-transition returns
// ErrNoChange (distinct from illegal — it's a no-op the caller should
// not have requested, but it's not a contract violation the same way).
func TestTransitionWithAudit_NoChangeRejected(t *testing.T) {
	err := TransitionWithAudit(context.Background(), nil, "fake-task", StateRunning, StateRunning, "test", nil)
	if !errors.Is(err, ErrNoChange) {
		t.Fatalf("self-transition err = %v, want ErrNoChange", err)
	}
}

// --- PG-backed tests below. Skipped when DATABASE_URL is unset so the
// suite stays green in environments without a database (CI sandbox,
// local lint). When a DB is available these exercise the real tx +
// optimistic-lock + events-insert path. ---

func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL unset; skipping PG-backed FSM test")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Skipf("could not connect to PG: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// seedTask inserts a task row in the given from state and returns its id.
func seedTask(t *testing.T, pool *pgxpool.Pool, from TaskState) string {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var id string
	err := pool.QueryRow(ctx, `
		INSERT INTO tasks (title, task_type, status, priority, max_attempts, created_by, created_at, updated_at)
		VALUES ($1, 'coding', $2, 50, 3, 'fsm_test', now(), now())
		RETURNING id`,
		"fsm-test-"+time.Now().Format("150405.000000"), ToDBString(from),
	).Scan(&id)
	if err != nil {
		t.Fatalf("seed task in state %v: %v", from, err)
	}
	t.Cleanup(func() {
		pool.Exec(context.Background(), `DELETE FROM tasks WHERE id = $1`, id)
	})
	return id
}

// TestTransitionWithAudit_PG_LegalUpdate: a legal transition updates
// the task status and writes exactly one audit event in the same tx.
func TestTransitionWithAudit_PG_LegalUpdate(t *testing.T) {
	pool := testPool(t)
	taskID := seedTask(t, pool, StatePending)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	before := countEvents(t, ctx, pool, taskID)
	err := TransitionWithAudit(ctx, pool, taskID, StatePending, StateDispatched, "poll", map[string]interface{}{"agent": "a1"})
	if err != nil {
		t.Fatalf("TransitionWithAudit legal: %v", err)
	}

	// Status updated.
	var got string
	pool.QueryRow(ctx, `SELECT status FROM tasks WHERE id = $1`, taskID).Scan(&got)
	if got != ToDBString(StateDispatched) {
		t.Fatalf("status after transition = %q, want %q", got, ToDBString(StateDispatched))
	}

	// Exactly one audit event added.
	after := countEvents(t, ctx, pool, taskID)
	if after-before != 1 {
		t.Fatalf("event count delta = %d, want 1", after-before)
	}

	// The audit event has the expected event_type and carries from/to in payload.
	var evtType, payload string
	pool.QueryRow(ctx, `
		SELECT event_type, payload::text FROM events
		WHERE task_id = $1 AND event_type = 'task.fsm_transition'
		ORDER BY created_at DESC LIMIT 1`, taskID).Scan(&evtType, &payload)
	if evtType != "task.fsm_transition" {
		t.Fatalf("audit event_type = %q, want task.fsm_transition", evtType)
	}
	var p map[string]interface{}
	if err := json.Unmarshal([]byte(payload), &p); err != nil {
		t.Fatalf("decode audit payload: %v", err)
	}
	if p["from"] != "queued" || p["to"] != "leased" || p["reason"] != "poll" {
		t.Fatalf("audit payload = %v, want from=queued/to=leased/reason=poll", p)
	}
}

// TestTransitionWithAudit_PG_ConcurrentModification: when the row's
// current status no longer matches `from` (another writer moved it),
// TransitionWithAudit must return ErrConcurrentModification and not
// write an audit event.
func TestTransitionWithAudit_PG_ConcurrentModification(t *testing.T) {
	pool := testPool(t)
	taskID := seedTask(t, pool, StatePending)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Simulate a concurrent writer moving the task to leased before we
	// get to attempt our Pending→Dispatched transition.
	if _, err := pool.Exec(ctx, `UPDATE tasks SET status='leased', updated_at=now() WHERE id=$1`, taskID); err != nil {
		t.Fatalf("preset status: %v", err)
	}

	before := countEvents(t, ctx, pool, taskID)
	err := TransitionWithAudit(ctx, pool, taskID, StatePending, StateDispatched, "stale", nil)
	if !errors.Is(err, ErrConcurrentModification) {
		t.Fatalf("concurrent-mod err = %v, want ErrConcurrentModification", err)
	}
	after := countEvents(t, ctx, pool, taskID)
	if after != before {
		t.Fatalf("audit event written on failed transition: delta=%d, want 0", after-before)
	}
}

func countEvents(t *testing.T, ctx context.Context, pool *pgxpool.Pool, taskID string) int {
	t.Helper()
	var n int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM events WHERE task_id = $1`, taskID).Scan(&n); err != nil {
		t.Fatalf("count events: %v", err)
	}
	return n
}
