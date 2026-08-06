package anniversary_keeper

import (
	"testing"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
	"github.com/konspace/unionagents-go/packages/asset-substrate/protocol"
)

// ── Mock Collaborator ──────────────────────────────────────────────

type mockCollaborator struct {
	response *protocol.CollaborationResponse
	err      error
}

func (m *mockCollaborator) SendRequest(req *protocol.CollaborationRequest) (*protocol.CollaborationResponse, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.response, nil
}

func TestAnniversaryKeeperCheckReminder(t *testing.T) {
	// Setup stores
	assetStore := protocol.NewMemAssetStore()
	sparkStore := protocol.NewMemSparkStore()
	memStore := lifememory.NewMemStore()

	// Seed data
	assetStore.Put(&protocol.AssetLedgerEntry{
		AssetID:   "anniv-001",
		AssetType: protocol.AssetCredential,
		Title:     "Wedding Anniversary",
		Owner:     "user/anniversary-keeper",
	})

	sparkStore.Put(protocol.Spark{
		ID:      "spark-001",
		Context: "anniversary-reminder",
		Insight: "Prepare a thoughtful gift and plan a special dinner",
		Score:   0.95,
	})

	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-001",
		Title:   "Anniversary Date",
		Content: "June 22",
		Tags:    []string{"anniversary", "family", "important"},
	})
	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-002",
		Title:   "Favorite Restaurant",
		Content: "The Italian Place - she loves their pasta",
		Tags:    []string{"anniversary", "food", "favorite"},
	})

	collab := &mockCollaborator{
		response: &protocol.CollaborationResponse{
			FromSeat: "user/memory-keeper",
			Success:  true,
			Data:     "Found 2 related memory nodes",
		},
	}

	agent := New(assetStore, sparkStore, memStore, collab)

	result, err := agent.CheckReminder("anniv-001", []string{"anniversary", "family"})
	if err != nil {
		t.Fatalf("CheckReminder failed: %v", err)
	}

	if result.AssetTitle != "Wedding Anniversary" {
		t.Errorf("expected 'Wedding Anniversary', got '%s'", result.AssetTitle)
	}

	if result.SparkInsight == "" {
		t.Error("expected non-empty spark insight")
	}
	if result.SparkInsight != "Prepare a thoughtful gift and plan a special dinner" {
		t.Errorf("unexpected spark: %s", result.SparkInsight)
	}

	if len(result.LifeMemories) != 1 { // only mem-001 has both "anniversary" AND "family"
		t.Errorf("expected 1 life-memory matching both tags, got %d", len(result.LifeMemories))
	}
	if len(result.LifeMemories) > 0 && result.LifeMemories[0].ID != "mem-001" {
		t.Errorf("expected mem-001, got %s", result.LifeMemories[0].ID)
	}

	if len(result.CollaborationLog) != 1 {
		t.Errorf("expected 1 collaboration log entry, got %d", len(result.CollaborationLog))
	} else {
		if !result.CollaborationLog[0].Success {
			t.Errorf("collaboration should succeed: %s", result.CollaborationLog[0].Error)
		}
	}
}

func TestAnniversaryKeeperAssetNotFound(t *testing.T) {
	assetStore := protocol.NewMemAssetStore()
	sparkStore := protocol.NewMemSparkStore()
	memStore := lifememory.NewMemStore()

	agent := New(assetStore, sparkStore, memStore, nil)

	_, err := agent.CheckReminder("nonexistent", []string{"test"})
	if err == nil {
		t.Fatal("expected error for nonexistent asset")
	}
}

func TestAnniversaryKeeperCollaborationFailure(t *testing.T) {
	assetStore := protocol.NewMemAssetStore()
	sparkStore := protocol.NewMemSparkStore()
	memStore := lifememory.NewMemStore()

	assetStore.Put(&protocol.AssetLedgerEntry{
		AssetID: "anniv-001",
		Title:   "Test",
		Owner:   "user/anniversary-keeper",
	})

	collab := &mockCollaborator{
		err: nil,
		response: &protocol.CollaborationResponse{
			FromSeat: "user/memory-keeper",
			Success:  false,
			Error:    "simulated failure",
		},
	}

	agent := New(assetStore, sparkStore, memStore, collab)
	result, err := agent.CheckReminder("anniv-001", []string{"test"})
	if err != nil {
		t.Fatalf("CheckReminder should not fail on collab error: %v", err)
	}

	if len(result.CollaborationLog) == 0 {
		t.Error("expected collaboration log entry")
	} else if result.CollaborationLog[0].Success {
		t.Error("expected collaboration failure")
	}
}

func TestAnniversaryKeeperSeatName(t *testing.T) {
	agent := New(nil, nil, nil, nil)
	if agent.SeatName() != "user/anniversary-keeper" {
		t.Errorf("expected user/anniversary-keeper, got %s", agent.SeatName())
	}
}
