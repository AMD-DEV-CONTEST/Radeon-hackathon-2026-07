package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
)

// setupMemoryStore installs a fresh MemStore as the global memory store
// for the duration of the test, returning it so the test can assert on
// its contents directly. Also returns a cleanup func.
func setupMemoryStore(t *testing.T) *lifememory.MemStore {
	t.Helper()
	store := lifememory.NewMemStore()
	SetMemoryStore(store)
	t.Cleanup(func() { globalMemoryStore = nil })
	return store
}

// TestMemoryCreateHandler_Basic: POST /memory/nodes creates a node and
// returns its id. The node is then retrievable via the store.
func TestMemoryCreateHandler_Basic(t *testing.T) {
	setupMemoryStore(t)

	body, _ := json.Marshal(map[string]interface{}{
		"title": "test memory", "content": "hello world", "tags": []string{"a", "b"},
	})
	req := httptest.NewRequest(http.MethodPost, "/memory/nodes", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	MemoryCreateNode(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201. body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		ID    string   `json:"id"`
		Title string   `json:"title"`
		Tags  []string `json:"tags"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v (body=%s)", err, rec.Body.String())
	}
	if resp.ID == "" {
		t.Fatal("response missing id")
	}
	if resp.Title != "test memory" {
		t.Fatalf("title = %s, want 'test memory'", resp.Title)
	}

	// Verify it landed in the store.
	node, err := globalMemoryStore.GetByID(resp.ID)
	if err != nil {
		t.Fatalf("store GetByID: %v", err)
	}
	if node.Content != "hello world" {
		t.Fatalf("content = %s", node.Content)
	}
}

// TestMemoryCreateHandler_RejectsMissingTitle: title is required; a
// request without it gets 400, not a created empty node.
func TestMemoryCreateHandler_RejectsMissingTitle(t *testing.T) {
	setupMemoryStore(t)
	body, _ := json.Marshal(map[string]interface{}{"content": "no title"})
	req := httptest.NewRequest(http.MethodPost, "/memory/nodes", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	MemoryCreateNode(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

// TestMemoryQueryHandler_ByTag: GET /memory/nodes?tag=a returns only
// nodes tagged "a".
func TestMemoryQueryHandler_ByTag(t *testing.T) {
	setupMemoryStore(t)
	// Seed two nodes.
	for _, n := range []*lifememory.MemoryNode{
		{ID: "m1", Title: "t1", Content: "c1", Tags: []string{"a"}},
		{ID: "m2", Title: "t2", Content: "c2", Tags: []string{"b"}},
	} {
		if err := globalMemoryStore.Insert(n); err != nil {
			t.Fatalf("seed: %v", err)
		}
	}

	req := httptest.NewRequest(http.MethodGet, "/memory/nodes?tag=a", nil)
	rec := httptest.NewRecorder()
	MemoryQueryNodes(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200. body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		Nodes []*lifememory.MemoryNode `json:"nodes"`
		Count int                       `json:"count"`
	}
	json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Count != 1 || resp.Nodes[0].ID != "m1" {
		t.Fatalf("got %+v, want only m1", resp.Nodes)
	}
}

// TestMemoryQueryHandler_Search: GET /memory/nodes?q=keyword does a
// case-insensitive search over title+content.
func TestMemoryQueryHandler_Search(t *testing.T) {
	setupMemoryStore(t)
	globalMemoryStore.Insert(&lifememory.MemoryNode{ID: "m1", Title: "PostgreSQL Notes", Content: "x", Tags: []string{}})
	globalMemoryStore.Insert(&lifememory.MemoryNode{ID: "m2", Title: "other", Content: "mentions postgresql here", Tags: []string{}})

	req := httptest.NewRequest(http.MethodGet, "/memory/nodes?q=postgresql", nil)
	rec := httptest.NewRecorder()
	MemoryQueryNodes(rec, req)

	var resp struct {
		Count int `json:"count"`
	}
	json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp.Count != 2 {
		t.Fatalf("search count = %d, want 2 (title + content match)", resp.Count)
	}
}

// TestMemoryGetNodeHandler: GET /memory/nodes/{id} returns the node;
// unknown id → 404.
func TestMemoryGetNodeHandler(t *testing.T) {
	setupMemoryStore(t)
	globalMemoryStore.Insert(&lifememory.MemoryNode{ID: "m1", Title: "T", Content: "C", Tags: []string{"x"}})

	req := httptest.NewRequest(http.MethodGet, "/memory/nodes/m1", nil)
	req.SetPathValue("nodeID", "m1")
	rec := httptest.NewRecorder()
	MemoryGetNode(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200. body=%s", rec.Code, rec.Body.String())
	}

	// Unknown id.
	req2 := httptest.NewRequest(http.MethodGet, "/memory/nodes/zzz", nil)
	req2.SetPathValue("nodeID", "zzz")
	rec2 := httptest.NewRecorder()
	MemoryGetNode(rec2, req2)
	if rec2.Code != http.StatusNotFound {
		t.Fatalf("unknown id status = %d, want 404", rec2.Code)
	}
}

// TestMemoryDeleteHandler: DELETE removes the node; second delete → 404.
func TestMemoryDeleteHandler(t *testing.T) {
	setupMemoryStore(t)
	globalMemoryStore.Insert(&lifememory.MemoryNode{ID: "m1", Title: "T", Content: "C", Tags: []string{}})

	req := httptest.NewRequest(http.MethodDelete, "/memory/nodes/m1", nil)
	req.SetPathValue("nodeID", "m1")
	rec := httptest.NewRecorder()
	MemoryDeleteNode(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("delete status = %d, want 200. body=%s", rec.Code, rec.Body.String())
	}
	if count, _ := globalMemoryStore.Count(); count != 0 {
		t.Fatalf("count after delete = %d, want 0", count)
	}

	// Second delete → 404.
	rec2 := httptest.NewRecorder()
	MemoryDeleteNode(rec2, req)
	if rec2.Code != http.StatusNotFound {
		t.Fatalf("second delete status = %d, want 404", rec2.Code)
	}
}

// TestMemoryCreate_FiresCreatedHook: creating a node via POST fires
// the memory.created event. We register a capturing hook and assert.
func TestMemoryCreate_FiresCreatedHook(t *testing.T) {
	setupMemoryStore(t)

	var captured map[string]interface{}
	globalHooks.Register("memory.created", func(ctx context.Context, e map[string]interface{}) error {
		captured = e
		return nil
	})

	body, _ := json.Marshal(map[string]interface{}{
		"title": "hooked", "content": "c", "tags": []string{"t"},
	})
	req := httptest.NewRequest(http.MethodPost, "/memory/nodes", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	MemoryCreateNode(rec, req)

	if captured == nil {
		t.Fatal("memory.created hook did not fire")
	}
	if captured["node_id"] == "" {
		t.Fatal("hook event missing node_id")
	}
}

// TestMemoryDelete_FiresDeletedHook: deleting fires memory.deleted.
func TestMemoryDelete_FiresDeletedHook(t *testing.T) {
	setupMemoryStore(t)
	globalMemoryStore.Insert(&lifememory.MemoryNode{ID: "m1", Title: "T", Content: "C", Tags: []string{}})

	var captured map[string]interface{}
	globalHooks.Register("memory.deleted", func(ctx context.Context, e map[string]interface{}) error {
		captured = e
		return nil
	})

	req := httptest.NewRequest(http.MethodDelete, "/memory/nodes/m1", nil)
	req.SetPathValue("nodeID", "m1")
	MemoryDeleteNode(httptest.NewRecorder(), req)

	if captured == nil || captured["node_id"] != "m1" {
		t.Fatalf("memory.deleted hook event = %+v, want node_id=m1", captured)
	}
}
