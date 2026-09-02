package casestore

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"

	"github.com/rvbernucci/signalforge/internal/privacy"
	"github.com/rvbernucci/signalforge/internal/workspace"
)

var (
	ErrNotFound = workspace.ErrCaseNotFound
	ErrConflict = workspace.ErrCaseConflict
)

type Store struct {
	db  *sql.DB
	now func() time.Time
}

func Open(path string) (*Store, error) {
	path = strings.TrimSpace(path)
	if path == "" {
		return nil, errors.New("case database path is required")
	}
	if path != ":memory:" {
		directory := filepath.Dir(path)
		if _, err := os.Stat(directory); errors.Is(err, os.ErrNotExist) {
			if err := os.MkdirAll(directory, 0o700); err != nil {
				return nil, fmt.Errorf("create case database directory: %w", err)
			}
			if err := os.Chmod(directory, 0o700); err != nil {
				return nil, fmt.Errorf("restrict case database directory: %w", err)
			}
		} else if err != nil {
			return nil, fmt.Errorf("inspect case database directory: %w", err)
		}
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open case database: %w", err)
	}
	db.SetMaxOpenConns(1)
	store := &Store{db: db, now: func() time.Time { return time.Now().UTC() }}
	if err := store.initialize(context.Background()); err != nil {
		db.Close()
		return nil, err
	}
	if path != ":memory:" {
		if err := os.Chmod(path, 0o600); err != nil {
			db.Close()
			return nil, fmt.Errorf("restrict case database: %w", err)
		}
	}
	return store, nil
}

func (store *Store) Close() error {
	if store == nil || store.db == nil {
		return nil
	}
	return store.db.Close()
}

