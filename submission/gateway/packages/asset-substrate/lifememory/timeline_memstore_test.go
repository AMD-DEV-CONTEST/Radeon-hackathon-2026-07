package lifememory

import (
	"testing"
	"time"
)

// insertAt inserts a node with a faked CreatedAt so time-range tests are
// deterministic (MemStore.Insert normally stamps time.Now()).
func insertAt(t *testing.T, s *MemStore, id, title, content string, tags []string, at time.Time) {
	t.Helper()
	n := &MemoryNode{ID: id, Title: title, Content: content, Tags: tags}
	if err := s.Insert(n); err != nil {
		t.Fatalf("insert %s: %v", id, err)
	}
	// Insert overwrote CreatedAt; fix it for the test.
	n.CreatedAt = at
	n.UpdatedAt = at
	s.nodes[id] = n
	// tagIdx was built from the node already; no reindex needed since
	// tags didn't change.
}

func TestMemStore_QueryByTimeRange(t *testing.T) {
	s := NewMemStore()
	t0 := time.Date(2026, 6, 23, 10, 0, 0, 0, time.UTC)
	insertAt(t, s, "n1", "first", "c1", []string{"a"}, t0)
	insertAt(t, s, "n2", "second", "c2", []string{"a"}, t0.Add(1*time.Hour))
	insertAt(t, s, "n3", "third", "c3", []string{"a"}, t0.Add(2*time.Hour))

	// [t0, t0+90min) → n1, n2 only.
	got, err := s.QueryByTimeRange(t0, t0.Add(90*time.Minute))
	if err != nil {
		t.Fatalf("QueryByTimeRange: %v", err)
	}
	if len(got) != 2 || got[0].ID != "n1" || got[1].ID != "n2" {
		t.Fatalf("got %v, want [n1, n2] oldest-first", idsOf(got))
	}

	// Open-ended [t0+1h, zero) → n2, n3.
	got, _ = s.QueryByTimeRange(t0.Add(1*time.Hour), time.Time{})
	if len(got) != 2 || got[0].ID != "n2" || got[1].ID != "n3" {
		t.Fatalf("open-ended got %v, want [n2, n3]", idsOf(got))
	}

	// Range before any node → empty.
	got, _ = s.QueryByTimeRange(t0.Add(-2*time.Hour), t0.Add(-1*time.Hour))
	if len(got) != 0 {
		t.Fatalf("empty range got %v, want []", idsOf(got))
	}
}

func TestMemStore_QueryByTagAndTimeRange(t *testing.T) {
	s := NewMemStore()
	t0 := time.Date(2026, 6, 23, 10, 0, 0, 0, time.UTC)
	insertAt(t, s, "n1", "first", "c1", []string{"work"}, t0)
	insertAt(t, s, "n2", "second", "c2", []string{"home"}, t0.Add(1*time.Hour))
	insertAt(t, s, "n3", "third", "c3", []string{"work"}, t0.Add(2*time.Hour))

	// work tag, full range → n1, n3 (n2 has "home").
	got, err := s.QueryByTagAndTimeRange("work", t0, time.Time{})
	if err != nil {
		t.Fatalf("QueryByTagAndTimeRange: %v", err)
	}
	if len(got) != 2 || got[0].ID != "n1" || got[1].ID != "n3" {
		t.Fatalf("got %v, want [n1, n3]", idsOf(got))
	}

	// work tag, range excluding n3 → only n1.
	got, _ = s.QueryByTagAndTimeRange("work", t0, t0.Add(90*time.Minute))
	if len(got) != 1 || got[0].ID != "n1" {
		t.Fatalf("got %v, want [n1]", idsOf(got))
	}

	// Tag nobody has → empty.
	got, _ = s.QueryByTagAndTimeRange("nonexistent", t0, time.Time{})
	if len(got) != 0 {
		t.Fatalf("got %v, want []", idsOf(got))
	}
}

func TestMemStore_Search(t *testing.T) {
	s := NewMemStore()
	insertAt(t, s, "n1", "Wedding Anniversary", "June 22 celebration", []string{"family"}, time.Now())
	insertAt(t, s, "n2", "Work Email", "alice@company.com", []string{"work"}, time.Now())
	insertAt(t, s, "n3", "Car Plate", "ABC-1234", []string{"vehicle"}, time.Now())

	// Match in title (case-insensitive).
	got, err := s.Search("WEDDING")
	if err != nil {
		t.Fatalf("Search: %v", err)
	}
	if len(got) != 1 || got[0].ID != "n1" {
		t.Fatalf("title match got %v, want [n1]", idsOf(got))
	}

	// Match in content.
	got, _ = s.Search("alice@company")
	if len(got) != 1 || got[0].ID != "n2" {
		t.Fatalf("content match got %v, want [n2]", idsOf(got))
	}

	// Substring across multiple nodes ("a" appears in several).
	got, _ = s.Search("a")
	if len(got) < 2 {
		t.Fatalf("broad search 'a' got %d, want >=2", len(got))
	}

	// No match.
	got, _ = s.Search("zzz-nope")
	if len(got) != 0 {
		t.Fatalf("no-match got %v, want []", idsOf(got))
	}

	// Empty keyword → empty result (NOT all nodes).
	got, _ = s.Search("")
	if len(got) != 0 {
		t.Fatalf("empty keyword got %d, want 0 (empty != wildcard)", len(got))
	}
}

// TestMemStore_ImplementsTimelineStore is a compile-time check that
// MemStore satisfies TimelineStore. If a method signature drifts this
// fails to compile, catching the break early.
func TestMemStore_ImplementsTimelineStore(t *testing.T) {
	var _ TimelineStore = (*MemStore)(nil)
}

func idsOf(nodes []*MemoryNode) []string {
	var ids []string
	for _, n := range nodes {
		ids = append(ids, n.ID)
	}
	return ids
}
