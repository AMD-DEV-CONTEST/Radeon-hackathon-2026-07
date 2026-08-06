package protocol

import (
	"errors"
	"sync"
)

// ── Memory Protocol ─────────────────────────────────────────────────
//
// Memory Protocol defines memory.set and memory.get operations.
// Memories are key-value pairs scoped to a namespace.

// MemoryEntry represents a single memory entry.
type MemoryEntry struct {
	Namespace string `json:"namespace"`
	Key       string `json:"key"`
	Value     string `json:"value"`
	Tags      []string `json:"tags,omitempty"`
}

// MemoryStore is the interface for memory.set and memory.get.
type MemoryStore interface {
	Set(namespace, key, value string, tags []string) error
	Get(namespace, key string) (*MemoryEntry, error)
}

// ── Errors ─────────────────────────────────────────────────────────

var (
	ErrMemoryNotFound = errors.New("protocol: memory not found")
)

// ── In-Memory Memory Store ──────────────────────────────────────────

// MemMemoryStore is an in-memory implementation for testing.
type MemMemoryStore struct {
	mu   sync.RWMutex
	data map[string]*MemoryEntry // key = namespace + ":" + key
}

func NewMemMemoryStore() *MemMemoryStore {
	return &MemMemoryStore{data: make(map[string]*MemoryEntry)}
}

func (s *MemMemoryStore) Set(namespace, key, value string, tags []string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[namespace+":"+key] = &MemoryEntry{
		Namespace: namespace,
		Key:       key,
		Value:     value,
		Tags:      tags,
	}
	return nil
}

func (s *MemMemoryStore) Get(namespace, key string) (*MemoryEntry, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	e, ok := s.data[namespace+":"+key]
	if !ok {
		return nil, ErrMemoryNotFound
	}
	return e, nil
}
