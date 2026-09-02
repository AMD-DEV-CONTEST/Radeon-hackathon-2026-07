package workspace

import (
	"context"
	"errors"
	"time"
)

const CaseExportSchemaV1 = "signalforge/research-case-export/v1"

var (
	ErrCaseNotFound = errors.New("research case not found")
	ErrCaseConflict = errors.New("research case already exists")
)

type CaseStore interface {
	Save(context.Context, Projection, string) error
	Get(context.Context, string) (Projection, CaseSummary, error)
	List(context.Context, int) ([]CaseSummary, error)
	Export(context.Context, string) (CaseExport, error)
	Delete(context.Context, string) error
}

type CaseSummary struct {
	CaseID              string    `json:"case_id"`
	RunID               string    `json:"run_id"`
	ParentRunID         string    `json:"parent_run_id,omitempty"`
	Title               string    `json:"title"`
	AsOf                time.Time `json:"as_of"`
	Intent              string    `json:"intent"`
	SavedAt             time.Time `json:"saved_at"`
	EvidenceItems       int       `json:"evidence_items"`
	CalculationReceipts int       `json:"calculation_receipts"`
	ProjectionSHA       string    `json:"projection_sha256"`
}

type CaseExport struct {
	SchemaVersion string      `json:"schema_version"`
	ExportedAt    time.Time   `json:"exported_at"`
	Summary       CaseSummary `json:"summary"`
	Case          Projection  `json:"case"`
}

type RetentionView struct {
	Requested bool   `json:"requested"`
	Status    string `json:"status"`
	CaseID    string `json:"case_id,omitempty"`
	ErrorCode string `json:"error_code,omitempty"`
}
