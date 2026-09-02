package producteval

import (
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/productscope"
)

const StandaloneEvaluationSchemaV1 = "signalforge/technology20-standalone-evaluation/v1"
const PeerEvaluationSchemaV1 = "signalforge/technology20-peer-evaluation-runtime/v1"

type StandaloneCaseResult struct {
	JourneyID                 string         `json:"journey_id"`
	CompanyID                 string         `json:"company_id"`
	PrimaryTicker             string         `json:"primary_ticker"`
	QuestionID                string         `json:"question_id"`
	AuthorityState            string         `json:"authority_state"`
	RuntimePassed             bool           `json:"runtime_passed"`
	RequiredSectionsPassed    bool           `json:"required_sections_passed"`
	ClaimAuthorityPassed      bool           `json:"claim_authority_passed"`
	BothCriticsApproved       bool           `json:"both_critics_approved"`
	RequiredReceiptsPassed    bool           `json:"required_receipts_passed"`
	ExpectedAbstentionsPassed bool           `json:"expected_abstentions_passed"`
	VisibleLimitations        bool           `json:"visible_limitations"`
	ContractPassed            bool           `json:"contract_passed"`
	FailureCode               string         `json:"failure_code,omitempty"`
	DurationMS                float64        `json:"duration_ms"`
	ModelCalls                int            `json:"model_calls"`
	PromptTokens              int            `json:"prompt_tokens"`
	CompletionTokens          int            `json:"completion_tokens"`
	ReceiptOperations         []string       `json:"receipt_operations"`
	ExpectedReceipts          []string       `json:"expected_receipts"`
	ExpectedAbstentions       []string       `json:"expected_abstentions"`
	ClaimBoundary             string         `json:"claim_boundary"`
	EvaluatedAt               time.Time      `json:"evaluated_at"`
	Report                    *golden.Report `json:"report,omitempty"`
}

type StandaloneEvaluation struct {
	SchemaVersion      string                 `json:"schema_version"`
	UniverseID         string                 `json:"universe_id"`
	Split              string                 `json:"split"`
	SuiteSHA256        string                 `json:"suite_sha256"`
	SourceCommit       string                 `json:"source_commit"`
	ModelID            string                 `json:"model_id"`
	BaseURL            string                 `json:"base_url"`
	SpecialistProvider string                 `json:"specialist_provider,omitempty"`
	SpecialistModel    string                 `json:"specialist_model,omitempty"`
	StartedAt          time.Time              `json:"started_at"`
	CompletedAt        time.Time              `json:"completed_at"`
	CasesSelected      int                    `json:"cases_selected"`
	CasesCompleted     int                    `json:"cases_completed"`
	ContractsPassed    int                    `json:"contracts_passed"`
	RuntimeFailures    int                    `json:"runtime_failures"`
	TotalModelCalls    int                    `json:"total_model_calls"`
	TotalPromptTokens  int                    `json:"total_prompt_tokens"`
	TotalOutputTokens  int                    `json:"total_completion_tokens"`
	Results            []StandaloneCaseResult `json:"results"`
	ClaimBoundary      string                 `json:"claim_boundary"`
	ReleaseDisposition string                 `json:"release_disposition"`
}

type PeerCaseResult struct {
	JourneyID                  string            `json:"journey_id"`
	LaneID                     string            `json:"lane_id"`
	CompanyIDs                 []string          `json:"company_ids"`
	QuestionID                 string            `json:"question_id"`
	AuthorityState             string            `json:"authority_state"`
	RuntimePassed              bool              `json:"runtime_passed"`
	RequiredSectionsPassed     bool              `json:"required_sections_passed"`
	ClaimAuthorityPassed       bool              `json:"claim_authority_passed"`
	BothCriticsApproved        bool              `json:"both_critics_approved"`
	MetricAuthorityPassed      bool              `json:"metric_authority_passed"`
	UnavailableMetricsWithheld bool              `json:"unavailable_metrics_withheld"`
	VisibleComparisonBoundary  bool              `json:"visible_comparison_boundary"`
	NoUnsupportedPairRanking   bool              `json:"no_unsupported_pair_ranking"`
	ContractPassed             bool              `json:"contract_passed"`
	FailureCode                string            `json:"failure_code,omitempty"`
	DurationMS                 float64           `json:"duration_ms"`
	ModelCalls                 int               `json:"model_calls"`
	PromptTokens               int               `json:"prompt_tokens"`
	CompletionTokens           int               `json:"completion_tokens"`
	ExpectedMetricDispositions map[string]string `json:"expected_metric_dispositions"`
	ClaimBoundary              string            `json:"claim_boundary"`
	EvaluatedAt                time.Time         `json:"evaluated_at"`
	Report                     *golden.Report    `json:"report,omitempty"`
}

