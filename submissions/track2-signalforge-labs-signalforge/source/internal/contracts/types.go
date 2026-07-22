package contracts

import "time"

const SchemaVersionV1 = "signalforge/v1"

type Scope struct {
	CompanyIDs  []string  `json:"company_ids,omitempty"`
	SecurityIDs []string  `json:"security_ids,omitempty"`
	Periods     []string  `json:"periods,omitempty"`
	AsOf        time.Time `json:"as_of"`
}

type EvidenceRef struct {
	EvidenceID      string    `json:"evidence_id"`
	SourceType      string    `json:"source_type"`
	DocumentSection string    `json:"document_section,omitempty"`
	Locator         string    `json:"locator"`
	ContentSHA      string    `json:"content_sha256"`
	AsOf            time.Time `json:"as_of"`
}

type ClaimType string

type FindingOrigin string

const (
	ClaimFact        ClaimType = "fact"
	ClaimCalculation ClaimType = "calculation"
	ClaimInference   ClaimType = "inference"
	ClaimHypothesis  ClaimType = "hypothesis"

	FindingOriginDeterministic    FindingOrigin = "deterministic_engine"
	FindingOriginSourceExtraction FindingOrigin = "source_extraction"
)

type Finding struct {
	ClaimID         string        `json:"claim_id"`
	ClaimType       ClaimType     `json:"claim_type"`
	Origin          FindingOrigin `json:"origin,omitempty"`
	Statement       string        `json:"statement"`
	EvidenceRefs    []string      `json:"evidence_refs,omitempty"`
	CalculationRefs []string      `json:"calculation_refs,omitempty"`
	NumericalRefs   []string      `json:"numerical_refs,omitempty"`
	AssumptionRefs  []string      `json:"assumption_refs,omitempty"`
	Confidence      float64       `json:"confidence"`
	ValidAsOf       time.Time     `json:"valid_as_of"`
}

type ContextPacket struct {
	SchemaVersion       string               `json:"schema_version"`
	PacketID            string               `json:"packet_id"`
	RunID               string               `json:"run_id"`
	StepID              string               `json:"step_id"`
	SpecialistRole      string               `json:"specialist_role"`
	Objective           string               `json:"objective"`
	Scope               Scope                `json:"scope"`
	Findings            []Finding            `json:"findings"`
	Evidence            []EvidenceRef        `json:"evidence,omitempty"`
	CalculationReceipts []CalculationReceipt `json:"calculation_receipts,omitempty"`
	NumericalContext    *NumericalContext    `json:"numerical_context,omitempty"`
	Counterevidence     []Finding            `json:"counterevidence,omitempty"`
	Assumptions         []string             `json:"assumptions,omitempty"`
	MissingEvidence     []string             `json:"missing_evidence,omitempty"`
	Conflicts           []string             `json:"conflicts,omitempty"`
	Uncertainties       []string             `json:"uncertainties,omitempty"`
	HandoffNotes        []string             `json:"handoff_notes,omitempty"`
}

type Quantity struct {
	Value    string     `json:"value"`
	Unit     string     `json:"unit"`
	Currency string     `json:"currency,omitempty"`
	Scale    int32      `json:"scale,omitempty"`
	Period   string     `json:"period,omitempty"`
	AsOf     *time.Time `json:"as_of,omitempty"`
}

type EngineInput struct {
	InputID      string   `json:"input_id"`
	Quantity     Quantity `json:"quantity"`
	Status       string   `json:"status"`
	EvidenceRefs []string `json:"evidence_refs,omitempty"`
}

type EngineRequest struct {
	SchemaVersion    string        `json:"schema_version"`
	RequestID        string        `json:"request_id"`
	RunID            string        `json:"run_id"`
	StepID           string        `json:"step_id"`
	RequestedBy      string        `json:"requested_by"`
	EngineID         string        `json:"engine_id"`
	OperationID      string        `json:"operation_id"`
	FormulaVersion   string        `json:"formula_version"`
	Scope            Scope         `json:"scope"`
	Inputs           []EngineInput `json:"inputs"`
	Assumptions      []string      `json:"assumptions,omitempty"`
	PrecisionPolicy  string        `json:"precision_policy"`
	RequestedOutputs []string      `json:"requested_outputs"`
}

type ReceiptStatus string

const (
	ReceiptSuccess       ReceiptStatus = "success"
	ReceiptPartial       ReceiptStatus = "partial"
	ReceiptRefused       ReceiptStatus = "refused"
	ReceiptInvalid       ReceiptStatus = "invalid"
	ReceiptNonConvergent ReceiptStatus = "non_convergent"
)

type ReceiptOutput struct {
	OutputID string   `json:"output_id"`
	Quantity Quantity `json:"quantity"`
	Status   string   `json:"status"`
}

type InvariantResult struct {
	InvariantID string `json:"invariant_id"`
	Passed      bool   `json:"passed"`
	Detail      string `json:"detail,omitempty"`
}

type CalculationReceipt struct {
	SchemaVersion      string            `json:"schema_version"`
	ReceiptID          string            `json:"receipt_id"`
	RequestID          string            `json:"request_id"`
	EngineID           string            `json:"engine_id"`
	EngineVersion      string            `json:"engine_version"`
	OperationID        string            `json:"operation_id"`
	FormulaVersion     string            `json:"formula_version"`
	Scope              Scope             `json:"scope,omitempty"`
	Status             ReceiptStatus     `json:"status"`
	NormalizedInputs   []EngineInput     `json:"normalized_inputs"`
	Assumptions        []string          `json:"assumptions,omitempty"`
	IntermediateValues []ReceiptOutput   `json:"intermediate_values,omitempty"`
	Outputs            []ReceiptOutput   `json:"outputs"`
	InvariantResults   []InvariantResult `json:"invariant_results"`
	TolerancePolicy    string            `json:"tolerance_policy"`
	Warnings           []string          `json:"warnings,omitempty"`
	EvidenceRefs       []string          `json:"evidence_refs,omitempty"`
	DatasetVersions    []string          `json:"dataset_versions,omitempty"`
	SourceAsOf         time.Time         `json:"source_as_of"`
	CodeCommit         string            `json:"code_commit"`
	InputSHA           string            `json:"input_sha256"`
	ReceiptSHA         string            `json:"receipt_sha256"`
	GeneratedAt        time.Time         `json:"generated_at"`
}

type EvidenceArtifact struct {
	ArtifactID string            `json:"artifact_id"`
	Kind       string            `json:"kind"`
	Path       string            `json:"path"`
	SHA256     string            `json:"sha256"`
	Metrics    map[string]string `json:"metrics,omitempty"`
}

type EvidenceManifest struct {
	SchemaVersion string             `json:"schema_version"`
	RunID         string             `json:"run_id"`
	CodeCommit    string             `json:"code_commit"`
	CodeTreeSHA   string             `json:"code_tree_sha256"`
	CodeDirty     bool               `json:"code_dirty"`
	CreatedAt     time.Time          `json:"created_at"`
	Runtime       RuntimeIdentity    `json:"runtime"`
	GPU           *GPUIdentity       `json:"gpu,omitempty"`
	Models        []ModelIdentity    `json:"models,omitempty"`
	Datasets      []DatasetIdentity  `json:"datasets,omitempty"`
	Artifacts     []EvidenceArtifact `json:"artifacts"`
	ManifestSHA   string             `json:"manifest_sha256"`
}
