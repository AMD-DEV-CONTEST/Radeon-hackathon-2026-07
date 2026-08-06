package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ── Cron Scheduler ──────────────────────────────────────────────────
//
// T2 — timed loop scheduler: cron expression → task:dispatch → audit chain.
// Reads enabled cron_schedules from DB, evaluates due expressions every 30s,
// dispatches tasks via the existing task creation path, and records each
// dispatch in cron_events (audit chain).

const cronPollIntervalSeconds = 30

// CronSchedule represents a single cron schedule row.
type CronSchedule struct {
	ID              string     `json:"id"`
	Name            string     `json:"name"`
	Description     string     `json:"description"`
	CronExpr        string     `json:"cron_expr"`
	TaskTemplate    []byte     `json:"task_template"`
	Enabled         bool       `json:"enabled"`
	LastTriggeredAt *time.Time `json:"last_triggered_at,omitempty"`
	CreatedBy       string     `json:"created_by"`
	CreatedAt       time.Time  `json:"created_at"`
	UpdatedAt       time.Time  `json:"updated_at"`
}

// RunCronLoop runs all cron schedule checks every cronPollIntervalSeconds.
// Called as a background goroutine from cmd/orchestrator/main.go.
func RunCronLoop(ctx context.Context, pool *pgxpool.Pool) {
	slog.Info("cron scheduler loop starting", "interval_s", cronPollIntervalSeconds)
	ticker := time.NewTicker(cronPollIntervalSeconds * time.Second)
	defer ticker.Stop()

	// Run once immediately on startup
	runCronCycle(ctx, pool)

	for {
		select {
		case <-ctx.Done():
			slog.Info("cron scheduler loop stopped")
			return
		case <-ticker.C:
			runCronCycle(ctx, pool)
		}
	}
}

func runCronCycle(ctx context.Context, pool *pgxpool.Pool) {
	schedules, err := loadEnabledSchedules(ctx, pool)
	if err != nil {
		slog.Error("cron load schedules", "err", err)
		return
	}

	now := time.Now().UTC()
	for _, s := range schedules {
		if !s.Enabled {
			continue
		}
		if !isCronDue(s.CronExpr, s.LastTriggeredAt, now) {
			continue
		}

		dispatchCronTask(ctx, pool, s, now)
	}
}

// loadEnabledSchedules fetches all enabled cron schedules from the DB.
func loadEnabledSchedules(ctx context.Context, pool *pgxpool.Pool) ([]CronSchedule, error) {
	rows, err := pool.Query(ctx,
		`SELECT id, name, description, cron_expr, task_template, enabled,
		        last_triggered_at, created_by, created_at, updated_at
		 FROM cron_schedules WHERE enabled = true
		 ORDER BY created_at`)
	if err != nil {
		return nil, fmt.Errorf("query cron_schedules: %w", err)
	}
	defer rows.Close()

	var schedules []CronSchedule
	for rows.Next() {
		var s CronSchedule
		if err := rows.Scan(&s.ID, &s.Name, &s.Description, &s.CronExpr,
			&s.TaskTemplate, &s.Enabled, &s.LastTriggeredAt,
			&s.CreatedBy, &s.CreatedAt, &s.UpdatedAt); err != nil {
			slog.Error("cron scan schedule row", "err", err)
			continue
		}
		schedules = append(schedules, s)
	}
	return schedules, nil
}

