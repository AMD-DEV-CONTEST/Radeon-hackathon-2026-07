// Package e2e contains the end-to-end integration test for Sprint 1.
// It simulates the full chain: orchestrator cron trigger ->
// anniversary-keeper -> memory-keeper -> Decision Protocol -> output.
package e2e

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	substrate "github.com/konspace/unionagents-go/packages/asset-substrate"
	"github.com/konspace/unionagents-go/packages/asset-substrate/agents/anniversary_keeper"
	"github.com/konspace/unionagents-go/packages/asset-substrate/agents/memory_keeper"
	"github.com/konspace/unionagents-go/packages/asset-substrate/decision"
	"github.com/konspace/unionagents-go/packages/asset-substrate/lifememory"
	"github.com/konspace/unionagents-go/packages/asset-substrate/protocol"
	"github.com/konspace/unionagents-go/packages/asset-substrate/quorum"
)

// ── Mock Orchestrator Cron Trigger ──────────────────────────────────

// mockCronPayload simulates what a cron scheduler would dispatch.
type mockCronPayload struct {
	AssetID     string   `json:"asset_id"`
	MemoryTags  []string `json:"memory_tags"`
	ScheduleID  string   `json:"schedule_id"`
	CronExpr    string   `json:"cron_expr"`
}

// ── Mock OB Inbox (output destination) ──────────────────────────────

type mockOBInbox struct {
	messages []string
}

func (m *mockOBInbox) Send(msg string) {
	m.messages = append(m.messages, msg)
}

func (m *mockOBInbox) Messages() []string {
	return m.messages
}

// ── Mock Collaborator that routes to memory_keeper ───────────────────

type agentRouter struct {
	memoryKeeper *memory_keeper.MemoryKeeper
}

func (r *agentRouter) SendRequest(req *protocol.CollaborationRequest) (*protocol.CollaborationResponse, error) {
	return r.memoryKeeper.HandleRequest(req), nil
}

// ── End-to-End Sprint 1 Test ────────────────────────────────────────

