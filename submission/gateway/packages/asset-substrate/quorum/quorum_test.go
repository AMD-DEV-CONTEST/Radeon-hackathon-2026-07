package quorum

import (
	"testing"
)

func sampleChain() []HashedEntry {
	return []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "bbb", PrevHash: "aaa"},
		{Index: 2, Hash: "ccc", PrevHash: "bbb"},
	}
}

func corruptedChain() []HashedEntry {
	return []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "xxx", PrevHash: "aaa"},
		{Index: 2, Hash: "yyy", PrevHash: "zzz"},
	}
}

func TestQuorumAllAgree(t *testing.T) {
	chain := sampleChain()
	nodes := make([]*Node, 5)
	for i := range nodes {
		nodes[i] = NewNode(NodeID("node-"+string(rune('A'+i))), chain)
	}
	cluster := NewCluster(nodes)

	result := cluster.Verify()
	if !result.Passed {
		t.Fatal("quorum should pass when all 5 nodes agree")
	}
	if result.Agreeing != 5 {
		t.Errorf("expected 5 agreeing, got %d", result.Agreeing)
	}
	if result.TipHash != "ccc" {
		t.Errorf("tip hash: got '%s', want 'ccc'", result.TipHash)
	}
	if len(result.Dissenting) != 0 {
		t.Errorf("expected 0 dissenting, got %d", len(result.Dissenting))
	}
}

func TestQuorum3of5(t *testing.T) {
	good := sampleChain()
	bad := []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "bbb", PrevHash: "aaa"},
		{Index: 2, Hash: "ddd", PrevHash: "bbb"},
	}

	nodes := []*Node{
		NewNode("n1", good),
		NewNode("n2", good),
		NewNode("n3", good),
		NewNode("n4", bad),
		NewNode("n5", bad),
	}
	cluster := NewCluster(nodes)

	result := cluster.Verify()
	if !result.Passed {
		t.Fatal("quorum should pass with 3/5 agreement")
	}
	if result.Agreeing != 3 {
		t.Errorf("expected 3 agreeing, got %d", result.Agreeing)
	}
	if len(result.Dissenting) != 2 {
		t.Errorf("expected 2 dissenting, got %d", len(result.Dissenting))
	}
}

func TestQuorumFails2of5(t *testing.T) {
	good := sampleChain()
	// Each bad node disagrees with everyone else — no 3-way consensus possible
	bad1 := []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "bbb", PrevHash: "aaa"},
		{Index: 2, Hash: "ddd", PrevHash: "bbb"},
	}
	bad2 := []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "bbb", PrevHash: "aaa"},
		{Index: 2, Hash: "eee", PrevHash: "bbb"},
	}
	bad3 := []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "bbb", PrevHash: "aaa"},
		{Index: 2, Hash: "fff", PrevHash: "bbb"},
	}

	nodes := []*Node{
		NewNode("n1", good),
		NewNode("n2", good),
		NewNode("n3", bad1),
		NewNode("n4", bad2),
		NewNode("n5", bad3),
	}
	cluster := NewCluster(nodes)

	result := cluster.Verify()
	if result.Passed {
		t.Fatal("quorum should fail with only 2/5 on correct chain")
	}
}

func TestQuorumCorruptedNode(t *testing.T) {
	good := sampleChain()
	corrupt := corruptedChain()

	nodes := []*Node{
		NewNode("n1", good),
		NewNode("n2", good),
		NewNode("n3", good),
		NewNode("n4", good),
		NewNode("n5", corrupt),
	}
	cluster := NewCluster(nodes)

	result := cluster.Verify()
	if !result.Passed {
		t.Fatal("quorum should pass: 4 valid nodes")
	}
	if len(result.Dissenting) != 1 {
		t.Errorf("expected 1 dissenting (corrupted), got %d", len(result.Dissenting))
	}
	if result.Dissenting[0] != "n5" {
		t.Errorf("dissenting node should be n5, got %s", result.Dissenting[0])
	}
}

func TestVerifySubset(t *testing.T) {
	chain := sampleChain()
	nodes := make([]*Node, 5)
	ids := []NodeID{"alpha", "beta", "gamma", "delta", "epsilon"}
	for i := range nodes {
		nodes[i] = NewNode(ids[i], chain)
	}
	cluster := NewCluster(nodes)

	result := cluster.VerifySubset([3]NodeID{"alpha", "gamma", "epsilon"})
	if !result.Passed {
		t.Fatal("subset quorum should pass")
	}
	if result.Agreeing != 3 {
		t.Errorf("expected 3 agreeing, got %d", result.Agreeing)
	}
}

func TestGossipNoMismatch(t *testing.T) {
	chain := sampleChain()
	nodes := make([]*Node, 5)
	for i := range nodes {
		nodes[i] = NewNode(NodeID("node-"+string(rune('A'+i))), chain)
	}
	cluster := NewCluster(nodes)

	mismatches := cluster.Gossip()
	if len(mismatches) != 0 {
		t.Errorf("expected 0 mismatches, got %d", len(mismatches))
	}
}

func TestGossipDetectsMismatch(t *testing.T) {
	good := sampleChain()
	bad := []HashedEntry{
		{Index: 0, Hash: "aaa", PrevHash: ""},
		{Index: 1, Hash: "bbb", PrevHash: "aaa"},
		{Index: 2, Hash: "ddd", PrevHash: "bbb"},
	}

	nodes := []*Node{
		NewNode("n1", good),
		NewNode("n2", good),
		NewNode("n3", bad),
		NewNode("n4", good),
		NewNode("n5", good),
	}
	cluster := NewCluster(nodes)

	mismatches := cluster.Gossip()
	if len(mismatches) == 0 {
		t.Fatal("expected gossip to find mismatches")
	}
	found := false
	for _, m := range mismatches {
		if m.NodeA == "n3" || m.NodeB == "n3" {
			found = true
			if m.AtIndex != 2 {
				t.Errorf("mismatch should be at index 2, got %d", m.AtIndex)
			}
		}
	}
	if !found {
		t.Error("n3 should appear in gossip mismatches")
	}
}
