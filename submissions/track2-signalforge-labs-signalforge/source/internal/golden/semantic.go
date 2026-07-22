package golden

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const (
	SemanticRubricSchemaV1     = "signalforge/golden-semantic-rubric/v1"
	SemanticEvaluationSchemaV1 = "signalforge/golden-semantic-evaluation/v1"
)

type SemanticSectionRequirement struct {
	SectionType   string   `json:"section_type"`
	RequiredRoles []string `json:"required_roles,omitempty"`
}

type SemanticEvidenceRequirement struct {
	RequirementID string   `json:"requirement_id"`
	SectionTypes  []string `json:"section_types"`
	AllOf         []string `json:"all_of,omitempty"`
	AnyOf         []string `json:"any_of,omitempty"`
}

type SemanticRubric struct {
	SchemaVersion             string                        `json:"schema_version"`
	RubricID                  string                        `json:"rubric_id"`
	FrozenAt                  time.Time                     `json:"frozen_at"`
	QuestionSHA               string                        `json:"question_sha256"`
	RequiredSections          []SemanticSectionRequirement  `json:"required_sections"`
	RequiredAssumptions       []string                      `json:"required_assumptions"`
	RequiredEvidence          []SemanticEvidenceRequirement `json:"required_evidence"`
	RequiredReceiptOperations map[string]int                `json:"required_receipt_operations"`
	RequiredMarketTickers     []string                      `json:"required_market_price_tickers"`
	BoundaryDisclosures       map[string]string             `json:"boundary_disclosures"`
	ForbiddenCausalPatterns   []string                      `json:"forbidden_causal_patterns"`
	RequiredSectionPatterns   map[string][]string           `json:"required_section_patterns,omitempty"`
	ForbiddenSectionPatterns  map[string][]string           `json:"forbidden_section_patterns,omitempty"`
}

type SemanticCheck struct {
	CheckID  string   `json:"check_id"`
	Passed   bool     `json:"passed"`
	Observed string   `json:"observed"`
	Refs     []string `json:"refs,omitempty"`
}

type SemanticEvaluation struct {
	SchemaVersion string          `json:"schema_version"`
	EvaluationID  string          `json:"evaluation_id"`
	EvaluatedAt   time.Time       `json:"evaluated_at"`
	RubricID      string          `json:"rubric_id"`
	RubricSHA     string          `json:"rubric_sha256"`
	ReportRunID   string          `json:"report_run_id"`
	Passed        bool            `json:"passed"`
	PassedChecks  int             `json:"passed_checks"`
	TotalChecks   int             `json:"total_checks"`
	Checks        []SemanticCheck `json:"checks"`
}

func LoadSemanticRubric(path string) (SemanticRubric, string, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return SemanticRubric{}, "", err
	}
	var rubric SemanticRubric
	if err := json.Unmarshal(payload, &rubric); err != nil {
		return SemanticRubric{}, "", fmt.Errorf("decode semantic rubric: %w", err)
	}
	if err := ValidateSemanticRubric(rubric); err != nil {
		return SemanticRubric{}, "", err
	}
	digest := sha256.Sum256(payload)
	return rubric, hex.EncodeToString(digest[:]), nil
}

func ValidateSemanticRubric(rubric SemanticRubric) error {
	if rubric.SchemaVersion != SemanticRubricSchemaV1 || strings.TrimSpace(rubric.RubricID) == "" ||
		rubric.FrozenAt.IsZero() || !shaPattern.MatchString(rubric.QuestionSHA) {
		return errors.New("semantic rubric envelope is invalid")
	}
	if len(rubric.RequiredSections) == 0 || len(rubric.RequiredAssumptions) == 0 || len(rubric.RequiredReceiptOperations) == 0 {
		return errors.New("semantic rubric requires sections, assumptions, and receipt operations")
	}
	sections := map[string]bool{}
	for _, requirement := range rubric.RequiredSections {
		if requirement.SectionType == "" || sections[requirement.SectionType] {
			return fmt.Errorf("invalid or duplicate required section %q", requirement.SectionType)
		}
		sections[requirement.SectionType] = true
	}
	for sectionType, disclosure := range rubric.BoundaryDisclosures {
		if !sections[sectionType] || strings.TrimSpace(disclosure) == "" {
			return fmt.Errorf("boundary disclosure targets unknown section %q", sectionType)
		}
	}
	for _, pattern := range rubric.ForbiddenCausalPatterns {
		if _, err := regexp.Compile(pattern); err != nil {
			return fmt.Errorf("compile forbidden causal pattern: %w", err)
		}
	}
	for _, patterns := range []map[string][]string{rubric.RequiredSectionPatterns, rubric.ForbiddenSectionPatterns} {
		for sectionType, sectionPatterns := range patterns {
			if !sections[sectionType] || len(sectionPatterns) == 0 {
				return fmt.Errorf("semantic pattern targets unknown or empty section %q", sectionType)
			}
			for _, pattern := range sectionPatterns {
				if _, err := regexp.Compile(pattern); err != nil {
					return fmt.Errorf("compile section pattern for %s: %w", sectionType, err)
				}
			}
		}
	}
	return nil
}

