package localagent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/planner"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type InterpreterAdapter struct {
	Client  Completer
	Model   string
	Prompts PromptRegistry
}

type interpretedBody struct {
	PrimaryIntent    string                    `json:"primary_intent"`
	SecondaryIntents []string                  `json:"secondary_intents,omitempty"`
	Entities         []contracts.EntityRef     `json:"entities,omitempty"`
	Period           contracts.PeriodScope     `json:"period"`
	Comparison       contracts.ComparisonScope `json:"comparison"`
	AnswerDepth      string                    `json:"answer_depth"`
	RequestedOutputs []string                  `json:"requested_outputs"`
	Assumptions      []string                  `json:"assumptions,omitempty"`
	Ambiguities      []string                  `json:"ambiguities,omitempty"`
	RiskFlags        []string                  `json:"risk_flags,omitempty"`
}

func NewInterpreter(client Completer, model string) (*InterpreterAdapter, error) {
	if client == nil || strings.TrimSpace(model) == "" {
		return nil, errors.New("local model client and model ID are required")
	}
	return &InterpreterAdapter{Client: client, Model: model, Prompts: DefaultPromptRegistry()}, nil
}

// Interpret keeps the zero-model deterministic path for explicit requests and invokes the local
// model only when the closed parser cannot resolve the request.
func (adapter *InterpreterAdapter) Interpret(ctx context.Context, input requestparser.Input) (contracts.ResearchRequest, error) {
	request, deterministicErr := requestparser.ParseDeterministic(input)
	if deterministicErr == nil {
		return request, nil
	}
	prompt, _ := adapter.Prompts.Get(roles.RequestInterpreter)
	payload, err := json.Marshal(struct {
		UserText          string                         `json:"user_text"`
		AsOf              time.Time                      `json:"as_of"`
		InheritedEntities []contracts.EntityRef          `json:"inherited_entities,omitempty"`
		FollowUp          *requestparser.FollowUpContext `json:"follow_up_context,omitempty"`
		AllowedIntents    []string                       `json:"allowed_intents"`
	}{
		UserText: input.Text, AsOf: input.AsOf, InheritedEntities: input.InheritedEntities, FollowUp: input.FollowUp,
		AllowedIntents: []string{
			"company_understanding", "financial_quality", "economic_transmission", "valuation",
			"company_comparison", "concept_education", "market_behavior", "thesis_review",
		},
	})
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	seed := 42
	completion, err := adapter.Client.Complete(ctx, benchmark.Request{
		Model:     adapter.Model,
		Messages:  []benchmark.Message{{Role: "system", Content: prompt.System}, {Role: "user", Content: string(payload)}},
		MaxTokens: prompt.MaxTokens, Temperature: 0, Seed: &seed,
		ResponseFormat:     prompt.ResponseFormat(),
		ChatTemplateKwargs: map[string]any{"enable_thinking": false},
	})
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	var body interpretedBody
	if err := decodeJSONObject(completion.Answer, &body); err != nil {
		return contracts.ResearchRequest{}, fmt.Errorf("decode interpreted request: %w", err)
	}
	intent, err := requestparser.NormalizeModelIntent(body.PrimaryIntent)
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	for index, secondary := range body.SecondaryIntents {
		normalized, normalizeErr := requestparser.NormalizeModelIntent(secondary)
		err = normalizeErr
		if err != nil {
			return contracts.ResearchRequest{}, err
		}
		body.SecondaryIntents[index] = string(normalized)
	}
	body.Entities, err = normalizeInterpretedEntities(body.Entities)
	if err != nil {
		return contracts.ResearchRequest{}, err
	}
	parentRequestID := input.ParentRequestID
	lineageEvidence, lineageReceipts := []string(nil), []string(nil)
	requestAsOf := input.AsOf
	if input.FollowUp != nil {
		parentRequestID = input.FollowUp.ParentRequestID
		lineageEvidence = append([]string(nil), input.FollowUp.EvidenceRefs...)
		lineageReceipts = append([]string(nil), input.FollowUp.ReceiptRefs...)
		requestAsOf = input.FollowUp.AsOf
		if len(body.Entities) == 0 {
			body.Entities = append([]contracts.EntityRef(nil), input.FollowUp.Entities...)
		}
		if body.Period.Kind == "" {
			body.Period = input.FollowUp.Period
		}
		if body.Comparison.Mode == "" {
			body.Comparison = input.FollowUp.Comparison
		}
	}
	request = contracts.ResearchRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: input.RequestID, RunID: input.RunID,
		ParentRequestID: parentRequestID, LineageEvidenceRefs: lineageEvidence,
		LineageReceiptRefs: lineageReceipts, UserText: input.Text, PrimaryIntent: string(intent),
		SecondaryIntents: body.SecondaryIntents, Entities: body.Entities, Period: body.Period,
		AsOf: requestAsOf, Comparison: body.Comparison, AnswerDepth: body.AnswerDepth,
		RequestedOutputs: contracts.RequiredFinalSections(string(intent)), Assumptions: body.Assumptions,
		Ambiguities: body.Ambiguities, RiskFlags: body.RiskFlags,
	}
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return contracts.ResearchRequest{}, err
	}
	return request, nil
}

func normalizeInterpretedEntities(entities []contracts.EntityRef) ([]contracts.EntityRef, error) {
	canonical := map[string]contracts.EntityRef{
		"microsoft":          {EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true},
		"msft":               {EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true},
		"sec-cik:0000789019": {EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true},
		"nvidia":             {EntityType: "company", EntityID: "sec-cik:0001045810", Mention: "NVIDIA", Resolved: true},
		"nvda":               {EntityType: "company", EntityID: "sec-cik:0001045810", Mention: "NVIDIA", Resolved: true},
		"sec-cik:0001045810": {EntityType: "company", EntityID: "sec-cik:0001045810", Mention: "NVIDIA", Resolved: true},
	}
	result := make([]contracts.EntityRef, 0, len(entities))
	seen := map[string]bool{}
	for _, entity := range entities {
		if entity.EntityType != "company" {
			return nil, fmt.Errorf("model proposed unsupported entity type %q", entity.EntityType)
		}
		key := strings.ToLower(strings.TrimSpace(entity.EntityID))
		if _, ok := canonical[key]; !ok {
			key = strings.ToLower(strings.TrimSpace(entity.Mention))
		}
		normalized, ok := canonical[key]
		if !ok {
			if entity.Resolved {
				return nil, fmt.Errorf("model proposed unverified entity ID %q", entity.EntityID)
			}
			result = append(result, entity)
			continue
		}
		if !seen[normalized.EntityID] {
			seen[normalized.EntityID] = true
			result = append(result, normalized)
		}
	}
	return result, nil
}

type PlannerAdapter struct{ Builder planner.Builder }

func DefaultPlannerAdapter() PlannerAdapter { return PlannerAdapter{Builder: planner.Default()} }

// Plan is intentionally deterministic. The model prompt remains versioned for comparison, but a
// candidate model plan cannot weaken the frozen role, capability, fan-out, review, or DAG gates.
func (adapter PlannerAdapter) Plan(request contracts.ResearchRequest) (contracts.ResearchPlan, error) {
	return adapter.Builder.Build(request)
}
