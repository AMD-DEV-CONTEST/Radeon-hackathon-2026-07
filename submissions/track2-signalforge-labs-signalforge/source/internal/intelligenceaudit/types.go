package intelligenceaudit

import (
	"context"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
)

const (
	SchemaVersionV1          = "signalforge/intelligence-lineage/v1"
	ProtectedSchemaVersionV1 = "signalforge/protected-inference-audit/v1"
)

type ModelObserver interface {
	ObserveModelCall(context.Context, string, string, benchmark.Request, benchmark.Completion, error)
}

type Record struct {
	SchemaVersion string            `json:"schema_version"`
	RunID         string            `json:"run_id"`
	RequestID     string            `json:"request_id"`
	TraceID       string            `json:"trace_id"`
	Status        string            `json:"status"`
	Capture       CaptureState      `json:"capture"`
	StartedAt     time.Time         `json:"started_at"`
	CompletedAt   *time.Time        `json:"completed_at,omitempty"`
	Timeline      []LifecycleEvent  `json:"timeline"`
	ModelCalls    []ModelCall       `json:"model_calls"`
	Retrievals    []RetrievalRecord `json:"retrievals"`
	Engines       []EngineCall      `json:"engine_calls"`
	Reviews       []ReviewRecord    `json:"reviews"`
	Release       *ReleaseRecord    `json:"release,omitempty"`
}

// LifecycleEvent is the bounded, public operational trace. It intentionally excludes prompt,
// response, evidence, calculation-value, memory, and error bodies.
type LifecycleEvent struct {
	Sequence            int       `json:"sequence"`
	StepID              string    `json:"step_id,omitempty"`
	EventType           string    `json:"event_type"`
	Status              string    `json:"status"`
	Wave                int       `json:"wave,omitempty"`
	RoleID              string    `json:"role_id,omitempty"`
	Route               string    `json:"route,omitempty"`
	RouteReasonCode     string    `json:"route_reason_code,omitempty"`
	Attempt             int       `json:"attempt,omitempty"`
	SpecialistCount     int       `json:"specialist_count,omitempty"`
	ConcurrencyLimit    int       `json:"concurrency_limit,omitempty"`
	SucceededCount      int       `json:"succeeded_count,omitempty"`
	FailedCount         int       `json:"failed_count,omitempty"`
	ObservedConcurrency int       `json:"observed_concurrency,omitempty"`
	FailureCode         string    `json:"failure_code,omitempty"`
	At                  time.Time `json:"at"`
}

type CaptureState struct {
	Enabled      bool       `json:"enabled"`
	Available    bool       `json:"available"`
	Status       string     `json:"status"`
	ExpiresAt    *time.Time `json:"expires_at,omitempty"`
	StoredBytes  int64      `json:"stored_bytes"`
	MaximumBytes int64      `json:"maximum_bytes"`
}

type ModelCall struct {
	ModelCallID       string    `json:"model_call_id"`
	StepID            string    `json:"step_id"`
	RoleID            string    `json:"role_id"`
	RoleClass         string    `json:"role_class"`
	ProviderID        string    `json:"provider_id"`
	ModelID           string    `json:"model_id"`
	Route             string    `json:"route"`
	PromptTemplateID  string    `json:"prompt_template_id"`
	PromptInstanceID  string    `json:"prompt_instance_id"`
	SystemPromptSHA   string    `json:"system_prompt_sha256"`
	RequestPayloadSHA string    `json:"request_payload_sha256"`
	ResponseSHA       string    `json:"response_payload_sha256,omitempty"`
	ResponseSchemaSHA string    `json:"response_schema_sha256,omitempty"`
	InputTokens       int       `json:"input_tokens"`
	OutputTokens      int       `json:"output_tokens"`
	MaxOutputTokens   int       `json:"max_output_tokens"`
	StartedAt         time.Time `json:"started_at"`
	DurationMS        float64   `json:"duration_ms"`
	TTFTMS            float64   `json:"ttft_ms"`
	FinishReason      string    `json:"finish_reason,omitempty"`
	Status            string    `json:"status"`
	FailureCode       string    `json:"failure_code,omitempty"`
	ProtectedInputID  string    `json:"protected_input_id,omitempty"`
	ProtectedOutputID string    `json:"protected_output_id,omitempty"`
}

