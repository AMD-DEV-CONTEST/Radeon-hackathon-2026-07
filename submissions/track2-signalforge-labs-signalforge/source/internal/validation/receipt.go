package validation

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const SchemaVersion = "signalforge/validation-receipt/v1"

type Status string

const (
	StatusPassed       Status = "passed"
	StatusRejected     Status = "rejected"
	StatusNotEvaluable Status = "not_evaluable"
)

type Code string

const (
	CodeContractInvalid  Code = "contract_invalid"
	CodeFutureEvidence   Code = "future_evidence"
	CodeStaleEvidence    Code = "stale_evidence"
	CodeReferenceInvalid Code = "reference_invalid"
	CodeQuantityInvalid  Code = "quantity_invalid"
	CodePeriodBridge     Code = "period_bridge_required"
	CodeEntailment       Code = "entailment_metadata_mismatch"
)

type Severity string

const (
	SeverityError   Severity = "error"
	SeverityMissing Severity = "missing_evidence"
)

type Issue struct {
	Code         Code     `json:"code"`
	Severity     Severity `json:"severity"`
	Owner        string   `json:"owner"`
	Path         string   `json:"path"`
	Detail       string   `json:"detail"`
	EvidenceRefs []string `json:"evidence_refs,omitempty"`
}

type PeriodBridge struct {
	ReceiptID string `json:"receipt_id"`
	FromKind  string `json:"from_kind"`
	ToKind    string `json:"to_kind"`
	Method    string `json:"method"`
}

type Policy struct {
	AsOf                    time.Time
	MaxEvidenceAge          map[string]time.Duration
	RequirePeriodBridges    bool
	AuthorizedPeriodBridges []PeriodBridge
	EvidenceEntailment      []EntailmentMetadata
}

// EntailmentMetadata is source-owned authority, not a model judgment. It can constrain a released
// claim to a hash-pinned evidence item, but it cannot create, repair, or expand a conclusion.
type EntailmentMetadata struct {
	EvidenceID        string                `json:"evidence_id"`
	ContentSHA        string                `json:"content_sha256"`
	AllowedClaimTypes []contracts.ClaimType `json:"allowed_claim_types"`
	RequiredTerms     []string              `json:"required_terms,omitempty"`
	ForbiddenTerms    []string              `json:"forbidden_terms,omitempty"`
}

type Receipt struct {
	SchemaVersion  string    `json:"schema_version"`
	ReceiptID      string    `json:"receipt_id"`
	TargetType     string    `json:"target_type"`
	TargetID       string    `json:"target_id"`
	InputSHA256    string    `json:"input_sha256"`
	ValidatedAsOf  time.Time `json:"validated_as_of"`
	Status         Status    `json:"status"`
	Issues         []Issue   `json:"issues"`
	RepairsApplied bool      `json:"repairs_applied"`
	Deterministic  bool      `json:"deterministic"`
}

var (
	instantPeriodPattern  = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)
	durationPeriodPattern = regexp.MustCompile(`(?i)^(?:FY\d{4}|Q[1-4][-_]?\d{4}|\d{4}[-_]?Q[1-4]|TTM|LTM)$`)
)

func ContextPacket(packet contracts.ContextPacket, policy Policy) Receipt {
	inputHash := hash(packet)
	asOf := policy.AsOf
	if asOf.IsZero() {
		asOf = packet.Scope.AsOf
	}
	receipt := Receipt{
		SchemaVersion: SchemaVersion,
		ReceiptID:     "validation:" + inputHash[:20],
		TargetType:    "ContextPacket", TargetID: packet.PacketID, InputSHA256: inputHash,
		ValidatedAsOf: asOf, Status: StatusPassed, Issues: []Issue{},
		RepairsApplied: false, Deterministic: true,
	}
	if err := contracts.ValidateContextPacket(packet); err != nil {
		receipt.Status = StatusRejected
		receipt.Issues = append(receipt.Issues, classifyContractError(err))
		return receipt
	}

	for index, evidence := range packet.Evidence {
		maxAge, constrained := policy.MaxEvidenceAge[evidence.SourceType]
		if !constrained || maxAge <= 0 || asOf.IsZero() || evidence.AsOf.After(asOf) {
			continue
		}
		if asOf.Sub(evidence.AsOf) > maxAge {
			receipt.Issues = append(receipt.Issues, Issue{
				Code: CodeStaleEvidence, Severity: SeverityMissing, Owner: "evidence-authority",
				Path:         fmt.Sprintf("evidence[%d]", index),
				Detail:       fmt.Sprintf("source age exceeds the declared %s freshness budget", maxAge),
				EvidenceRefs: []string{evidence.EvidenceID},
			})
		}
	}
	if policy.RequirePeriodBridges {
		bridges := authorizedBridges(policy.AuthorizedPeriodBridges)
		for index, calculation := range packet.CalculationReceipts {
			kinds := quantityPeriodKinds(calculation.NormalizedInputs)
			if len(kinds) > 1 && !bridges[calculation.ReceiptID] {
				receipt.Issues = append(receipt.Issues, Issue{
					Code: CodePeriodBridge, Severity: SeverityMissing, Owner: "deterministic-engine",
					Path:   fmt.Sprintf("calculation_receipts[%d]", index),
					Detail: "instant and duration quantities require an explicit deterministic bridge",
				})
			}
		}
	}
	receipt.Issues = append(receipt.Issues, validateEntailmentMetadata(packet, policy.EvidenceEntailment)...)
	if len(receipt.Issues) > 0 {
		receipt.Status = StatusNotEvaluable
	}
	return receipt
}

