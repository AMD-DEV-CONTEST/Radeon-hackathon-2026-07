package models

import (
	"encoding/json"
	"time"
)

// AgentStatus represents the liveness of an agent.
type AgentStatus string

const (
	AgentOnline    AgentStatus = "online"
	AgentOffline   AgentStatus = "offline"
	AgentDegraded  AgentStatus = "degraded"
	AgentDraining  AgentStatus = "draining"
	AgentDisabled  AgentStatus = "disabled"
)

// Agent represents a worker connected to the orchestrator.
type Agent struct {
	ID               string          `json:"id"`
	Name             string          `json:"name"`
	AgentType        string          `json:"agent_type"`
	HostID           string          `json:"host_id"`
	Status           AgentStatus     `json:"status"`
	OS               *string         `json:"os,omitempty"`
	Shell            *string         `json:"shell,omitempty"`
	PythonVersion    *string         `json:"python_version,omitempty"`
	WorkspaceRoot    *string         `json:"workspace_root,omitempty"`
	AvailableCommands json.RawMessage `json:"available_commands,omitempty"`
	Capabilities     json.RawMessage `json:"capabilities,omitempty"`
	NetworkCapabilities json.RawMessage `json:"network_capabilities,omitempty"`
	ModelPolicy      *string         `json:"model_policy,omitempty"`
	MaxConcurrency   int             `json:"max_concurrency"`
	BindingStatus    string          `json:"binding_status,omitempty"` // ready | degraded | failed — from Agent Binding Contract
	LastHeartbeatAt  *time.Time      `json:"last_heartbeat_at,omitempty"`
	LastPollAt       *time.Time      `json:"last_poll_at,omitempty"`
	PreferredAgentID *string         `json:"preferred_agent_id,omitempty"`
	CreatedAt        time.Time       `json:"created_at"`
	UpdatedAt        time.Time       `json:"updated_at"`
}
