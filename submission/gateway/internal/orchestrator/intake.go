package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/konspace/unionagents-go/internal/ironlaw"
)

// ── shared db ref ──────────────────────────────────────────────────────────

var pool *pgxpool.Pool

// SetPool must be called once during startup.
func SetPool(p *pgxpool.Pool) { pool = p }

// defaultLeaseDuration returns the configured task lease duration.
// Set TASK_LEASE_SECONDS env var to override (default: 600).
func defaultLeaseDuration() time.Duration {
	if s := os.Getenv("TASK_LEASE_SECONDS"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			return time.Duration(n) * time.Second
		}
	}
	return 600 * time.Second
}

// gatewayURL returns the gateway base URL for HTTP dispatch calls.
func gatewayURL() string {
	if u := os.Getenv("GATEWAY_URL"); u != "" {
		return u
	}
	return "http://127.0.0.1:8001"
}

// ── HTTP handlers ──────────────────────────────────────────────────────────

type CreateTaskRequest struct {
	Title                string                 `json:"title"`
	Description          string                 `json:"description"`
	TaskType             string                 `json:"task_type"`
	Priority             int                    `json:"priority"`
	Payload              map[string]interface{} `json:"payload,omitempty"`
	AcceptanceCheck      map[string]interface{} `json:"acceptance_check,omitempty"`
	RequiredCapabilities map[string]interface{} `json:"required_capabilities,omitempty"`
	TargetAgentID        *string                `json:"target_agent_id,omitempty"`
	CreatedBy            string                 `json:"created_by,omitempty"`
	MaxAttempts          int                    `json:"max_attempts,omitempty"`
}

type CreateTaskResponse struct {
	TaskID   string   `json:"task_id"`
	Status   string   `json:"status"`
	Warnings []string `json:"warnings,omitempty"`
}

type ILSGateError struct {
	Rule        int    `json:"rule"`
	Message     string `json:"message"`
	AutoFixable bool   `json:"auto_fixable"`
}

type CompleteTaskRequest struct {
	AgentID          string  `json:"agent_id"`
	Status           string  `json:"status"`
	ExitCode         *int    `json:"exit_code,omitempty"`
	ErrorType        *string `json:"error_type,omitempty"`
	ErrorMessage     *string `json:"error_message,omitempty"`
	Summary          *string `json:"summary,omitempty"`
	AcceptanceResult string  `json:"acceptance_result,omitempty"`
	// PartialResult is the predecessor agent's partial output, submitted
	// on a failed/timed-out attempt so the agent that takes over via
	// handoff (Phase 2.5) can pick up where it left off. Written to
	// tasks.partial_result only when Status indicates failure/timeout.
	PartialResult json.RawMessage `json:"partial_result,omitempty"`
}

