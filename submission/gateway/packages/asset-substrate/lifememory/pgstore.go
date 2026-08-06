package lifememory

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// PGStore implements TimelineStore backed by PostgreSQL. It is the
// production memory store; MemStore is its test double.
//
// The table is life_memory_nodes (see internal/db/postgres.go migration).
// All methods carry a 3s context timeout — memory ops are not on the
// hot path and should not hold a request open indefinitely.
type PGStore struct {
	pool *pgxpool.Pool
}

// NewPGStore returns a PGStore. The pool must already be connected;
// PGStore does no connection management of its own.
func NewPGStore(pool *pgxpool.Pool) *PGStore {
	return &PGStore{pool: pool}
}

// queryTimeout caps every PGStore operation. Memory writes/reads are
// not latency-critical; a stuck query should fail fast rather than pile
// up goroutines.
const queryTimeout = 3 * time.Second

// Insert adds a node. If node.ID is empty, the DB generates a UUID and
// it is written back into node.ID. CreatedAt/UpdatedAt are stamped by
// the DB default (now()) unless the caller already set them — the
// caller-set value wins so tests can pin timestamps.
func (s *PGStore) Insert(node *MemoryNode) error {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()

	if node.ID == "" {
		// Let DB generate the UUID; RETURNING fills it back in.
		var id string
		err := s.pool.QueryRow(ctx, `
			INSERT INTO life_memory_nodes (title, content, tags, created_at, updated_at)
			VALUES ($1, $2, $3, COALESCE($4, now()), COALESCE($4, now()))
			RETURNING id, created_at, updated_at`,
			node.Title, node.Content, node.Tags, nullableTime(node.CreatedAt),
		).Scan(&id, &node.CreatedAt, &node.UpdatedAt)
		if err != nil {
			return fmt.Errorf("lifememory insert: %w", err)
		}
		node.ID = id
		return nil
	}

	// Caller-supplied ID: insert it directly. On conflict (duplicate ID)
	// return an error rather than silently overwriting — memory nodes are
	// append-mostly and a collision is a caller bug.
	_, err := s.pool.Exec(ctx, `
		INSERT INTO life_memory_nodes (id, title, content, tags, created_at, updated_at)
		VALUES ($1, $2, $3, $4, COALESCE($5, now()), COALESCE($5, now()))`,
		node.ID, node.Title, node.Content, node.Tags, nullableTime(node.CreatedAt),
	)
	if err != nil {
		return fmt.Errorf("lifememory insert: %w", err)
	}
	if node.CreatedAt.IsZero() {
		// Read back the DB-stamped time so the caller sees what landed.
		s.pool.QueryRow(ctx, `SELECT created_at FROM life_memory_nodes WHERE id = $1`, node.ID).Scan(&node.CreatedAt)
		node.UpdatedAt = node.CreatedAt
	}
	return nil
}

// GetByID retrieves a single node. Returns ErrNodeNotFound when absent,
// matching MemStore.
func (s *PGStore) GetByID(id string) (*MemoryNode, error) {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	n, err := s.scanNode(ctx, `SELECT id, title, content, tags, created_at, updated_at
		FROM life_memory_nodes WHERE id = $1`, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNodeNotFound
	}
	return n, err
}

// QueryByTag returns nodes carrying the given tag, using the GIN index
// on tags (`tags @> ARRAY[...]`).
func (s *PGStore) QueryByTag(tag string) ([]*MemoryNode, error) {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
		FROM life_memory_nodes WHERE tags @> ARRAY[$1]::text[]
		ORDER BY created_at DESC`, tag)
}

// QueryByTags returns nodes matching ALL given tags (AND logic).
func (s *PGStore) QueryByTags(tags []string) ([]*MemoryNode, error) {
	if len(tags) == 0 {
		return []*MemoryNode{}, nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
		FROM life_memory_nodes WHERE tags @> $1::text[]
		ORDER BY created_at DESC`, tags)
}

// Delete removes a node by ID. ErrNodeNotFound if absent.
func (s *PGStore) Delete(id string) error {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	tag, err := s.pool.Exec(ctx, `DELETE FROM life_memory_nodes WHERE id = $1`, id)
	if err != nil {
		return fmt.Errorf("lifememory delete: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrNodeNotFound
	}
	return nil
}

// Count returns the total node count.
func (s *PGStore) Count() (int, error) {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	var n int
	err := s.pool.QueryRow(ctx, `SELECT count(*) FROM life_memory_nodes`).Scan(&n)
	return n, err
}

// ── TimelineStore methods ────────────────────────────────────────────

// QueryByTimeRange returns nodes with created_at in [start, end). A
// zero end means no upper bound. Ordered oldest-first to match MemStore.
func (s *PGStore) QueryByTimeRange(start, end time.Time) ([]*MemoryNode, error) {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	if end.IsZero() {
		return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
			FROM life_memory_nodes WHERE created_at >= $1
			ORDER BY created_at ASC`, start)
	}
	return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
		FROM life_memory_nodes WHERE created_at >= $1 AND created_at < $2
		ORDER BY created_at ASC`, start, end)
}

// QueryByTagAndTimeRange is QueryByTimeRange restricted to nodes with
// the given tag.
func (s *PGStore) QueryByTagAndTimeRange(tag string, start, end time.Time) ([]*MemoryNode, error) {
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	if end.IsZero() {
		return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
			FROM life_memory_nodes WHERE tags @> ARRAY[$1]::text[] AND created_at >= $2
			ORDER BY created_at ASC`, tag, start)
	}
	return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
		FROM life_memory_nodes WHERE tags @> ARRAY[$1]::text[] AND created_at >= $2 AND created_at < $3
		ORDER BY created_at ASC`, tag, start, end)
}

// Search returns nodes whose title or content contains keyword,
// case-insensitive (ILIKE). Empty keyword → empty result, matching
// MemStore's "empty is not a wildcard" contract.
func (s *PGStore) Search(keyword string) ([]*MemoryNode, error) {
	if keyword == "" {
		return []*MemoryNode{}, nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), queryTimeout)
	defer cancel()
	pattern := "%" + escapeLike(keyword) + "%"
	return s.scanNodes(ctx, `SELECT id, title, content, tags, created_at, updated_at
		FROM life_memory_nodes
		WHERE title ILIKE $1 OR content ILIKE $1
		ORDER BY created_at DESC`, pattern)
}

// ── scan helpers ─────────────────────────────────────────────────────

func (s *PGStore) scanNode(ctx context.Context, query string, args ...interface{}) (*MemoryNode, error) {
	row := s.pool.QueryRow(ctx, query, args...)
	n := &MemoryNode{}
	err := row.Scan(&n.ID, &n.Title, &n.Content, &n.Tags, &n.CreatedAt, &n.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return n, nil
}

func (s *PGStore) scanNodes(ctx context.Context, query string, args ...interface{}) ([]*MemoryNode, error) {
	rows, err := s.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []*MemoryNode
	for rows.Next() {
		n := &MemoryNode{}
		if err := rows.Scan(&n.ID, &n.Title, &n.Content, &n.Tags, &n.CreatedAt, &n.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

// nullableTime returns a pointer to t for COALESCE, or nil if t is zero
// (so the DB default now() applies).
func nullableTime(t time.Time) *time.Time {
	if t.IsZero() {
		return nil
	}
	return &t
}

// escapeLike neutralizes % and _ in a user keyword so they match
// literally in an ILIKE pattern. Backslash is the default ESCAPE char.
func escapeLike(s string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return r.Replace(s)
}
