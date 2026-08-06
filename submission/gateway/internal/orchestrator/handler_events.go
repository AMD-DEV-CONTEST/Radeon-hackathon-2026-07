package orchestrator

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"time"
)

// Phase 3.2: unified event timeline API.
//
// The events table already accumulates audit rows from the task FSM
// (task.fsm_transition), agent phase changes (agent.phase_change), and
// will gain memory.* events in 3.3. This handler is the single read
// path over all of them, with optional filters for time range, type,
// task_id, and agent_id.

const (
	timelineDefaultLimit = 100
	timelineMaxLimit     = 1000
	timelineDefaultWindow = 1 * time.Hour
)

// timelineParams is the parsed, typed form of the /events/timeline
// query string. Nil pointers mean "no filter on this dimension".
type timelineParams struct {
	From    *time.Time
	To      *time.Time
	Type    string
	TaskID  string
	AgentID string
	Limit   int
}

// buildTimelineQuery constructs the parameterized SQL + args for the
// timeline query. Filters are appended in a fixed arg order
// (from, to, type, task_id, agent_id, limit) so the query plan is stable
// and testable. `now` is injected so tests are deterministic.
//
// When From is nil the query defaults to now-1h (the typical "what just
// happened" use case). A non-positive or over-max Limit is clamped.
func buildTimelineQuery(p timelineParams, now time.Time) (string, []interface{}) {
	if p.From == nil {
		oneHourAgo := now.Add(-timelineDefaultWindow)
		p.From = &oneHourAgo
	}
	if p.Limit <= 0 {
		p.Limit = timelineDefaultLimit
	}
	if p.Limit > timelineMaxLimit {
		p.Limit = timelineMaxLimit
	}

	var (
		conds []string
		args  []interface{}
		n     = 1
	)
	conds = append(conds, "created_at >= $"+itoa(n))
	args = append(args, *p.From)
	n++

	if p.To != nil {
		conds = append(conds, "created_at < $"+itoa(n))
		args = append(args, *p.To)
		n++
	}
	if p.Type != "" {
		conds = append(conds, "event_type = $"+itoa(n))
		args = append(args, p.Type)
		n++
	}
	if p.TaskID != "" {
		conds = append(conds, "task_id = $"+itoa(n))
		args = append(args, p.TaskID)
		n++
	}
	if p.AgentID != "" {
		conds = append(conds, "agent_id = $"+itoa(n))
		args = append(args, p.AgentID)
		n++
	}

	limitArgPos := n
	args = append(args, p.Limit)

	q := `SELECT id, task_id, agent_id, event_type, message, level, payload, created_at
		FROM events`
	for i, c := range conds {
		if i == 0 {
			q += " WHERE "
		} else {
			q += " AND "
		}
		q += c
	}
	q += " ORDER BY created_at DESC LIMIT $" + itoa(limitArgPos)
	return q, args
}

// itoa is strconv.Itoa without the import (handler file stays light).
func itoa(n int) string {
	return strconv.Itoa(n)
}

// EventTimeline handles GET /events/timeline — unified event query.
//
//	Query params (all optional):
//	  from      RFC3339  default: now - 1h
//	  to        RFC3339  default: none (open upper bound)
//	  type      string   e.g. "task.fsm_transition"
//	  task_id   string
//	  agent_id  string
//	  limit     int      default 100, max 1000
func EventTimeline(w http.ResponseWriter, r *http.Request) {
	if pool == nil {
		http.Error(w, `{"error":"db not initialized"}`, http.StatusServiceUnavailable)
		return
	}

	p := timelineParams{Limit: timelineDefaultLimit}
	if v := r.URL.Query().Get("from"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			http.Error(w, `{"error":"invalid 'from' (use RFC3339)"}`, http.StatusBadRequest)
			return
		}
		p.From = &t
	}
	if v := r.URL.Query().Get("to"); v != "" {
		t, err := time.Parse(time.RFC3339, v)
		if err != nil {
			http.Error(w, `{"error":"invalid 'to' (use RFC3339)"}`, http.StatusBadRequest)
			return
		}
		p.To = &t
	}
	p.Type = r.URL.Query().Get("type")
	p.TaskID = r.URL.Query().Get("task_id")
	p.AgentID = r.URL.Query().Get("agent_id")
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			p.Limit = n
		}
	}

	q, args := buildTimelineQuery(p, time.Now().UTC())

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	rows, err := pool.Query(ctx, q, args...)
	if err != nil {
		slog.Error("event timeline query", "err", err)
		http.Error(w, `{"error":"db error"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	type eventRow struct {
		ID        string          `json:"id"`
		TaskID    *string         `json:"task_id,omitempty"`
		AgentID   *string         `json:"agent_id,omitempty"`
		EventType string          `json:"event_type"`
		Message   string          `json:"message"`
		Level     string          `json:"level"`
		Payload   json.RawMessage `json:"payload,omitempty"`
		CreatedAt time.Time       `json:"created_at"`
	}
	events := make([]eventRow, 0)
	for rows.Next() {
		var e eventRow
		if err := rows.Scan(&e.ID, &e.TaskID, &e.AgentID, &e.EventType, &e.Message, &e.Level, &e.Payload, &e.CreatedAt); err != nil {
			slog.Warn("event timeline scan", "err", err)
			continue
		}
		events = append(events, e)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"events": events,
		"count":  len(events),
	})
}
