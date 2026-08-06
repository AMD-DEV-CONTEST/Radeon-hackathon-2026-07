package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

// inboxRecord is one persisted line in a profile's inbox.ndjson.
// Field set matches the spec (Rev C §7.2): event_id, conversation_id,
// from_agent_id, target_agent_id, text, ts, and the raw event payload.
type inboxRecord struct {
	EventID        string                 `json:"event_id"`
	ConversationID string                 `json:"conversation_id"`
	FromAgentID    string                 `json:"from_agent_id"`
	TargetAgentID  string                 `json:"target_agent_id"`
	Text           string                 `json:"text"`
	Ts             string                 `json:"ts"`
	Raw            map[string]interface{} `json:"raw"`
}

// inboxAppender is a thread-safe append-only writer to one profile's
// inbox.ndjson. One instance per profile (guarded by its own mutex).
type inboxAppender struct {
	mu   sync.Mutex
	path string
}

func newInboxAppender(path string) *inboxAppender {
	return &inboxAppender{path: path}
}

// append writes one inboxRecord as a JSON line. MkdirAll on the dir
// first; O_APPEND|O_CREATE|O_WRONLY (same pattern as writeBridgeInbox
// in bridge_chat.go:48-82, but NO socket broadcast — local daemon is
// file-only).
func (a *inboxAppender) append(rec inboxRecord) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(a.path), 0o755); err != nil {
		return err
	}
	b, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(a.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err := f.Write(append(b, '\n')); err != nil {
		return err
	}
	return nil
}

// eventToInboxRecord maps a uasclient.Event to an inboxRecord addressed
// to agentID. Broadcasts (empty target_agent_id) are NOT written — the
// caller filters them. Raw retains the full original event payload.
func eventToInboxRecord(e uasclient.Event, agentID string) inboxRecord {
	convID := e.ConversationID
	if convID == "" {
		convID = e.ConvID
	}
	from := e.FromAgentID
	if from == "" {
		from = e.From
	}
	to := e.TargetAgentID
	if to == "" {
		to = agentID
	}
	ts := e.Timestamp
	if ts == "" {
		ts = time.Now().UTC().Format(time.RFC3339)
	}
	return inboxRecord{
		EventID:        e.EventID,
		ConversationID: convID,
		FromAgentID:    from,
		TargetAgentID:  to,
		Text:           e.Text,
		Ts:             ts,
		Raw:            e.Raw,
	}
}

// persistingInboxHandler returns an OnEvent callback that appends each
// event addressed to agentID to the given inbox file. Broadcasts (empty
// target_agent_id) are dropped — they are for OB/Cockpit, not agents
// (same Feishu-bot-model filter as daemon.go handleChatEvent).
func persistingInboxHandler(inboxPath, agentID string) func(ctx context.Context, e uasclient.Event) error {
	app := newInboxAppender(inboxPath)
	return func(ctx context.Context, e uasclient.Event) error {
		if e.TargetAgentID != "" && e.TargetAgentID != agentID {
			return nil
		}
		if e.TargetAgentID == "" {
			return nil // drop broadcasts
		}
		return app.append(eventToInboxRecord(e, agentID))
	}
}

// daemonProfile is a resolved profile ready to run under the local
// daemon. Fields are fully resolved (defaults applied) at daemon start
// time, before any goroutine is launched.
type daemonProfile struct {
	Name               string
	AgentID            string
	InboxPath          string
	UasclientWorkspace string
	LockPath           string
}

// localDaemonOptions configures `ils local daemon`.
type localDaemonOptions struct {
	GatewayURL  string
	Profiles    []daemonProfile
	NoHeartbeat bool
	Stderr      io.Writer
}

// validateProfiles runs the pre-flight guards BEFORE starting any
// goroutine: (a) no duplicate agent_id across profiles, (b) every
// profile's lock is acquirable. Returns the acquired release funcs in
// order on success (caller defers them). On failure returns the error
// and releases any locks already taken.
func validateProfiles(profiles []daemonProfile) ([]func() error, error) {
	seen := map[string]string{} // agent_id -> profile name
	for _, p := range profiles {
		if prev, ok := seen[p.AgentID]; ok {
			return nil, fmt.Errorf("duplicate agent_id %q used by profiles %q and %q", p.AgentID, prev, p.Name)
		}
		seen[p.AgentID] = p.Name
	}
	var releases []func() error
	for _, p := range profiles {
		rel, err := acquireProfileLock(p.LockPath)
		if err != nil {
			// Roll back locks already taken.
			for _, r := range releases {
				_ = r()
			}
			return nil, fmt.Errorf("profile %q: %w", p.Name, err)
		}
		releases = append(releases, rel)
	}
	return releases, nil
}

// runLocalDaemon runs one client-mode subscription per profile until ctx
// is cancelled. Guards (duplicate agent_id, per-profile lock) run first;
// any failure aborts before any WS connection is opened.
func runLocalDaemon(ctx context.Context, opts localDaemonOptions) error {
	if len(opts.Profiles) == 0 {
		return fmt.Errorf("no profiles")
	}
	if opts.Stderr == nil {
		opts.Stderr = io.Discard
	}
	releases, err := validateProfiles(opts.Profiles)
	if err != nil {
		return err
	}
	defer func() {
		for _, r := range releases {
			_ = r()
		}
	}()

	// Each profile gets its own goroutine. A single profile's error
	// doesn't cancel the others; the parent ctx still governs shutdown.
	type result struct {
		name string
		err  error
	}
	errCh := make(chan result, len(opts.Profiles))
	for _, p := range opts.Profiles {
		p := p
		go func() {
			err := runProfileClient(ctx, profileClientOptions{
				GatewayURL:  opts.GatewayURL,
				AgentID:     p.AgentID,
				AgentName:   "ils-local-" + p.Name,
				Workspace:   p.UasclientWorkspace,
				NoHeartbeat: opts.NoHeartbeat,
				Stderr:      opts.Stderr,
				OnEvent:     persistingInboxHandler(p.InboxPath, p.AgentID),
			})
			errCh <- result{p.Name, err}
		}()
	}
	// Wait for ctx cancellation (normal shutdown) or all profiles to exit.
	for range opts.Profiles {
		select {
		case <-ctx.Done():
			return nil
		case r := <-errCh:
			if r.err != nil {
				fmt.Fprintf(opts.Stderr, "[local] profile %s exited: %v\n", r.name, r.err)
			}
		}
	}
	return nil
}
