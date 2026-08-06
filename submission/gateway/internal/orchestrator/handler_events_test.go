package orchestrator

import (
	"testing"
	"time"
)

// TestBuildTimelineQuery_Defaults: with no params, the query defaults
// to the last hour, limit 100, ordered DESC. The SQL must contain the
// created_at >= $1 filter and the LIMIT.
func TestBuildTimelineQuery_Defaults(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	q, args := buildTimelineQuery(timelineParams{}, now)

	if q == "" {
		t.Fatal("expected non-empty SQL")
	}
	if !contains(q, "created_at >= $1") {
		t.Fatalf("SQL missing default created_at filter: %s", q)
	}
	if !contains(q, "ORDER BY created_at DESC") {
		t.Fatalf("SQL missing DESC order: %s", q)
	}
	if !contains(q, "LIMIT") {
		t.Fatalf("SQL missing LIMIT: %s", q)
	}
	// Default window is 1h before `now`.
	if len(args) < 1 {
		t.Fatalf("expected at least 1 arg, got %d", len(args))
	}
	if got, ok := args[0].(time.Time); !ok || got.Sub(now.Add(-1*time.Hour)) != 0 {
		t.Fatalf("default from-arg = %v, want %v", args[0], now.Add(-1*time.Hour))
	}
}

// TestBuildTimelineQuery_FullFilters: every filter maps to a WHERE
// clause and a positional arg, in a stable order.
func TestBuildTimelineQuery_FullFilters(t *testing.T) {
	now := time.Date(2026, 6, 23, 12, 0, 0, 0, time.UTC)
	from := now.Add(-24 * time.Hour)
	to := now.Add(-1 * time.Hour)
	p := timelineParams{
		From:     &from,
		To:       &to,
		Type:     "task.fsm_transition",
		AgentID:  "agent-xyz",
		Limit:    50,
	}
	q, args := buildTimelineQuery(p, now)

	if !contains(q, "created_at >= $1") {
		t.Fatalf("missing from filter: %s", q)
	}
	if !contains(q, "created_at < $2") {
		t.Fatalf("missing to filter: %s", q)
	}
	if !contains(q, "event_type = $3") {
		t.Fatalf("missing type filter: %s", q)
	}
	if !contains(q, "agent_id = $4") {
		t.Fatalf("missing agent_id filter: %s", q)
	}
	if !contains(q, "LIMIT $5") {
		t.Fatalf("missing limit filter: %s", q)
	}
	if len(args) != 5 {
		t.Fatalf("expected 5 args, got %d (%v)", len(args), args)
	}
	if args[0].(time.Time) != from {
		t.Fatalf("arg0 = %v, want %v", args[0], from)
	}
	if args[1].(time.Time) != to {
		t.Fatalf("arg1 = %v, want %v", args[1], to)
	}
	if args[2] != "task.fsm_transition" {
		t.Fatalf("arg2 = %v, want task.fsm_transition", args[2])
	}
	if args[3] != "agent-xyz" {
		t.Fatalf("arg3 = %v, want agent-xyz", args[3])
	}
	if args[4].(int) != 50 {
		t.Fatalf("arg4 = %v, want 50", args[4])
	}
}

// TestBuildTimelineQuery_LimitClamped: a limit over the max is clamped,
// and a non-positive limit falls back to the default. This guards
// against unbounded scans and silly inputs.
func TestBuildTimelineQuery_LimitClamped(t *testing.T) {
	now := time.Now()
	maxLimit := 1000

	for _, in := range []int{0, -5} {
		q, args := buildTimelineQuery(timelineParams{Limit: in}, now)
		// Default limit applied.
		_ = q
		if last := args[len(args)-1].(int); last != 100 {
			t.Fatalf("limit=%d → arg %d, want default 100", in, last)
		}
	}

	q, args := buildTimelineQuery(timelineParams{Limit: 5000}, now)
	_ = q
	if last := args[len(args)-1].(int); last != maxLimit {
		t.Fatalf("limit=5000 → arg %d, want clamped to %d", last, maxLimit)
	}
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
