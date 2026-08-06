package models

import (
	"encoding/json"
	"time"
)

// EventLevel represents the severity of an event.
type EventLevel string

const (
	LevelDebug EventLevel = "debug"
	LevelInfo  EventLevel = "info"
	LevelWarn  EventLevel = "warn"
	LevelError EventLevel = "error"
)

// Event records an auditable action in the system.
type Event struct {
	ID        string          `json:"id"`
	TaskID    *string         `json:"task_id,omitempty"`
	AttemptID *string         `json:"attempt_id,omitempty"`
	AgentID   *string         `json:"agent_id,omitempty"`
	EventType string          `json:"event_type"`
	Message   string          `json:"message"`
	Level     EventLevel      `json:"level"`
	Payload   json.RawMessage `json:"payload,omitempty"`
	CreatedAt time.Time       `json:"created_at"`
}