func EvaluateSemantics(report Report, rubric SemanticRubric, rubricSHA string, evaluatedAt time.Time) SemanticEvaluation {
	evaluation := SemanticEvaluation{
		SchemaVersion: SemanticEvaluationSchemaV1,
		EvaluationID:  "semantic-" + rubric.RubricID + "-" + report.Request.RunID,
		EvaluatedAt:   evaluatedAt.UTC(), RubricID: rubric.RubricID, RubricSHA: rubricSHA,
		ReportRunID: report.Request.RunID,
	}
	add := func(id string, passed bool, observed string, refs ...string) {
		sort.Strings(refs)
		evaluation.Checks = append(evaluation.Checks, SemanticCheck{CheckID: id, Passed: passed, Observed: observed, Refs: refs})
		if passed {
			evaluation.PassedChecks++
		}
	}

	questionDigest := sha256.Sum256([]byte(report.Question))
	add("question_identity", hex.EncodeToString(questionDigest[:]) == rubric.QuestionSHA,
		hex.EncodeToString(questionDigest[:]))
	answer := report.Result.Answer
	add("answer_released", answer != nil && report.Result.Failure == nil,
		fmt.Sprintf("answer=%t failure=%t", answer != nil, report.Result.Failure != nil))
	if answer == nil {
		evaluation.TotalChecks = len(evaluation.Checks)
		evaluation.Passed = false
		return evaluation
	}

	claims, claimRoles := reportClaimAuthority(report)
	sections := make(map[string]contracts.AnswerSection, len(answer.Sections))
	for _, section := range answer.Sections {
		sections[section.SectionType] = section
	}
	for _, requirement := range rubric.RequiredSections {
		section, present := sections[requirement.SectionType]
		add("section:"+requirement.SectionType, present && strings.TrimSpace(section.Content) != "",
			fmt.Sprintf("present=%t claim_refs=%d", present, len(section.ClaimRefs)), section.ClaimRefs...)
		for _, roleID := range requirement.RequiredRoles {
			roleRefs := []string{}
			for _, claimID := range section.ClaimRefs {
				if claimRoles[claimID] == roleID {
					roleRefs = append(roleRefs, claimID)
				}
			}
			add("section_role:"+requirement.SectionType+":"+roleID, len(roleRefs) > 0,
				fmt.Sprintf("matching_claims=%d", len(roleRefs)), roleRefs...)
		}
	}

	assumptions := semanticStringSet(answer.Assumptions)
	for _, assumption := range rubric.RequiredAssumptions {
		add("assumption:"+shortHash(assumption), assumptions[assumption], assumption)
	}

	for _, requirement := range rubric.RequiredEvidence {
		available := map[string]bool{}
		for _, sectionType := range requirement.SectionTypes {
			for _, ref := range sections[sectionType].EvidenceRefs {
				available[ref] = true
			}
		}
		passed := true
		for _, ref := range requirement.AllOf {
			passed = passed && available[ref]
		}
		if len(requirement.AnyOf) > 0 {
			any := false
			for _, ref := range requirement.AnyOf {
				any = any || available[ref]
			}
			passed = passed && any
		}
		refs := make([]string, 0, len(available))
		for ref := range available {
			refs = append(refs, ref)
		}
		add("evidence:"+requirement.RequirementID, passed,
			fmt.Sprintf("available=%d", len(available)), refs...)
	}

	receiptCounts := map[string]int{}
	marketTickers := map[string]bool{}
	for _, packet := range report.Result.Packets {
		for _, receipt := range packet.CalculationReceipts {
			receiptCounts[receipt.OperationID]++
		}
		for _, evidence := range packet.Evidence {
			if strings.HasPrefix(evidence.EvidenceID, "market-price:") {
				marketTickers[strings.TrimPrefix(evidence.EvidenceID, "market-price:")] = true
			}
		}
	}
	operations := make([]string, 0, len(rubric.RequiredReceiptOperations))
	for operation := range rubric.RequiredReceiptOperations {
		operations = append(operations, operation)
	}
	sort.Strings(operations)
	for _, operation := range operations {
		minimum := rubric.RequiredReceiptOperations[operation]
		add("receipt_operation:"+operation, receiptCounts[operation] >= minimum,
			fmt.Sprintf("observed=%d minimum=%d", receiptCounts[operation], minimum))
	}
	for _, ticker := range rubric.RequiredMarketTickers {
		add("market_price:"+ticker, marketTickers[ticker], fmt.Sprintf("present=%t", marketTickers[ticker]))
	}

	for sectionType, disclosure := range rubric.BoundaryDisclosures {
		content := sections[sectionType].Content
		add("boundary:"+sectionType, strings.Contains(content, disclosure), disclosure)
	}
	for index, pattern := range rubric.ForbiddenCausalPatterns {
		re := regexp.MustCompile(pattern)
		violations := []string{}
		for _, sectionType := range []string{"transmission_mechanisms", "market_measurement"} {
			if re.MatchString(sections[sectionType].Content) {
				violations = append(violations, sectionType)
			}
		}
		add(fmt.Sprintf("causal_pattern:%d", index+1), len(violations) == 0,
			"violations="+strings.Join(violations, ","), violations...)
	}
	sectionTypes := make([]string, 0, len(rubric.RequiredSectionPatterns)+len(rubric.ForbiddenSectionPatterns))
	sectionSet := map[string]bool{}
	for sectionType := range rubric.RequiredSectionPatterns {
		sectionSet[sectionType] = true
	}
	for sectionType := range rubric.ForbiddenSectionPatterns {
		sectionSet[sectionType] = true
	}
	for sectionType := range sectionSet {
		sectionTypes = append(sectionTypes, sectionType)
	}
	sort.Strings(sectionTypes)
	for _, sectionType := range sectionTypes {
		content := sections[sectionType].Content
		for index, pattern := range rubric.RequiredSectionPatterns[sectionType] {
			matched := regexp.MustCompile(pattern).MatchString(content)
			add(fmt.Sprintf("section_pattern:required:%s:%d", sectionType, index+1), matched,
				fmt.Sprintf("matched=%t", matched))
		}
		for index, pattern := range rubric.ForbiddenSectionPatterns[sectionType] {
			matched := regexp.MustCompile(pattern).MatchString(content)
			add(fmt.Sprintf("section_pattern:forbidden:%s:%d", sectionType, index+1), !matched,
				fmt.Sprintf("matched=%t", matched))
		}
	}

	approved := map[string]int{}
	for _, critique := range report.Result.Critiques {
		for _, claimID := range critique.ApprovedClaims {
			approved[claimID]++
		}
	}
	released := map[string]bool{}
	for _, section := range answer.Sections {
		for _, claimID := range section.ClaimRefs {
			released[claimID] = true
		}
	}
	unanimous := true
	unknown := false
	for claimID := range released {
		unanimous = unanimous && approved[claimID] == len(report.Result.Critiques)
		_, exists := claims[claimID]
		unknown = unknown || !exists
	}
	add("released_claim_authority", !unknown && unanimous && len(released) > 0,
		fmt.Sprintf("released=%d unknown=%t unanimous=%t", len(released), unknown, unanimous))

	evaluation.TotalChecks = len(evaluation.Checks)
	evaluation.Passed = evaluation.TotalChecks > 0 && evaluation.PassedChecks == evaluation.TotalChecks
	return evaluation
}

var shaPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

func reportClaimAuthority(report Report) (map[string]contracts.Finding, map[string]string) {
	claims := map[string]contracts.Finding{}
	roles := map[string]string{}
	for _, packet := range report.Result.Packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			claims[finding.ClaimID] = finding
			roles[finding.ClaimID] = packet.SpecialistRole
		}
	}
	return claims, roles
}

func semanticStringSet(values []string) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		result[value] = true
	}
	return result
}

func shortHash(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:6])
}
