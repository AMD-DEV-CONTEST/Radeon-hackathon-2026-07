// Package uasclient is the long-connection client used by the UnionAgents
// ILS CLI and, eventually, Agent runtimes to talk to a UAS Gateway.
//
// It implements the same shape as a Feishu/Lark bot long connection:
// register → WS dial → server:welcome + client.ready handshake →
// receive events → auto-ack → optional reply → keepalive ping.
//
// On top of the basic shape, this package adds three production-grade
// features that the rest of UnionAgents depends on:
//
//   - Automatic reconnect with exponential backoff (2s → 60s, reset on
//     success). Re-registration is triggered on a 401 from /register/*
//     so a Gateway restart that invalidates the app_id self-heals.
//
//   - event_id deduplication with a local on-disk set, so a replayed
//     event is acknowledged (to keep server-side pending counters
//     honest) but not delivered twice to the OnEvent callback.
//
//   - Replay-on-reconnect: when a non-empty last_event_id cursor exists
//     for an event key, the client requests /events/replay and feeds
//     the returned events through the same dedupe + OnEvent path.
//
// Known limits, in the spirit of not papering over them:
//
//   - The server-side replay buffer is in-memory only, 5 minute TTL,
//     capped at 100 events. Reconnect-replay can NOT guarantee zero
//     loss. A client that reconnects after >5 minutes of offline time
//     will see only events still inside the server's buffer.
//
//   - The on-disk dedupe set is append-only and intentionally simple.
//     A long-lived process will grow it. A periodic compaction step
//     could be added later if it ever becomes a problem.
//
//   - The package is one process per connection: the dedupe set and
//     cursor are per-process, not per-host. If you run two ILS
//     processes against the same Agent identity, they will see the
//     same events; each will dedupe independently. That's fine for
//     the current single-process-per-Agent model.
package uasclient

import (
	"context"
	"io"
	"time"
)

// Event is the union of every event kind this client cares about.
// Today only chat is wired up, but the field set is the wire-level
// schema the Gateway emits so consumers can switch on type.
//
// The fields intentionally mirror the JSON keys sent by the server;
// mapping them through a struct keeps the OnEvent callback API
// stable even if the server adds optional fields later.
type Event struct {
	Type           string `json:"type"`
	EventID        string `json:"event_id,omitempty"`
	EventKey       string `json:"event_key,omitempty"`
	EventType      string `json:"event_type,omitempty"`
	MessageID      string `json:"message_id,omitempty"`
	ConvID         string `json:"conv_id,omitempty"`
	ConversationID string `json:"conversation_id,omitempty"`
	From           string `json:"from,omitempty"`
	FromAgentID    string `json:"from_agent_id,omitempty"`
	TargetAgentID  string `json:"target_agent_id,omitempty"`
	Text           string `json:"text,omitempty"`
	Timestamp      string `json:"ts,omitempty"`
	// Source/Target/Delivery are reserved for the richer message
	// envelope the Gateway is moving toward. We don't decode them
	// today, but we capture the raw JSON so a future caller can read
	// them without us having to add fields.
	Raw map[string]interface{} `json:"-"`
}

// Outgoing is the body of a chat message sent by this client. The
// field set is the same shape server-side chat handlers accept.
type Outgoing struct {
	From          string `json:"from,omitempty"`
	FromAgentID   string `json:"from_agent_id,omitempty"`
	TargetAgentID string `json:"target_agent_id,omitempty"`
	Text          string `json:"text,omitempty"`
	ConvID        string `json:"conv_id,omitempty"`
}

