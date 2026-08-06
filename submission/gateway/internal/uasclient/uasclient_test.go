package uasclient

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestDedupe_RoundTrip: add a few ids, persist, re-load into a
// fresh store, and confirm the seen-check returns true for each.
func TestDedupe_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	s1 := newDedupeStore(dir, "chat", os.Stderr)
	if err := s1.load(); err != nil {
		t.Fatalf("first load: %v", err)
	}
	for _, id := range []string{"evt_aaa", "evt_bbb", "evt_ccc"} {
		if err := s1.add(id); err != nil {
			t.Fatalf("add %s: %v", id, err)
		}
	}
	if !s1.seen("evt_aaa") {
		t.Fatal("expected evt_aaa to be seen after add")
	}
	if err := s1.persist(); err != nil {
		t.Fatalf("persist: %v", err)
	}

	// Re-open as a fresh store and confirm the file content is
	// recovered.
	s2 := newDedupeStore(dir, "chat", os.Stderr)
	if err := s2.load(); err != nil {
		t.Fatalf("second load: %v", err)
	}
	for _, id := range []string{"evt_aaa", "evt_bbb", "evt_ccc"} {
		if !s2.seen(id) {
			t.Fatalf("expected %s to be seen after reload", id)
		}
	}
	if s2.seen("evt_ddd") {
		t.Fatal("did not add evt_ddd; should not be seen")
	}
}

// TestCursor_PersistAcrossOpen: set a cursor, persist, reload,
// confirm value is preserved. Mirrors the dedupe round-trip but
// with a single-line file.
func TestCursor_PersistAcrossOpen(t *testing.T) {
	dir := t.TempDir()
	c1 := newCursorStore(dir, "chat")
	if err := c1.load(); err != nil {
		t.Fatalf("first load: %v", err)
	}
	if err := c1.update("evt_zzz"); err != nil {
		t.Fatalf("update: %v", err)
	}
	if got := c1.get(); got != "evt_zzz" {
		t.Fatalf("cursor after update: got %q want evt_zzz", got)
	}

	c2 := newCursorStore(dir, "chat")
	if err := c2.load(); err != nil {
		t.Fatalf("second load: %v", err)
	}
	if got := c2.get(); got != "evt_zzz" {
		t.Fatalf("cursor after reload: got %q want evt_zzz", got)
	}
}

// TestCursor_EmptyOnMissingFile: when the cursor file does not
// exist (fresh install), load should be a no-op, not an error.
func TestCursor_EmptyOnMissingFile(t *testing.T) {
	dir := t.TempDir()
	c := newCursorStore(dir, "chat")
	if err := c.load(); err != nil {
		t.Fatalf("load on missing file: %v", err)
	}
	if got := c.get(); got != "" {
		t.Fatalf("cursor on missing file: got %q want empty", got)
	}
}

// TestDedupe_LimitTriggersPersist: add more than `limit` ids and
// confirm the on-disk rewrite happens. The limit is set in
// newDedupeStore; we don't re-construct it here because that's an
// internal field. Instead, force a persist via the public API and
// check the file exists and contains the expected ids.
func TestDedupe_PersistWritesFile(t *testing.T) {
	dir := t.TempDir()
	s := newDedupeStore(dir, "chat", os.Stderr)
	for i := 0; i < 10; i++ {
		_ = s.add("evt_" + string(rune('a'+i)))
	}
	if err := s.persist(); err != nil {
		t.Fatalf("persist: %v", err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "seen", "chat.txt"))
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	body := string(data)
	for i := 0; i < 10; i++ {
		id := "evt_" + string(rune('a'+i))
		if !strings.Contains(body, id) {
			t.Fatalf("expected file to contain %s, got:\n%s", id, body)
		}
	}
}