// dispatchCronTask creates a task from the cron schedule template and records
// the dispatch in the audit chain (events + cron_events tables).
func dispatchCronTask(ctx context.Context, pool *pgxpool.Pool, s CronSchedule, now time.Time) {
	// Parse task template from the schedule
	taskPayload := map[string]any{
		"title":        fmt.Sprintf("[cron] %s", s.Name),
		"description":  s.Description,
		"task_type":    "cron_triggered",
		"priority":     100,
		"max_attempts": 1,
		"payload":      map[string]any{},
	}

	if len(s.TaskTemplate) > 0 && string(s.TaskTemplate) != "null" {
		if err := json.Unmarshal(s.TaskTemplate, &taskPayload); err != nil {
			slog.Warn("cron parse task_template, using defaults", "schedule", s.ID, "err", err)
		}
	}

	// Ensure required fields
	title, _ := taskPayload["title"].(string)
	if title == "" {
		title = fmt.Sprintf("[cron] %s", s.Name)
	}
	desc, _ := taskPayload["description"].(string)
	taskType, _ := taskPayload["task_type"].(string)
	if taskType == "" {
		taskType = "cron_triggered"
	}
	priority := 100
	if p, ok := taskPayload["priority"].(float64); ok {
		priority = int(p)
	}
	maxAttempts := 1
	if m, ok := taskPayload["max_attempts"].(float64); ok {
		maxAttempts = int(m)
	}
	payloadBytes, _ := json.Marshal(taskPayload["payload"])

	// Try to create the task; record failure/success in audit chain regardless
	var taskID string
	taskErr := pool.QueryRow(ctx,
		`INSERT INTO tasks (title, description, task_type, priority, max_attempts, payload, created_by, status)
		 VALUES ($1, $2, $3, $4, $5, $6, 'cron', 'queued')
		 RETURNING id`,
		title, desc, taskType, priority, maxAttempts, payloadBytes).Scan(&taskID)

	if taskErr != nil {
		slog.Error("cron create task", "schedule", s.ID, "err", taskErr)
		// Record failure in audit chain
		_, auditErr := pool.Exec(ctx,
			`INSERT INTO cron_events (schedule_id, schedule_name, cron_expr, task_id, status, message, triggered_at)
			 VALUES ($1, $2, $3, NULL, 'failed', $4, $5)`,
			s.ID, s.Name, s.CronExpr,
			fmt.Sprintf("Cron schedule '%s' failed to create task: %s", s.Name, taskErr.Error()),
			now)
		if auditErr != nil {
			slog.Error("cron insert failed cron_event", "schedule", s.ID, "err", auditErr)
		}
		return
	}

	// Update last_triggered_at
	_, err := pool.Exec(ctx,
		`UPDATE cron_schedules SET last_triggered_at = $1, updated_at = $1 WHERE id = $2`,
		now, s.ID)
	if err != nil {
		slog.Error("cron update last_triggered_at", "schedule", s.ID, "err", err)
	}

	// Record cron event (audit chain) — success
	_, err = pool.Exec(ctx,
		`INSERT INTO cron_events (schedule_id, schedule_name, cron_expr, task_id, status, message, triggered_at)
		 VALUES ($1, $2, $3, $4, 'dispatched', $5, $6)`,
		s.ID, s.Name, s.CronExpr, taskID,
		fmt.Sprintf("Cron schedule '%s' dispatched task %s", s.Name, taskID),
		now)
	if err != nil {
		slog.Error("cron insert cron_event", "schedule", s.ID, "err", err)
	}

	// Also write to events table (general audit chain)
	evtPayload, _ := json.Marshal(map[string]any{
		"schedule_id":   s.ID,
		"schedule_name": s.Name,
		"cron_expr":     s.CronExpr,
		"triggered_at":  now.Format(time.RFC3339),
	})
	_, err = pool.Exec(ctx,
		`INSERT INTO events (task_id, event_type, message, level, payload)
		 VALUES ($1, 'cron.triggered', $2, 'info', $3)`,
		taskID,
		fmt.Sprintf("Cron schedule '%s' (%s) triggered task dispatch", s.Name, s.CronExpr),
		evtPayload)
	if err != nil {
		slog.Error("cron insert event", "schedule", s.ID, "err", err)
	}

	slog.Info("cron dispatched",
		"schedule", s.Name,
		"schedule_id", s.ID,
		"cron_expr", s.CronExpr,
		"task_id", taskID)
}

// ── Cron Expression Parser ─────────────────────────────────────────
//
// Parses standard 5-field cron: minute hour day-of-month month day-of-week
// Supports: * (any), N (exact), N,M,... (list), N-M (range), */N (step)

// cronField holds parsed values for one cron field.
type cronField struct {
	any    bool
	values map[int]bool
}

