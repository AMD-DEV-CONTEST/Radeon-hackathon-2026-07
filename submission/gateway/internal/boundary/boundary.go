package boundary

import "time"

const Version = "2026-06-13"

type Snapshot struct {
	Status             string              `json:"status"`
	BoundaryVersion    string              `json:"boundary_version"`
	GeneratedAt        string              `json:"generated_at"`
	Component          string              `json:"component"`
	Role               string              `json:"role"`
	UASChain           []Node              `json:"uas_chain"`
	ServerDuties       []string            `json:"server_duties,omitempty"`
	ExternalReferences []ExternalReference `json:"external_references"`
	ForbiddenMappings  []string            `json:"forbidden_mappings"`
	Verification       []Verification      `json:"verification"`
}

type Node struct {
	Name   string `json:"name"`
	Kind   string `json:"kind"`
	Duty   string `json:"duty"`
	Status string `json:"status"`
}

type ExternalReference struct {
	Name       string   `json:"name"`
	Relation   string   `json:"relation"`
	AllowedUse []string `json:"allowed_use"`
	Forbidden  []string `json:"forbidden"`
}

type Verification struct {
	Area    string `json:"area"`
	Command string `json:"command"`
	Expect  string `json:"expect"`
}

func NewSnapshot(component, role string) Snapshot {
	return Snapshot{
		Status:          "ok",
		BoundaryVersion: Version,
		GeneratedAt:     time.Now().UTC().Format(time.RFC3339),
		Component:       component,
		Role:            role,
		UASChain: []Node{
			{
				Name:   "OB",
				Kind:   "client",
				Duty:   "User-facing Omima Beside / UAS Operation Bridge client for chat and status surfaces.",
				Status: "uas-owned",
			},
			{
				Name:   "JD-ECS / UAS Gateway",
				Kind:   "server",
				Duty:   "UAS-owned HTTP/WS relay, chat delivery, ready/ack/replay, and event status.",
				Status: "uas-owned",
			},
			{
				Name:   "JD-ECS / Orchestrator",
				Kind:   "server",
				Duty:   "UAS-owned agent registry, heartbeat, task lease, task state, and scheduling.",
				Status: "uas-owned",
			},
			{
				Name:   "Agent Runtime / uas-client",
				Kind:   "runtime",
				Duty:   "Planned UAS-owned resident runtime for online state, WS, bridge, and dispatch.",
				Status: "planned",
			},
			{
				Name:   "Agent CLI Runtime",
				Kind:   "runtime",
				Duty:   "Agent-specific execution surface such as reasonix, opencode, claude_code, or hermes.",
				Status: "external-agent-runtime",
			},
		},
		ServerDuties: []string{
			"Expose UAS-owned boundary metadata for OB and CLI verification.",
			"Maintain UAS event identity, delivery, ack, replay, and ready state without borrowing external-platform fields.",
			"Maintain agent registration, heartbeat, online/offline, binding_status, and task state.",
			"Keep Lark CLI / Feishu Cloud as reference-only samples, never as UAS chain nodes.",
		},
		ExternalReferences: []ExternalReference{
			{
				Name:     "Lark CLI / Feishu Cloud",
				Relation: "reference_only",
				AllowedUse: []string{
					"Study command shape, dry-run, schema, and event-consume ergonomics.",
					"Use as a comparison point when naming CLI categories.",
				},
				Forbidden: []string{
					"Do not put Feishu Cloud into the UAS architecture chain.",
					"Do not map Feishu event_id/message_id/chat_id/open_id into UAS protocol fields.",
					"Do not treat Lark event bus as equivalent to ils daemon or uas-client.",
				},
			},
		},
		ForbiddenMappings: []string{
			"Feishu Cloud -> Hermes Gateway -> UAS Gateway",
			"JD-ECS receives Feishu Cloud events",
			"UAS maps Feishu event_id/message_id/chat_id/open_id",
			"Lark CLI event bus == ils daemon",
			"OB == OpenCode Bridge",
		},
		Verification: []Verification{
			{
				Area:    "server",
				Command: "curl -s http://<jd-ecs>:8001/boundary && curl -s http://<jd-ecs>:8000/boundary",
				Expect:  "Both endpoints return reference_only for Lark CLI / Feishu Cloud and UAS-owned nodes only in uas_chain.",
			},
			{
				Area:    "ob",
				Command: "OB loads /boundary before rendering connection diagnostics.",
				Expect:  "OB labels itself as Omima Beside / UAS Operation Bridge and does not display Lark/Feishu as a UAS node.",
			},
			{
				Area:    "cli",
				Command: "ils boundary status --json",
				Expect:  "CLI reports gateway_boundary and orchestrator_boundary as ok.",
			},
		},
	}
}
