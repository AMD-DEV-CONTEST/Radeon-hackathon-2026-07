package permissions

import (
	"fmt"
)

// Level is the real permission level for a tool category.
type Level string

const (
	Allow Level = "allow"
	Ask   Level = "ask"
	Deny  Level = "deny"
)

// Category identifies a real class of tool action the agent might
// take, each independently gated by its own permission level.
type Category string

const (
	LocalFiles        Category = "local_files"
	WebSearch         Category = "web_search"
	WriteCorpus       Category = "write_corpus"
	ShellExecution    Category = "shell_execution"
	ExternalMessaging Category = "external_messaging"
)

// ConfirmFunc is called for any action requiring "Ask" -- a real,
// injectable confirmation step (in a real UI, this would prompt the
// user directly; for this demo, a simple stdin-based confirmation).
type ConfirmFunc func(action string) bool

// Policy holds the real, current permission level for each real tool
// category the agent can use, plus the real confirmation function
// used for any category set to Ask.
type Policy struct {
	Levels  map[Category]Level
	Confirm ConfirmFunc
}

// DefaultPolicy returns real, sensible defaults -- genuinely
// conservative, matching this whole project's privacy-first
// philosophy: local file access and web search are allowed outright,
// but writing to the persistent corpus requires confirmation, and
// anything with real external side effects (shell execution, sending
// messages) is denied by default.
func DefaultPolicy(confirm ConfirmFunc) *Policy {
	return &Policy{
		Levels: map[Category]Level{
			LocalFiles:        Allow,
			WebSearch:         Allow,
			WriteCorpus:       Ask,
			ShellExecution:    Deny,
			ExternalMessaging: Deny,
		},
		Confirm: confirm,
	}
}

// Check enforces the real policy for a given category before an
// action is allowed to proceed. Returns nil if the action may
// proceed, or a real, honest error explaining why it was blocked.
func (p *Policy) Check(category Category, action string) error {
	level, ok := p.Levels[category]
	if !ok {
		// A real, honest default for any category not explicitly
		// configured: deny, not silently allow. An unknown tool
		// category should never default to permissive.
		return fmt.Errorf("permission denied: %q is not a recognized tool category (default-deny)", category)
	}

	switch level {
	case Allow:
		return nil
	case Deny:
		return fmt.Errorf("permission denied: %q is set to Deny for category %q", action, category)
	case Ask:
		if p.Confirm == nil {
			return fmt.Errorf("permission denied: %q requires confirmation, but no confirmation function was configured", action)
		}
		if p.Confirm(action) {
			return nil
		}
		return fmt.Errorf("permission denied: user declined to confirm %q", action)
	default:
		return fmt.Errorf("permission denied: unrecognized permission level %q for category %q", level, category)
	}
}
