package orchestrator

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// TestAgentList_ScopeAll_IncludesRemote: with scope=all, the /agents
// response carries "remote" and "peers_healthy" fields sourced from
// the peer cache. We pre-seed the cache directly (no network) and
// assert the handler surfaces them. PG-backed — skips without a DB.
func TestAgentList_ScopeAll_IncludesRemote(t *testing.T) {
	pool := testPool(t)
	SetPool(pool)
	t.Cleanup(func() { SetPool(nil) })

	// Seed one remote agent from a fake peer.
	globalPeerCache.set("http://fake-peer:8000",
		[]PeerAgent{{ID: "remote-1", Name: "remote-alpha", AgentType: "worker", Status: "online", PeerURL: "http://fake-peer:8000"}},
		time.Now())

	req := httptest.NewRequest(http.MethodGet, "/agents?scope=all", nil)
	rec := httptest.NewRecorder()
	AgentList(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200. body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		Remote       []PeerAgent      `json:"remote"`
		PeersHealthy map[string]bool  `json:"peers_healthy"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v (body=%s)", err, rec.Body.String())
	}
	if len(resp.Remote) != 1 || resp.Remote[0].ID != "remote-1" {
		t.Fatalf("remote = %+v, want [remote-1]", resp.Remote)
	}
	if !resp.PeersHealthy["http://fake-peer:8000"] {
		t.Fatalf("peers_healthy = %+v, want fake-peer healthy", resp.PeersHealthy)
	}
}

// TestAgentList_ScopeLocal_OmitsRemoteFields: the default (local) path
// must NOT add remote/peers_healthy — backward compatibility for
// existing callers that would break on unexpected fields. PG-backed.
func TestAgentList_ScopeLocal_OmitsRemoteFields(t *testing.T) {
	pool := testPool(t)
	SetPool(pool)
	t.Cleanup(func() { SetPool(nil) })

	globalPeerCache.set("http://fake-peer:8000",
		[]PeerAgent{{ID: "remote-1"}}, time.Now())

	req := httptest.NewRequest(http.MethodGet, "/agents", nil) // no scope param
	rec := httptest.NewRecorder()
	AgentList(rec, req)

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(rec.Body.Bytes(), &raw); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if _, present := raw["remote"]; present {
		t.Fatal("scope=local must not include 'remote' field (backward compat)")
	}
	if _, present := raw["peers_healthy"]; present {
		t.Fatal("scope=local must not include 'peers_healthy' field (backward compat)")
	}
}

// TestAgentDiscover_GroupsByType: /agents/discover returns agents
// grouped by agent_type, with local and remote merged into the same
// buckets. We seed a remote worker and (via PG) at least the local
// agents the DB already holds; assert the worker bucket is non-empty
// and the remote one is present. PG-backed.
func TestAgentDiscover_GroupsByType(t *testing.T) {
	pool := testPool(t)
	SetPool(pool)
	t.Cleanup(func() { SetPool(nil) })

	globalPeerCache.set("http://fake-peer:8000",
		[]PeerAgent{{ID: "remote-worker-1", Name: "rw", AgentType: "worker", Status: "online", PeerURL: "http://fake-peer:8000"}},
		time.Now())

	req := httptest.NewRequest(http.MethodGet, "/agents/discover", nil)
	rec := httptest.NewRecorder()
	AgentDiscover(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200. body=%s", rec.Code, rec.Body.String())
	}
	var resp struct {
		ByType map[string][]map[string]interface{} `json:"by_type"`
		ByBase map[string]int                       `json:"by_base"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode: %v (body=%s)", err, rec.Body.String())
	}
	workers, ok := resp.ByType["worker"]
	if !ok {
		t.Fatalf("by_type missing 'worker' bucket: %+v", resp.ByType)
	}
	foundRemote := false
	for _, w := range workers {
		if w["id"] == "remote-worker-1" {
			foundRemote = true
			break
		}
	}
	if !foundRemote {
		t.Fatalf("remote-worker-1 not in worker bucket: %+v", workers)
	}
	if resp.ByBase["http://fake-peer:8000"] != 1 {
		t.Fatalf("by_base peer count = %d, want 1", resp.ByBase["http://fake-peer:8000"])
	}
}
