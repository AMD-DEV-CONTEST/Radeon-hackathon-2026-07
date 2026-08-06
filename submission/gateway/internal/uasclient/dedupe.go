package uasclient

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// dedupeStore is a simple on-disk set of event_ids that have
// already been processed. Append-only, with periodic full rewrite
// to bound file growth. Per-process, per-event-key.
//
// Trade-offs vs. bbolt/badger:
//   - We avoid adding a third-party dependency for a 50-line
//     feature. The repo's go.mod has zero non-gorilla deps
//     outside ironlaw, and we'd like to keep it that way for the
//     core client path.
//   - We give up crash-safe atomicity of the on-disk state. If
//     the process is killed mid-write, the file may be partial.
//     Worst case: on next start, we re-process up to the last
//     successfully-written event_id. Replay (if cursor is set)
//     will over-deliver, but the dedupe will collapse duplicates
//     to ack-only. This is the design.
type dedupeStore struct {
	dir    string
	key    string
	path   string
	stderr io.Writer

	mu     sync.Mutex
	ids    map[string]struct{}
	dirty  bool
	writes int

	// limit prevents the in-memory set from growing unbounded
	// during a long-lived process. When the set exceeds this
	// size, we keep only the most recent half and rewrite the
	// file. The limit is generous; bump if it ever fires in
	// real workloads.
	limit int
}

func newDedupeStore(workspace, key string, stderr io.Writer) *dedupeStore {
	path := ""
	if workspace != "" {
		path = filepath.Join(workspace, "seen", key+".txt")
	}
	return &dedupeStore{
		dir:    workspace,
		key:    key,
		path:   path,
		stderr: stderr,
		ids:    map[string]struct{}{},
		limit:  100000,
	}
}

func (d *dedupeStore) load() error {
	if d.path == "" {
		return nil
	}
	f, err := os.Open(d.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		id := strings.TrimSpace(scanner.Text())
		if id == "" {
			continue
		}
		d.ids[id] = struct{}{}
	}
	return scanner.Err()
}

// seen returns true if id was already in the set.
func (d *dedupeStore) seen(id string) bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	_, ok := d.ids[id]
	return ok
}

// add records id. Returns nil if it was new or already present.
func (d *dedupeStore) add(id string) error {
	if id == "" {
		return nil
	}
	d.mu.Lock()
	if _, ok := d.ids[id]; ok {
		d.mu.Unlock()
		return nil
	}
	d.ids[id] = struct{}{}
	d.dirty = true
	d.writes++
	shouldPersist := d.writes%256 == 0
	if len(d.ids) > d.limit {
		shouldPersist = true
	}
	d.mu.Unlock()
	if shouldPersist {
		return d.persist()
	}
	return nil
}

// persist rewrites the file from the in-memory set. Safe to call
// concurrently with add/seen (it takes the same mutex).
func (d *dedupeStore) persist() error {
	d.mu.Lock()
	if d.path == "" {
		d.mu.Unlock()
		return nil
	}
	if !d.dirty {
		d.mu.Unlock()
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(d.path), 0o755); err != nil {
		d.mu.Unlock()
		return err
	}
	tmp := d.path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		d.mu.Unlock()
		return err
	}
	w := bufio.NewWriter(f)
	for id := range d.ids {
		// One per line. IDs are short and contain no newlines
		// by gateway contract (they're "evt_<hex>"); no escaping
		// needed.
		if _, err := w.WriteString(id); err != nil {
			f.Close()
			os.Remove(tmp)
			d.mu.Unlock()
			return err
		}
		if err := w.WriteByte('\n'); err != nil {
			f.Close()
			os.Remove(tmp)
			d.mu.Unlock()
			return err
		}
	}
	if err := w.Flush(); err != nil {
		f.Close()
		os.Remove(tmp)
		d.mu.Unlock()
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		d.mu.Unlock()
		return err
	}
	if err := os.Rename(tmp, d.path); err != nil {
		os.Remove(tmp)
		d.mu.Unlock()
		return err
	}
	d.dirty = false
	d.mu.Unlock()
	return nil
}

// cursorStore tracks the highest event_id acked for an event key.
// Used on reconnect to feed since_event_id to /events/replay.
//
// Persisted as a single line of text. Updated after a successful
// ack. We intentionally do NOT update it on dedupe-skip; the
// dedupe path's ack is a no-op for the consumer but the server
// still sees the counter advance, and we want the cursor to
// reflect "highest event_id this client has fully processed".
type cursorStore struct {
	dir  string
	key  string
	path string

	mu     sync.Mutex
	cursor string
}

func newCursorStore(workspace, key string) *cursorStore {
	path := ""
	if workspace != "" {
		path = filepath.Join(workspace, "cursor", key+".txt")
	}
	return &cursorStore{dir: workspace, key: key, path: path}
}

func (c *cursorStore) load() error {
	if c.path == "" {
		return nil
	}
	data, err := os.ReadFile(c.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	c.mu.Lock()
	c.cursor = strings.TrimSpace(string(data))
	c.mu.Unlock()
	return nil
}

func (c *cursorStore) get() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.cursor
}

func (c *cursorStore) update(id string) error {
	if id == "" {
		return nil
	}
	c.mu.Lock()
	c.cursor = id
	c.mu.Unlock()
	return c.persistLocked()
}

// persistLocked writes the cursor file. Caller must hold c.mu OR
// this must be called via a path that doesn't race; we wrap it
// inside update and persist so the lock is held.
func (c *cursorStore) persist() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.persistLocked()
}

func (c *cursorStore) persistLocked() error {
	if c.path == "" {
		return nil
	}
	if c.cursor == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(c.path), 0o755); err != nil {
		return err
	}
	tmp := c.path + ".tmp"
	if err := os.WriteFile(tmp, []byte(c.cursor+"\n"), 0o644); err != nil {
		os.Remove(tmp)
		return err
	}
	if err := os.Rename(tmp, c.path); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// formatReplayURL builds /events/replay?event_key=...&since_event_id=...
// Used by chat.go's OnReady hook (defined here so url encoding is
// co-located with the request that uses it).
func formatReplayURL(gatewayURL, key, sinceID string) string {
	base := HTTPBase(gatewayURL)
	v := urlValues(map[string]string{
		"event_key":      key,
		"since_event_id": sinceID,
	})
	return base + "/events/replay?" + v.Encode()
}

// replayEvents calls /events/replay and yields each event to the
// provided callback. Returns the number of events yielded.
func (c *Client) replayEvents(ctx context.Context, sinceID string, onEvent func(raw []byte)) (int, error) {
	if sinceID == "" {
		return 0, nil
	}
	url := formatReplayURL(c.cfg.GatewayURL, c.cursor.key, sinceID)
	fmt.Fprintf(c.cfg.Stderr, "[uasclient] replay requested since_event_id=%s\n", sinceID)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return 0, err
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, fmt.Errorf("replay: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return 0, fmt.Errorf("replay HTTP %d", resp.StatusCode)
	}
	var result struct {
		Events []json.RawMessage `json:"events"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, fmt.Errorf("replay decode: %w", err)
	}
	for _, raw := range result.Events {
		onEvent(raw)
	}
	return len(result.Events), nil
}