type PeerEvaluation struct {
	SchemaVersion      string           `json:"schema_version"`
	UniverseID         string           `json:"universe_id"`
	Split              string           `json:"split"`
	SuiteSHA256        string           `json:"suite_sha256"`
	SourceCommit       string           `json:"source_commit"`
	ModelID            string           `json:"model_id"`
	BaseURL            string           `json:"base_url"`
	SpecialistProvider string           `json:"specialist_provider,omitempty"`
	SpecialistModel    string           `json:"specialist_model,omitempty"`
	StartedAt          time.Time        `json:"started_at"`
	CompletedAt        time.Time        `json:"completed_at"`
	CasesSelected      int              `json:"cases_selected"`
	CasesCompleted     int              `json:"cases_completed"`
	ContractsPassed    int              `json:"contracts_passed"`
	RuntimeFailures    int              `json:"runtime_failures"`
	TotalModelCalls    int              `json:"total_model_calls"`
	TotalPromptTokens  int              `json:"total_prompt_tokens"`
	TotalOutputTokens  int              `json:"total_completion_tokens"`
	Results            []PeerCaseResult `json:"results"`
	ClaimBoundary      string           `json:"claim_boundary"`
	ReleaseDisposition string           `json:"release_disposition"`
}

func ScoreStandaloneCase(
	item productscope.StandaloneJourneyCase,
	report golden.Report,
	includePrivateReport bool,
) StandaloneCaseResult {
	result := StandaloneCaseResult{
		JourneyID: item.JourneyID, CompanyID: item.CompanyID,
		PrimaryTicker: item.PrimaryTicker, QuestionID: item.QuestionID,
		AuthorityState:         report.Request.AuthorityState,
		RuntimePassed:          report.Result.Failure == nil && report.Result.Answer != nil,
		RequiredSectionsPassed: report.Acceptance.RequiredSectionsReady,
		ClaimAuthorityPassed:   report.Metrics.Claims == report.Metrics.SupportedClaims,
		BothCriticsApproved:    report.Acceptance.BothCriticsApproved,
		DurationMS:             report.Metrics.DurationMS,
		ModelCalls:             report.Metrics.ModelCalls,
		PromptTokens:           report.Metrics.PromptTokens,
		CompletionTokens:       report.Metrics.CompletionTokens,
		ExpectedReceipts:       append([]string(nil), item.ExpectedReceipts...),
		ExpectedAbstentions:    append([]string(nil), item.ExpectedAbstentions...),
		ClaimBoundary: "This score covers typed runtime and answer-contract behavior. It does not " +
			"replace human factual, accounting, rights, or investment-domain review.",
		EvaluatedAt: time.Now().UTC(),
	}
	if report.Result.Failure != nil {
		result.FailureCode = report.Result.Failure.FailureCode
	}
	receiptSet := map[string]bool{}
	for _, packet := range report.Result.Packets {
		for _, receipt := range packet.CalculationReceipts {
			receiptSet[receipt.OperationID] = true
		}
	}
	for operationID := range receiptSet {
		result.ReceiptOperations = append(result.ReceiptOperations, operationID)
	}
	sort.Strings(result.ReceiptOperations)
	result.RequiredReceiptsPassed = containsAll(receiptSet, item.ExpectedReceipts)
	result.VisibleLimitations = visibleLimitations(report)
	result.ExpectedAbstentionsPassed = abstentionsPreserved(receiptSet, item.ExpectedAbstentions) &&
		(len(item.ExpectedAbstentions) == 0 || result.VisibleLimitations)
	result.ContractPassed = result.RuntimePassed && result.RequiredSectionsPassed &&
		result.ClaimAuthorityPassed && result.BothCriticsApproved &&
		result.RequiredReceiptsPassed && result.ExpectedAbstentionsPassed
	if includePrivateReport {
		copy := report
		result.Report = &copy
	}
	return result
}

var unsupportedPairRankingPattern = regexp.MustCompile(
	`(?i)\b(?:better|best|winner|superior|inferior)\s+(?:company|business|investment|stock)\b|\b(?:choose|prefer)\s+[A-Z][A-Za-z.]*\s+(?:over|instead\s+of)\b`,
)

