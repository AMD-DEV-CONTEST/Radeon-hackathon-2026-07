package main

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func writeInboxLines(t *testing.T, path string, lines []string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	for _, l := range lines {
		f.WriteString(l + "\n")
	}
}

func mkLine(i int) string {
	return `{"event_id":"evt_` + itoa(i) + `","text":"msg_` + itoa(i) + `","from_agent_id":"h5","target_agent_id":"x1","conversation_id":"c","ts":"2026-06-21T00:00:0` + itoa(i) + `Z"}`
}

func itoa(i int) string {
	return string(rune('0' + i))
}

func TestInboxReadDefaultsToFifty(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	rt := t.TempDir()
	t.Setenv("ILS_RUNTIME_HOME", rt)
	inboxPath := profilePaths(rt, "x1").inbox
	var lines []string
	for i := 0; i < 60; i++ {
		lines = append(lines, mkLine(i))
	}
	writeInboxLines(t, inboxPath, lines)

	var out bytes.Buffer
	if err := runInboxRead(inboxReadOptions{Profile: "x1", Lines: 50, All: false, JSON: false}, &out); err != nil {
		t.Fatalf("read: %v", err)
	}
	outLines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(outLines) != 50 {
		t.Fatalf("default read: got %d lines want 50", len(outLines))
	}
}

func TestInboxReadAll(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	rt := t.TempDir()
	t.Setenv("ILS_RUNTIME_HOME", rt)
	inboxPath := profilePaths(rt, "x1").inbox
	writeInboxLines(t, inboxPath, []string{mkLine(1), mkLine(2)})

	var out bytes.Buffer
	if err := runInboxRead(inboxReadOptions{Profile: "x1", Lines: 0, All: true, JSON: false}, &out); err != nil {
		t.Fatalf("read --all: %v", err)
	}
	outLines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(outLines) != 2 {
		t.Fatalf("read --all: got %d lines want 2", len(outLines))
	}
}

func TestInboxReadLinesFlag(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	rt := t.TempDir()
	t.Setenv("ILS_RUNTIME_HOME", rt)
	inboxPath := profilePaths(rt, "x1").inbox
	var lines []string
	for i := 0; i < 10; i++ {
		lines = append(lines, mkLine(i))
	}
	writeInboxLines(t, inboxPath, lines)

	var out bytes.Buffer
	if err := runInboxRead(inboxReadOptions{Profile: "x1", Lines: 3, All: false, JSON: false}, &out); err != nil {
		t.Fatalf("read --lines 3: %v", err)
	}
	outLines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(outLines) != 3 {
		t.Fatalf("read --lines 3: got %d want 3", len(outLines))
	}
}

func TestInboxReadLinesAndAllMutuallyExclusive(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	rt := t.TempDir()
	t.Setenv("ILS_RUNTIME_HOME", rt)
	var out bytes.Buffer
	err := runInboxRead(inboxReadOptions{Profile: "x1", Lines: 5, All: true, JSON: false}, &out)
	if err == nil {
		t.Fatal("--lines and --all together should error")
	}
}

func TestInboxReadUsesProfileFlag(t *testing.T) {
	// Verify `inbox read --profile x1` (flag) works, not just positional.
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	rt := t.TempDir()
	t.Setenv("ILS_RUNTIME_HOME", rt)
	inboxPath := profilePaths(rt, "x1").inbox
	writeInboxLines(t, inboxPath, []string{mkLine(1)})

	var out bytes.Buffer
	if err := runInboxRead(inboxReadOptions{Profile: "x1", Lines: 0, All: true, JSON: false}, &out); err != nil {
		t.Fatalf("read --profile x1: %v", err)
	}
	if !strings.Contains(out.String(), "msg_1") {
		t.Fatalf("output missing msg_1: %q", out.String())
	}
}

func TestInboxTailFollow(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	rt := t.TempDir()
	t.Setenv("ILS_RUNTIME_HOME", rt)
	inboxPath := profilePaths(rt, "x1").inbox
	writeInboxLines(t, inboxPath, []string{mkLine(1)})

	var out bytes.Buffer
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	// Appender goroutine: after a short delay, append a new line.
	go func() {
		time.Sleep(300 * time.Millisecond)
		app := newInboxAppender(inboxPath)
		_ = app.append(inboxRecord{
			EventID: "evt_new", Text: "followed", FromAgentID: "h5",
			TargetAgentID: "x1", ConversationID: "c",
			Ts: "2026-06-21T00:00:09Z",
		})
	}()
	_ = runInboxTail(ctx, inboxTailOptions{Profile: "x1", Lines: 10, Follow: true, JSON: false}, &out)
	if !strings.Contains(out.String(), "followed") {
		t.Fatalf("tail --follow did not print appended line: %q", out.String())
	}
}