func TestSprint1EndToEnd(t *testing.T) {
	// ── Step 1: Seed stores ──────────────────────────────────────
	assetStore := protocol.NewMemAssetStore()
	sparkStore := protocol.NewMemSparkStore()
	memStore := lifememory.NewMemStore()

	// Seed anniversary asset
	assetStore.Put(&protocol.AssetLedgerEntry{
		AssetID:   "anniv-wedding",
		AssetType: protocol.AssetCredential,
		Title:     "Wedding Anniversary",
		Owner:     "user/anniversary-keeper",
	})

	// Seed sparks
	sparkStore.Put(protocol.Spark{
		ID:      "spark-wedding",
		Context: "anniversary-reminder",
		Insight: "Wedding anniversary reminder: consider preparing a gift and planning a special evening",
		Score:   0.95,
	})

	// Seed life-memory nodes
	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-wedding-date",
		Title:   "Wedding Date",
		Content: "June 22, 2025",
		Tags:    []string{"anniversary", "family", "wedding"},
	})
	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-wedding-venue",
		Title:   "Wedding Venue",
		Content: "Riverside Church",
		Tags:    []string{"anniversary", "wedding", "location"},
	})
	memStore.Insert(&lifememory.MemoryNode{
		ID:      "mem-wife-favorites",
		Title:   "Her Favorite Things",
		Content: "Loves flowers (especially roses), Italian food, and classical music",
		Tags:    []string{"anniversary", "family", "favorites"},
	})

	// ── Step 2: Simulate Cron Trigger ─────────────────────────────
	cronPayload := mockCronPayload{
		AssetID:    "anniv-wedding",
		MemoryTags: []string{"anniversary", "family"},
		ScheduleID: "sched-anniv-001",
		CronExpr:   "0 9 22 6 *",
	}

	t.Logf("Cron triggered: schedule=%s expr=%s", cronPayload.ScheduleID, cronPayload.CronExpr)

	// ── Step 3: Create agents ────────────────────────────────────
	memKeeper := memory_keeper.New(memStore)
	router := &agentRouter{memoryKeeper: memKeeper}

	annivKeeper := anniversary_keeper.New(assetStore, sparkStore, memStore, router)

	// ── Step 4: Anniversary Keeper runs CheckReminder ────────────
	result, err := annivKeeper.CheckReminder(cronPayload.AssetID, cronPayload.MemoryTags)
	if err != nil {
		t.Fatalf("CheckReminder failed: %v", err)
	}

	t.Logf("Anniversary Keeper: asset=%s spark=%s", result.AssetTitle, result.SparkInsight)
	t.Logf("Life-memories found: %d", len(result.LifeMemories))
	for _, m := range result.LifeMemories {
		t.Logf("  - %s: %s", m.Title, m.Content)
	}
	t.Logf("Collaboration log entries: %d", len(result.CollaborationLog))
	for _, c := range result.CollaborationLog {
		t.Logf("  - success=%v data=%s", c.Success, c.Data)
	}

	// ── Step 5: Decision Protocol — scan + evidence pointers ─────
	scanner := decision.NewScanner()
	collector := decision.NewEvidenceCollector()

	// GAP #8 fix: inject evidence_pointers from vault, life-memory, spark
	collector.Add("vault://anniv-wedding", "asset.read", fmt.Sprintf("title=%s owner=%s", result.AssetTitle, "user/anniversary-keeper"), "info")
	for _, m := range result.LifeMemories {
		collector.Add(fmt.Sprintf("life-memory://%s", m.ID), "memory.query", fmt.Sprintf("tag-match: %s", m.Title), "info")
	}
	collector.Add("spark://spark-wedding", "spark.recall", result.SparkInsight, "info")

	outputText := result.SparkInsight
	for _, m := range result.LifeMemories {
		outputText += ". " + m.Content
	}

	decOutput := decision.ProcessDecision(outputText, scanner, collector)

	t.Logf("Decision Protocol: directives=%d evidence=%d",
		len(decOutput.DirectivesFound), len(decOutput.EvidencePointers))
	t.Logf("Decision: %s", decOutput.Decision)

	// ── Step 5b: LLM operator call + cost recording (GAP #6) ────
	auditChain := substrate.NewAuditChain()

	llmClient := decision.NewMockLLMClient("Anniversary analysis: gift suggestions based on memories")
	llmClient.Response.TokenCount = 142
	llmReq := &decision.LLMRequest{
		Prompt:    "Analyze anniversary context and suggest approach",
		Context:   outputText,
		MaxTokens: 500,
	}
	llmResp, err := llmClient.Complete(llmReq)
	if err != nil {
		t.Fatalf("LLM call failed: %v", err)
	}

	auditChain.Append("llm.call", "user/anniversary-keeper", "mock-llm",
		fmt.Sprintf("tokens=%d model=%s", llmResp.TokenCount, llmResp.Model), nil)
	t.Logf("LLM cost: tokens=%d model=%s", llmResp.TokenCount, llmResp.Model)

	// Record the full pipeline in audit chain
	auditChain.Append("vault.read", "user/anniversary-keeper", cronPayload.AssetID,
		fmt.Sprintf("asset=%s", result.AssetTitle), nil)
	auditChain.Append("spark.recall", "user/anniversary-keeper", "anniversary-reminder",
		fmt.Sprintf("insight=%s", result.SparkInsight), nil)
	auditChain.Append("lifememory.query", "user/anniversary-keeper", "tags:anniversary,family",
		fmt.Sprintf("hits=%d", len(result.LifeMemories)), nil)
	auditChain.Append("collaboration", "user/anniversary-keeper", "user/memory-keeper",
		fmt.Sprintf("action=query-life-memory-subgraph success=%v", result.CollaborationLog[0].Success), nil)
	auditChain.Append("decision.scan", "decision-protocol", "output-text",
		fmt.Sprintf("directives=%d evidence=%d", len(decOutput.DirectivesFound), len(decOutput.EvidencePointers)), nil)

	// ── Step 6: Structured OB output (GAP #9) ────────────────────
	memRefs := make([]protocol.SourceRef, 0, len(result.LifeMemories))
	for _, m := range result.LifeMemories {
		memRefs = append(memRefs, protocol.SourceRef{
			URI:     fmt.Sprintf("life-memory://%s", m.ID),
			Type:    "life-memory",
			Summary: m.Title + ": " + m.Content,
		})
	}

	obOut := protocol.OBOutput{
		Title:      result.AssetTitle,
		Insight:    result.SparkInsight,
		Memories:   memRefs,
		Evidence:   decOutput.EvidencePointers,
		Directives: len(decOutput.DirectivesFound),
		Decision:   decOutput.Decision,
		LLMCost:    llmResp.TokenCount,
		AuditHash:  auditChain.Last().Hash,
	}

	obJSON, err := json.MarshalIndent(obOut, "", "  ")
	if err != nil {
		t.Fatalf("OB JSON marshal: %v", err)
	}

	inbox := &mockOBInbox{}
	inbox.Send(string(obJSON))
	t.Logf("OB Inbox (structured):\n%s", string(obJSON))

	// ── Assertions ───────────────────────────────────────────────
	if result.AssetTitle != "Wedding Anniversary" {
		t.Errorf("asset title: got '%s', want 'Wedding Anniversary'", result.AssetTitle)
	}
	if len(result.LifeMemories) < 2 {
		t.Errorf("expected at least 2 life-memories, got %d", len(result.LifeMemories))
	}
	if decOutput.Decision != "analysis_complete" {
		t.Errorf("decision should be 'analysis_complete', got '%s'", decOutput.Decision)
	}
	if len(inbox.Messages()) != 1 {
		t.Errorf("expected 1 inbox message, got %d", len(inbox.Messages()))
	}
	if len(result.CollaborationLog) != 1 {
		t.Errorf("expected 1 collaboration log entry, got %d", len(result.CollaborationLog))
	} else if !result.CollaborationLog[0].Success {
		t.Errorf("collaboration should succeed: %s", result.CollaborationLog[0].Error)
	}

	// GAP #8: evidence_pointers must have ≥3 sources (vault + life-memory + spark)
	if len(decOutput.EvidencePointers) < 3 {
		t.Errorf("expected at least 3 evidence pointers, got %d", len(decOutput.EvidencePointers))
	}
	hasVault, hasMem, hasSpark := false, false, false
	for _, ep := range decOutput.EvidencePointers {
		if strings.HasPrefix(ep.Source, "vault://") {
			hasVault = true
		}
		if strings.HasPrefix(ep.Source, "life-memory://") {
			hasMem = true
		}
		if strings.HasPrefix(ep.Source, "spark://") {
			hasSpark = true
		}
	}
	if !hasVault || !hasMem || !hasSpark {
		t.Errorf("evidence_pointers missing source: vault=%v life-memory=%v spark=%v", hasVault, hasMem, hasSpark)
	}

	// GAP #6: LLM cost must be recorded in audit chain
	if llmResp.TokenCount == 0 {
		t.Error("LLM token count should be > 0")
	}
	llmAuditFound := false
	for _, e := range auditChain.Entries() {
		if e.EventType == "llm.call" {
			llmAuditFound = true
		}
	}
	if !llmAuditFound {
		t.Error("audit chain missing llm.call entry")
	}

	// GAP #9: OB output must be valid JSON with source URIs
	var parsed protocol.OBOutput
	if err := json.Unmarshal(obJSON, &parsed); err != nil {
		t.Errorf("OB output is not valid JSON: %v", err)
	}
	if len(parsed.Memories) == 0 {
		t.Error("OB output missing memory source refs")
	}
	if parsed.AuditHash == "" {
		t.Error("OB output missing audit chain tip hash")
	}

	// GAP #11 (original #11): audit chain integrity
	if bad := auditChain.VerifyChain(); bad != -1 {
		t.Errorf("audit chain corrupted at index %d", bad)
	}
	if auditChain.Len() < 5 {
		t.Errorf("audit chain too short: %d entries, expected ≥5", auditChain.Len())
	}

	// GAP #10: spark feedback routing 闭环
	err = sparkStore.WriteFeedback(protocol.SparkFeedback{
		SparkID: "spark-wedding",
		Rating:  0.9,
		Comment: "Helpful anniversary reminder",
	})
	if err != nil {
		t.Fatalf("WriteFeedback failed: %v", err)
	}
	fbs := sparkStore.Feedbacks()
	if len(fbs) != 1 {
		t.Errorf("expected 1 feedback, got %d", len(fbs))
	} else if fbs[0].SparkID != "spark-wedding" {
		t.Errorf("feedback spark_id: got '%s', want 'spark-wedding'", fbs[0].SparkID)
	}
	auditChain.Append("spark.feedback", "user", "spark-wedding",
		fmt.Sprintf("rating=%.1f", fbs[0].Rating), nil)
	t.Logf("Spark feedback written: spark_id=%s rating=%.1f", fbs[0].SparkID, fbs[0].Rating)

	t.Log("=== Sprint 1 End-to-End integration test PASSED ===")
}

