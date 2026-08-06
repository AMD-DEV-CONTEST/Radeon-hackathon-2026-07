// Package lifememory implements the Life-Memory Protocol:
// memory nodes with tags, stored via pure SQL (no pgvector).
package lifememory

import (
	"errors"
	"sort"
	"strings"
	"time"
)

// ── Data Model ──────────────────────────────────────────────────────

// MemoryNode represents a single life-memory node.
type MemoryNode struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	Content   string    `json:"content"`
	Tags      []string  `json:"tags"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// ── Errors ─────────────────────────────────────────────────────────

var (
	ErrNodeNotFound = errors.New("lifememory: node not found")
)

// ── Store Interface ─────────────────────────────────────────────────

// Store defines the Life-Memory Protocol operations.
type Store interface {
	// Insert adds a new memory node with tags.
	Insert(node *MemoryNode) error
	// GetByID retrieves a single node by ID.
	GetByID(id string) (*MemoryNode, error)
	// QueryByTag returns all nodes that have the given tag.
	QueryByTag(tag string) ([]*MemoryNode, error)
	// QueryByTags returns nodes matching ALL given tags (AND logic).
	QueryByTags(tags []string) ([]*MemoryNode, error)
	// Delete removes a node by ID.
	Delete(id string) error
	// Count returns the total number of nodes.
	Count() (int, error)
}

// TimelineStore extends Store with time-range and full-text queries.
// It is the interface the Phase 3.1 PGStore implements so the
// orchestrator's /events/timeline and /memory/nodes handlers can serve
// "what happened between X and Y" and "find nodes mentioning Z" without
// every caller hand-rolling SQL. MemStore implements it too so tests
// can run without a database.
type TimelineStore interface {
	Store
	// QueryByTimeRange returns nodes created in [start, end), ordered
	// oldest-first. An open end (end.IsZero()) means "no upper bound".
	QueryByTimeRange(start, end time.Time) ([]*MemoryNode, error)
	// QueryByTagAndTimeRange is QueryByTimeRange filtered to nodes that
	// also carry the given tag.
	QueryByTagAndTimeRange(tag string, start, end time.Time) ([]*MemoryNode, error)
	// Search returns nodes whose title or content contains keyword
	// (case-insensitive). Empty keyword returns an empty slice, not all
	// nodes — a search with no term is a caller bug, not a wildcard.
	Search(keyword string) ([]*MemoryNode, error)
}

// ── In-Memory Store (for testing, no SQL driver needed) ─────────────

// MemStore implements Store using in-memory Go data structures.
// The SQL semantics are preserved: tags are matched by exact string.
type MemStore struct {
	nodes  map[string]*MemoryNode
	tagIdx map[string][]string // tag -> []nodeID
}

func NewMemStore() *MemStore {
	return &MemStore{
		nodes:  make(map[string]*MemoryNode),
		tagIdx: make(map[string][]string),
	}
}

func (s *MemStore) Insert(node *MemoryNode) error {
	if node.ID == "" {
		return errors.New("lifememory: node ID required")
	}
	node.CreatedAt = time.Now().UTC()
	node.UpdatedAt = node.CreatedAt

	s.nodes[node.ID] = node

	// Index tags
	for _, tag := range node.Tags {
		s.tagIdx[tag] = append(s.tagIdx[tag], node.ID)
	}
	return nil
}

func (s *MemStore) GetByID(id string) (*MemoryNode, error) {
	n, ok := s.nodes[id]
	if !ok {
		return nil, ErrNodeNotFound
	}
	return n, nil
}

func (s *MemStore) QueryByTag(tag string) ([]*MemoryNode, error) {
	ids, ok := s.tagIdx[tag]
	if !ok {
		return []*MemoryNode{}, nil
	}
	result := make([]*MemoryNode, 0, len(ids))
	for _, id := range ids {
		if n, ok := s.nodes[id]; ok {
			result = append(result, n)
		}
	}
	return result, nil
}

func (s *MemStore) QueryByTags(tags []string) ([]*MemoryNode, error) {
	if len(tags) == 0 {
		return []*MemoryNode{}, nil
	}

	// Start with the first tag's results
	candidates, err := s.QueryByTag(tags[0])
	if err != nil {
		return nil, err
	}

	// Filter by remaining tags
	for _, tag := range tags[1:] {
		filtered := make([]*MemoryNode, 0, len(candidates))
		for _, n := range candidates {
			if hasTag(n.Tags, tag) {
				filtered = append(filtered, n)
			}
		}
		candidates = filtered
	}
	return candidates, nil
}

func (s *MemStore) Delete(id string) error {
	n, ok := s.nodes[id]
	if !ok {
		return ErrNodeNotFound
	}

	// Remove from tag index
	for _, tag := range n.Tags {
		ids := s.tagIdx[tag]
		for i, tid := range ids {
			if tid == id {
				s.tagIdx[tag] = append(ids[:i], ids[i+1:]...)
				break
			}
		}
	}

	delete(s.nodes, id)
	return nil
}

func (s *MemStore) Count() (int, error) {
	return len(s.nodes), nil
}

// ── MemStore TimelineStore methods ───────────────────────────────────

// QueryByTimeRange returns nodes with CreatedAt in [start, end). A zero
// end means no upper bound. Results are ordered oldest-first so a
// timeline consumer reads chronologically without re-sorting.
func (s *MemStore) QueryByTimeRange(start, end time.Time) ([]*MemoryNode, error) {
	var out []*MemoryNode
	for _, n := range s.nodes {
		if n.CreatedAt.Before(start) {
			continue
		}
		if !end.IsZero() && !n.CreatedAt.Before(end) {
			continue
		}
		out = append(out, n)
	}
	sortByCreatedAsc(out)
	return out, nil
}

// QueryByTagAndTimeRange is QueryByTimeRange restricted to nodes
// carrying the given tag.
func (s *MemStore) QueryByTagAndTimeRange(tag string, start, end time.Time) ([]*MemoryNode, error) {
	inRange, err := s.QueryByTimeRange(start, end)
	if err != nil {
		return nil, err
	}
	out := inRange[:0]
	for _, n := range inRange {
		if hasTag(n.Tags, tag) {
			out = append(out, n)
		}
	}
	return out, nil
}

// Search returns nodes whose title or content contains keyword,
// case-insensitive. Empty keyword yields an empty result (not all
// nodes) — searching nothing is a caller bug, not a wildcard.
func (s *MemStore) Search(keyword string) ([]*MemoryNode, error) {
	if keyword == "" {
		return []*MemoryNode{}, nil
	}
	needle := strings.ToLower(keyword)
	var out []*MemoryNode
	for _, n := range s.nodes {
		if strings.Contains(strings.ToLower(n.Title), needle) ||
			strings.Contains(strings.ToLower(n.Content), needle) {
			out = append(out, n)
		}
	}
	return out, nil
}

// sortByCreatedAsc orders nodes oldest-first in place.
func sortByCreatedAsc(nodes []*MemoryNode) {
	sort.Slice(nodes, func(i, j int) bool {
		return nodes[i].CreatedAt.Before(nodes[j].CreatedAt)
	})
}

// ── Helpers ─────────────────────────────────────────────────────────

func hasTag(tags []string, tag string) bool {
	for _, t := range tags {
		if t == tag {
			return true
		}
	}
	return false
}
