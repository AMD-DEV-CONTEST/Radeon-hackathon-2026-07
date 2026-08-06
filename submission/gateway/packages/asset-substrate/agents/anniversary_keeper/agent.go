// Package anniversary_keeper implements the user/anniversary-keeper agent:
// consumes vault.Read + spark.Recall + lifememory.QueryByTag and sends
// collaboration requests to user/memory-keeper.
package anniversary_keeper

import (
	"fmt"

	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
	"github.com/konspace/unionagents-go/packages/asset-substrate/protocol"
)

// AnniversaryKeeper is the user/anniversary-keeper agent.
type AnniversaryKeeper struct {
	assetStore     protocol.AssetStore
	sparkStore     protocol.SparkStore
	memStore       lifememory.Store
	collaborator   Collaborator
	seatName       string
}

// Collaborator is the interface for sending collaboration requests to other agents.
type Collaborator interface {
	SendRequest(req *protocol.CollaborationRequest) (*protocol.CollaborationResponse, error)
}

// New creates a new AnniversaryKeeper agent.
func New(
	assetStore protocol.AssetStore,
	sparkStore protocol.SparkStore,
	memStore lifememory.Store,
	collaborator Collaborator,
) *AnniversaryKeeper {
	return &AnniversaryKeeper{
		assetStore:   assetStore,
		sparkStore:   sparkStore,
		memStore:     memStore,
		collaborator: collaborator,
		seatName:     "user/anniversary-keeper",
	}
}

// ── Core Logic ──────────────────────────────────────────────────────

// ReminderResult is the output of a reminder check.
type ReminderResult struct {
	AssetTitle       string                   `json:"asset_title"`
	SparkInsight     string                   `json:"spark_insight"`
	LifeMemories     []*lifememory.MemoryNode `json:"life_memories"`
	CollaborationLog []*protocol.CollaborationResponse `json:"collaboration_log,omitempty"`
}

// CheckReminder runs the full anniversary-keeper workflow:
// 1. vault.Read the anniversary asset
// 2. spark.Recall for anniversary context
// 3. lifememory.QueryByTag for related life memories
// 4. Send collaboration request to memory-keeper
func (ak *AnniversaryKeeper) CheckReminder(assetID string, memoryTags []string) (*ReminderResult, error) {
	result := &ReminderResult{}

	// 1. Asset Protocol: vault.Read
	asset, err := ak.assetStore.Read(assetID)
	if err != nil {
		return nil, fmt.Errorf("anniversary-keeper: vault.Read(%s): %w", assetID, err)
	}
	result.AssetTitle = asset.Title

	// 2. Spark Protocol: spark.Recall
	spark, err := ak.sparkStore.Recall("anniversary-reminder")
	if err == nil { // non-fatal if no spark found
		result.SparkInsight = spark.Insight
	} else {
		result.SparkInsight = "no spark available"
	}

	// 3. Life-Memory Protocol: QueryByTag
	memories, err := ak.memStore.QueryByTags(memoryTags)
	if err != nil {
		return nil, fmt.Errorf("anniversary-keeper: lifememory.QueryByTags(%v): %w", memoryTags, err)
	}
	result.LifeMemories = memories

	// 4. Collaboration: send request to memory-keeper
	if ak.collaborator != nil {
		resp, err := ak.collaborator.SendRequest(&protocol.CollaborationRequest{
			FromSeat: ak.seatName,
			ToSeat:   "user/memory-keeper",
			Action:   "query-life-memory-subgraph",
			Payload:  fmt.Sprintf("tags=%v,asset=%s", memoryTags, assetID),
			Context:  fmt.Sprintf("Anniversary reminder for %s (spark: %s)", asset.Title, result.SparkInsight),
		})
		if err != nil {
			result.CollaborationLog = append(result.CollaborationLog, &protocol.CollaborationResponse{
				FromSeat: "user/memory-keeper",
				Success:  false,
				Error:    err.Error(),
			})
		} else {
			result.CollaborationLog = append(result.CollaborationLog, resp)
		}
	}

	return result, nil
}

// SeatName returns this agent's seat name.
func (ak *AnniversaryKeeper) SeatName() string {
	return ak.seatName
}