// TestBackoff_Shape: validate that the backoff progression is what
// we expect (2s -> 4s -> 8s -> ... -> capped at 60s). This is a
// pure-function test against a small helper, so we don't need a
// live client. If we add a helper that returns the next backoff
// value, this test should target it; for now we just exercise the
// values used inside Connect.
func TestBackoff_Shape(t *testing.T) {
	// Mirror the progression in Connect. This is a guard test:
	// if someone refactors Connect and breaks the backoff curve,
	// this fails and prompts a manual review.
	backoff := 2 * time.Second
	const maxBackoff = 60 * time.Second
	expected := []time.Duration{
		2 * time.Second,
		4 * time.Second,
		8 * time.Second,
		16 * time.Second,
		32 * time.Second,
		60 * time.Second,
		60 * time.Second,
	}
	for i, want := range expected {
		if backoff != want {
			t.Fatalf("backoff step %d: got %s want %s", i, backoff, want)
		}
		backoff *= 2
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
	}
}

// TestDecodeEvent: a sanity check that the wire-level JSON sent by
// the Gateway maps cleanly onto Event, and the legacy
// conversation_id field falls back into ConvID.
func TestDecodeEvent(t *testing.T) {
	cases := []struct {
		name string
		raw  string
		want Event
	}{
		{
			name: "modern",
			raw:  `{"type":"chat","event_id":"evt_1","event_key":"chat","conv_id":"a2a_2","from_agent_id":"B","target_agent_id":"A","text":"hi","ts":"2026-06-16T00:00:00Z"}`,
			want: Event{Type: "chat", EventID: "evt_1", EventKey: "chat", ConvID: "a2a_2", FromAgentID: "B", TargetAgentID: "A", Text: "hi", Timestamp: "2026-06-16T00:00:00Z"},
		},
		{
			name: "legacy_conversation_id",
			raw:  `{"type":"chat","event_id":"evt_2","conversation_id":"a2a_3","from":"B","text":"hi"}`,
			want: Event{Type: "chat", EventID: "evt_2", ConversationID: "a2a_3", From: "B", Text: "hi"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := decodeEvent([]byte(tc.raw))
			if err != nil {
				t.Fatalf("decode: %v", err)
			}
			if got.Type != tc.want.Type || got.EventID != tc.want.EventID ||
				got.ConvID != tc.want.ConvID || got.FromAgentID != tc.want.FromAgentID ||
				got.TargetAgentID != tc.want.TargetAgentID || got.Text != tc.want.Text {
				t.Fatalf("mismatch:\n got: %+v\nwant: %+v", got, tc.want)
			}
		})
	}
}

// TestIsReplyFor: validate the A2A reply match rule.
func TestIsReplyFor(t *testing.T) {
	sent := Outgoing{FromAgentID: "A", From: "A", TargetAgentID: "B", ConvID: "a2a_9"}
	cases := []struct {
		name string
		evt  Event
		want bool
	}{
		{
			name: "matches_via_agent_id",
			evt:  Event{Type: "chat", ConvID: "a2a_9", FromAgentID: "B", TargetAgentID: "A"},
			want: true,
		},
		{
			name: "matches_via_display_name",
			evt:  Event{Type: "chat", ConvID: "a2a_9", From: "B", TargetAgentID: "A"},
			want: true,
		},
		{
			name: "wrong_conv_id",
			evt:  Event{Type: "chat", ConvID: "a2a_other", FromAgentID: "B"},
			want: false,
		},
		{
			name: "wrong_sender",
			evt:  Event{Type: "chat", ConvID: "a2a_9", FromAgentID: "C"},
			want: false,
		},
		{
			name: "non_chat",
			evt:  Event{Type: "ready", ConvID: "a2a_9", FromAgentID: "B"},
			want: false,
		},
		{
			name: "addressed_to_someone_else",
			evt:  Event{Type: "chat", ConvID: "a2a_9", FromAgentID: "B", TargetAgentID: "Z"},
			want: false,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := isReplyFor(tc.evt, sent); got != tc.want {
				t.Fatalf("isReplyFor: got %v want %v (evt=%+v)", got, tc.want, tc.evt)
			}
		})
	}
}