func ScorePeerCase(
	item productscope.PeerJourneyCase,
	report golden.Report,
	includePrivateReport bool,
) PeerCaseResult {
	result := PeerCaseResult{
		JourneyID: item.JourneyID, LaneID: item.LaneID,
		CompanyIDs: append([]string(nil), item.CompanyIDs...), QuestionID: item.QuestionID,
		AuthorityState:             report.Request.AuthorityState,
		RuntimePassed:              report.Result.Failure == nil && report.Result.Answer != nil,
		RequiredSectionsPassed:     report.Acceptance.RequiredSectionsReady,
		ClaimAuthorityPassed:       report.Metrics.Claims == report.Metrics.SupportedClaims,
		BothCriticsApproved:        report.Acceptance.BothCriticsApproved,
		DurationMS:                 report.Metrics.DurationMS,
		ModelCalls:                 report.Metrics.ModelCalls,
		PromptTokens:               report.Metrics.PromptTokens,
		CompletionTokens:           report.Metrics.CompletionTokens,
		ExpectedMetricDispositions: copyDispositionMap(item.ExpectedMetrics),
		ClaimBoundary: "This score measures typed runtime, comparison authority, and answer-contract " +
			"behavior. It does not promote a peer lane or replace professional review.",
		EvaluatedAt: time.Now().UTC(),
	}
	if report.Result.Failure != nil {
		result.FailureCode = report.Result.Failure.FailureCode
	}
	result.MetricAuthorityPassed = comparisonAuthorityPresent(report, item.ExpectedMetrics)
	result.UnavailableMetricsWithheld = unavailableMetricsWithheld(report, item.ExpectedMetrics)
	result.VisibleComparisonBoundary = visibleComparisonBoundary(report)
	result.NoUnsupportedPairRanking = noUnsupportedPairRanking(report)
	result.ContractPassed = result.RuntimePassed && result.RequiredSectionsPassed &&
		result.ClaimAuthorityPassed && result.BothCriticsApproved &&
		result.MetricAuthorityPassed && result.UnavailableMetricsWithheld &&
		result.VisibleComparisonBoundary && result.NoUnsupportedPairRanking
	if includePrivateReport {
		copy := report
		result.Report = &copy
	}
	return result
}

func comparisonAuthorityPresent(report golden.Report, expected map[string]string) bool {
	required := 0
	for _, disposition := range expected {
		if disposition != "unavailable" {
			required++
		}
	}
	seen := 0
	for _, ref := range report.Request.AuthorityRefs {
		if strings.HasPrefix(ref, "comparability-receipt-sha256:") {
			seen++
		}
	}
	return seen == required && report.Request.AuthorityState == "limited"
}

func unavailableMetricsWithheld(report golden.Report, expected map[string]string) bool {
	for _, packet := range report.Result.Packets {
		if packet.NumericalContext == nil {
			continue
		}
		for _, variable := range packet.NumericalContext.Variables {
			for metric, disposition := range expected {
				if (disposition == "unavailable" || disposition == "not_comparable") &&
					strings.HasPrefix(variable.MetricID, metric) {
					return false
				}
			}
		}
		for _, relation := range packet.NumericalContext.Relations {
			for metric, disposition := range expected {
				if (disposition == "unavailable" || disposition == "not_comparable") &&
					strings.HasPrefix(relation.MetricID, metric) {
					return false
				}
			}
		}
	}
	return true
}

func visibleComparisonBoundary(report golden.Report) bool {
	if report.Result.Answer == nil {
		return false
	}
	text := strings.Join(report.Result.Answer.Limitations, " ")
	for _, section := range report.Result.Answer.Sections {
		text += " " + section.Content
	}
	lower := strings.ToLower(text)
	for _, term := range []string{"withheld", "not comparable", "unavailable", "caveat", "period", "fiscal", "boundary"} {
		if strings.Contains(lower, term) {
			return true
		}
	}
	return false
}

func noUnsupportedPairRanking(report golden.Report) bool {
	if report.Result.Answer == nil {
		return false
	}
	for _, section := range report.Result.Answer.Sections {
		if unsupportedPairRankingPattern.MatchString(section.Content) {
			return false
		}
	}
	return true
}

func copyDispositionMap(input map[string]string) map[string]string {
	result := make(map[string]string, len(input))
	for key, value := range input {
		result[key] = value
	}
	return result
}

func visibleLimitations(report golden.Report) bool {
	if report.Result.Answer == nil {
		return false
	}
	if len(report.Result.Answer.Limitations) > 0 {
		return true
	}
	for _, section := range report.Result.Answer.Sections {
		if section.SectionType == "limitations" && strings.TrimSpace(section.Content) != "" {
			return true
		}
	}
	return false
}

func abstentionsPreserved(receipts map[string]bool, expected []string) bool {
	for _, operationID := range expected {
		if receipts[operationID] {
			return false
		}
	}
	return true
}

func containsAll(values map[string]bool, expected []string) bool {
	for _, value := range expected {
		if !values[value] {
			return false
		}
	}
	return true
}
