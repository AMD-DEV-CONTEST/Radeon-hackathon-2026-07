package protocol

import (
	"errors"
	"sync"
	"time"
)

// ── Spark Protocol ──────────────────────────────────────────────────
//
// Spark Protocol defines the spark.recall operation: recalling a
// thinking spark (insight) based on a context query.

// Spark represents a single thinking spark (insight/recall).
type Spark struct {
	ID        string    `json:"id"`
	Context   string    `json:"context"`
	Insight   string    `json:"insight"`
	CreatedAt time.Time `json:"created_at"`
	Score     float64   `json:"score,omitempty"` // relevance score 0.0-1.0
}

// SparkFeedback records user feedback on a spark-generated output.
type SparkFeedback struct {
	SparkID string  `json:"spark_id"`
	Rating  float64 `json:"rating"`
	Comment string  `json:"comment,omitempty"`
}

// SparkStore is the interface for spark.recall and spark.feedback.
type SparkStore interface {
	Recall(context string) (*Spark, error)
	WriteFeedback(fb SparkFeedback) error
	Feedbacks() []SparkFeedback
}

// ── Errors ─────────────────────────────────────────────────────────

var (
	ErrSparkNotFound = errors.New("protocol: no spark found for context")
)

// ── In-Memory Spark Store ──────────────────────────────────────────

// MemSparkStore is an in-memory implementation for testing.
type MemSparkStore struct {
	mu        sync.RWMutex
	sparks    []Spark
	feedbacks []SparkFeedback
}

func NewMemSparkStore() *MemSparkStore {
	return &MemSparkStore{sparks: make([]Spark, 0)}
}

func (s *MemSparkStore) Recall(context string) (*Spark, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	// Simple keyword-match recall for testing
	for i := len(s.sparks) - 1; i >= 0; i-- {
		if s.sparks[i].Context == context {
			return &s.sparks[i], nil
		}
	}
	return nil, ErrSparkNotFound
}

func (s *MemSparkStore) Put(spark Spark) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sparks = append(s.sparks, spark)
}

func (s *MemSparkStore) WriteFeedback(fb SparkFeedback) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.feedbacks = append(s.feedbacks, fb)
	return nil
}

func (s *MemSparkStore) Feedbacks() []SparkFeedback {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]SparkFeedback, len(s.feedbacks))
	copy(result, s.feedbacks)
	return result
}
