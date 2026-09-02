package requestparser

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/domaincontrols"
	"github.com/rvbernucci/signalforge/internal/entityresolver"
	"github.com/rvbernucci/signalforge/internal/runid"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

type Input struct {
	Text              string
	AsOf              time.Time
	RunID             string
	RequestID         string
	ParentRequestID   string
	InheritedEntities []contracts.EntityRef
	FollowUp          *FollowUpContext
}

// FollowUpContext carries only governed scope and lineage identifiers. Evidence and receipt IDs
// are retrieval hints for a new run; they never authorize a claim without fresh material loading,
// validation, and review.
type FollowUpContext struct {
	ParentRequestID string
	Entities        []contracts.EntityRef
	Period          contracts.PeriodScope
	Comparison      contracts.ComparisonScope
	AsOf            time.Time
	EvidenceRefs    []string
	ReceiptRefs     []string
}

func ParseDeterministic(input Input) (contracts.ResearchRequest, error) {
	if strings.TrimSpace(input.Text) == "" || input.AsOf.IsZero() {
		return contracts.ResearchRequest{}, errors.New("text and as_of are required")
	}
	intent, err := taxonomy.Interpret(input.Text)
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	runID, requestID := input.RunID, input.RequestID
	if runID == "" {
		runID, err = runid.New(input.AsOf)
		if err != nil {
			return contracts.ResearchRequest{}, err
		}
	}
	if requestID == "" {
		requestID, err = runid.New(input.AsOf)
		if err != nil {
			return contracts.ResearchRequest{}, err
		}
	}
	followUp, err := normalizedFollowUpContext(input)
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	resolvedEntities := entities(input.Text)
	inheritedEntities := input.InheritedEntities
	if followUp != nil {
		inheritedEntities = followUp.Entities
	}
	if len(resolvedEntities) == 0 && len(inheritedEntities) > 0 {
		resolvedEntities = append([]contracts.EntityRef(nil), inheritedEntities...)
	}
	requestAsOf := input.AsOf.UTC()
	requestPeriod, periodDecision := domaincontrols.ResolvePeriod(input.Text, input.AsOf)
	requestComparison := comparison(input.Text)
	parentRequestID := input.ParentRequestID
	lineageEvidence, lineageReceipts := []string(nil), []string(nil)
	if followUp != nil {
		parentRequestID = followUp.ParentRequestID
		lineageEvidence = append([]string(nil), followUp.EvidenceRefs...)
		lineageReceipts = append([]string(nil), followUp.ReceiptRefs...)
		if !requestsFreshAsOf(input.Text) {
			requestAsOf = followUp.AsOf.UTC()
		}
		if !hasExplicitPeriod(input.Text) {
			requestPeriod = followUp.Period
		}
		if !hasExplicitComparison(input.Text) {
			requestComparison = followUp.Comparison
		}
	}
	if requestComparison.Mode == "peer" && len(requestComparison.EntityIDs) == 0 {
		for _, entity := range resolvedEntities {
			if entity.Resolved && entity.EntityID != "" {
				requestComparison.EntityIDs = append(requestComparison.EntityIDs, entity.EntityID)
			}
		}
	}
	request := contracts.ResearchRequest{
		SchemaVersion:       contracts.SchemaVersionV1,
		RequestID:           requestID,
		RunID:               runID,
		ParentRequestID:     parentRequestID,
		LineageEvidenceRefs: lineageEvidence,
		LineageReceiptRefs:  lineageReceipts,
		UserText:            strings.TrimSpace(input.Text),
		PrimaryIntent:       string(intent),
		Entities:            resolvedEntities,
		Period:              requestPeriod,
		AsOf:                requestAsOf,
		Comparison:          requestComparison,
		AnswerDepth:         answerDepth(input.Text),
		RequestedOutputs:    contracts.RequiredFinalSections(string(intent)),
		RiskFlags:           riskFlags(input.Text),
	}
	if !periodDecision.Allowed {
		request.Ambiguities = append(request.Ambiguities, periodDecision.Codes...)
	}
	if len(request.Entities) == 0 && intent != taxonomy.ConceptEducation {
		request.Ambiguities = append(request.Ambiguities, "company_or_prior_conversation_context_required")
	}
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return contracts.ResearchRequest{}, err
	}
	return request, nil
}

func NewFollowUpContext(parent contracts.ResearchRequest, answer contracts.FinalAnswer) (FollowUpContext, error) {
	if err := contracts.ValidateResearchRequest(parent); err != nil {
		return FollowUpContext{}, fmt.Errorf("invalid parent request: %w", err)
	}
	if err := contracts.ValidateFinalAnswer(answer); err != nil {
		return FollowUpContext{}, fmt.Errorf("invalid parent answer: %w", err)
	}
	if answer.RequestID != parent.RequestID || answer.RunID != parent.RunID || !answer.AsOf.Equal(parent.AsOf) {
		return FollowUpContext{}, errors.New("parent answer does not match the parent request")
	}
	evidence := append([]string(nil), parent.LineageEvidenceRefs...)
	receipts := append([]string(nil), parent.LineageReceiptRefs...)
	for _, section := range answer.Sections {
		evidence = append(evidence, section.EvidenceRefs...)
		receipts = append(receipts, section.ReceiptRefs...)
	}
	context := FollowUpContext{
		ParentRequestID: parent.RequestID,
		Entities:        append([]contracts.EntityRef(nil), parent.Entities...),
		Period:          parent.Period,
		Comparison:      parent.Comparison,
		AsOf:            parent.AsOf,
		EvidenceRefs:    uniqueSorted(evidence),
		ReceiptRefs:     uniqueSorted(receipts),
	}
	if err := validateFollowUpContext(context); err != nil {
		return FollowUpContext{}, err
	}
	return context, nil
}