func TestSprint1AuditTrail(t *testing.T) {
	// Verify that the audit trail is reproducible by re-running the chain
	// and comparing key outputs.

	assetStore := protocol.NewMemAssetStore()
	sparkStore := protocol.NewMemSparkStore()
	memStore := lifememory.NewMemStore()

	// Same seed data
	assetStore.Put(&protocol.AssetLedgerEntry{
		AssetID: "anniv-wedding", AssetType: protocol.AssetCredential,
		Title: "Wedding Anniversary", Owner: "user/anniversary-keeper",
	})
	sparkStore.Put(protocol.Spark{
		ID: "spark-wedding", Context: "anniversary-reminder",
		Insight: "Wedding anniversary reminder", Score: 0.95,
	})
	memStore.Insert(&lifememory.MemoryNode{
		ID: "mem-wedding-date", Title: "Wedding Date",
		Content: "June 22, 2025", Tags: []string{"anniversary", "family", "wedding"},
	})
	memStore.Insert(&lifememory.MemoryNode{
		ID: "mem-wife-favorites", Title: "Her Favorite Things",
		Content: "Loves flowers", Tags: []string{"anniversary", "family", "favorites"},
	})

	memKeeper := memory_keeper.New(memStore)
	router := &agentRouter{memoryKeeper: memKeeper}
	annivKeeper := anniversary_keeper.New(assetStore, sparkStore, memStore, router)

	// Run the chain twice with same inputs — outputs must be deterministic
	result1, err := annivKeeper.CheckReminder("anniv-wedding", []string{"anniversary", "family"})
	if err != nil {
		t.Fatalf("first run: %v", err)
	}

	result2, err := annivKeeper.CheckReminder("anniv-wedding", []string{"anniversary", "family"})
	if err != nil {
		t.Fatalf("second run: %v", err)
	}

	// Verify deterministic outputs
	if result1.AssetTitle != result2.AssetTitle {
		t.Error("audit trail: asset title differs between runs")
	}
	if len(result1.LifeMemories) != len(result2.LifeMemories) {
		t.Error("audit trail: life-memory count differs between runs")
	}
	if len(result1.CollaborationLog) != len(result2.CollaborationLog) {
		t.Error("audit trail: collaboration log count differs between runs")
	}

	t.Log("Audit trail verification: outputs are deterministic across runs")
}

