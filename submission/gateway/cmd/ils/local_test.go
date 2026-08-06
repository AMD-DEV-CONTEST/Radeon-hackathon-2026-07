package main

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func startMockGateway(t *testing.T, events []map[string]interface{}) *inboxMockGateway {
	t.Helper()
	return newInboxMockGateway(t, [][]map[string]interface{}{events})
}

func TestRunProfileClientPersistsInbox(t *testing.T) {
	gw := startMockGateway(t, []map[string]interface{}{
		chatEvent("evt_l1", "msg_l1", "conv_l1", "h5", "x1", "hello-x1"),
		chatEvent("evt_l2", "msg_l2", "conv_l1", "h5", "x1", "second"),
	})
	inboxPath := filepath.Join(t.TempDir(), "inbox.ndjson")
	ws := t.TempDir()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	// runProfileClient starts a goroutine that calls cl.Close() when ctx
	// fires, which unblocks the WS ReadMessage on both sides. Events are
	// persisted before the connection closes.
	_ = runProfileClient(ctx, profileClientOptions{
		GatewayURL:  gw.wsURL(),
		AgentID:     "x1",
		AgentName:   "ils-local-x1",
		Workspace:   ws,
		NoHeartbeat: true,
		Stderr:      io.Discard,
		OnEvent:     persistingInboxHandler(inboxPath, "x1"),
	})

	lines := readInboxFile(t, inboxPath)
	if len(lines) != 2 {
		t.Fatalf("inbox lines: got %d want 2", len(lines))
	}
	var first inboxRecord
	if err := json.Unmarshal([]byte(lines[0]), &first); err != nil {
		t.Fatalf("parse first: %v", err)
	}
	if first.EventID != "evt_l1" || first.FromAgentID != "h5" || first.TargetAgentID != "x1" || first.Text != "hello-x1" {
		t.Fatalf("first record: %+v", first)
	}
	if first.ConversationID != "conv_l1" {
		t.Fatalf("conversation_id: got %q want conv_l1", first.ConversationID)
	}
	if first.Raw == nil || first.Raw["event_id"] != "evt_l1" {
		t.Fatalf("raw payload missing event_id: %+v", first.Raw)
	}
	// Force-close gateway so WS connections drop before t.TempDir cleanup
	// (Windows can't remove workspace dir while files are open).
	gw.server.Close()
	time.Sleep(100 * time.Millisecond)
}

func readInboxFile(t *testing.T, path string) []string {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open inbox: %v", err)
	}
	defer f.Close()
	var lines []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if s := strings.TrimSpace(sc.Text()); s != "" {
			lines = append(lines, s)
		}
	}
	return lines
}

func TestLocalDaemonMultiProfileNoCrossTalk(t *testing.T) {
	// Broadcast mock: sends the same events to ALL connections (not just
	// the one at idx 0), so both profiles receive the batch and the
	// correct one persists it regardless of connection order.
	events := []map[string]interface{}{
		chatEvent("evt_x1only", "msg", "conv", "h5", "x1", "only-for-x1"),
	}
	gw := newInboxMockGateway(t, [][]map[string]interface{}{events, events})
	rt := t.TempDir()
	x1Inbox := filepath.Join(rt, "x1", "inbox.ndjson")
	c1Inbox := filepath.Join(rt, "c1", "inbox.ndjson")

	profiles := []daemonProfile{
		{Name: "x1", AgentID: "x1", InboxPath: x1Inbox, UasclientWorkspace: filepath.Join(rt, "x1", "uas"), LockPath: filepath.Join(rt, "x1", "daemon.lock")},
		{Name: "c1", AgentID: "c1", InboxPath: c1Inbox, UasclientWorkspace: filepath.Join(rt, "c1", "uas"), LockPath: filepath.Join(rt, "c1", "daemon.lock")},
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_ = runLocalDaemon(ctx, localDaemonOptions{
		GatewayURL:  gw.wsURL(),
		Profiles:    profiles,
		NoHeartbeat: true,
		Stderr:      io.Discard,
	})

	x1Lines := readInboxFile(t, x1Inbox)
	if len(x1Lines) != 1 {
		t.Fatalf("x1 inbox: got %d lines want 1", len(x1Lines))
	}
	// c1 inbox must be empty — the event was addressed to x1 only.
	if _, err := os.Stat(c1Inbox); err == nil {
		c1Lines := readInboxFile(t, c1Inbox)
		if len(c1Lines) != 0 {
			t.Fatalf("c1 inbox cross-talk: got %d lines want 0", len(c1Lines))
		}
	}
	// On Windows the uasclient may still have the workspace dir open
	// (dedupe/cursor files written during Connect). Force-close the
	// gateway so the WS connections drop and file handles are released
	// before t.TempDir cleanup runs.
	gw.server.Close()
	time.Sleep(100 * time.Millisecond)
}

func TestLocalDaemonRejectsDuplicateAgentID(t *testing.T) {
	gw := startMockGateway(t, nil)
	rt := t.TempDir()
	profiles := []daemonProfile{
		{Name: "x1", AgentID: "x1", InboxPath: filepath.Join(rt, "x1", "inbox.ndjson"), UasclientWorkspace: filepath.Join(rt, "x1", "uas"), LockPath: filepath.Join(rt, "x1", "daemon.lock")},
		{Name: "c1", AgentID: "x1", InboxPath: filepath.Join(rt, "c1", "inbox.ndjson"), UasclientWorkspace: filepath.Join(rt, "c1", "uas"), LockPath: filepath.Join(rt, "c1", "daemon.lock")},
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err := runLocalDaemon(ctx, localDaemonOptions{
		GatewayURL:  gw.wsURL(),
		Profiles:    profiles,
		NoHeartbeat: true,
		Stderr:      io.Discard,
	})
	if err == nil {
		t.Fatal("runLocalDaemon should reject duplicate agent_id")
	}
	if !strings.Contains(err.Error(), "duplicate agent_id") {
		t.Fatalf("error should mention duplicate agent_id: %v", err)
	}
}

func TestLocalDaemonRejectsAlreadyLockedProfile(t *testing.T) {
	gw := startMockGateway(t, nil)
	rt := t.TempDir()
	lockPath := filepath.Join(rt, "x1", "daemon.lock")
	// Pre-acquire the lock so the daemon's acquire must fail.
	rel, err := acquireProfileLock(lockPath)
	if err != nil {
		t.Fatalf("pre-acquire: %v", err)
	}
	defer rel()

	profiles := []daemonProfile{
		{Name: "x1", AgentID: "x1", InboxPath: filepath.Join(rt, "x1", "inbox.ndjson"), UasclientWorkspace: filepath.Join(rt, "x1", "uas"), LockPath: lockPath},
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err = runLocalDaemon(ctx, localDaemonOptions{
		GatewayURL:  gw.wsURL(),
		Profiles:    profiles,
		NoHeartbeat: true,
		Stderr:      io.Discard,
	})
	if err == nil {
		t.Fatal("runLocalDaemon should reject already-locked profile")
	}
	if !strings.Contains(err.Error(), "locked") {
		t.Fatalf("error should mention locked: %v", err)
	}
}