func validateEntailmentMetadata(packet contracts.ContextPacket, values []EntailmentMetadata) []Issue {
	if len(values) == 0 {
		return nil
	}
	evidence := make(map[string]contracts.EvidenceRef, len(packet.Evidence))
	for _, item := range packet.Evidence {
		evidence[item.EvidenceID] = item
	}
	rules := make(map[string]EntailmentMetadata, len(values))
	issues := []Issue{}
	for index, value := range values {
		if strings.TrimSpace(value.EvidenceID) == "" || strings.TrimSpace(value.ContentSHA) == "" || len(value.AllowedClaimTypes) == 0 {
			issues = append(issues, Issue{
				Code: CodeEntailment, Severity: SeverityMissing, Owner: "evidence-authority",
				Path: fmt.Sprintf("policy.evidence_entailment[%d]", index), Detail: "entailment metadata is incomplete",
			})
			continue
		}
		if _, duplicate := rules[value.EvidenceID]; duplicate {
			issues = append(issues, Issue{
				Code: CodeEntailment, Severity: SeverityMissing, Owner: "evidence-authority",
				Path: fmt.Sprintf("policy.evidence_entailment[%d]", index), Detail: "entailment metadata duplicates an evidence ID",
				EvidenceRefs: []string{value.EvidenceID},
			})
			continue
		}
		rules[value.EvidenceID] = value
	}
	findings := append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...)
	for findingIndex, finding := range findings {
		statement := strings.ToLower(strings.TrimSpace(finding.Statement))
		for _, evidenceID := range finding.EvidenceRefs {
			rule, constrained := rules[evidenceID]
			if !constrained {
				continue
			}
			item, exists := evidence[evidenceID]
			if !exists || item.ContentSHA != rule.ContentSHA {
				issues = append(issues, entailmentIssue(findingIndex, finding.ClaimID, evidenceID, "metadata is not bound to the cited evidence hash"))
				continue
			}
			if !claimTypeAllowed(finding.ClaimType, rule.AllowedClaimTypes) {
				issues = append(issues, entailmentIssue(findingIndex, finding.ClaimID, evidenceID, "claim type is outside source-owned entailment authority"))
				continue
			}
			for _, term := range rule.RequiredTerms {
				if term = strings.ToLower(strings.TrimSpace(term)); term != "" && !strings.Contains(statement, term) {
					issues = append(issues, entailmentIssue(findingIndex, finding.ClaimID, evidenceID, "released prose omits a required source term"))
				}
			}
			for _, term := range rule.ForbiddenTerms {
				if term = strings.ToLower(strings.TrimSpace(term)); term != "" && strings.Contains(statement, term) {
					issues = append(issues, entailmentIssue(findingIndex, finding.ClaimID, evidenceID, "released prose contains a source-forbidden term"))
				}
			}
		}
	}
	return issues
}

func claimTypeAllowed(value contracts.ClaimType, allowed []contracts.ClaimType) bool {
	for _, candidate := range allowed {
		if value == candidate {
			return true
		}
	}
	return false
}

func entailmentIssue(index int, claimID, evidenceID, detail string) Issue {
	return Issue{
		Code: CodeEntailment, Severity: SeverityMissing, Owner: "evidence-authority",
		Path: fmt.Sprintf("findings[%d]", index), Detail: detail + " for claim " + claimID,
		EvidenceRefs: []string{evidenceID},
	}
}

func classifyContractError(err error) Issue {
	detail := err.Error()
	lower := strings.ToLower(detail)
	issue := Issue{Code: CodeContractInvalid, Severity: SeverityError, Owner: "contracts", Path: "packet", Detail: detail}
	switch {
	case strings.Contains(lower, "later than") || strings.Contains(lower, "future"):
		issue.Code, issue.Owner = CodeFutureEvidence, "evidence-authority"
	case strings.Contains(lower, "reference") || strings.Contains(lower, "duplicates"):
		issue.Code, issue.Owner = CodeReferenceInvalid, "lineage"
	case strings.Contains(lower, "quantity") || strings.Contains(lower, "finite decimal") || strings.Contains(lower, "currency"):
		issue.Code, issue.Owner = CodeQuantityInvalid, "deterministic-engine"
	}
	return issue
}

func authorizedBridges(values []PeriodBridge) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		if strings.TrimSpace(value.ReceiptID) != "" && strings.TrimSpace(value.FromKind) != "" &&
			strings.TrimSpace(value.ToKind) != "" && strings.TrimSpace(value.Method) != "" {
			result[value.ReceiptID] = true
		}
	}
	return result
}

func quantityPeriodKinds(inputs []contracts.EngineInput) []string {
	set := map[string]bool{}
	for _, input := range inputs {
		switch periodKind(strings.TrimSpace(input.Quantity.Period)) {
		case "instant":
			set["instant"] = true
		case "duration":
			set["duration"] = true
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func periodKind(value string) string {
	if instantPeriodPattern.MatchString(value) {
		return "instant"
	}
	if durationPeriodPattern.MatchString(value) {
		return "duration"
	}
	return "unknown"
}

func hash(value any) string {
	payload, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}