// GetTask handles GET /tasks/{taskID} — returns task status + latest attempt summary.
// This endpoint is consumed by Cockpit's HTTP poll fallback (fetch_task_status).
func GetTask(w http.ResponseWriter, r *http.Request) {
	taskID := r.PathValue("taskID")
	if taskID == "" {
		http.Error(w, `{"error":"taskID is required"}`, http.StatusBadRequest)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	var task struct {
		ID            string
		Title         string
		Description   string
		TaskType      string
		Status        string
		Priority      int
		CreatedBy     string
		LeaseOwner    *string
		TargetAgentID *string
		CreatedAt     time.Time
		UpdatedAt     time.Time
		FinishedAt    *time.Time
	}

	err := pool.QueryRow(ctx, `
		SELECT id, title, description, task_type, status, priority,
			created_by, lease_owner, target_agent_id,
			created_at, updated_at, finished_at
		FROM tasks WHERE id = $1`, taskID).
		Scan(&task.ID, &task.Title, &task.Description, &task.TaskType,
			&task.Status, &task.Priority, &task.CreatedBy,
			&task.LeaseOwner, &task.TargetAgentID,
			&task.CreatedAt, &task.UpdatedAt, &task.FinishedAt)
	if err != nil {
		http.Error(w, `{"error":"task not found"}`, http.StatusNotFound)
		return
	}

	// Fetch latest attempt summary/error
	var summary, errorMessage *string
	var exitCode *int
	pool.QueryRow(ctx, `
		SELECT summary, error_message, exit_code
		FROM task_attempts
		WHERE task_id = $1
		ORDER BY attempt_no DESC LIMIT 1`, taskID).
		Scan(&summary, &errorMessage, &exitCode)

	resp := map[string]interface{}{
		"task_id":    task.ID,
		"title":      task.Title,
		"status":     task.Status,
		"created_by": task.CreatedBy,
		"created_at": task.CreatedAt.Format(time.RFC3339),
		"updated_at": task.UpdatedAt.Format(time.RFC3339),
	}
	if task.FinishedAt != nil {
		resp["finished_at"] = task.FinishedAt.Format(time.RFC3339)
	}
	if summary != nil {
		resp["summary"] = *summary
	}
	if errorMessage != nil {
		resp["error_message"] = *errorMessage
	}
	if exitCode != nil {
		resp["exit_code"] = *exitCode
	}
	if task.LeaseOwner != nil {
		resp["lease_owner"] = *task.LeaseOwner
	}
	if task.TargetAgentID != nil {
		resp["target_agent_id"] = *task.TargetAgentID
	}

	w.Header().Set("Content-Type", "application/json")
	writeJSON(w, resp)
}

// CreateTask handles POST /tasks — ILS validation + DB insert.
func CreateTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req CreateTaskRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if req.Title == "" {
		http.Error(w, `{"error":"title is required"}`, http.StatusBadRequest)
		return
	}

	taskMap := map[string]interface{}{
		"title":                 req.Title,
		"description":           req.Description,
		"task_type":             req.TaskType,
		"payload":               req.Payload,
		"acceptance_check":      req.AcceptanceCheck,
		"required_capabilities": req.RequiredCapabilities,
	}

	// ILS gate validation
	warnings, err := ironlaw.ValidateTaskBeforeDispatch(taskMap)
	if err != nil {
		v, ok := err.(*ironlaw.RuleViolation)
		if !ok {
			http.Error(w, fmt.Sprintf(`{"error":"ILS_GATE: %s"}`, err.Error()), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnprocessableEntity)
		writeJSON(w, map[string]interface{}{
			"error": "ILS_GATE", "rule": v.Rule, "message": v.Message, "auto_fixable": v.AutoFixable,
		})
		return
	}
	for _, w := range warnings {
		slog.Warn("ils_warning", "msg", w)
	}

	// Defaults
	if req.Priority <= 0 {
		req.Priority = 50
	}
	if req.MaxAttempts <= 0 {
		req.MaxAttempts = 3
	}
	if req.CreatedBy == "" {
		req.CreatedBy = "api"
	}

	// DB insert
	now := time.Now().UTC()
	payloadJSON, err := json.Marshal(req.Payload)
	if err != nil {
		slog.Error("marshal payload", "err", err)
		http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
		return
	}
	acceptJSON, err := json.Marshal(req.AcceptanceCheck)
	if err != nil {
		slog.Error("marshal acceptance_check", "err", err)
		http.Error(w, `{"error":"invalid acceptance_check"}`, http.StatusBadRequest)
		return
	}
	capsJSON, err := json.Marshal(req.RequiredCapabilities)
	if err != nil {
		slog.Error("marshal required_capabilities", "err", err)
		http.Error(w, `{"error":"invalid required_capabilities"}`, http.StatusBadRequest)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	var taskID string
	err = pool.QueryRow(ctx, `
		INSERT INTO tasks (title, description, task_type, status, priority,
			max_attempts, created_by, target_agent_id, payload,
			acceptance_check, required_capabilities, created_at, updated_at)
		VALUES ($1,$2,$3,'queued',$4,$5,$6,$7,$8,$9,$10,$11,$12)
		RETURNING id`,
		req.Title, req.Description, req.TaskType, req.Priority,
		req.MaxAttempts, req.CreatedBy, req.TargetAgentID, payloadJSON,
		acceptJSON, capsJSON, now, now,
	).Scan(&taskID)
	if err != nil {
		slog.Error("CreateTask db insert", "err", err)
		http.Error(w, fmt.Sprintf(`{"error":"%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}

	slog.Info("task created", "id", taskID, "title", req.Title)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	writeJSON(w, CreateTaskResponse{
		TaskID:   taskID,
		Status:   "queued",
		Warnings: warnings,
	})
}

// CompleteTask handles POST /tasks/{taskID}/complete — marks task done + next_tasks chain.
func CompleteTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	taskID := r.PathValue("taskID")
	if taskID == "" {
		http.Error(w, `{"error":"taskID is required"}`, http.StatusBadRequest)
		return
	}

	var req CompleteTaskRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if req.Status == "" {
		req.Status = "done"
	}

	// ILS-R014: permanent errors must not be retried — route directly to needs_review (CM-UAS-010/016)
	if req.ErrorType != nil && *req.ErrorType == "permanent" {
		req.Status = "needs_review"
	}

	now := time.Now().UTC()
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	// P2-11: idempotency — skip if already in terminal state
	var currentStatus string
	if err := pool.QueryRow(ctx, `SELECT status FROM tasks WHERE id = $1`, taskID).Scan(&currentStatus); err != nil {
		slog.Error("CompleteTask lookup", "err", err)
		http.Error(w, `{"error":"task not found"}`, http.StatusNotFound)
		return
	}
	if currentStatus == "done" || currentStatus == "failed_final" || currentStatus == "archived" || currentStatus == "cancelled" {
		slog.Warn("CompleteTask idempotent skip", "task", taskID, "current", currentStatus)
		writeJSON(w, map[string]interface{}{
			"status":   currentStatus,
			"task_id":  taskID,
			"skipped":  true,
			"reason":   "task already in terminal state",
		})
		return
	}

	// Begin transaction for atomicity
	tx, err := pool.Begin(ctx)
	if err != nil {
		slog.Error("CompleteTask begin tx", "err", err)
		http.Error(w, fmt.Sprintf(`{"error":"db error: %s"}`, err.Error()), http.StatusInternalServerError)
		return
	}
	defer tx.Rollback(ctx)

	// Mark task as completed
	_, err = tx.Exec(ctx, `
		UPDATE tasks SET status = $1, finished_at = $2, updated_at = $2
		WHERE id = $3`, req.Status, now, taskID)
	if err != nil {
		slog.Error("CompleteTask update", "err", err)
		http.Error(w, fmt.Sprintf(`{"error":"db update error: %s"}`, err.Error()), http.StatusInternalServerError)
		return
	}

	// Phase 2.5: on a failure/timeout, persist the agent's partial output
	// so a handoff successor can read it via PollTask. Successful (done)
	// completions carry their result in summary; partial_result is only
	// for the "didn't finish but here's what I got" case.
	if len(req.PartialResult) > 0 && isFailureStatus(req.Status) {
		if _, err := tx.Exec(ctx, `
			UPDATE tasks SET partial_result = $1, updated_at = $2 WHERE id = $3`,
			req.PartialResult, now, taskID); err != nil {
			slog.Error("CompleteTask partial_result update", "task", taskID, "err", err)
			// Non-fatal: the status change already landed.
		}
	}

	// Update latest attempt
	_, err = tx.Exec(ctx, `
		UPDATE task_attempts SET status = $1, exit_code = $2, error_type = $3,
			error_message = $4, summary = $5, finished_at = $6, updated_at = $6
		WHERE ctid = (
			SELECT ctid FROM task_attempts
			WHERE task_id = $7 AND status IN ('leased','running')
			ORDER BY attempt_no DESC LIMIT 1
		)`,
		req.Status, req.ExitCode, req.ErrorType, req.ErrorMessage, req.Summary, now, taskID)
	if err != nil {
		slog.Error("CompleteTask attempt update", "err", err)
		// Continue — the attempt update is non-critical
	}

	// Log main event
	evtPayload, _ := json.Marshal(map[string]interface{}{
		"completed_at": now.Format(time.RFC3339),
		"status":       req.Status,
	})
	_, err = tx.Exec(ctx, `
		INSERT INTO events (task_id, event_type, message, level, payload)
		VALUES ($1, $2, $3, 'info', $4)`,
		taskID, "task."+req.Status, fmt.Sprintf("Task completed with status %s", req.Status), evtPayload)
	if err != nil {
		slog.Error("CompleteTask event insert", "err", err)
		// Continue — the event log is non-critical
	}

	// ── NEXT_TASKS chain dispatch ─────────────────────────────────────────
	// If the completed task's payload contains "next_tasks", create them.
	var payloadJSON []byte
	err = tx.QueryRow(ctx, `SELECT payload FROM tasks WHERE id = $1`, taskID).Scan(&payloadJSON)
	if err == nil && len(payloadJSON) > 0 {
		var p map[string]interface{}
		if json.Unmarshal(payloadJSON, &p) == nil {
			if nextTasksRaw, ok := p["next_tasks"]; ok {
				nextTasks, _ := json.Marshal(nextTasksRaw)
				var chain []map[string]interface{}
				if json.Unmarshal(nextTasks, &chain) == nil {
					chainsCreated := 0
					for _, ct := range chain {
						title, _ := ct["title"].(string)
						desc, _ := ct["description"].(string)
						taskType, _ := ct["task_type"].(string)
						if taskType == "" {
							taskType = "coding"
						}
						priority := 50
						if p, ok := ct["priority"].(float64); ok {
							priority = int(p)
						}
						var targetAgentID *string
						if t, ok := ct["target_agent_id"].(string); ok && t != "" {
							targetAgentID = &t
						}
						childPayload, _ := json.Marshal(ct)

						var childID string
						err := tx.QueryRow(ctx, `
							INSERT INTO tasks (parent_task_id, title, description, task_type, status, priority,
								max_attempts, created_by, target_agent_id, payload, created_at, updated_at)
							VALUES ($1,$2,$3,$4,'queued',$5,3,'chain',$6,$7,$8,$8)
							RETURNING id`,
							taskID, title, desc, taskType, priority, targetAgentID, childPayload, now,
						).Scan(&childID)
						if err != nil {
							slog.Error("next_tasks chain insert", "title", title, "err", err)
							continue
						}
						chainsCreated++

						// Log chain event
						childEvt, _ := json.Marshal(map[string]interface{}{
							"parent_task_id": taskID,
							"child_task_id":  childID,
							"created_at":     now.Format(time.RFC3339),
						})
						tx.Exec(ctx, `
							INSERT INTO events (task_id, event_type, message, level, payload)
							VALUES ($1, 'task.next_dispatched', $2, 'info', $3)`,
							taskID,
							fmt.Sprintf("Chain task %s created from parent %s", childID, taskID),
							childEvt,
						)
						slog.Info("next_tasks created child", "child_id", childID, "parent", taskID, "title", title)
					}
					if chainsCreated > 0 {
						slog.Info("next_tasks chain done", "count", chainsCreated, "parent", taskID)
					}
				}
			}
		}
	}

	// Commit transaction
	if err := tx.Commit(ctx); err != nil {
		slog.Error("CompleteTask commit", "err", err)
		http.Error(w, fmt.Sprintf(`{"error":"db commit error: %s"}`, err.Error()), http.StatusInternalServerError)
		return
	}

	slog.Info("task completed", "id", taskID, "status", req.Status)

	// Phase 3.3: persist a life-memory node for completed tasks that
	// carry a summary. Best-effort — fireTaskDone no-ops when no memory
	// store is wired, and the hook swallows its own errors.
	if req.Status == "done" && req.Summary != nil && *req.Summary != "" {
		fireTaskDone(taskID, "", *req.Summary)
	}

	// Broadcast task completion to Gateway for client notification
	go broadcastToGateway("task:complete", taskID, map[string]interface{}{
		"status":  req.Status,
		"result":  req.Summary,
		"error":   req.ErrorMessage,
		"exit_code": req.ExitCode,
	})

	// If chat task, also broadcast chat:reply so OB/Cockpit shows the response
	go func() {
		var taskType, leaseOwnerStr string
		var leaseOwnerNull *string
		err := pool.QueryRow(context.Background(),
			`SELECT COALESCE(task_type,''), lease_owner FROM tasks WHERE id = $1`, taskID,
		).Scan(&taskType, &leaseOwnerNull)
		if err != nil {
			slog.Warn("chat:reply lookup failed", "task", taskID, "err", err)
			return
		}
		if leaseOwnerNull != nil {
			leaseOwnerStr = *leaseOwnerNull
		}
		slog.Info("chat:reply check", "task", taskID, "taskType", taskType, "hasSummary", req.Summary != nil, "leaseOwner", leaseOwnerStr)
		if taskType == "chat" && req.Summary != nil && *req.Summary != "" && leaseOwnerStr != "" {
			var agentName string
			pool.QueryRow(context.Background(),
				`SELECT COALESCE(name,'') FROM agents WHERE id = $1`, leaseOwnerStr,
			).Scan(&agentName)
			if agentName == "" {
				agentName = leaseOwnerStr
			}
			slog.Info("chat:reply broadcasting", "from", agentName, "contentLen", len(*req.Summary))
			go broadcastToGateway("chat:reply", taskID, map[string]interface{}{
				"from_agent": agentName,
				"content":    *req.Summary,
				"subtype":    "task_summary",
			})
		}
	}()

	// Circuit breaker: record success or failure for the agent
	// Get the lease owner (agent_id) from the task
	var leaseOwner string
	pool.QueryRow(ctx, `SELECT COALESCE(lease_owner,'') FROM tasks WHERE id = $1`, taskID).Scan(&leaseOwner)
	if leaseOwner != "" {
		if req.Status == "done" || req.Status == "needs_review" {
			RecordTaskSuccess(context.Background(), pool, leaseOwner)
		} else if req.Status == "failed" || req.Status == "failed_final" {
			RecordTaskFailure(context.Background(), pool, leaseOwner)
		}
	}

	writeJSON(w, map[string]interface{}{
		"status":       req.Status,
		"task_id":      taskID,
		"completed_at": now.Format(time.RFC3339),
	})
}

// ExtendTaskLease handles POST /tasks/{taskID}/extend-lease
// Agents running long tasks call this to prevent scanner from killing the lease.
func ExtendTaskLease(w http.ResponseWriter, r *http.Request) {
	taskID := r.PathValue("taskID")
	if taskID == "" {
		writeError(w, http.StatusBadRequest, "taskID is required")
		return
	}

	var req struct {
		AgentID       string `json:"agent_id"`
		ExtendSeconds int    `json:"extend_seconds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid body")
		return
	}
	if req.AgentID == "" {
		writeError(w, http.StatusBadRequest, "agent_id is required")
		return
	}
	if req.ExtendSeconds <= 0 {
		req.ExtendSeconds = int(defaultLeaseDuration().Seconds())
	}
	if req.ExtendSeconds > 3600 {
		req.ExtendSeconds = 3600 // cap at 1 hour
	}

	now := time.Now().UTC()
	newExpiry := now.Add(time.Duration(req.ExtendSeconds) * time.Second)

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	tag, err := pool.Exec(ctx, `
		UPDATE tasks SET lease_expires_at = $1, updated_at = $2
		WHERE id = $3 AND lease_owner = $4
		  AND status IN ('leased', 'running')`,
		newExpiry, now, taskID, req.AgentID)
	if err != nil {
		slog.Error("ExtendTaskLease update", "task", taskID, "err", err)
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if tag.RowsAffected() == 0 {
		writeError(w, http.StatusConflict, "task not found, not leased by this agent, or already terminal")
		return
	}

	pool.Exec(ctx, `
		UPDATE task_attempts SET heartbeat_at = $1, updated_at = $1
		WHERE task_id = $2 AND status IN ('leased', 'running')`,
		now, taskID)

	slog.Info("lease extended", "task", taskID, "agent", req.AgentID, "new_expiry", newExpiry.Format(time.RFC3339))
	w.Header().Set("Content-Type", "application/json")
	writeJSON(w, map[string]interface{}{
		"task_id":         taskID,
		"lease_expires_at": newExpiry.Format(time.RFC3339),
		"extended_seconds": req.ExtendSeconds,
	})
}

// TaskHeartbeat handles POST /tasks/{taskID}/heartbeat.
// Updates heartbeat_at and silently extends the lease by 120s (backward-compat with Python workers).
func TaskHeartbeat(w http.ResponseWriter, r *http.Request) {
	taskID := r.PathValue("taskID")
	if taskID == "" {
		writeError(w, http.StatusBadRequest, "taskID is required")
		return
	}
	var req struct {
		AgentID string `json:"agent_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.AgentID == "" {
		writeError(w, http.StatusBadRequest, "agent_id is required")
		return
	}

	now := time.Now().UTC()
	newExpiry := now.Add(120 * time.Second)
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	pool.Exec(ctx, `
		UPDATE task_attempts SET heartbeat_at = $1, updated_at = $1
		WHERE task_id = $2 AND status IN ('leased', 'running')`,
		now, taskID)

	pool.Exec(ctx, `
		UPDATE tasks SET lease_expires_at = GREATEST(lease_expires_at, $1), updated_at = $2
		WHERE id = $3 AND lease_owner = $4
		  AND status IN ('leased', 'running')`,
		newExpiry, now, taskID, req.AgentID)

	w.Header().Set("Content-Type", "application/json")
	writeJSON(w, map[string]string{"status": "ok"})
}

// PollTask handles POST /tasks/poll — atomic CTE lease.
func PollTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		AgentID string `json:"agent_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid body"}`, http.StatusBadRequest)
		return
	}
	if req.AgentID == "" {
		http.Error(w, `{"error":"agent_id is required"}`, http.StatusBadRequest)
		return
	}

	now := time.Now().UTC()
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	// Circuit breaker check — don't dispatch to unhealthy/dead agents
	if ok, reason := ShouldDispatchTask(ctx, pool, req.AgentID); !ok {
		slog.Warn("poll blocked by circuit breaker", "agent", req.AgentID, "reason", reason)
		writeJSON(w, map[string]interface{}{"task": nil, "blocked": true, "reason": reason})
		return
	}

	// Mark agent poll activity
	pool.Exec(ctx, `UPDATE agents SET last_poll_at = $1, updated_at = $1 WHERE id = $2`, now, req.AgentID)

	leaseExpires := now.Add(defaultLeaseDuration())

	// CTE: pick next queued task, atomically lease it
	var task struct {
		ID                   string
		Title                string
		Description          string
		TaskType             string
		Status               string
		Priority             int
		MaxAttempts          int
		CreatedBy            string
		TargetAgentID        *string
		Payload              []byte
		RequiredCapabilities []byte
		LeaseOwner           *string
		LeaseExpiresAt       *time.Time
		CreatedAt            time.Time
		UpdatedAt            time.Time
		// Phase 2.5 handoff context: present when this task was handed
		// off from a previous agent after a timeout. handoff_from_agent
		// is the predecessor; partial_result is its unfinished output.
		HandoffFromAgent *string
		PartialResult    []byte
	}

	err := pool.QueryRow(ctx, `
		WITH next_task AS (
			SELECT id FROM tasks
			WHERE status = 'queued'
			  AND (target_agent_id IS NULL OR target_agent_id = $1)
			  AND (blocked_until IS NULL OR blocked_until < $2)
			ORDER BY priority DESC, created_at
			LIMIT 1
			FOR UPDATE SKIP LOCKED
		)
		UPDATE tasks SET
			status = 'leased',
			lease_owner = $1,
			lease_expires_at = $3,
			updated_at = $2
		FROM next_task
		WHERE tasks.id = next_task.id
		RETURNING tasks.id, tasks.title, tasks.description, tasks.task_type,
			tasks.status, tasks.priority, tasks.max_attempts, tasks.created_by,
			tasks.target_agent_id, tasks.payload, tasks.required_capabilities,
			tasks.lease_owner, tasks.lease_expires_at, tasks.created_at, tasks.updated_at,
			tasks.handoff_from_agent, tasks.partial_result`,
		req.AgentID, now, leaseExpires,
	).Scan(
		&task.ID, &task.Title, &task.Description, &task.TaskType,
		&task.Status, &task.Priority, &task.MaxAttempts, &task.CreatedBy,
		&task.TargetAgentID, &task.Payload, &task.RequiredCapabilities,
		&task.LeaseOwner, &task.LeaseExpiresAt, &task.CreatedAt, &task.UpdatedAt,
		&task.HandoffFromAgent, &task.PartialResult,
	)
	if err != nil {
		// No task available — normal
		writeJSON(w, map[string]interface{}{"task": nil})
		return
	}

	// Record attempt
	var attemptNo int
	pool.QueryRow(ctx,
		`SELECT COALESCE(MAX(attempt_no),0)+1 FROM task_attempts WHERE task_id=$1`, task.ID).Scan(&attemptNo)
	pool.Exec(ctx, `
		INSERT INTO task_attempts (task_id, attempt_no, agent_id, lease_expires_at, status, created_at, updated_at)
		VALUES ($1,$2,$3,$4,'leased',$5,$5)`,
		task.ID, attemptNo, req.AgentID, leaseExpires, now)

	slog.Info("task leased", "id", task.ID, "agent", req.AgentID, "attempt", attemptNo)

	// Broadcast task dispatch to Gateway for real-time agents
	var payload map[string]interface{}
	if err := json.Unmarshal(task.Payload, &payload); err != nil {
		payload = map[string]interface{}{}
	}
	go broadcastToGateway("task:dispatch", task.ID, map[string]interface{}{
		"agent_id": req.AgentID,
		"title":    task.Title,
		"description": task.Description,
		"task_type": task.TaskType,
		"payload": payload,
	})

	resp := map[string]interface{}{
		"id":             task.ID,
		"title":          task.Title,
		"description":    task.Description,
		"task_type":      task.TaskType,
		"status":         task.Status,
		"priority":       task.Priority,
		"max_attempts":   task.MaxAttempts,
		"created_by":     task.CreatedBy,
		"lease_owner":    task.LeaseOwner,
		"created_at":     task.CreatedAt.Format(time.RFC3339),
		"updated_at":     task.UpdatedAt.Format(time.RFC3339),
		"attempt_no":     attemptNo,
	}
	if task.TargetAgentID != nil {
		resp["target_agent_id"] = *task.TargetAgentID
	}
	if task.LeaseExpiresAt != nil {
		resp["lease_expires_at"] = task.LeaseExpiresAt.Format(time.RFC3339)
	}
	if task.Payload != nil {
		var p map[string]interface{}
		if json.Unmarshal(task.Payload, &p) == nil {
			resp["payload"] = p
		}
	}
	// Phase 2.5: surface handoff context so the picking-up agent knows
	// this task was previously worked on and can resume from partial_result.
	if task.HandoffFromAgent != nil && *task.HandoffFromAgent != "" {
		resp["handoff_from_agent"] = *task.HandoffFromAgent
	}
	if len(task.PartialResult) > 0 {
		var pr interface{}
		if json.Unmarshal(task.PartialResult, &pr) == nil {
			resp["partial_result"] = pr
		}
	}

	writeJSON(w, map[string]interface{}{"task": resp})
}

// Heartbeat handles POST /agents/{agentID}/heartbeat
func Heartbeat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	agentID := r.PathValue("agentID")
	if agentID == "" {
		http.Error(w, `{"error":"agentID is required"}`, http.StatusBadRequest)
		return
	}

	now := time.Now().UTC()
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	_, err := pool.Exec(ctx,
		`UPDATE agents SET last_heartbeat_at = $1, status = 'online', updated_at = $1 WHERE id = $2`,
		now, agentID)
	if err != nil {
		slog.Error("heartbeat update", "agent", agentID, "err", err)
		http.Error(w, `{"error":"db error"}`, http.StatusInternalServerError)
		return
	}

	writeJSON(w, map[string]string{"status": "online"})
}

// randomHex generates a pseudorandom hex string (for placeholder IDs).
func randomHex(n int) string {
	const letters = "0123456789abcdef"
	b := make([]byte, n)
	for i := range b {
		b[i] = letters[i%len(letters)]
	}
	return string(b)
}

// TaskStats handles GET /tasks/stats — returns count by status.
func TaskStats(w http.ResponseWriter, r *http.Request) {
	if pool == nil {
		http.Error(w, `{"error":"db not initialized"}`, http.StatusServiceUnavailable)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	rows, err := pool.Query(ctx, `SELECT status, count(*) FROM tasks GROUP BY status`)
	if err != nil {
		slog.Error("task stats query", "err", err)
		http.Error(w, `{"error":"db error"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	byStatus := make(map[string]int)
	total := 0
	for rows.Next() {
		var status string
		var count int
		if err := rows.Scan(&status, &count); err != nil {
			continue
		}
		byStatus[status] = count
		total += count
	}
	byStatus["total"] = total

	writeJSON(w, map[string]interface{}{
		"stats": byStatus,
	})
}

func writeJSON(w http.ResponseWriter, v interface{}) {
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Warn("writeJSON encode", "err", err)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	writeJSON(w, map[string]string{"error": msg})
}

// broadcastToGateway sends task events to Gateway WSS for client notification.
func broadcastToGateway(eventType string, taskID string, data map[string]interface{}) {
	gwURL := os.Getenv("GATEWAY_URL")
	if gwURL == "" {
		gwURL = "http://127.0.0.1:8001"
	}
	// Use HTTP gateway endpoint (port 8001) not WSS
	if gwURL == "ws://127.0.0.1:3389" || gwURL == "wss://127.0.0.1:3389" {
		gwURL = "http://127.0.0.1:8001"
	}

	payload := map[string]interface{}{
		"type":    eventType,
		"task_id": taskID,
		"event_type": eventType,
	}
	for k, v := range data {
		payload[k] = v
	}

	body, _ := json.Marshal(payload)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, "POST", gwURL+"/broadcast", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	// Add a simple auth header for internal use
	req.Header.Set("X-Internal-Secret", "internal-broadcast")

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("broadcast to gateway failed", "event", eventType, "task", taskID, "err", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusAccepted && resp.StatusCode != http.StatusUnauthorized {
		slog.Warn("broadcast to gateway non-ok", "event", eventType, "task", taskID, "status", resp.StatusCode)
	} else {
		slog.Info("broadcast to gateway", "event", eventType, "task", taskID, "status", resp.StatusCode)
	}
}

// ── /tasks/inject: gate-skipping dynamic task injection ────────────────────

// InjectRequest is the body of POST /tasks/inject. It is CreateTaskRequest
// plus two fields:
//
//   - PriorityLevel: semantic "high"/"medium"/"low" mapped to the DB int
//     priority column via PriorityToInt. Empty defaults to medium.
//   - Source: who injected this task — "api" (default), "scanner",
//     "chain", "recovery". Becomes tasks.created_by, which is how we
//     tell injected tasks apart from user-created ones at query time.
//
// Inject skips the ILS gate (ironlaw.ValidateTaskBeforeDispatch) that
// CreateTask runs. Rationale: inject is the internal/system channel —
// scanner re-dispatch, next_tasks chain creation, auto-recovery — where
// the task has already passed ILS or is system-generated. Re-running
// the gate there would reject legitimate internal work (e.g. a chain
// child with no context.goal, which ILS Rule 1 would block). Inject
// still classifies via ironlaw.ClassifyTask and stamps the category into
// payload.task_category, so routing stays correct.
type InjectRequest struct {
	Title                string                 `json:"title"`
	Description          string                 `json:"description"`
	TaskType             string                 `json:"task_type"`
	Payload              map[string]interface{} `json:"payload,omitempty"`
	AcceptanceCheck      map[string]interface{} `json:"acceptance_check,omitempty"`
	RequiredCapabilities map[string]interface{} `json:"required_capabilities,omitempty"`
	TargetAgentID        *string                `json:"target_agent_id,omitempty"`
	MaxAttempts          int                    `json:"max_attempts,omitempty"`
	PriorityLevel        string                 `json:"priority_level,omitempty"`
	Source               string                 `json:"source,omitempty"`
}

// prepareInject is the pure, DB-free core of /tasks/inject: it maps the
// semantic request fields to the values InjectTask will write to the DB.
// Pulled out so the "skip gate + classify + priority mapping" contract is
// unit-testable without a database.
//
// Returns (category, dbPriority, createdBy).
func prepareInject(req InjectRequest) (ironlaw.TaskCategory, int, string) {
	cat := ironlaw.ClassifyTask(req.TaskType, req.Title, req.Description)

	level := PriorityMedium
	switch strings.ToLower(strings.TrimSpace(req.PriorityLevel)) {
	case "high":
		level = PriorityHigh
	case "low":
		level = PriorityLow
	}
	dbPriority := PriorityToInt(level)

	createdBy := req.Source
	if createdBy == "" {
		createdBy = "api"
	}
	return cat, dbPriority, createdBy
}

// InjectTask handles POST /tasks/inject — gate-skipping dynamic task
// injection. See InjectRequest for the rationale and the contract vs
// CreateTask (POST /tasks).
func InjectTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req InjectRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}
	if req.Title == "" {
		http.Error(w, `{"error":"title is required"}`, http.StatusBadRequest)
		return
	}

	category, dbPriority, createdBy := prepareInject(req)

	if req.MaxAttempts <= 0 {
		req.MaxAttempts = 3
	}

	// Stamp the category into payload so downstream routing can read it
	// without re-classifying. We merge into whatever payload the caller
	// supplied rather than replacing it.
	if req.Payload == nil {
		req.Payload = map[string]interface{}{}
	}
	req.Payload["task_category"] = string(category)

	now := time.Now().UTC()
	payloadJSON, err := json.Marshal(req.Payload)
	if err != nil {
		slog.Error("inject marshal payload", "err", err)
		http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
		return
	}
	acceptJSON, _ := json.Marshal(req.AcceptanceCheck)
	capsJSON, _ := json.Marshal(req.RequiredCapabilities)

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	var taskID string
	err = pool.QueryRow(ctx, `
		INSERT INTO tasks (title, description, task_type, status, priority,
			max_attempts, created_by, target_agent_id, payload,
			acceptance_check, required_capabilities, created_at, updated_at)
		VALUES ($1,$2,$3,'queued',$4,$5,$6,$7,$8,$9,$10,$11,$11)
		RETURNING id`,
		req.Title, req.Description, req.TaskType, dbPriority,
		req.MaxAttempts, createdBy, req.TargetAgentID, payloadJSON,
		acceptJSON, capsJSON, now,
	).Scan(&taskID)
	if err != nil {
		slog.Error("inject db insert", "err", err, "source", createdBy)
		http.Error(w, fmt.Sprintf(`{"error":"%s"}`, err.Error()), http.StatusInternalServerError)
		return
	}

	slog.Info("task injected", "id", taskID, "title", req.Title, "source", createdBy, "category", category)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	writeJSON(w, map[string]interface{}{
		"task_id":  taskID,
		"status":   "queued",
		"category": string(category),
	})
}

// isFailureStatus reports whether a CompleteTask status means "did not
// succeed" — the case where the agent's partial_result is worth keeping
// for a handoff successor. "done" and idempotent re-completions are not
// failures. needs_review is included: it usually follows a permanent
// error and the reviewer benefits from the predecessor's partial work.
func isFailureStatus(status string) bool {
	switch status {
	case "failed", "failed_final", "failed_retryable",
		"timeout_silent", "needs_review":
		return true
	}
	return false
}
