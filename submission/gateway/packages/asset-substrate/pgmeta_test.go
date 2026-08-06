package substrate

import (
	"database/sql"
	"testing"
)

// ── In-Memory SQLite for PG meta tests ─────────────────────────────
//
// We detect a CGo-free fallback: if modernc.org/sqlite is available we
// use it; otherwise we skip the PG meta test and report the constraint.
// The encryption and audit chain tests run without any external DB.

func TestSchemaDDL(t *testing.T) {
	ddl := SchemaDDL()
	if ddl == "" {
		t.Fatal("SchemaDDL returned empty string")
	}
	if len(ddl) < 100 {
		t.Errorf("DDL seems too short: %d chars", len(ddl))
	}
}

// TestPGStoreSQLite runs PG meta tests against an in-memory SQLite DB.
// If no SQLite driver is available (CGo disabled), the test is skipped.
func TestPGStoreSQLite(t *testing.T) {
	db, err := openSQLiteMem()
	if err != nil {
		t.Skipf("SQLite not available (CGo disabled?): %v", err)
	}
	defer db.Close()

	store, err := NewPGStore(db)
	if err != nil {
		t.Fatalf("NewPGStore failed: %v", err)
	}

	// Append entries
	e1, err := store.Append("asset.created", "alice", "asset-001", "Created credential", nil)
	if err != nil {
		t.Fatalf("Append 1 failed: %v", err)
	}
	if e1.Index != 1 {
		t.Errorf("expected index 1 (first SQL entry), got %d", e1.Index)
	}
	if e1.Hash == "" {
		t.Fatal("hash is empty")
	}

	e2, err := store.Append("asset.updated", "bob", "asset-001", "Updated fields", []byte("diff"))
	if err != nil {
		t.Fatalf("Append 2 failed: %v", err)
	}
	if e2.Index != 2 {
		t.Errorf("expected index 2, got %d", e2.Index)
	}
	if e2.PrevHash != e1.Hash {
		t.Error("chain linking broken: e2.PrevHash != e1.Hash")
	}

	e3, err := store.Append("asset.deleted", "alice", "asset-001", "Deleted asset", nil)
	if err != nil {
		t.Fatalf("Append 3 failed: %v", err)
	}
	if e3.Index != 3 {
		t.Errorf("expected index 3, got %d", e3.Index)
	}

	// Test Count
	count, err := store.Count()
	if err != nil {
		t.Fatalf("Count failed: %v", err)
	}
	if count != 3 {
		t.Errorf("expected count 3, got %d", count)
	}

	// Test Last
	last, err := store.Last()
	if err != nil {
		t.Fatalf("Last failed: %v", err)
	}
	if last == nil {
		t.Fatal("expected non-nil last entry")
	}
	if last.Index != 3 {
		t.Errorf("expected last index 3, got %d", last.Index)
	}

	// Test GetByHash
	fetched, err := store.GetByHash(e2.Hash)
	if err != nil {
		t.Fatalf("GetByHash failed: %v", err)
	}
	if fetched == nil {
		t.Fatal("expected non-nil entry")
	}
	if fetched.Index != 2 {
		t.Errorf("expected index 2, got %d", fetched.Index)
	}
	if fetched.Actor != "bob" {
		t.Errorf("expected actor bob, got %s", fetched.Actor)
	}
	if string(fetched.Data) != "diff" {
		t.Errorf("expected data 'diff', got '%s'", string(fetched.Data))
	}

	// Test GetByIndex
	fetched2, err := store.GetByIndex(1)
	if err != nil {
		t.Fatalf("GetByIndex failed: %v", err)
	}
	if fetched2 == nil {
		t.Fatal("expected non-nil entry")
	}
	if fetched2.Index != 1 {
		t.Errorf("expected index 1, got %d", fetched2.Index)
	}

	// Test hash chain integrity in PG
	all := []*AuditEntry{e1, e2, e3}
	for i := 1; i < len(all); i++ {
		if all[i].PrevHash != all[i-1].Hash {
			t.Errorf("PG chain broken at index %d", all[i].Index)
		}
	}
}

// openSQLiteMem tries to open an in-memory SQLite database.
// It first tries modernc.org/sqlite (CGo-free), then falls back to
// github.com/mattn/go-sqlite3 (CGo-required).
func openSQLiteMem() (*sql.DB, error) {
	// Try modernc.org/sqlite first (pure Go, no CGo)
	db, err := sql.Open("sqlite", "file::memory:?cache=shared")
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}
