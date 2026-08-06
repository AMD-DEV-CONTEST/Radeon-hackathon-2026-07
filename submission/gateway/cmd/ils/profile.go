package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Profile is one local agent identity persisted in profiles.json.
//
// StatePath is an ILS-owned directory for the profile's own runtime state
// (not a single file, not the uasclient dedupe/cursor workspace — the
// uasclient workspace is a separate UasclientWorkspace under the same
// profile runtime tree, resolved by profilePaths). If empty, defaults to
// {runtime_base}/runtime/agents/{profile}/state/.
type Profile struct {
	Name      string `json:"name"`
	AgentID   string `json:"agent_id"`
	InboxPath string `json:"inbox_path,omitempty"` // defaults to .../inbox.ndjson
	StatePath string `json:"state_path,omitempty"` // defaults to .../state/ (dir, not a file)
	LogPath   string `json:"log_path,omitempty"`   // defaults to .../daemon.log
}

// profileFile is the on-disk shape of profiles.json.
type profileFile struct {
	Profiles []Profile `json:"profiles"`
}

// lockProfiles acquires a cross-process lock on profiles.json via a
// .lock file with O_CREATE|O_EXCL, retrying with exponential backoff up
// to a 10s deadline. On Windows, O_EXCL maps to CREATE_NEW (atomic
// existence check). This protects the write path from concurrent
// `ils profile set/rm` calls in different terminals — a sync.Mutex only
// guards within one process.
//
// Windows-specific: when one goroutine creates the lock, another
// deletes it, and a third tries to create it in the brief window the
// file is being unlinked, Windows returns ERROR_SHARING_VIOLATION
// ("Access is denied") rather than ERROR_FILE_EXISTS. os.IsExist does
// NOT match that, so we retry on ANY create error whose message
// indicates contention ("exists" or "denied"), and only fail fast on
// genuinely fatal errors (e.g. the parent dir missing).
func lockProfiles() (unlock func(), err error) {
	lockPath := profilesJSONPath() + ".lock"
	if err := os.MkdirAll(filepath.Dir(lockPath), 0o755); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(10 * time.Second)
	backoff := 2 * time.Millisecond
	const maxBackoff = 50 * time.Millisecond
	for {
		f, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err == nil {
			_ = f.Close()
			return func() { _ = os.Remove(lockPath) }, nil
		}
		// Retry on contention: file exists (POSIX/Windows) OR Windows
		// sharing violation ("Access is denied" during create/unlink race).
		// Any other error (e.g. permission denied on the dir itself) is fatal.
		if !isLockContention(err) {
			return nil, err
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("profiles.json locked by another process (10s timeout): %w", err)
		}
		time.Sleep(backoff)
		backoff *= 2
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
	}
}

// isLockContention returns true if err indicates the lock file is
// contended (exists, or Windows sharing-violation during a create/
// unlink race) and the caller should retry.
func isLockContention(err error) bool {
	if err == nil {
		return false
	}
	if os.IsExist(err) {
		return true
	}
	// Windows ERROR_SHARING_VIOLATION surfaces as "Access is denied"
	// during the create/unlink race window; os.IsExist misses it.
	msg := err.Error()
	return strings.Contains(msg, "Access is denied") || strings.Contains(msg, "being used by another process")
}

func profilesJSONPath() string {
	return filepath.Join(ilsHome(), "profiles.json")
}

// loadProfiles reads profiles.json. Missing/empty file → empty store
// (no error), so a fresh ILS_HOME works without pre-creating the file.
func loadProfiles() (profileFile, error) {
	var pf profileFile
	data, err := os.ReadFile(profilesJSONPath())
	if err != nil {
		if os.IsNotExist(err) {
			return pf, nil
		}
		return pf, err
	}
	if len(data) == 0 {
		return pf, nil
	}
	if err := json.Unmarshal(data, &pf); err != nil {
		return pf, fmt.Errorf("profiles.json parse: %w", err)
	}
	return pf, nil
}

// saveProfiles writes profiles.json via os.WriteFile (truncate-replace).
//
// Cross-process safety: callers (profileSet, profileRm) acquire a
// cross-process lock (lockProfiles) before calling saveProfiles. The
// lock file (profiles.json.lock, O_CREATE|O_EXCL with retry) serializes
// writes across terminals. os.WriteFile is NOT atomic on Windows for
// existing files (it truncates then writes), but the lock ensures only
// one writer at a time — no torn content.
func saveProfiles(pf profileFile) error {
	if err := os.MkdirAll(ilsHome(), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(pf, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(profilesJSONPath(), data, 0o644)
}

func profileSet(p Profile) error {
	unlock, err := lockProfiles()
	if err != nil {
		return err
	}
	defer unlock()
	if p.Name == "" {
		return fmt.Errorf("profile name required")
	}
	if p.AgentID == "" {
		return fmt.Errorf("profile agent_id required")
	}
	pf, err := loadProfiles()
	if err != nil {
		return err
	}
	for i, ex := range pf.Profiles {
		if ex.Name == p.Name {
			pf.Profiles[i] = p
			return saveProfiles(pf)
		}
	}
	pf.Profiles = append(pf.Profiles, p)
	return saveProfiles(pf)
}

func profileGet(name string) (Profile, error) {
	pf, err := loadProfiles()
	if err != nil {
		return Profile{}, err
	}
	for _, p := range pf.Profiles {
		if p.Name == name {
			return p, nil
		}
	}
	return Profile{}, fmt.Errorf("profile %q not found", name)
}

func profileList() ([]Profile, error) {
	pf, err := loadProfiles()
	if err != nil {
		return nil, err
	}
	out := append([]Profile(nil), pf.Profiles...)
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

func profileRm(name string) error {
	unlock, err := lockProfiles()
	if err != nil {
		return err
	}
	defer unlock()
	pf, err := loadProfiles()
	if err != nil {
		return err
	}
	for i, p := range pf.Profiles {
		if p.Name == name {
			pf.Profiles = append(pf.Profiles[:i], pf.Profiles[i+1:]...)
			return saveProfiles(pf)
		}
	}
	return fmt.Errorf("profile %q not found", name)
}