type RetrievalRecord struct {
	RetrievalID       string                 `json:"retrieval_id"`
	StepID            string                 `json:"step_id"`
	RoleID            string                 `json:"role_id"`
	Method            string                 `json:"method"`
	IndexVersion      string                 `json:"index_version,omitempty"`
	QuerySHA          string                 `json:"query_sha256,omitempty"`
	ContextPacketID   string                 `json:"context_packet_id"`
	EvidenceIDs       []string               `json:"evidence_ids"`
	EvidenceSources   []EvidenceSourceRecord `json:"evidence_sources,omitempty"`
	ChunkIDs          []string               `json:"chunk_ids,omitempty"`
	DocumentIDs       []string               `json:"document_ids,omitempty"`
	GraphTraversalIDs []string               `json:"graph_traversal_ids,omitempty"`
	DroppedIDs        []string               `json:"dropped_ids,omitempty"`
	EstimatedTokens   int                    `json:"estimated_tokens"`
	Status            string                 `json:"status"`
	CompletedAt       time.Time              `json:"completed_at"`
}

type EvidenceSourceRecord struct {
	EvidenceID      string    `json:"evidence_id"`
	SourceType      string    `json:"source_type"`
	Locator         string    `json:"locator"`
	DocumentSection string    `json:"document_section,omitempty"`
	ContentSHA      string    `json:"content_sha256"`
	AsOf            time.Time `json:"as_of"`
}

type EngineCall struct {
	EngineCallID    string    `json:"engine_call_id"`
	StepID          string    `json:"step_id"`
	RequestedBy     string    `json:"requested_by"`
	EngineID        string    `json:"engine_id"`
	EngineVersion   string    `json:"engine_version"`
	OperationID     string    `json:"operation_id"`
	FormulaVersion  string    `json:"formula_version"`
	ReceiptID       string    `json:"receipt_id"`
	ReceiptSHA      string    `json:"receipt_sha256"`
	InputRefs       []string  `json:"input_refs"`
	OutputRefs      []string  `json:"output_refs"`
	EvidenceRefs    []string  `json:"evidence_refs,omitempty"`
	InvariantsTotal int       `json:"invariants_total"`
	InvariantsPass  int       `json:"invariants_passed"`
	Status          string    `json:"status"`
	GeneratedAt     time.Time `json:"generated_at"`
}

type ReviewRecord struct {
	ReviewID       string   `json:"review_id"`
	RoleID         string   `json:"role_id"`
	Decision       string   `json:"decision"`
	RepairPass     int      `json:"repair_pass"`
	ApprovedClaims []string `json:"approved_claims,omitempty"`
	RejectedClaims []string `json:"rejected_claims,omitempty"`
}

type ReleaseRecord struct {
	AnswerID      string   `json:"answer_id"`
	PrimaryIntent string   `json:"primary_intent"`
	SectionTypes  []string `json:"section_types"`
	ClaimRefs     []string `json:"claim_refs"`
	EvidenceRefs  []string `json:"evidence_refs"`
	ReceiptRefs   []string `json:"receipt_refs"`
	Status        string   `json:"status"`
}

type ProtectedRecord struct {
	SchemaVersion string               `json:"schema_version"`
	RunID         string               `json:"run_id"`
	RequestID     string               `json:"request_id"`
	Question      string               `json:"question"`
	CreatedAt     time.Time            `json:"created_at"`
	ExpiresAt     time.Time            `json:"expires_at"`
	ModelCalls    []ProtectedModelCall `json:"model_calls"`
	Receipts      []ProtectedReceipt   `json:"receipts"`
}

type ProtectedModelCall struct {
	ModelCallID      string          `json:"model_call_id"`
	PromptInstanceID string          `json:"prompt_instance_id"`
	Messages         []SafeMessage   `json:"messages"`
	ResponseFormat   map[string]any  `json:"response_format,omitempty"`
	Parameters       ModelParameters `json:"parameters"`
	RawOutput        string          `json:"raw_output,omitempty"`
}

type SafeMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type ModelParameters struct {
	Model       string  `json:"model"`
	MaxTokens   int     `json:"max_tokens"`
	Temperature float64 `json:"temperature"`
	Stream      bool    `json:"stream"`
}

type ProtectedReceipt struct {
	ReceiptID string `json:"receipt_id"`
	Payload   any    `json:"payload"`
}

type ProjectionInput struct {
	RunID       string
	RequestID   string
	Question    string
	StartedAt   time.Time
	CompletedAt time.Time
	Status      string
	Retrievals  []RetrievalRecord
	Engines     []EngineCall
	Reviews     []ReviewRecord
	Release     *ReleaseRecord
	Receipts    []ProtectedReceipt
}