// SendResult is the structured answer to a Send call. The shape
// matches what the Gateway returns from POST /chat, with no
// transformation; the ILS CLI's existing chat send JSON output
// was built from this same body, so callers see no surprise.
type SendResult struct {
	Status                 string `json:"status"`
	EventID                string `json:"event_id,omitempty"`
	ConversationID         string `json:"conversation_id,omitempty"`
	TargetConnected        bool   `json:"target_connected"`
	ConnectionCount        int    `json:"connection_count,omitempty"`
	DeliveredToConnections int    `json:"delivered_to_connections,omitempty"`
	FailedWrites           int    `json:"failed_writes,omitempty"`
	AckRequired            bool   `json:"ack_required,omitempty"`
	Route                  string `json:"route,omitempty"`
	Target                 string `json:"target,omitempty"`
}

// Status is a snapshot of the client's current state, used by
// doctor/status commands. Cheap to read; doesn't block.
type Status struct {
	State           string // "idle", "connecting", "ready", "closed"
	ReconnectCount  int
	LastReconnectAt time.Time
	LastError       string
}

// Config is the user-facing knobs. All fields have zero-value
// defaults that read from env vars, so an empty Config is usable
// for the most common cases.
type Config struct {
	// GatewayURL is the ws:// or wss:// base of the Gateway. The
	// client appends /ws when dialing. Default: env GATEWAY_URL,
	// or ws://111.228.42.18:8001.
	GatewayURL string

	// AgentID, AgentName, AgentType pick the /register/agent path
	// when AgentID is non-empty. Otherwise the client registers
	// as a "client" (no agent_type). All three default to env
	// AGENT_ID, AGENT_NAME, AGENT_TYPE.
	AgentID   string
	AgentName string
	AgentType string

	// ClientAgentID is only used in client mode. It lets tools such
	// as `ils inbox watch --agent-id=x1` receive messages addressed
	// to that logical agent id without registering as a brain/worker
	// agent. AgentID still means full agent-mode registration.
	ClientAgentID string

	// Password is the Gateway admin password. Only required in
	// agent mode; client registration is auth-free. Default: env
	// GATEWAY_PASSWORD.
	Password string

	// OrchestratorURL is used for the optional HTTP heartbeat to
	// /agents/heartbeat. Set empty to disable heartbeat. Default
	// env ORCHESTRATOR_URL, or http://111.228.42.18:8000.
	OrchestratorURL string

	// Workspace is the directory where dedupe sets and the
	// last_event_id cursor are persisted. Default:
	// $XDG_DATA_HOME/unionagents/uasclient (falls back to
	// %APPDATA%\unionagents\uasclient on Windows, then
	// ~/.local/share/unionagents/uasclient).
	Workspace string

	// NoHeartbeat disables the optional orchestrator HTTP
	// heartbeat loop. Doctor and the event consume CLI use it.
	NoHeartbeat bool

	// Stderr is where status lines are written. Default: os.Stderr.
	// Use a buffer in tests to keep the test output clean.
	Stderr io.Writer

	// OnRawEvent is called for every parseable WS frame, BEFORE the
	// type-based filter. The daemon uses this to intercept task:dispatch
	// and other non-chat events. If the callback returns true, the
	// frame is consumed (no further processing). Returning false lets
	// the normal chat/dedupe/ack path handle it. If nil, all frames
	// go through the normal path.
	OnRawEvent func(ctx context.Context, raw map[string]interface{}) bool

	// OnEvent is called for every accepted (post-dedupe) chat
	// event. Returning a non-nil error does NOT prevent ack; ack
	// always fires. The error is logged to Stderr. If nil, the
	// event is acked but not handed to any callback.
	OnEvent func(ctx context.Context, e Event) error

	// OnReady is called after every successful (re)connect+ready
	// handshake, before the read loop starts. Used by the
	// reconnect→replay path: it triggers the replay request from
	// inside OnReady.
	OnReady func(ctx context.Context) error

	// Router, when non-nil, selects the Gateway URL per target agent
	// ID for outgoing Send/Reply calls. This is the multi-base hook
	// (H5/H6): without it, every Send goes to GatewayURL. nil keeps
	// the original single-gateway behavior, so existing callers are
	// unaffected. See router.go for the contract.
	Router Router
}
