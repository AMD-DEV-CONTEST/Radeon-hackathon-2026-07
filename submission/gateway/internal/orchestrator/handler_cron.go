package orchestrator

import (
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"log/slog"
	"net/http"
	"time"
)

// ── Cron Schedule CRUD Handlers ──────────────────────────────────

// CreateCronSchedule handles POST /cron-schedules
func CreateCronSchedule(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name         string          `json:"name"`
		Description  string          `json:"description"`
		CronExpr     string          `json:"cron_expr"`
		TaskTemplate json.RawMessage `json:"task_template"`
		Enabled      *bool           `json:"enabled"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid json"}`, http.StatusBadRequest)
		return
	}
	if req.Name == "" || req.CronExpr == "" {
		http.Error(w, `{"error":"name and cron_expr are required"}`, http.StatusBadRequest)
		return
	}

	// Validate cron expression by parsing it
	if _, err := parseCronExpr(req.CronExpr); err != nil {
		http.Error(w, `{"error":"invalid cron expression: `+err.Error()+`"}`, http.StatusBadRequest)
		return
	}

	enabled := true
	if req.Enabled != nil {
		enabled = *req.Enabled
	}

	tmplBytes := []byte("{}")
	if len(req.TaskTemplate) > 0 {
		tmplBytes = []byte(req.TaskTemplate)
	}

	var id string
	var createdAt time.Time
	err := pool.QueryRow(r.Context(),
		`INSERT INTO cron_schedules (name, description, cron_expr, task_template, enabled, created_by)
		 VALUES ($1, $2, $3, $4, $5, 'api')
		 RETURNING id, created_at`,
		req.Name, req.Description, req.CronExpr, tmplBytes, enabled).Scan(&id, &createdAt)
	if err != nil {
		slog.Error("create cron_schedule", "err", err)
		http.Error(w, `{"error":"failed to create schedule"}`, http.StatusInternalServerError)
		return
	}

	writeJSON(w, map[string]any{
		"id":         id,
		"name":       req.Name,
		"created_at": createdAt.Format(time.RFC3339),
	})
}

// ListCronSchedules handles GET /cron-schedules
func ListCronSchedules(w http.ResponseWriter, r *http.Request) {
	rows, err := pool.Query(r.Context(),
		`SELECT id, name, description, cron_expr, task_template, enabled,
		        last_triggered_at, created_by, created_at, updated_at
		 FROM cron_schedules ORDER BY created_at`)
	if err != nil {
		slog.Error("list cron_schedules", "err", err)
		http.Error(w, `{"error":"query failed"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	type cronScheduleRow struct {
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

	var schedules []cronScheduleRow
	for rows.Next() {
		var s cronScheduleRow
		if err := rows.Scan(&s.ID, &s.Name, &s.Description, &s.CronExpr,
			&s.TaskTemplate, &s.Enabled, &s.LastTriggeredAt,
			&s.CreatedBy, &s.CreatedAt, &s.UpdatedAt); err != nil {
			slog.Warn("cron schedule scan", "err", err)
			continue
		}
		schedules = append(schedules, s)
	}
	if schedules == nil {
		schedules = []cronScheduleRow{}
	}

	writeJSON(w, map[string]any{"schedules": schedules})
}

// GetCronSchedule handles GET /cron-schedules/{id}
func GetCronSchedule(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	var s struct {
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

	err := pool.QueryRow(r.Context(),
		`SELECT id, name, description, cron_expr, task_template, enabled,
		        last_triggered_at, created_by, created_at, updated_at
		 FROM cron_schedules WHERE id = $1`, id).Scan(
		&s.ID, &s.Name, &s.Description, &s.CronExpr,
		&s.TaskTemplate, &s.Enabled, &s.LastTriggeredAt,
		&s.CreatedBy, &s.CreatedAt, &s.UpdatedAt)
	if err != nil {
		http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
		return
	}

	writeJSON(w, s)
}

// DeleteCronSchedule handles DELETE /cron-schedules/{id}
func DeleteCronSchedule(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	tag, err := pool.Exec(r.Context(),
		`DELETE FROM cron_schedules WHERE id = $1`, id)
	if err != nil {
		http.Error(w, `{"error":"delete failed"}`, http.StatusInternalServerError)
		return
	}
	if tag.RowsAffected() == 0 {
		http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
		return
	}

	writeJSON(w, map[string]string{"status": "deleted"})
}

// ListCronEvents handles GET /cron-events
// Returns audit trail of cron-triggered dispatches.
func ListCronEvents(w http.ResponseWriter, r *http.Request) {
	scheduleID := r.URL.Query().Get("schedule_id")
	limit := 50

	type cronEvent struct {
		ID           string    `json:"id"`
		ScheduleID   string    `json:"schedule_id"`
		ScheduleName string    `json:"schedule_name"`
		CronExpr     string    `json:"cron_expr"`
		TaskID       *string   `json:"task_id,omitempty"`
		Status       string    `json:"status"`
		Message      string    `json:"message"`
		TriggeredAt  time.Time `json:"triggered_at"`
	}

	var events []cronEvent

	var rows pgx.Rows
	var err error

	if scheduleID != "" {
		rows, err = pool.Query(r.Context(),
			`SELECT id, schedule_id, schedule_name, cron_expr, task_id, status, message, triggered_at
			 FROM cron_events WHERE schedule_id = $1
			 ORDER BY triggered_at DESC LIMIT $2`, scheduleID, limit)
	} else {
		rows, err = pool.Query(r.Context(),
			`SELECT id, schedule_id, schedule_name, cron_expr, task_id, status, message, triggered_at
			 FROM cron_events ORDER BY triggered_at DESC LIMIT $1`, limit)
	}

	if err != nil {
		slog.Error("list cron_events", "err", err)
		http.Error(w, `{"error":"query failed"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	for rows.Next() {
		var e cronEvent
		if err := rows.Scan(&e.ID, &e.ScheduleID, &e.ScheduleName, &e.CronExpr,
			&e.TaskID, &e.Status, &e.Message, &e.TriggeredAt); err != nil {
			continue
		}
		events = append(events, e)
	}
	if events == nil {
		events = []cronEvent{}
	}

	writeJSON(w, map[string]any{"events": events})
}
