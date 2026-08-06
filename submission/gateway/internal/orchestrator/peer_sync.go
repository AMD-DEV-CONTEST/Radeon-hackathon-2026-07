package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

// peerCacheTTL is how long a successful peer fetch stays "healthy".
// Beyond this the peer is treated as invisible (partitioned) and its
// cached agents are dropped rather than served stale.
const peerCacheTTL = 5 * time.Minute

// PeerAgent is an agent reported by a peer Orchestrator. It is the
// cross-base discovery record: same shape as a local AgentSummary but
// stamped with PeerURL so a caller can tell which base it lives on.
//
// It is a transient, in-memory view — peer agents are NOT written to
// the local agents table. The local DB is the source of truth only for
// agents registered against THIS orchestrator; peers own their own rows.
type PeerAgent struct {
	ID             string                 `json:"id"`
	Name           string                 `json:"name"`
	AgentType      string                 `json:"agent_type"`
	HostID         string                 `json:"host_id"`
	Status         string                 `json:"status"`
	Capabilities   map[string]interface{} `json:"capabilities,omitempty"`
	MaxConcurrency int                    `json:"max_concurrency"`
	PeerURL        string                 `json:"peer_url"`
	LastSyncAt     time.Time              `json:"last_sync_at"`
}

// peerCacheEntry holds one peer's last-known agents and the time we
// last fetched them successfully. Mutated only under peerAgentCache.mu.
type peerCacheEntry struct {
	agents []PeerAgent
	fetchedAt time.Time
}

// peerAgentCache is the in-memory store of remote agent views. It is
// safe for concurrent use. Keyed by normalized peer URL.
type peerAgentCache struct {
	mu      sync.RWMutex
	entries map[string]peerCacheEntry
}

func newPeerAgentCache() *peerAgentCache {
	return &peerAgentCache{entries: map[string]peerCacheEntry{}}
}

// set records a successful fetch for peerURL at fetchedAt.
func (c *peerAgentCache) set(peerURL string, agents []PeerAgent, fetchedAt time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[peerURL] = peerCacheEntry{agents: agents, fetchedAt: fetchedAt}
}

// get returns the agents for peerURL and a healthy flag. A peer is
// healthy only if its last fetch is within peerCacheTTL of `now`.
// Expired peers return (nil, false) — stale agents are never served.
func (c *peerAgentCache) get(peerURL string, now time.Time) ([]PeerAgent, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	e, ok := c.entries[peerURL]
	if !ok {
		return nil, false
	}
	if now.Sub(e.fetchedAt) > peerCacheTTL {
		return nil, false
	}
	return e.agents, true
}

// allRemote returns every healthy peer's agents flattened into one
// slice, evaluated at `now`. Used by /agents/discover and the handoff
// evaluator to answer "who else can take this task?".
func (c *peerAgentCache) allRemote(now time.Time) []PeerAgent {
	c.mu.RLock()
	defer c.mu.RUnlock()
	var out []PeerAgent
	for _, e := range c.entries {
		if now.Sub(e.fetchedAt) > peerCacheTTL {
			continue
		}
		out = append(out, e.agents...)
	}
	return out
}

// peersHealthy returns the {peerURL: bool} health snapshot for the
// /agents?scope=all response.
func (c *peerAgentCache) peersHealthy(now time.Time) map[string]bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := map[string]bool{}
	for url, e := range c.entries {
		out[url] = now.Sub(e.fetchedAt) <= peerCacheTTL
	}
	return out
}

// globalPeerCache is the package-level cache RunPeerSyncLoop writes to
// and the /agents handlers read from. Set once at orchestrator startup.
var globalPeerCache = newPeerAgentCache()

// parsePeerOrchestrators splits the PEER_ORCHESTRATORS env value into
// normalized peer URLs. Whitespace and empty segments are dropped;
// trailing slashes are trimmed so "http://h:8000/" and "http://h:8000"
// compare equal as cache keys.
func parsePeerOrchestrators(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		return nil
	}
	var peers []string
	for _, seg := range strings.Split(raw, ",") {
		u := strings.TrimSpace(seg)
		u = strings.TrimRight(u, "/")
		if u == "" {
			continue
		}
		peers = append(peers, u)
	}
	return peers
}

// fetchPeerAgents GETs {peerURL}/agents?scope=local and decodes the
// standard AgentList response into []PeerAgent, stamping each with the
// PeerURL we fetched it from. Returns an error on any transport or
// decode failure; callers (the sync loop) tolerate it.
func fetchPeerAgents(ctx context.Context, hc *http.Client, peerURL string) ([]PeerAgent, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, peerURL+"/agents?scope=local", nil)
	if err != nil {
		return nil, err
	}
	resp, err := hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("peer %s returned HTTP %d", peerURL, resp.StatusCode)
	}
	var body struct {
		Agents []struct {
			ID             string                 `json:"id"`
			Name           string                 `json:"name"`
			AgentType      string                 `json:"agent_type"`
			HostID         string                 `json:"host_id"`
			Status         string                 `json:"status"`
			Capabilities   map[string]interface{} `json:"capabilities"`
			MaxConcurrency int                    `json:"max_concurrency"`
		} `json:"agents"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, fmt.Errorf("peer %s decode: %w", peerURL, err)
	}
	out := make([]PeerAgent, 0, len(body.Agents))
	for _, a := range body.Agents {
		out = append(out, PeerAgent{
			ID:             a.ID,
			Name:           a.Name,
			AgentType:      a.AgentType,
			HostID:         a.HostID,
			Status:         a.Status,
			Capabilities:   a.Capabilities,
			MaxConcurrency: a.MaxConcurrency,
			PeerURL:        peerURL,
		})
	}
	return out, nil
}

// syncOnce performs one fetch cycle across all peers, writing results
// into cache. A failure on one peer is logged and does not abort the
// cycle — the remaining peers still get cached.
func syncOnce(ctx context.Context, peers []string, cache *peerAgentCache, hc *http.Client) {
	now := time.Now()
	for _, peer := range peers {
		agents, err := fetchPeerAgents(ctx, hc, peer)
		if err != nil {
			slog.Warn("peer sync fetch failed", "peer", peer, "err", err)
			continue
		}
		cache.set(peer, agents, now)
		slog.Info("peer sync ok", "peer", peer, "agents", len(agents))
	}
}

// RunPeerSyncLoop is the background goroutine that keeps globalPeerCache
// fresh. It runs every 30s until ctx is cancelled. With no peers
// configured it returns immediately (single-base mode is a no-op).
func RunPeerSyncLoop(ctx context.Context) {
	peers := parsePeerOrchestrators(os.Getenv("PEER_ORCHESTRATORS"))
	if len(peers) == 0 {
		slog.Info("peer sync disabled (PEER_ORCHESTRATORS unset) — single-base mode")
		return
	}
	slog.Info("peer sync started", "peers", peers)

	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	// One immediate sync at startup so the cache isn't empty for 30s.
	syncOnce(ctx, peers, globalPeerCache, http.DefaultClient)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			syncOnce(ctx, peers, globalPeerCache, http.DefaultClient)
		}
	}
}
