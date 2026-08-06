package memory_keeper

import (
	"testing"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
	"github.com/konspace/unionagents-go/packages/asset-substrate/protocol"
)

func TestMemoryKeeperHandleQuery(t *testing.T) {
	memStore := lifememory.NewMemStore()
	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-001",
		Title:   "Anniversary Date",
		Content: "June 22",
		Tags:    []string{"anniversary", "family"},
	})
	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-002",
		Title:   "Gift Ideas",
		Content: "She mentioned wanting a new watch",
		Tags:    []string{"anniversary", "gift"},
	})

	keeper := New(memStore)

	req := &protocol.CollaborationRequest{
		FromSeat: "user/anniversary-keeper",
		ToSeat:   "user/memory-keeper",
		Action:   "query-life-memory-subgraph",
		Payload:  "tags=anniversary,family",
		Context:  "Anniversary reminder",
	}

	resp := keeper.HandleRequest(req)
	if !resp.Success {
		t.Fatalf("expected success, got error: %s", resp.Error)
	}
	if resp.Data == "" {
		t.Fatal("expected non-empty response data")
	}
}

func TestMemoryKeeperHandleStore(t *testing.T) {
	memStore := lifememory.NewMemStore()
	keeper := New(memStore)

	req := &protocol.CollaborationRequest{
		FromSeat: "user/anniversary-keeper",
		ToSeat:   "user/memory-keeper",
		Action:   "store-memory",
		Payload:  "Remember to buy flowers",
		Context:  "anniversary-prep",
	}

	resp := keeper.HandleRequest(req)
	if !resp.Success {
		t.Fatalf("expected success, got error: %s", resp.Error)
	}
	if resp.Data == "" {
		t.Fatal("expected non-empty response data")
	}

	// Verify the node was stored
	count, _ := memStore.Count()
	if count != 1 {
		t.Errorf("expected 1 stored node, got %d", count)
	}
}

func TestMemoryKeeperUnknownAction(t *testing.T) {
	memStore := lifememory.NewMemStore()
	keeper := New(memStore)

	req := &protocol.CollaborationRequest{
		FromSeat: "user/anniversary-keeper",
		ToSeat:   "user/memory-keeper",
		Action:   "unknown-action",
	}

	resp := keeper.HandleRequest(req)
	if resp.Success {
		t.Error("expected failure for unknown action")
	}
}

func TestMemoryKeeperEmptyStore(t *testing.T) {
	memStore := lifememory.NewMemStore()
	keeper := New(memStore)

	req := &protocol.CollaborationRequest{
		FromSeat: "user/anniversary-keeper",
		ToSeat:   "user/memory-keeper",
		Action:   "query-life-memory-subgraph",
		Payload:  "tags=nonexistent",
	}

	resp := keeper.HandleRequest(req)
	if !resp.Success {
		t.Fatalf("expected success even with no results: %s", resp.Error)
	}
	if resp.Data != "no matching life-memory nodes found" {
		t.Errorf("expected 'no matching' message, got '%s'", resp.Data)
	}
}

func TestMemoryKeeperSeatName(t *testing.T) {
	keeper := New(nil)
	if keeper.SeatName() != "user/memory-keeper" {
		t.Errorf("expected user/memory-keeper, got %s", keeper.SeatName())
	}
}
