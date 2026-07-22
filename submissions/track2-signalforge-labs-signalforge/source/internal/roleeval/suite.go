package roleeval

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"slices"
	"strings"

	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/roles"
)

const SuiteVersion = "signalforge/role-evaluation-suite/v1"

type EvidenceSeed struct {
	EvidenceID   string   `json:"evidence_id"`
	State        string   `json:"state"`
	Statement    string   `json:"statement"`
	ConflictRefs []string `json:"conflict_refs,omitempty"`
}

type CalculationSeed struct {
	ReceiptID string `json:"receipt_id"`
	Operation string `json:"operation_id"`
	OutputID  string `json:"output_id"`
	Value     string `json:"value"`
	Unit      string `json:"unit"`
}

type Expected struct {
	PrimaryIntent         string   `json:"primary_intent,omitempty"`
	AllowedDecisions      []string `json:"allowed_decisions,omitempty"`
	RequiredTerms         []string `json:"required_terms,omitempty"`
	ForbiddenTerms        []string `json:"forbidden_terms,omitempty"`
	MinimumFindings       int      `json:"minimum_findings,omitempty"`
	RequireEvidence       bool     `json:"require_evidence,omitempty"`
	RequireCalculationRef bool     `json:"require_calculation_ref,omitempty"`
	RequireMissing        bool     `json:"require_missing,omitempty"`
	RequireConflict       bool     `json:"require_conflict,omitempty"`
	RequiredHandoff       string   `json:"required_handoff,omitempty"`
	RequiredSections      []string `json:"required_sections,omitempty"`
	MandatoryRoles        []string `json:"mandatory_roles,omitempty"`
	MandatoryCapabilities []string `json:"mandatory_capabilities,omitempty"`
}

type Case struct {
	CaseID       string            `json:"case_id"`
	RoleID       string            `json:"role_id"`
	Kind         string            `json:"kind"`
	Scenario     string            `json:"scenario"`
	Question     string            `json:"question"`
	Evidence     []EvidenceSeed    `json:"evidence,omitempty"`
	Calculations []CalculationSeed `json:"calculations,omitempty"`
	Expected     Expected          `json:"expected"`
}

type Suite struct {
	SchemaVersion    string `json:"schema_version"`
	SuiteID          string `json:"suite_id"`
	PromptSetVersion string `json:"prompt_set_version"`
	Cases            []Case `json:"cases"`
}

func LoadSuite(path string) (Suite, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return Suite{}, err
	}
	var suite Suite
	if err := json.Unmarshal(payload, &suite); err != nil {
		return Suite{}, err
	}
	return suite, suite.Validate()
}

func (suite Suite) Validate() error {
	if suite.SchemaVersion != SuiteVersion || suite.SuiteID == "" ||
		suite.PromptSetVersion != localagent.PromptSetVersion || len(suite.Cases) == 0 {
		return errors.New("role evaluation suite header is invalid")
	}
	roleRegistry := roles.DefaultRegistry()
	seenCases := map[string]bool{}
	roleCounts := map[string]int{}
	for index, item := range suite.Cases {
		if item.CaseID == "" || seenCases[item.CaseID] || item.Question == "" || item.Scenario == "" {
			return fmt.Errorf("cases[%d] has invalid identity", index)
		}
		seenCases[item.CaseID] = true
		role, ok := roleRegistry.Get(item.RoleID)
		if !ok {
			return fmt.Errorf("cases[%d] has unknown role %q", index, item.RoleID)
		}
		validKind := (item.Kind == "interpreter" && role.ID == roles.RequestInterpreter) ||
			(item.Kind == "planner" && role.ID == roles.ResearchOrchestrator) ||
			(item.Kind == "context" && role.Class == roles.ClassContext) ||
			(item.Kind == "review" && role.Class == roles.ClassReview) ||
			(item.Kind == "synthesis" && role.Class == roles.ClassSynthesis)
		if !validKind {
			return fmt.Errorf("cases[%d] kind %q does not match role %q", index, item.Kind, item.RoleID)
		}
		roleCounts[item.RoleID]++
		for evidenceIndex, evidence := range item.Evidence {
			if evidence.EvidenceID == "" || evidence.Statement == "" ||
				!slices.Contains([]string{"available", "stale", "conflicting", "missing", "incomparable"}, evidence.State) {
				return fmt.Errorf("cases[%d].evidence[%d] is invalid", index, evidenceIndex)
			}
			if evidence.State == "conflicting" && len(evidence.ConflictRefs) == 0 {
				return fmt.Errorf("cases[%d].evidence[%d] requires conflict_refs", index, evidenceIndex)
			}
		}
		for _, value := range append(append([]string(nil), item.Expected.RequiredTerms...), item.Expected.ForbiddenTerms...) {
			if strings.TrimSpace(value) == "" {
				return fmt.Errorf("case %q contains an empty term", item.CaseID)
			}
		}
	}
	for _, role := range roleRegistry.List() {
		if roleCounts[role.ID] < 3 {
			return fmt.Errorf("role %q has only %d held-out cases", role.ID, roleCounts[role.ID])
		}
	}
	return nil
}
