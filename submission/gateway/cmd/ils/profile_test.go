package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func newProfileStoreDir(t *testing.T) string {
	t.Helper()
	d := t.TempDir()
	t.Setenv("ILS_HOME", d)
	return d
}

func TestProfileSetGetList(t *testing.T) {
	newProfileStoreDir(t)
	if err := profileSet(Profile{Name: "x1", AgentID: "x1"}); err != nil {
		t.Fatalf("set x1: %v", err)
	}
	if err := profileSet(Profile{Name: "c1", AgentID: "c1"}); err != nil {
		t.Fatalf("set c1: %v", err)
	}
	got, err := profileGet("x1")
	if err != nil {
		t.Fatalf("get x1: %v", err)
	}
	if got.AgentID != "x1" {
		t.Fatalf("x1 agent_id: got %q", got.AgentID)
	}
	list, err := profileList()
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list) != 2 {
		t.Fatalf("list len: got %d want 2", len(list))
	}
}

func TestProfileSetUpdatesExisting(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	_ = profileSet(Profile{Name: "x1", AgentID: "x1-new"})
	got, _ := profileGet("x1")
	if got.AgentID != "x1-new" {
		t.Fatalf("update: got %q want x1-new", got.AgentID)
	}
}

func TestProfileRm(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	if err := profileRm("x1"); err != nil {
		t.Fatalf("rm: %v", err)
	}
	if _, err := profileGet("x1"); err == nil {
		t.Fatal("get after rm should error")
	}
}

func TestProfilesConcurrentWrite(t *testing.T) {
	newProfileStoreDir(t)
	var wg sync.WaitGroup
	// Collect errors so a goroutine failure is NOT silently swallowed
	// (root cause A from C1 review: `_ = profileSet(...)` hid races).
	errCh := make(chan error, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			// distinct single-rune names a..t
			name := "p" + string(rune('a'+i))
			if err := profileSet(Profile{Name: name, AgentID: name}); err != nil {
				errCh <- fmt.Errorf("profileSet %s: %w", name, err)
				return
			}
			errCh <- nil
		}(i)
	}
	wg.Wait()
	close(errCh)
	for e := range errCh {
		if e != nil {
			t.Fatalf("concurrent profileSet failed: %v", e)
		}
	}
	list, _ := profileList()
	if len(list) != 20 {
		t.Fatalf("after concurrent set: list len %d want 20", len(list))
	}
	// JSON must be valid
	data, err := os.ReadFile(filepath.Join(os.Getenv("ILS_HOME"), "profiles.json"))
	if err != nil {
		t.Fatalf("read profiles.json: %v", err)
	}
	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatalf("profiles.json invalid after concurrent writes: %v", err)
	}
}

func TestProfilesWriteIsTruncateNotRename(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "old", AgentID: "old"})
	_ = profileSet(Profile{Name: "new", AgentID: "new"})
	// Both must survive: truncate-write appends to the map; rename
	// (the dedupe.go pattern) would lose "old" because the target exists.
	list, _ := profileList()
	names := map[string]bool{}
	for _, p := range list {
		names[p.Name] = true
	}
	if !names["old"] || !names["new"] {
		t.Fatalf("truncate-write lost a profile: %v", names)
	}
}
