package models

import (
	"encoding/json"
	"time"
)

// TaskStatus represents the lifecycle state of a task.
type TaskStatus string

const (
	StatusQueued        TaskStatus = "queued"
	StatusLeased        TaskStatus = "leased"
	StatusRunning       TaskStatus = "running"
	StatusDone          TaskStatus = "done"
	StatusFailedFinal   TaskStatus = "failed_final"
	StatusArchived      TaskStatus = "archived"
	StatusCancelled     TaskStatus = "cancelled"
	StatusNeedsReview   TaskStatus = "needs_review"
	StatusTimeoutSilent TaskStatus = "timeout_silent"
	StatusFailedRetryable TaskStatus = "failed_retryable"
	StatusBlockedRateLimit TaskStatus = "blocked_rate_limit"
)

// Task is the core unit of work in UnionAgents.
type Task struct {
	ID                   string           `json:"id"`
	Title                string           `json:"title"`
	Description          string           `json:"description"`
	TaskType             string           `json:"task_type"`
	Status               TaskStatus       `json:"status"`
	Priority             int              `json:"priority"`
	MaxAttempts          int              `json:"max_attempts"`
	TargetAgentID        *string          `json:"target_agent_id,omitempty"`
	LeaseOwner           *string          `json:"lease_owner,omitempty"`
	LeaseExpiresAt       *time.Time       `json:"lease_expires_at,omitempty"`
	CreatedBy            string           `json:"created_by"`
	Payload              json.RawMessage  `json:"payload,omitempty"`
	Dependencies         json.RawMessage  `json:"dependencies,omitempty"`
	AcceptanceCheck      json.RawMessage  `json:"acceptance_check,omitempty"`
	RequiredCapabilities json.RawMessage  `json:"required_capabilities,omitempty"`
	ParentTaskID         *string          `json:"parent_task_id,omitempty"`
	BlockedUntil         *time.Time       `json:"blocked_until,omitempty"`
	CreatedAt            time.Time        `json:"created_at"`
	UpdatedAt            time.Time        `json:"updated_at"`
	FinishedAt           *time.Time       `json:"finished_at,omitempty"`
}

// TaskAttempt records a single execution attempt for a task.
type TaskAttempt struct {
	ID             string     `json:"id"`
	TaskID         string     `json:"task_id"`
	AttemptNo      int        `json:"attempt_no"`
	AgentID        *string    `json:"agent_id,omitempty"`
	LeaseExpiresAt *time.Time `json:"lease_expires_at,omitempty"`
	HeartbeatAt    *time.Time `json:"heartbeat_at,omitempty"`
	StartedAt      *time.Time `json:"started_at,omitempty"`
	FinishedAt     *time.Time `json:"finished_at,omitempty"`
	Status         string     `json:"status"`
	ExitCode       *int       `json:"exit_code,omitempty"`
	ErrorType      *string    `json:"error_type,omitempty"`
	ErrorMessage   *string    `json:"error_message,omitempty"`
	BlockedUntil   *time.Time `json:"blocked_until,omitempty"`
	Summary        *string    `json:"summary,omitempty"`
	Metadata       json.RawMessage `json:"metadata,omitempty"`
	CreatedAt      time.Time  `json:"created_at"`
	UpdatedAt      time.Time  `json:"updated_at"`
}