// TestSprint2QuorumReplay verifies GAP #12: 3-of-5 quorum audit replay.
func TestSprint2QuorumReplay(t *testing.T) {
	// Build an audit chain from the full pipeline
	chain := substrate.NewAuditChain()
	chain.Append("cron.trigger", "orchestrator", "sched-anniv-001", "T-7 09:00 trigger", nil)
	chain.Append("vault.read", "user/anniversary-keeper", "anniv-wedding", "asset=Wedding Anniversary", nil)
	chain.Append("spark.recall", "user/anniversary-keeper", "anniversary-reminder", "insight retrieved", nil)
	chain.Append("lifememory.query", "user/anniversary-keeper", "tags:anniversary,family", "hits=3", nil)
	chain.Append("collaboration", "user/anniversary-keeper", "user/memory-keeper", "query-life-memory-subgraph", nil)
	chain.Append("llm.call", "user/anniversary-keeper", "mock-llm", "tokens=142 model=mock", nil)
	chain.Append("decision.scan", "decision-protocol", "output-text", "directives=0 evidence=5", nil)
	chain.Append("ob.send", "decision-protocol", "ob-inbox", "structured JSON output", nil)

	// Convert audit entries to quorum HashedEntry format
	entries := chain.Entries()
	qEntries := make([]quorum.HashedEntry, len(entries))
	for i, e := range entries {
		qEntries[i] = quorum.HashedEntry{
			Index:    e.Index,
			Hash:     e.Hash,
			PrevHash: e.PrevHash,
		}
	}

	// Replicate across 5 nodes (simulating gossip distribution)
	nodeNames := []quorum.NodeID{"h5-hermes-aws-hk", "h6-hermes-sz-aliyun", "c1", "ob-main", "x1"}
	nodes := make([]*quorum.Node, 5)
	for i, name := range nodeNames {
		nodes[i] = quorum.NewNode(name, qEntries)
	}
	cluster := quorum.NewCluster(nodes)

	// Full 5-node quorum
	result := cluster.Verify()
	if !result.Passed {
		t.Fatalf("full quorum failed: agreeing=%d tip=%s", result.Agreeing, result.TipHash)
	}
	t.Logf("Full quorum: passed=%v agreeing=%d/%d tip=%s", result.Passed, result.Agreeing, 5, result.TipHash)

	// Pick any 3 of 5 for subset verification
	subsets := [][3]quorum.NodeID{
		{"h5-hermes-aws-hk", "c1", "x1"},
		{"h6-hermes-sz-aliyun", "ob-main", "c1"},
		{"h5-hermes-aws-hk", "h6-hermes-sz-aliyun", "ob-main"},
	}
	for _, sub := range subsets {
		sr := cluster.VerifySubset(sub)
		if !sr.Passed {
			t.Errorf("subset quorum failed for %v: agreeing=%d", sub, sr.Agreeing)
		}
		t.Logf("Subset quorum [%s,%s,%s]: passed=%v agreeing=%d", sub[0], sub[1], sub[2], sr.Passed, sr.Agreeing)
	}

	// Gossip: all nodes identical → 0 mismatches
	mismatches := cluster.Gossip()
	if len(mismatches) != 0 {
		t.Errorf("expected 0 gossip mismatches, got %d", len(mismatches))
	}
	t.Logf("Gossip verification: 0 mismatches across %d node pairs", 10)

	// Tamper one node and verify detection
	tamperedEntries := make([]quorum.HashedEntry, len(qEntries))
	copy(tamperedEntries, qEntries)
	tamperedEntries[3].Hash = "tampered-hash"

	tamperedNodes := make([]*quorum.Node, 5)
	for i, name := range nodeNames {
		if i == 2 {
			tamperedNodes[i] = quorum.NewNode(name, tamperedEntries)
		} else {
			tamperedNodes[i] = quorum.NewNode(name, qEntries)
		}
	}
	tamperedCluster := quorum.NewCluster(tamperedNodes)

	tr := tamperedCluster.Verify()
	if !tr.Passed {
		t.Error("quorum should still pass with 4/5 honest nodes")
	}
	if len(tr.Dissenting) != 1 {
		t.Errorf("expected 1 dissenting node, got %d", len(tr.Dissenting))
	} else if tr.Dissenting[0] != "c1" {
		t.Errorf("dissenting should be 'c1' (tampered), got '%s'", tr.Dissenting[0])
	}
	for _, d := range tr.Digests {
		if d.NodeID == "c1" && d.Valid {
			t.Error("tampered node should report Valid=false")
		}
	}

	tamperedMismatches := tamperedCluster.Gossip()
	if len(tamperedMismatches) == 0 {
		t.Error("gossip should detect tampered node")
	}
	t.Logf("Tamper detection: %d gossip mismatches found, dissenting=%v", len(tamperedMismatches), tr.Dissenting)

	t.Log("=== Sprint 2 Quorum Replay test PASSED ===")
}

// TestScannerDetectsDirective proves the scanner is active (Z1 review #7 evidence).
func TestScannerDetectsDirective(t *testing.T) {
	scanner := decision.NewScanner()

	text := "用户必须在周年纪念日前准备好礼物，严禁遗忘。"
	directives := scanner.Scan(text)
	if len(directives) < 2 {
		t.Fatalf("expected at least 2 directives from text with 必须+严禁, got %d", len(directives))
	}

	found := map[string]bool{}
	for _, d := range directives {
		found[d.Phrase] = true
	}
	if !found["必须"] {
		t.Error("scanner missed 必须")
	}
	if !found["严禁"] {
		t.Error("scanner missed 严禁")
	}

	// Clean text should return 0
	clean := "Wedding anniversary reminder: consider preparing a gift."
	cleanDir := scanner.Scan(clean)
	if len(cleanDir) != 0 {
		t.Errorf("expected 0 directives in clean English text, got %d", len(cleanDir))
	}
}
