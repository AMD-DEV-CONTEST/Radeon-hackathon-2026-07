package contracts

import "time"

type EntityRef struct {
	EntityType string `json:"entity_type"`
	EntityID   string `json:"entity_id,omitempty"`
	Mention    string `json:"mention"`
	Resolved   bool   `json:"resolved"`
}

type PeriodScope struct {
	Kind          string     `json:"kind"`
	LookbackYears int        `json:"lookback_years,omitempty"`
	Start         *time.Time `json:"start,omitempty"`
	End           *time.Time `json:"end,omitempty"`
	FiscalYears   []int      `json:"fiscal_years,omitempty"`
	FiscalPeriods []string   `json:"fiscal_periods,omitempty"`
}

type ComparisonScope struct {
	Mode      string   `json:"mode"`
	EntityIDs []string `json:"entity_ids,omitempty"`
	Metrics   []string `json:"metrics,omitempty"`
}

type ResearchRequest struct {
	SchemaVersion       string          `json:"schema_version"`
	RequestID           string          `json:"request_id"`
	RunID               string          `json:"run_id"`
	ParentRequestID     string          `json:"parent_request_id,omitempty"`
	LineageEvidenceRefs []string        `json:"lineage_evidence_refs,omitempty"`
	LineageReceiptRefs  []string        `json:"lineage_receipt_refs,omitempty"`
	UserText            string          `json:"user_text"`
	PrimaryIntent       string          `json:"primary_intent"`
	SecondaryIntents    []string        `json:"secondary_intents,omitempty"`
	Entities            []EntityRef     `json:"entities,omitempty"`
	Period              PeriodScope     `json:"period"`
	AsOf                time.Time       `json:"as_of"`
	Comparison          ComparisonScope `json:"comparison"`
	AnswerDepth         string          `json:"answer_depth"`
	RequestedOutputs    []string        `json:"requested_outputs"`
	Assumptions         []string        `json:"assumptions,omitempty"`
	Ambiguities         []string        `json:"ambiguities,omitempty"`
	RiskFlags           []string        `json:"risk_flags,omitempty"`
}

type PlanStep struct {
	StepID               string   `json:"step_id"`
	Kind                 string   `json:"kind"`
	Wave                 int      `json:"wave,omitempty"`
	Objective            string   `json:"objective"`
	RoleID               string   `json:"role_id,omitempty"`
	CapabilityIDs        []string `json:"capability_ids,omitempty"`
	EvidenceRequirements []string `json:"evidence_requirements,omitempty"`
	DependsOn            []string `json:"depends_on,omitempty"`
	Mandatory            bool     `json:"mandatory"`
	ContextBudget        int      `json:"context_budget_tokens"`
	TimeoutMS            int      `json:"timeout_ms"`
}

type ResearchPlan struct {
	SchemaVersion          string     `json:"schema_version"`
	PlanID                 string     `json:"plan_id"`
	RunID                  string     `json:"run_id"`
	RequestID              string     `json:"request_id"`
	Steps                  []PlanStep `json:"steps"`
	MaxParallelSpecialists int        `json:"max_parallel_specialists"`
	MaxRepairPasses        int        `json:"max_repair_passes"`
	DeadlineMS             int        `json:"deadline_ms"`
	CompletionConditions   []string   `json:"completion_conditions"`
	AbstentionConditions   []string   `json:"abstention_conditions"`
}

type ContextRequest struct {
	SchemaVersion    string   `json:"schema_version"`
	ContextRequestID string   `json:"context_request_id"`
	RunID            string   `json:"run_id"`
	StepID           string   `json:"step_id"`
	SpecialistRole   string   `json:"specialist_role"`
	Objective        string   `json:"objective"`
	ResearchQuestion string   `json:"research_question"`
	Scope            Scope    `json:"scope"`
	CapabilityIDs    []string `json:"capability_ids,omitempty"`
	EvidenceRefs     []string `json:"evidence_refs,omitempty"`
	ReceiptRefs      []string `json:"receipt_refs,omitempty"`
	Assumptions      []string `json:"assumptions,omitempty"`
	TokenBudget      int      `json:"token_budget"`
}

type EvidenceState string

const (
	EvidenceAvailable    EvidenceState = "available"
	EvidenceStale        EvidenceState = "stale"
	EvidenceConflicting  EvidenceState = "conflicting"
	EvidenceMissing      EvidenceState = "missing"
	EvidenceIncomparable EvidenceState = "incomparable"
)

type EvidenceItem struct {
	EvidenceRef  EvidenceRef   `json:"evidence_ref"`
	State        EvidenceState `json:"state"`
	Statement    string        `json:"statement,omitempty"`
	ConflictRefs []string      `json:"conflict_refs,omitempty"`
	Warnings     []string      `json:"warnings,omitempty"`
}

