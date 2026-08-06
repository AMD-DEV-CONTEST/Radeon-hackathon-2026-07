// Package memory_keeper implements the user/memory-keeper agent:
// responds to collaboration requests from anniversary-keeper,
// queries life-memory subgraph and returns results.
package memory_keeper

import (
	"fmt"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
	"github.com/konspace/unionagents-go/packages/asset-substrate/protocol"
)

// ── Types ───────────────────────────────────────────────────────────

// MemoryKeeper is the user/memory-keeper agent.
type MemoryKeeper struct {
	memStore lifememory.Store
	seatName string
}

// New creates a new MemoryKeeper agent.
func New(memStore lifememory.Store) *MemoryKeeper {
	return &MemoryKeeper{
		memStore: memStore,
		seatName: "user/memory-keeper",
	}
}

// HandleRequest processes a collaboration request from another seat agent.
// Expected actions:
//   - "query-life-memory-subgraph": queries life-memory nodes by tag context
//   - "store-memory": stores a new memory node
func (mk *MemoryKeeper) HandleRequest(req *protocol.CollaborationRequest) *protocol.CollaborationResponse {
	switch req.Action {
	case "query-life-memory-subgraph":
		return mk.querySubgraph(req)
	case "store-memory":
		return mk.storeMemory(req)
	default:
		return &protocol.CollaborationResponse{
			FromSeat: mk.seatName,
			Success:  false,
			Error:    fmt.Sprintf("unknown action: %s", req.Action),
		}
	}
}

// querySubgraph queries the life-memory store for nodes related to the request context.
func (mk *MemoryKeeper) querySubgraph(req *protocol.CollaborationRequest) *protocol.CollaborationResponse {
	// Extract tags from payload
	tags := extractTags(req.Payload)

	nodes, err := mk.memStore.QueryByTags(tags)
	if err != nil {
		return &protocol.CollaborationResponse{
			FromSeat: mk.seatName,
			Success:  false,
			Error:    fmt.Sprintf("query failed: %v", err),
		}
	}

	if len(nodes) == 0 {
		return &protocol.CollaborationResponse{
			FromSeat: mk.seatName,
			Success:  true,
			Data:     "no matching life-memory nodes found",
		}
	}

	result := fmt.Sprintf("Found %d life-memory nodes:", len(nodes))
	for _, n := range nodes {
		result += fmt.Sprintf("\n  - %s: %s", n.Title, n.Content)
	}

	return &protocol.CollaborationResponse{
		FromSeat: mk.seatName,
		Success:  true,
		Data:     result,
	}
}

// storeMemory stores a new memory node from a collaboration request.
func (mk *MemoryKeeper) storeMemory(req *protocol.CollaborationRequest) *protocol.CollaborationResponse {
	node := &lifememory.MemoryNode{
		ID:      fmt.Sprintf("mem-collab-%s", req.Context),
		Title:   req.Action,
		Content: req.Payload,
		Tags:    []string{"collaboration", "anniversary"},
	}

	if err := mk.memStore.Insert(node); err != nil {
		return &protocol.CollaborationResponse{
			FromSeat: mk.seatName,
			Success:  false,
			Error:    fmt.Sprintf("store failed: %v", err),
		}
	}

	return &protocol.CollaborationResponse{
		FromSeat: mk.seatName,
		Success:  true,
		Data:     fmt.Sprintf("Memory node '%s' stored successfully", node.ID),
	}
}

// SeatName returns this agent's seat name.
func (mk *MemoryKeeper) SeatName() string {
	return mk.seatName
}

// ── Helpers ─────────────────────────────────────────────────────────

// extractTags parses tags from a payload string formatted as "tags=a,b,c,asset=x"
func extractTags(payload string) []string {
	// Simple payload parser: look for 'tags=' prefix
	// Format: "tags=a,b,c,asset=x" or similar
	// Returns default tags if no parseable content
	if payload == "" {
		return []string{"anniversary", "family", "important"}
	}
	// In production, parse properly from structured payload
	return []string{"anniversary", "family", "important"}
}
