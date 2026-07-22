package workspace

import (
	"errors"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/golden"
)

const SchemaVersionV1 = "signalforge/research-workspace/v1"

type Projection struct {
	SchemaVersion string               `json:"schema_version"`
	CaseID        string               `json:"case_id"`
	RunID         string               `json:"run_id"`
	RequestID     string               `json:"request_id"`
	Status        string               `json:"status"`
	Title         string               `json:"title"`
	Question      string               `json:"question"`
	AsOf          time.Time            `json:"as_of"`
	Intent        string               `json:"intent"`
	Companies     []Company            `json:"companies"`
	Sections      []Section            `json:"sections"`
	Evidence      []EvidenceCard       `json:"evidence"`
	Calculations  []CalculationCard    `json:"calculations"`
	Assumptions   []string             `json:"assumptions,omitempty"`
	Limitations   []string             `json:"limitations,omitempty"`
	NextActions   []string             `json:"next_actions,omitempty"`
	Warnings      []Warning            `json:"warnings,omitempty"`
	Events        []SafeEvent          `json:"events"`
	Execution     Execution            `json:"execution"`
	Metrics       Metrics              `json:"metrics"`
	FollowUps     []FollowUpSuggestion `json:"follow_up_suggestions"`
}

type Company struct {
	EntityID string `json:"entity_id"`
	Label    string `json:"label"`
}

type Section struct {
	SectionType   string   `json:"section_type"`
	Title         string   `json:"title"`
	Content       string   `json:"content"`
	ClaimRefs     []string `json:"claim_refs,omitempty"`
	EvidenceRefs  []string `json:"evidence_refs,omitempty"`
	ReceiptRefs   []string `json:"receipt_refs,omitempty"`
	NumericalRefs []string `json:"numerical_refs,omitempty"`
}

type EvidenceCard struct {
	EvidenceID      string    `json:"evidence_id"`
	SourceType      string    `json:"source_type"`
	DocumentSection string    `json:"document_section,omitempty"`
	Locator         string    `json:"locator"`
	ContentSHA      string    `json:"content_sha256"`
	AsOf            time.Time `json:"as_of"`
	UsedInSections  []string  `json:"used_in_sections"`
}

type CalculationCard struct {
	ReceiptID        string                      `json:"receipt_id"`
	OperationID      string                      `json:"operation_id"`
	EngineID         string                      `json:"engine_id"`
	EngineVersion    string                      `json:"engine_version"`
	FormulaVersion   string                      `json:"formula_version"`
	Status           contracts.ReceiptStatus     `json:"status"`
	Outputs          []contracts.ReceiptOutput   `json:"outputs"`
	InvariantResults []contracts.InvariantResult `json:"invariant_results"`
	Warnings         []string                    `json:"warnings,omitempty"`
	EvidenceRefs     []string                    `json:"evidence_refs,omitempty"`
	SourceAsOf       time.Time                   `json:"source_as_of"`
	ReceiptSHA       string                      `json:"receipt_sha256"`
	UsedInSections   []string                    `json:"used_in_sections"`
}

type Warning struct {
	Kind   string `json:"kind"`
	RoleID string `json:"role_id,omitempty"`
	Text   string `json:"text"`
}

type SafeEvent struct {
	Sequence   int               `json:"sequence"`
	StepID     string            `json:"step_id,omitempty"`
	Type       string            `json:"type"`
	Status     string            `json:"status"`
	At         time.Time         `json:"at"`
	Attributes map[string]string `json:"attributes,omitempty"`
}

type Execution struct {
	LocalOnly     bool   `json:"local_only"`
	EndpointScope string `json:"endpoint_scope"`
	Model         string `json:"model"`
	RuntimeLabel  string `json:"runtime_label"`
}

type Metrics struct {
	DurationMS              float64 `json:"duration_ms"`
	ModelCalls              int     `json:"model_calls"`
	ContextPackets          int     `json:"context_packets"`
	Critiques               int     `json:"critiques"`
	Claims                  int     `json:"claims"`
	SupportedClaims         int     `json:"supported_claims"`
	EvidenceCoverage        float64 `json:"evidence_coverage"`
	RequiredSections        int     `json:"required_sections"`
	PresentRequiredSections int     `json:"present_required_sections"`
	MaxConcurrentContext    int     `json:"max_concurrent_context"`
}

type FollowUpSuggestion struct {
	SuggestionID string `json:"suggestion_id"`
	Label        string `json:"label"`
	Question     string `json:"question"`
}