type EvidenceBundle struct {
	SchemaVersion string         `json:"schema_version"`
	BundleID      string         `json:"bundle_id"`
	RunID         string         `json:"run_id"`
	StepID        string         `json:"step_id"`
	AsOf          time.Time      `json:"as_of"`
	Items         []EvidenceItem `json:"items"`
	Missing       []string       `json:"missing,omitempty"`
}

type ToolReceipt struct {
	SchemaVersion string        `json:"schema_version"`
	ReceiptID     string        `json:"receipt_id"`
	RunID         string        `json:"run_id"`
	StepID        string        `json:"step_id"`
	ToolID        string        `json:"tool_id"`
	Status        ReceiptStatus `json:"status"`
	InputSHA      string        `json:"input_sha256"`
	OutputSHA     string        `json:"output_sha256"`
	EvidenceRefs  []string      `json:"evidence_refs,omitempty"`
	Warnings      []string      `json:"warnings,omitempty"`
	StartedAt     time.Time     `json:"started_at"`
	CompletedAt   time.Time     `json:"completed_at"`
}

type CritiqueDecision string

const (
	CritiqueApprove CritiqueDecision = "approve"
	CritiqueRepair  CritiqueDecision = "repair"
	CritiqueNarrow  CritiqueDecision = "narrow"
	CritiqueReject  CritiqueDecision = "reject"
)

type CritiqueIssue struct {
	IssueID     string   `json:"issue_id"`
	Severity    string   `json:"severity"`
	ClaimRefs   []string `json:"claim_refs,omitempty"`
	Description string   `json:"description"`
	RepairHint  string   `json:"repair_hint,omitempty"`
}

type CritiqueReport struct {
	SchemaVersion  string           `json:"schema_version"`
	ReportID       string           `json:"report_id"`
	RunID          string           `json:"run_id"`
	ReviewerRole   string           `json:"reviewer_role"`
	Decision       CritiqueDecision `json:"decision"`
	ApprovedClaims []string         `json:"approved_claims,omitempty"`
	RejectedClaims []string         `json:"rejected_claims,omitempty"`
	Issues         []CritiqueIssue  `json:"issues,omitempty"`
	RepairPass     int              `json:"repair_pass"`
	CreatedAt      time.Time        `json:"created_at"`
}

type AnswerSection struct {
	SectionType   string   `json:"section_type"`
	Title         string   `json:"title"`
	Content       string   `json:"content"`
	ClaimRefs     []string `json:"claim_refs,omitempty"`
	EvidenceRefs  []string `json:"evidence_refs,omitempty"`
	ReceiptRefs   []string `json:"receipt_refs,omitempty"`
	NumericalRefs []string `json:"numerical_refs,omitempty"`
}

type FinalAnswer struct {
	SchemaVersion string          `json:"schema_version"`
	AnswerID      string          `json:"answer_id"`
	RunID         string          `json:"run_id"`
	RequestID     string          `json:"request_id"`
	PrimaryIntent string          `json:"primary_intent"`
	AsOf          time.Time       `json:"as_of"`
	Sections      []AnswerSection `json:"sections"`
	CritiqueRefs  []string        `json:"critique_refs"`
	Assumptions   []string        `json:"assumptions,omitempty"`
	Limitations   []string        `json:"limitations,omitempty"`
	NextActions   []string        `json:"next_actions,omitempty"`
	ReleasedBy    string          `json:"released_by"`
	ReleasedAt    time.Time       `json:"released_at"`
}

type MemoryCandidate struct {
	SchemaVersion     string     `json:"schema_version"`
	CandidateID       string     `json:"candidate_id"`
	RunID             string     `json:"run_id"`
	Content           string     `json:"content"`
	SourceArtifactIDs []string   `json:"source_artifact_ids"`
	Sensitivity       string     `json:"sensitivity"`
	RequiresApproval  bool       `json:"requires_approval"`
	ExpiresAt         *time.Time `json:"expires_at,omitempty"`
	CreatedAt         time.Time  `json:"created_at"`
}

type FailureReceipt struct {
	SchemaVersion string    `json:"schema_version"`
	FailureID     string    `json:"failure_id"`
	RunID         string    `json:"run_id"`
	StepID        string    `json:"step_id"`
	ComponentID   string    `json:"component_id"`
	FailureCode   string    `json:"failure_code"`
	Message       string    `json:"message"`
	Retryable     bool      `json:"retryable"`
	EvidenceRefs  []string  `json:"evidence_refs,omitempty"`
	CreatedAt     time.Time `json:"created_at"`
}
