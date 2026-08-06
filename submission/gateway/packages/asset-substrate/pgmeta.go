package substrate

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"time"
)

// ── PostgreSQL Meta Store ───────────────────────────────────────────
//
// PGStore provides CRUD operations for audit chain entries backed by
// PostgreSQL. The schema uses a single `substrate_audit` table with
// the same fields as AuditEntry.

const schemaSQL = `
CREATE TABLE IF NOT EXISTS substrate_audit (
    idx         BIGINT PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL UNIQUE,
    data        BYTEA
);

CREATE INDEX IF NOT EXISTS idx_substrate_audit_hash ON substrate_audit(hash);
CREATE INDEX IF NOT EXISTS idx_substrate_audit_actor ON substrate_audit(actor);
CREATE INDEX IF NOT EXISTS idx_substrate_audit_type ON substrate_audit(event_type);
`

const insertEntrySQL = `
INSERT INTO substrate_audit (idx, ts, event_type, actor, target, summary, prev_hash, hash, data)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
`

const lastEntrySQL = `
SELECT idx, ts, event_type, actor, target, summary, prev_hash, hash, data
FROM substrate_audit
ORDER BY idx DESC
LIMIT 1
`

const entryByHashSQL = `
SELECT idx, ts, event_type, actor, target, summary, prev_hash, hash, data
FROM substrate_audit
WHERE hash = $1
`

const entryByIndexSQL = `
SELECT idx, ts, event_type, actor, target, summary, prev_hash, hash, data
FROM substrate_audit
WHERE idx = $1
`

const countEntriesSQL = `SELECT COUNT(*) FROM substrate_audit`

// PGStore wraps a *sql.DB connection for substrate audit operations.
type PGStore struct {
	db *sql.DB
}

// NewPGStore creates a new PGStore and ensures the schema exists.
func NewPGStore(db *sql.DB) (*PGStore, error) {
	store := &PGStore{db: db}
	if err := store.EnsureSchema(); err != nil {
		return nil, fmt.Errorf("substrate: ensure schema: %w", err)
	}
	return store, nil
}

// EnsureSchema creates the substrate_audit table and indexes if they don't exist.
func (s *PGStore) EnsureSchema() error {
	_, err := s.db.Exec(schemaSQL)
	return err
}

// Append inserts a new audit entry into PostgreSQL.
// Returns the entry with its computed hash.
func (s *PGStore) Append(eventType, actor, target, summary string, data []byte) (*AuditEntry, error) {
	// Get the last entry's hash (or genesis hash)
	var prevHash string
	var lastIdx uint64
	last, err := s.Last()
	if err != nil {
		return nil, fmt.Errorf("substrate: get last: %w", err)
	}
	if last != nil {
		prevHash = last.Hash
		lastIdx = last.Index
	} else {
		prevHash = GenesisHash()
		lastIdx = 0
	}

	entry := AuditEntry{
		Index:     lastIdx + 1,
		Timestamp: time.Now().UTC(),
		EventType: eventType,
		Actor:     actor,
		Target:    target,
		Summary:   summary,
		PrevHash:  prevHash,
		Data:      data,
	}
	entry.Hash = entry.ComputeHash()

	_, err = s.db.Exec(insertEntrySQL,
		entry.Index, entry.Timestamp, entry.EventType, entry.Actor,
		entry.Target, entry.Summary, entry.PrevHash, entry.Hash, entry.Data)
	if err != nil {
		return nil, fmt.Errorf("substrate: insert: %w", err)
	}
	return &entry, nil
}

// Last retrieves the most recent entry, or nil if the table is empty.
func (s *PGStore) Last() (*AuditEntry, error) {
	row := s.db.QueryRow(lastEntrySQL)
	return scanEntry(row)
}

// GetByHash retrieves an entry by its SHA-256 hash.
func (s *PGStore) GetByHash(hash string) (*AuditEntry, error) {
	row := s.db.QueryRow(entryByHashSQL, hash)
	return scanEntry(row)
}

// GetByIndex retrieves an entry by its sequential index.
func (s *PGStore) GetByIndex(idx uint64) (*AuditEntry, error) {
	row := s.db.QueryRow(entryByIndexSQL, idx)
	return scanEntry(row)
}

// Count returns the total number of entries.
func (s *PGStore) Count() (int, error) {
	var count int
	err := s.db.QueryRow(countEntriesSQL).Scan(&count)
	return count, err
}

// ── Schema DDL ──────────────────────────────────────────────────────

// SchemaDDL returns the SQL DDL for the substrate_audit table.
func SchemaDDL() string {
	return schemaSQL
}

// ── Helpers ─────────────────────────────────────────────────────────

// scanner is an interface satisfied by both *sql.Row and *sql.Rows.
type scanner interface {
	Scan(dest ...interface{}) error
}

func scanEntry(row scanner) (*AuditEntry, error) {
	var e AuditEntry
	var dataBytes []byte
	err := row.Scan(
		&e.Index, &e.Timestamp, &e.EventType, &e.Actor,
		&e.Target, &e.Summary, &e.PrevHash, &e.Hash, &dataBytes,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("substrate: scan: %w", err)
	}
	e.Data = dataBytes
	return &e, nil
}

// ── JSON Helpers ────────────────────────────────────────────────────

// AuditEntryJSON returns the JSON representation of an audit entry.
func AuditEntryJSON(e *AuditEntry) ([]byte, error) {
	if e == nil {
		return []byte("null"), nil
	}
	return json.Marshal(e)
}