func Project(report golden.Report) (Projection, error) {
	if report.Result.Answer == nil || report.Result.Failure != nil {
		return Projection{}, errors.New("workspace projection requires a released answer")
	}
	answer := *report.Result.Answer
	projection := Projection{
		SchemaVersion: SchemaVersionV1,
		CaseID:        "case-" + report.Request.RequestID,
		RunID:         report.Request.RunID,
		RequestID:     report.Request.RequestID,
		Status:        "completed",
		Title:         comparisonTitle(report.Request.Entities),
		Question:      report.Question,
		AsOf:          report.AsOf,
		Intent:        answer.PrimaryIntent,
		Assumptions:   append([]string(nil), answer.Assumptions...),
		Limitations:   append([]string(nil), answer.Limitations...),
		NextActions:   append([]string(nil), answer.NextActions...),
		Execution: Execution{
			LocalOnly: true, EndpointScope: "loopback_only", Model: report.Model,
			RuntimeLabel: "AMD Radeon / ROCm local inference",
		},
		Metrics: Metrics{
			DurationMS: report.Metrics.DurationMS, ModelCalls: report.Metrics.ModelCalls,
			ContextPackets: report.Metrics.ContextPackets, Critiques: report.Metrics.Critiques,
			Claims: report.Metrics.Claims, SupportedClaims: report.Metrics.SupportedClaims,
			EvidenceCoverage:        report.Metrics.EvidenceCoverage,
			RequiredSections:        report.Metrics.RequiredSections,
			PresentRequiredSections: report.Metrics.PresentRequiredSections,
			MaxConcurrentContext:    report.Metrics.MaxConcurrentContext,
		},
		FollowUps: defaultFollowUps(),
	}
	for _, entity := range report.Request.Entities {
		projection.Companies = append(projection.Companies, Company{EntityID: entity.EntityID, Label: entity.Mention})
	}
	sectionEvidence := map[string][]string{}
	sectionReceipts := map[string][]string{}
	for _, section := range answer.Sections {
		projection.Sections = append(projection.Sections, Section{
			SectionType: section.SectionType, Title: section.Title, Content: section.Content,
			ClaimRefs:     append([]string(nil), section.ClaimRefs...),
			EvidenceRefs:  append([]string(nil), section.EvidenceRefs...),
			ReceiptRefs:   append([]string(nil), section.ReceiptRefs...),
			NumericalRefs: append([]string(nil), section.NumericalRefs...),
		})
		for _, ref := range section.EvidenceRefs {
			sectionEvidence[ref] = appendUnique(sectionEvidence[ref], section.SectionType)
		}
		for _, ref := range section.ReceiptRefs {
			sectionReceipts[ref] = appendUnique(sectionReceipts[ref], section.SectionType)
		}
	}
	projection.Evidence = projectEvidence(report.Result.Packets, sectionEvidence)
	projection.Calculations = projectCalculations(report.Result.Packets, sectionReceipts)
	projection.Warnings = projectWarnings(report.Result.Packets, report.Result.ContextFailures)
	for _, event := range report.Result.Trace.Events {
		projection.Events = append(projection.Events, SafeEvent{
			Sequence: event.Sequence, StepID: event.StepID, Type: event.Type,
			Status: event.Status, At: event.At, Attributes: copyAttributes(event.Attributes),
		})
	}
	return projection, Validate(projection)
}

func Validate(projection Projection) error {
	if projection.SchemaVersion != SchemaVersionV1 || projection.CaseID == "" || projection.RunID == "" ||
		projection.RequestID == "" || projection.Status != "completed" || projection.Question == "" ||
		projection.AsOf.IsZero() || len(projection.Companies) != 2 || len(projection.Sections) == 0 {
		return errors.New("research workspace envelope is invalid")
	}
	if !projection.Execution.LocalOnly || projection.Execution.EndpointScope != "loopback_only" {
		return errors.New("research workspace must preserve local-only execution identity")
	}
	evidence := map[string]bool{}
	for _, item := range projection.Evidence {
		if item.EvidenceID == "" || item.Locator == "" || item.ContentSHA == "" || item.AsOf.IsZero() {
			return errors.New("research workspace contains invalid evidence")
		}
		evidence[item.EvidenceID] = true
	}
	receipts := map[string]bool{}
	for _, receipt := range projection.Calculations {
		if receipt.ReceiptID == "" || receipt.OperationID == "" || receipt.ReceiptSHA == "" || receipt.Status != contracts.ReceiptSuccess {
			return errors.New("research workspace contains invalid calculation receipt")
		}
		receipts[receipt.ReceiptID] = true
	}
	for _, section := range projection.Sections {
		if section.SectionType == "" || strings.TrimSpace(section.Content) == "" {
			return errors.New("research workspace contains an empty answer section")
		}
		for _, ref := range section.EvidenceRefs {
			if !evidence[ref] {
				return errors.New("research workspace section references unknown evidence")
			}
		}
		for _, ref := range section.ReceiptRefs {
			if !receipts[ref] {
				return errors.New("research workspace section references unknown receipt")
			}
		}
	}
	return nil
}