// parseCronField parses a single cron field string.
func parseCronField(field string, min, max int) (cronField, error) {
	f := cronField{values: make(map[int]bool)}

	if field == "*" {
		f.any = true
		return f, nil
	}

	parts := strings.Split(field, ",")
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}

		// Check for step: */N or N-M/N
		step := 1
		if slashIdx := strings.Index(part, "/"); slashIdx >= 0 {
			stepStr := part[slashIdx+1:]
			var err error
			step, err = strconv.Atoi(stepStr)
			if err != nil || step < 1 {
				return f, fmt.Errorf("invalid step: %s", stepStr)
			}
			part = part[:slashIdx]
		}

		if part == "*" {
			// */N — every N values
			for v := min; v <= max; v += step {
				f.values[v] = true
			}
			continue
		}

		if strings.Contains(part, "-") {
			// Range: N-M
			dashIdx := strings.Index(part, "-")
			start, err1 := strconv.Atoi(part[:dashIdx])
			end, err2 := strconv.Atoi(part[dashIdx+1:])
			if err1 != nil || err2 != nil {
				return f, fmt.Errorf("invalid range: %s", part)
			}
			if start < min || start > max || end < min || end > max || end < start {
				return f, fmt.Errorf("range %s out of bounds [%d-%d]", part, min, max)
			}
			for v := start; v <= end; v += step {
				f.values[v] = true
			}
		} else {
			// Single value or step on single value
			v, err := strconv.Atoi(part)
			if err != nil {
				return f, fmt.Errorf("invalid value: %s", part)
			}
			if v < min || v > max {
				return f, fmt.Errorf("value %d out of bounds [%d-%d]", v, min, max)
			}
			if step > 1 {
				for ; v <= max; v += step {
					f.values[v] = true
				}
			} else {
				f.values[v] = true
			}
		}
	}

	return f, nil
}

// parseCronExpr parses a standard 5-field cron expression.
// Fields: minute(0-59) hour(0-23) day-of-month(1-31) month(1-12) day-of-week(0-7, 0&7=Sun)
func parseCronExpr(expr string) (fields [5]cronField, err error) {
	parts := strings.Fields(expr)
	if len(parts) != 5 {
		return fields, fmt.Errorf("cron expr must have 5 fields, got %d: %q", len(parts), expr)
	}

	ranges := [5][2]int{
		{0, 59}, // minute
		{0, 23}, // hour
		{1, 31}, // day-of-month
		{1, 12}, // month
		{0, 7},  // day-of-week
	}

	for i, part := range parts {
		f, parseErr := parseCronField(part, ranges[i][0], ranges[i][1])
		if parseErr != nil {
			return fields, fmt.Errorf("field %d: %w", i, parseErr)
		}
		fields[i] = f
	}
	return fields, nil
}

// isCronDue checks if a cron expression should trigger now, given the last trigger time.
// Returns true if the current time matches the expression AND we haven't already triggered
// in this minute window (avoids duplicate triggers).
func isCronDue(expr string, lastTriggered *time.Time, now time.Time) bool {
	fields, err := parseCronExpr(expr)
	if err != nil {
		slog.Warn("cron parse error", "expr", expr, "err", err)
		return false
	}

	// Check all 5 fields match
	if !fieldMatches(fields[0], now.Minute()) {
		return false
	}
	if !fieldMatches(fields[1], now.Hour()) {
		return false
	}
	if !fieldMatches(fields[2], now.Day()) {
		return false
	}
	if !fieldMatches(fields[3], int(now.Month())) {
		return false
	}
	// Day of week: cron uses 0=Sun, Go uses 0=Sun
	dow := int(now.Weekday())
	if !fieldMatches(fields[4], dow) && !(dow == 0 && fieldMatches(fields[4], 7)) {
		return false
	}

	// Deduplicate: if we already triggered within this minute, skip
	if lastTriggered != nil {
		lastUTC := lastTriggered.UTC()
		nowUTC := now.UTC()
		if lastUTC.Year() == nowUTC.Year() &&
			lastUTC.Month() == nowUTC.Month() &&
			lastUTC.Day() == nowUTC.Day() &&
			lastUTC.Hour() == nowUTC.Hour() &&
			lastUTC.Minute() == nowUTC.Minute() {
			return false
		}
	}

	return true
}

// fieldMatches checks if a value matches a parsed cron field.
func fieldMatches(f cronField, val int) bool {
	if f.any {
		return true
	}
	return f.values[val]
}
