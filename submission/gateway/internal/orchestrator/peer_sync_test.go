package orchestrator

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// TestParsePeerOrchestrators: the env var is a comma-separated URL list.
// Whitespace is trimmed, empty segments dropped, trailing slash normalized
// away so "http://h6:8000/" and "http://h6:8000" are the same peer.
func TestParsePeerOrchestrators(t *testing.T) {
	cases := []struct {
		in   string
		want []string
	}{
		{"", nil},
		{"http://h6:8000", []string{"http://h6:8000"}},
		{"http://h6:8000, http://h5:8000", []string{"http://h6:8000", "http://h5:8000"}},
		{"http://h6:8000/,, http://h5:8000/", []string{"http://h6:8000", "http://h5:8000"}},
		{"   ", nil},
	}
	for _, c := range cases {
		got := parsePeerOrchestrators(c.in)
		if len(got) != len(c.want) {
			t.Fatalf("parsePeerOrchestrators(%q) = %v, want %v", c.in, got, c.want)
		}
		for i := range got {
			if got[i] != c.want[i] {
				t.Fatalf("parsePeerOrchestrators(%q)[%d] = %q, want %q", c.in, i, got[i], c.want[i])
			}
		}
	}
}

// TestFetchPeerAgents_ParsesAgentList: a peer's GET /agents returns the
// standard {agents:[...], count} shape; fetchPeerAgents must decode it
// into []PeerAgent with PeerURL stamped from the peer we asked.
func TestFetchPeerAgents_ParsesAgentList(t *testing.T) {
	peer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/agents" || r.URL.Query().Get("scope") != "local" {
			t.Errorf("unexpected request: %s?%s", r.URL.Path, r.URL.RawQuery)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"agents": []map[string]interface{}{
				{"id": "a1", "name": "alpha", "agent_type": "worker", "host_id": "h6", "status": "online", "max_concurrency": 2},
				{"id": "a2", "name": "beta", "agent_type": "keeper", "host_id": "h6", "status": "online", "max_concurrency": 1},
			},
			"count": 2,
		})
	}))
	defer peer.Close()

	got, err := fetchPeerAgents(context.Background(), http.DefaultClient, peer.URL)
	if err != nil {
		t.Fatalf("fetchPeerAgents: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("got %d agents, want 2", len(got))
	}
	if got[0].PeerURL != peer.URL {
		t.Fatalf("PeerURL = %q, want %q (must be stamped by fetcher)", got[0].PeerURL, peer.URL)
	}
	if got[0].ID != "a1" || got[0].Name != "alpha" || got[0].AgentType != "worker" {
		t.Fatalf("first agent decoded wrong: %+v", got[0])
	}
}

// TestFetchPeerAgents_NetworkError: a dead/unreachable peer returns an
// error but does NOT panic. The sync loop relies on this to tolerate
// network partitions.
func TestFetchPeerAgents_NetworkError(t *testing.T) {
	_, err := fetchPeerAgents(context.Background(), &http.Client{Timeout: 1 * time.Second}, "http://127.0.0.1:1/nope")
	if err == nil {
		t.Fatal("expected error for unreachable peer, got nil")
	}
}

// TestPeerAgentCache_SetAndGet: after a successful sync, agents are
// retrievable by peer URL; the cache reports the peer as healthy.
func TestPeerAgentCache_SetAndGet(t *testing.T) {
	c := newPeerAgentCache()
	now := time.Now()
	c.set("http://h6:8000", []PeerAgent{{ID: "a1", Name: "alpha", PeerURL: "http://h6:8000"}}, now)

	agents, healthy := c.get("http://h6:8000", now)
	if !healthy {
		t.Fatal("peer should be healthy immediately after set")
	}
	if len(agents) != 1 || agents[0].ID != "a1" {
		t.Fatalf("get returned %+v, want [a1]", agents)
	}
}

// TestPeerAgentCache_TTLExpiry: a cached peer older than the TTL is
// reported as unhealthy AND its agents are cleared (stale data must not
// be served — a partitioned peer is "invisible", not "frozen in time").
func TestPeerAgentCache_TTLExpiry(t *testing.T) {
	c := newPeerAgentCache()
	stale := time.Now().Add(-10 * time.Minute)
	c.set("http://h6:8000", []PeerAgent{{ID: "a1", Name: "alpha"}}, stale)

	agents, healthy := c.get("http://h6:8000", time.Now())
	if healthy {
		t.Fatal("peer older than TTL should be unhealthy")
	}
	if len(agents) != 0 {
		t.Fatalf("stale peer should return empty agents, got %d", len(agents))
	}
}

// TestPeerAgentCache_AllRemote: a snapshot of every peer's agents
// flattened into one slice, used by /agents/discover and the 2.5
// handoff evaluator.
func TestPeerAgentCache_AllRemote(t *testing.T) {
	c := newPeerAgentCache()
	now := time.Now()
	c.set("http://h6:8000", []PeerAgent{{ID: "a1"}, {ID: "a2"}}, now)
	c.set("http://h5:8000", []PeerAgent{{ID: "b1"}}, now)
	// An expired peer contributes nothing.
	c.set("http://h7:8000", []PeerAgent{{ID: "c1"}}, now.Add(-10*time.Minute))

	all := c.allRemote(now)
	if len(all) != 3 {
		t.Fatalf("allRemote returned %d agents, want 3 (a1,a2,b1; c1 expired)", len(all))
	}
	seen := map[string]bool{}
	for _, a := range all {
		seen[a.ID] = true
	}
	for _, want := range []string{"a1", "a2", "b1"} {
		if !seen[want] {
			t.Fatalf("allRemote missing %s", want)
		}
	}
	if seen["c1"] {
		t.Fatal("expired peer's agent c1 should not appear in allRemote")
	}
}

// TestRunPeerSyncLoop_OneCycle: drive a single sync cycle against a
// mock peer and confirm the cache is populated. We don't test the
// full long-running loop (that's a goroutine with a ticker); we test
// syncOnce, the per-cycle function RunPeerSyncLoop calls.
func TestSyncOnce_PopulatesCache(t *testing.T) {
	peer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"agents": []map[string]interface{}{
				{"id": "a1", "name": "alpha", "agent_type": "worker", "status": "online"},
			},
			"count": 1,
		})
	}))
	defer peer.Close()

	cache := newPeerAgentCache()
	syncOnce(context.Background(), []string{peer.URL}, cache, &http.Client{Timeout: 2 * time.Second})

	agents, healthy := cache.get(peer.URL, time.Now())
	if !healthy {
		t.Fatal("after syncOnce peer should be healthy")
	}
	if len(agents) != 1 || agents[0].ID != "a1" {
		t.Fatalf("cache after syncOnce = %+v, want [a1]", agents)
	}
}

// TestSyncOnce_ToleratesUnreachablePeer: one dead peer among several
// must not abort the whole cycle — the live peers still get cached.
func TestSyncOnce_ToleratesUnreachablePeer(t *testing.T) {
	live := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"agents": []map[string]interface{}{{"id": "live1"}}, "count": 1,
		})
	}))
	defer live.Close()

	cache := newPeerAgentCache()
	dead := "http://127.0.0.1:1"
	syncOnce(context.Background(), []string{dead, live.URL}, cache, &http.Client{Timeout: 1 * time.Second})

	if _, healthy := cache.get(dead, time.Now()); healthy {
		t.Fatal("dead peer should not be healthy")
	}
	agents, healthy := cache.get(live.URL, time.Now())
	if !healthy || len(agents) != 1 {
		t.Fatalf("live peer should be cached despite dead sibling: healthy=%v agents=%d", healthy, len(agents))
	}
}
