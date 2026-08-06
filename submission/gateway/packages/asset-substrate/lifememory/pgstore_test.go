package lifememory

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// testPool returns a PG pool for PGStore tests, or skips the test when
// DATABASE_URL is unset. Mirrors the orchestrator package's testPool
// pattern.
func testPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL unset; skipping PG-backed lifememory test")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Skipf("could not connect to PG: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

// cleanupNodes removes the given IDs so tests don't accumulate rows.
func cleanupNodes(t *testing.T, pool *pgxpool.Pool, ids ...string) {
	t.Helper()
	if len(ids) == 0 {
		return
	}
	pool.Exec(context.Background(),
		`DELETE FROM life_memory_nodes WHERE id = ANY($1)`, ids)
}

func TestPGStore_InsertAndGetByID(t *testing.T) {
	pool := testPool(t)
	s := NewPGStore(pool)

	node := &MemoryNode{Title: "pg-test-insert", Content: "hello pg", Tags: []string{"t1", "t2"}}
	if err := s.Insert(node); err != nil {
		t.Fatalf("Insert: %v", err)
	}
	t.Cleanup(func() { cleanupNodes(t, pool, node.ID) })

	if node.ID == "" {
		t.Fatal("Insert did not fill ID (DB-generated UUID expected)")
	}

	got, err := s.GetByID(node.ID)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if got.Title != "pg-test-insert" || got.Content != "hello pg" {
		t.Fatalf("round-trip mismatch: %+v", got)
	}
	if len(got.Tags) != 2 || got.Tags[0] != "t1" {
		t.Fatalf("tags mismatch: %v", got.Tags)
	}
}

func TestPGStore_GetByID_NotFound(t *testing.T) {
	pool := testPool(t)
	s := NewPGStore(pool)

	_, err := s.GetByID("00000000-0000-0000-0000-000000000000")
	if err != ErrNodeNotFound {
		t.Fatalf("expected ErrNodeNotFound, got %v", err)
	}
}

func TestPGStore_QueryByTagAndTimeRange(t *testing.T) {
	pool := testPool(t)
	s := NewPGStore(pool)

	t0 := time.Date(2026, 6, 23, 10, 0, 0, 0, time.UTC)
	n1 := &MemoryNode{Title: "p1", Content: "c1", Tags: []string{"work"}, CreatedAt: t0}
	n2 := &MemoryNode{Title: "p2", Content: "c2", Tags: []string{"home"}, CreatedAt: t0.Add(1 * time.Hour)}
	n3 := &MemoryNode{Title: "p3", Content: "c3", Tags: []string{"work"}, CreatedAt: t0.Add(2 * time.Hour)}
	for _, n := range []*MemoryNode{n1, n2, n3} {
		if err := s.Insert(n); err != nil {
			t.Fatalf("Insert: %v", err)
		}
	}
	t.Cleanup(func() { cleanupNodes(t, pool, n1.ID, n2.ID, n3.ID) })

	// work tag, full range → n1, n3 oldest-first.
	got, err := s.QueryByTagAndTimeRange("work", t0, time.Time{})
	if err != nil {
		t.Fatalf("QueryByTagAndTimeRange: %v", err)
	}
	if len(got) != 2 || got[0].ID != n1.ID || got[1].ID != n3.ID {
		t.Fatalf("got %v, want [n1, n3]", nodeIDs(got))
	}

	// work tag, range excluding n3 → only n1.
	got, _ = s.QueryByTagAndTimeRange("work", t0, t0.Add(90*time.Minute))
	if len(got) != 1 || got[0].ID != n1.ID {
		t.Fatalf("got %v, want [n1]", nodeIDs(got))
	}
}

func TestPGStore_Search(t *testing.T) {
	pool := testPool(t)
	s := NewPGStore(pool)

	n := &MemoryNode{Title: "PostgreSQL Backup", Content: "pg_dump nightly", Tags: []string{"ops"}}
	if err := s.Insert(n); err != nil {
		t.Fatalf("Insert: %v", err)
	}
	t.Cleanup(func() { cleanupNodes(t, pool, n.ID) })

	// Case-insensitive title match.
	got, err := s.Search("postgresql")
	if err != nil {
		t.Fatalf("Search: %v", err)
	}
	if len(got) != 1 || got[0].ID != n.ID {
		t.Fatalf("title search got %v, want [%s]", nodeIDs(got), n.ID)
	}

	// Content match.
	got, _ = s.Search("pg_dump")
	if len(got) != 1 || got[0].ID != n.ID {
		t.Fatalf("content search got %v, want [%s]", nodeIDs(got), n.ID)
	}

	// Keyword with special LIKE chars must match literally, not as pattern.
	// Insert a node containing a literal underscore.
	n2 := &MemoryNode{Title: "node_2", Content: "x_y", Tags: []string{"s"}}
	s.Insert(n2)
	t.Cleanup(func() { cleanupNodes(t, pool, n2.ID) })
	got, _ = s.Search("node_2")
	if len(got) != 1 || got[0].ID != n2.ID {
		t.Fatalf("underscore literal search got %v, want [%s]", nodeIDs(got), n2.ID)
	}
}

func TestPGStore_Delete(t *testing.T) {
	pool := testPool(t)
	s := NewPGStore(pool)

	n := &MemoryNode{Title: "to-delete", Content: "bye", Tags: []string{"t"}}
	s.Insert(n)
	t.Cleanup(func() { cleanupNodes(t, pool, n.ID) })

	if err := s.Delete(n.ID); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, err := s.GetByID(n.ID); err != ErrNodeNotFound {
		t.Fatalf("after delete GetByID err = %v, want ErrNodeNotFound", err)
	}
	if err := s.Delete(n.ID); err != ErrNodeNotFound {
		t.Fatalf("double delete err = %v, want ErrNodeNotFound", err)
	}
}

// TestPGStore_ImplementsTimelineStore: compile-time check.
func TestPGStore_ImplementsTimelineStore(t *testing.T) {
	var _ TimelineStore = (*PGStore)(nil)
}

func nodeIDs(nodes []*MemoryNode) []string {
	var ids []string
	for _, n := range nodes {
		ids = append(ids, n.ID)
	}
	return ids
}