func (store *Store) Save(ctx context.Context, projection workspace.Projection, parentRunID string) error {
	if err := workspace.Validate(projection); err != nil {
		return fmt.Errorf("validate case projection: %w", err)
	}
	payload, err := json.Marshal(projection)
	if err != nil {
		return fmt.Errorf("encode case projection: %w", err)
	}
	if privacy.ContainsSecret(payload) {
		return errors.New("case projection contains a credential-shaped value")
	}
	digest := sha256.Sum256(payload)
	savedAt := store.now().UTC()
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	result, err := tx.ExecContext(ctx, `
		INSERT INTO research_cases (
			case_id, run_id, parent_run_id, title, as_of, intent, saved_at,
			evidence_items, calculation_receipts, projection_sha256, projection_json
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, projection.CaseID, projection.RunID, nullable(parentRunID), projection.Title,
		projection.AsOf.UTC().Format(time.RFC3339Nano), projection.Intent, savedAt.Format(time.RFC3339Nano),
		len(projection.Evidence), len(projection.Calculations), hex.EncodeToString(digest[:]), payload)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") {
			return ErrConflict
		}
		return fmt.Errorf("insert research case: %w", err)
	}
	if affected, affectedErr := result.RowsAffected(); affectedErr != nil || affected != 1 {
		return errors.New("research case insert was not atomic")
	}
	for _, item := range projection.Evidence {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO case_evidence_refs (case_id, evidence_id, content_sha256, locator)
			VALUES (?, ?, ?, ?)
		`, projection.CaseID, item.EvidenceID, item.ContentSHA, item.Locator); err != nil {
			return fmt.Errorf("insert evidence reference: %w", err)
		}
	}
	for _, receipt := range projection.Calculations {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO case_calculation_refs (case_id, receipt_id, receipt_sha256, operation_id)
			VALUES (?, ?, ?, ?)
		`, projection.CaseID, receipt.ReceiptID, receipt.ReceiptSHA, receipt.OperationID); err != nil {
			return fmt.Errorf("insert calculation reference: %w", err)
		}
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO case_telemetry (
			case_id, duration_ms, model_calls, context_packets, critiques,
			claims, supported_claims, evidence_coverage, recorded_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, projection.CaseID, projection.Metrics.DurationMS, projection.Metrics.ModelCalls,
		projection.Metrics.ContextPackets, projection.Metrics.Critiques, projection.Metrics.Claims,
		projection.Metrics.SupportedClaims, projection.Metrics.EvidenceCoverage, savedAt.Format(time.RFC3339Nano)); err != nil {
		return fmt.Errorf("insert aggregate telemetry: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit research case: %w", err)
	}
	return nil
}

func (store *Store) Get(ctx context.Context, caseID string) (workspace.Projection, workspace.CaseSummary, error) {
	row := store.db.QueryRowContext(ctx, `
		SELECT case_id, run_id, COALESCE(parent_run_id, ''), title, as_of, intent, saved_at,
		       evidence_items, calculation_receipts, projection_sha256, projection_json
		FROM research_cases WHERE case_id = ?
	`, caseID)
	var summary workspace.CaseSummary
	var asOfRaw, savedAtRaw string
	var payload []byte
	if err := row.Scan(&summary.CaseID, &summary.RunID, &summary.ParentRunID, &summary.Title,
		&asOfRaw, &summary.Intent, &savedAtRaw, &summary.EvidenceItems,
		&summary.CalculationReceipts, &summary.ProjectionSHA, &payload); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return workspace.Projection{}, workspace.CaseSummary{}, ErrNotFound
		}
		return workspace.Projection{}, workspace.CaseSummary{}, err
	}
	var err error
	if summary.AsOf, err = time.Parse(time.RFC3339Nano, asOfRaw); err != nil {
		return workspace.Projection{}, workspace.CaseSummary{}, errors.New("stored case has invalid as-of time")
	}
	if summary.SavedAt, err = time.Parse(time.RFC3339Nano, savedAtRaw); err != nil {
		return workspace.Projection{}, workspace.CaseSummary{}, errors.New("stored case has invalid saved-at time")
	}
	digest := sha256.Sum256(payload)
	if hex.EncodeToString(digest[:]) != summary.ProjectionSHA {
		return workspace.Projection{}, workspace.CaseSummary{}, errors.New("stored case projection hash mismatch")
	}
	var projection workspace.Projection
	if err := json.Unmarshal(payload, &projection); err != nil {
		return workspace.Projection{}, workspace.CaseSummary{}, errors.New("stored case projection is malformed")
	}
	if err := workspace.Validate(projection); err != nil {
		return workspace.Projection{}, workspace.CaseSummary{}, fmt.Errorf("stored case projection is invalid: %w", err)
	}
	return projection, summary, nil
}

func (store *Store) List(ctx context.Context, limit int) ([]workspace.CaseSummary, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := store.db.QueryContext(ctx, `
		SELECT case_id, run_id, COALESCE(parent_run_id, ''), title, as_of, intent, saved_at,
		       evidence_items, calculation_receipts, projection_sha256
		FROM research_cases ORDER BY saved_at DESC, case_id DESC LIMIT ?
	`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var result []workspace.CaseSummary
	for rows.Next() {
		var item workspace.CaseSummary
		var asOfRaw, savedAtRaw string
		if err := rows.Scan(&item.CaseID, &item.RunID, &item.ParentRunID, &item.Title,
			&asOfRaw, &item.Intent, &savedAtRaw, &item.EvidenceItems,
			&item.CalculationReceipts, &item.ProjectionSHA); err != nil {
			return nil, err
		}
		if item.AsOf, err = time.Parse(time.RFC3339Nano, asOfRaw); err != nil {
			return nil, err
		}
		if item.SavedAt, err = time.Parse(time.RFC3339Nano, savedAtRaw); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (store *Store) Export(ctx context.Context, caseID string) (workspace.CaseExport, error) {
	projection, summary, err := store.Get(ctx, caseID)
	if err != nil {
		return workspace.CaseExport{}, err
	}
	return workspace.CaseExport{SchemaVersion: workspace.CaseExportSchemaV1, ExportedAt: store.now().UTC(), Summary: summary, Case: projection}, nil
}

func (store *Store) Delete(ctx context.Context, caseID string) error {
	result, err := store.db.ExecContext(ctx, `DELETE FROM research_cases WHERE case_id = ?`, caseID)
	if err != nil {
		return err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if affected == 0 {
		return ErrNotFound
	}
	return nil
}

func (store *Store) initialize(ctx context.Context) error {
	for _, statement := range []string{
		`PRAGMA foreign_keys = ON`,
		`PRAGMA busy_timeout = 5000`,
		`PRAGMA secure_delete = ON`,
		`CREATE TABLE IF NOT EXISTS research_cases (
			case_id TEXT PRIMARY KEY,
			run_id TEXT NOT NULL UNIQUE,
			parent_run_id TEXT,
			title TEXT NOT NULL,
			as_of TEXT NOT NULL,
			intent TEXT NOT NULL,
			saved_at TEXT NOT NULL,
			evidence_items INTEGER NOT NULL CHECK (evidence_items >= 0),
			calculation_receipts INTEGER NOT NULL CHECK (calculation_receipts >= 0),
			projection_sha256 TEXT NOT NULL CHECK (length(projection_sha256) = 64),
			projection_json BLOB NOT NULL
		) STRICT`,
		`CREATE TABLE IF NOT EXISTS case_evidence_refs (
			case_id TEXT NOT NULL REFERENCES research_cases(case_id) ON DELETE CASCADE,
			evidence_id TEXT NOT NULL,
			content_sha256 TEXT NOT NULL,
			locator TEXT NOT NULL,
			PRIMARY KEY (case_id, evidence_id)
		) STRICT`,
		`CREATE TABLE IF NOT EXISTS case_calculation_refs (
			case_id TEXT NOT NULL REFERENCES research_cases(case_id) ON DELETE CASCADE,
			receipt_id TEXT NOT NULL,
			receipt_sha256 TEXT NOT NULL,
			operation_id TEXT NOT NULL,
			PRIMARY KEY (case_id, receipt_id)
		) STRICT`,
		`CREATE TABLE IF NOT EXISTS case_telemetry (
			case_id TEXT PRIMARY KEY REFERENCES research_cases(case_id) ON DELETE CASCADE,
			duration_ms REAL NOT NULL,
			model_calls INTEGER NOT NULL,
			context_packets INTEGER NOT NULL,
			critiques INTEGER NOT NULL,
			claims INTEGER NOT NULL,
			supported_claims INTEGER NOT NULL,
			evidence_coverage REAL NOT NULL,
			recorded_at TEXT NOT NULL
		) STRICT`,
	} {
		if _, err := store.db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("initialize case database: %w", err)
		}
	}
	return nil
}

func nullable(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}
