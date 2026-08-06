package orchestrator

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
)

// Phase 3.5: REST API for life-memory nodes.
//
// These handlers expose the global memory store (SetMemoryStore at
// startup — PGStore when DB is up, MemStore fallback) to agents and
// external callers. Writes fire memory.created / memory.deleted events
// through the 3.3 HookRegistry so future hooks (e.g. "memory created →
// notify cockpit") plug in without touching this file.
//
// All handlers degrade to 503 when no store is wired (tests that don't
// call SetMemoryStore, or a misconfigured startup).

// memoryNodeRequest is the POST body for creating a node.
type memoryNodeRequest struct {
	Title   string   `json:"title"`
	Content string   `json:"content"`
	Tags    []string `json:"tags,omitempty"`
}

// MemoryCreateNode handles POST /memory/nodes.
func MemoryCreateNode(w http.ResponseWriter, r *http.Request) {
	store := globalMemoryStore
	if store == nil {
		http.Error(w, `{"error":"memory store not initialized"}`, http.StatusServiceUnavailable)
		return
	}
	var req memoryNodeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid body"}`, http.StatusBadRequest)
		return
	}
	if req.Title == "" {
		http.Error(w, `{"error":"title is required"}`, http.StatusBadRequest)
		return
	}
	// Generate a client-side ID so MemStore and PGStore behave the same
	// (MemStore requires a non-empty ID; PGStore would otherwise gen a
	// UUID, diverging the two). time + counter keeps it unique within a
	// process without importing uuid.
	node := &lifememory.MemoryNode{
		ID:      "mem_" + strconv.FormatInt(time.Now().UnixNano(), 36),
		Title:   req.Title,
		Content: req.Content,
		Tags:    req.Tags,
	}
	if err := store.Insert(node); err != nil {
		slog.Error("memory create insert", "err", err)
		http.Error(w, `{"error":"store error"}`, http.StatusInternalServerError)
		return
	}

	// Fire memory.created so downstream hooks (3.3 registry) can react.
	globalHooks.Fire(r.Context(), "memory.created", map[string]interface{}{
		"node_id": node.ID,
		"title":   node.Title,
		"tags":    node.Tags,
	})

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	writeJSON(w, node)
}

// MemoryQueryNodes handles GET /memory/nodes with optional filters.
// Precedence: q (search) > tag+time > tag > time > all.
//
//	?tag=xxx          nodes with that tag
//	?from=RFC3339&to=RFC3339   nodes created in [from,to)
//	?q=keyword        case-insensitive title/content search
//	?limit=50         (reserved; MemStore ignores, PGStore caps via SQL)
func MemoryQueryNodes(w http.ResponseWriter, r *http.Request) {
	store := globalMemoryStore
	if store == nil {
		http.Error(w, `{"error":"memory store not initialized"}`, http.StatusServiceUnavailable)
		return
	}
	// TimelineStore query methods only exist on the extended interface.
	// A bare Store (legacy) is handled by falling back to QueryByTag.
	ts, hasTimeline := store.(lifememory.TimelineStore)

	q := r.URL.Query().Get("q")
	tag := r.URL.Query().Get("tag")
	from := parseTimeQuery(r, "from")
	to := parseTimeQuery(r, "to")

	var nodes []*lifememory.MemoryNode
	var err error
	switch {
	case q != "" && hasTimeline:
		nodes, err = ts.Search(q)
	case tag != "" && hasTimeline && (from != nil || to != nil):
		nodes, err = ts.QueryByTagAndTimeRange(tag, orZero(from), orZero(to))
	case tag != "":
		nodes, err = store.QueryByTag(tag)
	case hasTimeline && (from != nil || to != nil):
		nodes, err = ts.QueryByTimeRange(orZero(from), orZero(to))
	case hasTimeline:
		// No filter: return all via an open time range.
		nodes, err = ts.QueryByTimeRange(time.Time{}, time.Time{})
	default:
		// Bare Store with no timeline methods and no tag: nothing to
		// offer. Return empty rather than erroring — the caller asked
		// for "everything" and we can't enumerate.
		nodes = []*lifememory.MemoryNode{}
	}
	if err != nil {
		slog.Error("memory query", "err", err)
		http.Error(w, `{"error":"store error"}`, http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	writeJSON(w, map[string]interface{}{
		"nodes": nodes,
		"count": len(nodes),
	})
}

// MemoryGetNode handles GET /memory/nodes/{nodeID}.
func MemoryGetNode(w http.ResponseWriter, r *http.Request) {
	store := globalMemoryStore
	if store == nil {
		http.Error(w, `{"error":"memory store not initialized"}`, http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("nodeID")
	if nodeID == "" {
		http.Error(w, `{"error":"nodeID required"}`, http.StatusBadRequest)
		return
	}
	node, err := store.GetByID(nodeID)
	if err == lifememory.ErrNodeNotFound {
		http.Error(w, `{"error":"node not found"}`, http.StatusNotFound)
		return
	}
	if err != nil {
		slog.Error("memory get", "err", err)
		http.Error(w, `{"error":"store error"}`, http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	writeJSON(w, node)
}

// MemoryDeleteNode handles DELETE /memory/nodes/{nodeID}.
func MemoryDeleteNode(w http.ResponseWriter, r *http.Request) {
	store := globalMemoryStore
	if store == nil {
		http.Error(w, `{"error":"memory store not initialized"}`, http.StatusServiceUnavailable)
		return
	}
	nodeID := r.PathValue("nodeID")
	if nodeID == "" {
		http.Error(w, `{"error":"nodeID required"}`, http.StatusBadRequest)
		return
	}
	if err := store.Delete(nodeID); err == lifememory.ErrNodeNotFound {
		http.Error(w, `{"error":"node not found"}`, http.StatusNotFound)
		return
	} else if err != nil {
		slog.Error("memory delete", "err", err)
		http.Error(w, `{"error":"store error"}`, http.StatusInternalServerError)
		return
	}
	globalHooks.Fire(r.Context(), "memory.deleted", map[string]interface{}{
		"node_id": nodeID,
	})
	w.Header().Set("Content-Type", "application/json")
	writeJSON(w, map[string]string{"status": "deleted", "node_id": nodeID})
}

// parseTimeQuery parses an RFC3339 query param, returning nil when the
// param is absent or malformed (malformed → nil rather than 400 so a
// bad `from` doesn't block the whole query; the caller just sees no
// time filter).
func parseTimeQuery(r *http.Request, key string) *time.Time {
	v := r.URL.Query().Get(key)
	if v == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, v)
	if err != nil {
		return nil
	}
	return &t
}

// orZero dereferences a *time.Time to its value, or the zero time when
// nil. Used to feed QueryByTimeRange's non-pointer signature.
func orZero(t *time.Time) time.Time {
	if t == nil {
		return time.Time{}
	}
	return *t
}
