// Package quorum implements 3-of-5 audit chain quorum verification.
// Each node holds a copy of the audit chain. Verification succeeds when
// at least 3 of 5 nodes agree on the chain's tip hash and full integrity.
//
// This package only checks chain structure (PrevHash linkage). It does NOT
// recompute content hashes — that is the responsibility of each node's local
// substrate.AuditChain.VerifyChain (which recomputes SHA-256 over payload).
package quorum

import (
	"fmt"
	"sync"
)

// NodeID identifies a node in the quorum.
type NodeID string

// ChainDigest is the summary a node reports for its audit chain copy.
type ChainDigest struct {
	NodeID  NodeID `json:"node_id"`
	TipHash string `json:"tip_hash"`
	Length  int    `json:"length"`
	Valid   bool   `json:"valid"`
}

// Node holds a replicated audit chain and can produce a digest.
type Node struct {
	id      NodeID
	entries []HashedEntry
}

// HashedEntry is a minimal representation of an audit entry for quorum purposes.
type HashedEntry struct {
	Index    uint64 `json:"index"`
	Hash     string `json:"hash"`
	PrevHash string `json:"prev_hash"`
}

// NewNode creates a quorum node with the given ID and chain entries.
func NewNode(id NodeID, entries []HashedEntry) *Node {
	return &Node{id: id, entries: entries}
}

// ID returns the node's identifier.
func (n *Node) ID() NodeID { return n.id }

// Digest produces the chain digest for this node.
func (n *Node) Digest() ChainDigest {
	d := ChainDigest{
		NodeID: n.id,
		Length: len(n.entries),
		Valid:  n.verifyChain(),
	}
	if len(n.entries) > 0 {
		d.TipHash = n.entries[len(n.entries)-1].Hash
	}
	return d
}

func (n *Node) verifyChain() bool {
	for i, e := range n.entries {
		if i > 0 && e.PrevHash != n.entries[i-1].Hash {
			return false
		}
	}
	return true
}

// Entries returns the node's chain entries.
func (n *Node) Entries() []HashedEntry {
	result := make([]HashedEntry, len(n.entries))
	copy(result, n.entries)
	return result
}

// Cluster is a set of 5 nodes that participate in quorum verification.
type Cluster struct {
	mu    sync.RWMutex
	nodes []*Node
}

// NewCluster creates a cluster. Panics if not exactly 5 nodes.
func NewCluster(nodes []*Node) *Cluster {
	if len(nodes) != 5 {
		panic(fmt.Sprintf("quorum: cluster requires exactly 5 nodes, got %d", len(nodes)))
	}
	return &Cluster{nodes: nodes}
}

// QuorumResult is the outcome of a quorum verification.
type QuorumResult struct {
	Passed     bool           `json:"passed"`
	Threshold  int            `json:"threshold"`
	Agreeing   int            `json:"agreeing"`
	TipHash    string         `json:"tip_hash"`
	Digests    []ChainDigest  `json:"digests"`
	Dissenting []NodeID       `json:"dissenting,omitempty"`
}

// Verify runs quorum verification: collects digests from all 5 nodes,
// checks that at least 3 agree on tip hash and all report valid chains.
func (c *Cluster) Verify() QuorumResult {
	c.mu.RLock()
	defer c.mu.RUnlock()

	digests := make([]ChainDigest, len(c.nodes))
	for i, n := range c.nodes {
		digests[i] = n.Digest()
	}

	votes := make(map[string]int)
	for _, d := range digests {
		if d.Valid {
			votes[d.TipHash]++
		}
	}

	bestHash := ""
	bestCount := 0
	for h, count := range votes {
		if count > bestCount {
			bestHash = h
			bestCount = count
		}
	}

	var dissenting []NodeID
	for _, d := range digests {
		if !d.Valid || d.TipHash != bestHash {
			dissenting = append(dissenting, d.NodeID)
		}
	}

	return QuorumResult{
		Passed:     bestCount >= 3,
		Threshold:  3,
		Agreeing:   bestCount,
		TipHash:    bestHash,
		Digests:    digests,
		Dissenting: dissenting,
	}
}

// VerifySubset picks 3 specific nodes and verifies quorum among them.
func (c *Cluster) VerifySubset(nodeIDs [3]NodeID) QuorumResult {
	c.mu.RLock()
	defer c.mu.RUnlock()

	var subset []*Node
	for _, id := range nodeIDs {
		for _, n := range c.nodes {
			if n.id == id {
				subset = append(subset, n)
				break
			}
		}
	}

	digests := make([]ChainDigest, len(subset))
	for i, n := range subset {
		digests[i] = n.Digest()
	}

	votes := make(map[string]int)
	for _, d := range digests {
		if d.Valid {
			votes[d.TipHash]++
		}
	}

	bestHash := ""
	bestCount := 0
	for h, count := range votes {
		if count > bestCount {
			bestHash = h
			bestCount = count
		}
	}

	var dissenting []NodeID
	for _, d := range digests {
		if !d.Valid || d.TipHash != bestHash {
			dissenting = append(dissenting, d.NodeID)
		}
	}

	return QuorumResult{
		Passed:     bestCount >= 3,
		Threshold:  3,
		Agreeing:   bestCount,
		TipHash:    bestHash,
		Digests:    digests,
		Dissenting: dissenting,
	}
}

// GossipMismatch records a hash disagreement between two nodes.
type GossipMismatch struct {
	NodeA   NodeID `json:"node_a"`
	NodeB   NodeID `json:"node_b"`
	AtIndex uint64 `json:"at_index"`
	HashA   string `json:"hash_a"`
	HashB   string `json:"hash_b"`
}

// Gossip runs pairwise comparison across all nodes and returns all mismatches.
func (c *Cluster) Gossip() []GossipMismatch {
	c.mu.RLock()
	defer c.mu.RUnlock()

	var mismatches []GossipMismatch
	for i := 0; i < len(c.nodes); i++ {
		for j := i + 1; j < len(c.nodes); j++ {
			a := c.nodes[i].entries
			b := c.nodes[j].entries
			minLen := len(a)
			if len(b) < minLen {
				minLen = len(b)
			}
			for k := 0; k < minLen; k++ {
				if a[k].Hash != b[k].Hash {
					mismatches = append(mismatches, GossipMismatch{
						NodeA:   c.nodes[i].id,
						NodeB:   c.nodes[j].id,
						AtIndex: uint64(k),
						HashA:   a[k].Hash,
						HashB:   b[k].Hash,
					})
				}
			}
		}
	}
	return mismatches
}