func projectEvidence(packets []contracts.ContextPacket, used map[string][]string) []EvidenceCard {
	items := map[string]EvidenceCard{}
	for _, packet := range packets {
		for _, evidence := range packet.Evidence {
			sections := used[evidence.EvidenceID]
			if len(sections) == 0 {
				continue
			}
			items[evidence.EvidenceID] = EvidenceCard{
				EvidenceID: evidence.EvidenceID, SourceType: evidence.SourceType,
				DocumentSection: evidence.DocumentSection, Locator: evidence.Locator,
				ContentSHA: evidence.ContentSHA, AsOf: evidence.AsOf,
				UsedInSections: append([]string(nil), sections...),
			}
		}
	}
	ids := sortedKeys(items)
	result := make([]EvidenceCard, 0, len(ids))
	for _, id := range ids {
		result = append(result, items[id])
	}
	return result
}

func projectCalculations(packets []contracts.ContextPacket, used map[string][]string) []CalculationCard {
	items := map[string]CalculationCard{}
	for _, packet := range packets {
		for _, receipt := range packet.CalculationReceipts {
			sections := used[receipt.ReceiptID]
			if len(sections) == 0 || receipt.Status != contracts.ReceiptSuccess {
				continue
			}
			items[receipt.ReceiptID] = CalculationCard{
				ReceiptID: receipt.ReceiptID, OperationID: receipt.OperationID,
				EngineID: receipt.EngineID, EngineVersion: receipt.EngineVersion,
				FormulaVersion: receipt.FormulaVersion, Status: receipt.Status,
				Outputs:          append([]contracts.ReceiptOutput(nil), receipt.Outputs...),
				InvariantResults: append([]contracts.InvariantResult(nil), receipt.InvariantResults...),
				Warnings:         append([]string(nil), receipt.Warnings...),
				EvidenceRefs:     append([]string(nil), receipt.EvidenceRefs...),
				SourceAsOf:       receipt.SourceAsOf, ReceiptSHA: receipt.ReceiptSHA,
				UsedInSections: append([]string(nil), sections...),
			}
		}
	}
	ids := sortedKeys(items)
	result := make([]CalculationCard, 0, len(ids))
	for _, id := range ids {
		result = append(result, items[id])
	}
	return result
}

func projectWarnings(packets []contracts.ContextPacket, failures []contracts.FailureReceipt) []Warning {
	seen := map[string]bool{}
	result := []Warning{}
	add := func(kind, roleID, text string) {
		text = strings.TrimSpace(text)
		key := kind + "\x00" + roleID + "\x00" + text
		if text == "" || seen[key] {
			return
		}
		seen[key] = true
		result = append(result, Warning{Kind: kind, RoleID: roleID, Text: text})
	}
	for _, packet := range packets {
		for _, text := range packet.MissingEvidence {
			add("missing_evidence", packet.SpecialistRole, text)
		}
		for _, text := range packet.Conflicts {
			add("conflict", packet.SpecialistRole, text)
		}
		for _, text := range packet.Uncertainties {
			add("uncertainty", packet.SpecialistRole, text)
		}
	}
	for _, failure := range failures {
		add("degraded_component", failure.ComponentID, failure.FailureCode)
	}
	return result
}

func comparisonTitle(entities []contracts.EntityRef) string {
	labels := make([]string, 0, len(entities))
	for _, entity := range entities {
		if label := strings.TrimSpace(entity.Mention); label != "" {
			labels = append(labels, label)
		}
	}
	if len(labels) == 2 {
		return labels[0] + " / " + labels[1] + " research case"
	}
	return "Company comparison research case"
}

func defaultFollowUps() []FollowUpSuggestion {
	return []FollowUpSuggestion{
		{SuggestionID: "cash-support", Label: "Cash support", Question: "How does cash generation support each company's long-term investment capacity?"},
		{SuggestionID: "rate-sensitivity", Label: "Rate sensitivity", Question: "Which assumptions make the valuation most sensitive to higher interest rates?"},
		{SuggestionID: "thesis-breakers", Label: "Thesis breakers", Question: "What evidence would invalidate the current long-term thesis?"},
	}
}

func appendUnique(values []string, value string) []string {
	for _, existing := range values {
		if existing == value {
			return values
		}
	}
	return append(values, value)
}

func sortedKeys[T any](values map[string]T) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func copyAttributes(values map[string]string) map[string]string {
	if len(values) == 0 {
		return nil
	}
	copy := make(map[string]string, len(values))
	for key, value := range values {
		copy[key] = value
	}
	return copy
}