func normalizedFollowUpContext(input Input) (*FollowUpContext, error) {
	if input.FollowUp == nil {
		return nil, nil
	}
	context := *input.FollowUp
	context.Entities = append([]contracts.EntityRef(nil), input.FollowUp.Entities...)
	context.EvidenceRefs = uniqueSorted(input.FollowUp.EvidenceRefs)
	context.ReceiptRefs = uniqueSorted(input.FollowUp.ReceiptRefs)
	if input.ParentRequestID != "" && input.ParentRequestID != context.ParentRequestID {
		return nil, errors.New("follow-up parent_request_id conflicts with input")
	}
	if err := validateFollowUpContext(context); err != nil {
		return nil, err
	}
	return &context, nil
}

func validateFollowUpContext(context FollowUpContext) error {
	if strings.TrimSpace(context.ParentRequestID) == "" || context.AsOf.IsZero() || context.Period.Kind == "" || context.Comparison.Mode == "" {
		return errors.New("follow-up context requires parent, as_of, period, and comparison")
	}
	if len(context.Entities) == 0 {
		return errors.New("follow-up context requires at least one inherited entity")
	}
	probe := contracts.ResearchRequest{
		SchemaVersion: contracts.SchemaVersionV1,
		RequestID:     "follow-up-context-validation", RunID: "follow-up-context-validation",
		ParentRequestID: context.ParentRequestID, LineageEvidenceRefs: context.EvidenceRefs,
		LineageReceiptRefs: context.ReceiptRefs, UserText: "follow-up context validation",
		PrimaryIntent: "company_understanding", Entities: context.Entities, Period: context.Period,
		AsOf: context.AsOf, Comparison: context.Comparison, AnswerDepth: "brief",
		RequestedOutputs: contracts.RequiredFinalSections("company_understanding"),
	}
	return contracts.ValidateResearchRequest(probe)
}

func uniqueSorted(values []string) []string {
	set := map[string]bool{}
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			set[value] = true
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func NormalizeModelIntent(value string) (taxonomy.Intent, error) {
	intent := taxonomy.Intent(strings.ToLower(strings.TrimSpace(value)))
	if err := taxonomy.ValidateIntent(intent); err != nil {
		return "", err
	}
	return intent, nil
}

func entities(text string) []contracts.EntityRef {
	resolutions := entityresolver.DefaultRegistry().ResolveText(text)
	result := make([]contracts.EntityRef, 0, len(resolutions))
	seen := map[string]bool{}
	for _, resolution := range resolutions {
		if !resolution.Resolved || seen[resolution.CompanyID] {
			continue
		}
		result = append(result, contracts.EntityRef{
			EntityType: "company", EntityID: resolution.CompanyID,
			Mention: resolution.Mention, Resolved: true,
		})
		seen[resolution.CompanyID] = true
	}
	return result
}

func hasExplicitPeriod(text string) bool {
	lower := strings.ToLower(text)
	return containsAny(lower, "five years", "five fiscal years", "three years", "three fiscal years",
		"last fiscal year", "previous fiscal year", "fiscal year", "fy ", "latest 10-q",
		"latest quarter", "current price", "today", "latest", "current", " from ")
}

func requestsFreshAsOf(text string) bool {
	lower := strings.ToLower(text)
	return containsAny(lower, "today", "current price", "latest 10-q", "latest quarter", "new filing", "since then")
}

func comparison(text string) contracts.ComparisonScope {
	entities := entities(text)
	result := contracts.ComparisonScope{Mode: "none"}
	lower := strings.ToLower(text)
	if len(entities) > 1 || containsAny(lower, "compare", "which company", "these two companies", "both companies") {
		result.Mode = "peer"
		for _, entity := range entities {
			result.EntityIDs = append(result.EntityIDs, entity.EntityID)
		}
	}
	return result
}

func hasExplicitComparison(text string) bool {
	lower := strings.ToLower(text)
	return len(entities(text)) > 1 || containsAny(lower, "compare", "which company", "these two companies", "both companies")
}

func answerDepth(text string) string {
	lower := strings.ToLower(text)
	if strings.Contains(lower, "deep") || strings.Contains(lower, "sensitivity") || strings.Contains(lower, "challenge") {
		return "deep"
	}
	if len([]rune(text)) < 80 {
		return "brief"
	}
	return "standard"
}

func riskFlags(text string) []string {
	lower := strings.ToLower(text)
	result := []string{}
	for _, candidate := range []struct{ phrase, flag string }{
		{"guarantee", "guaranteed_return_request"},
		{"must buy", "personalized_trade_instruction"},
		{"tell me to sell", "personalized_trade_instruction"},
		{"all my savings", "high_stakes_concentration"},
		{"ignore contrary evidence", "confirmation_bias_request"},
	} {
		if strings.Contains(lower, candidate.phrase) && !contains(result, candidate.flag) {
			result = append(result, candidate.flag)
		}
	}
	language := domaincontrols.AssessLanguage(text)
	if !language.Allowed {
		result = append(result, language.Codes...)
	}
	scope := domaincontrols.AssessResponsibleScope(text)
	if !scope.Allowed {
		result = append(result, scope.Codes...)
	}
	return uniqueSorted(result)
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func containsAny(value string, candidates ...string) bool {
	for _, candidate := range candidates {
		if strings.Contains(value, candidate) {
			return true
		}
	}
	return false
}
