package planner

import (
	"errors"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

func TestBuilderCreatesBoundedAuthorizedPlan(t *testing.T) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion and free cash flow.",
		AsOf: time.Now().UTC(), RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Default().Build(request)
	if err != nil {
		t.Fatal(err)
	}
	contextCount, synthesisCount := 0, 0
	for _, step := range plan.Steps {
		switch step.Kind {
		case "context":
			contextCount++
		case "synthesis":
			synthesisCount++
			if step.RoleID != roles.FinalResearchAnalyst {
				t.Fatalf("unexpected synthesis role %q", step.RoleID)
			}
		}
	}
	if contextCount != 2 || synthesisCount != 1 || plan.MaxParallelSpecialists != 4 || plan.MaxRepairPasses != 1 {
		t.Fatalf("unexpected bounded plan %+v", plan)
	}
}

func TestBuilderRecognizesCashSupportAsCashConversion(t *testing.T) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "And is that margin improvement supported by cash?", AsOf: time.Now().UTC(),
		RunID: "run-1", RequestID: "request-1", ParentRequestID: "request-parent",
		InheritedEntities: []contracts.EntityRef{{
			EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true,
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Default().Build(request)
	if err != nil {
		t.Fatal(err)
	}
	wanted := map[string]bool{"financial.margin": false, "financial.cash_conversion": false}
	for _, step := range plan.Steps {
		for _, capabilityID := range step.CapabilityIDs {
			if _, ok := wanted[capabilityID]; ok {
				wanted[capabilityID] = true
			}
		}
	}
	for capabilityID, found := range wanted {
		if !found {
			t.Fatalf("expected capability %q in plan %+v", capabilityID, plan)
		}
	}
}

func TestBuilderRefusesAmbiguousContext(t *testing.T) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "How sensitive has this stock been to the Nasdaq?", AsOf: time.Now().UTC(), RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Default().Build(request); !errors.Is(err, ErrClarificationRequired) {
		t.Fatalf("expected clarification refusal, got %v", err)
	}
}

func TestThesisReviewKeepsContrarianInReviewWave(t *testing.T) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Challenge my Microsoft thesis and identify evidence that would invalidate it.", AsOf: time.Now().UTC(), RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Default().Build(request)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, step := range plan.Steps {
		if step.RoleID == roles.RiskContrarian {
			found = step.Kind == "review"
		}
	}
	if !found {
		t.Fatal("risk contrarian must execute in the review wave")
	}
}

func TestMaterialSecondaryIntentAddsIndependentContrarianReview(t *testing.T) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA.", AsOf: time.Now().UTC(), RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	request.SecondaryIntents = []string{string(taxonomy.Valuation), string(taxonomy.ThesisReview)}
	plan, err := Default().Build(request)
	if err != nil {
		t.Fatal(err)
	}
	reviewers := map[string]bool{}
	for _, step := range plan.Steps {
		if step.Kind == "review" {
			reviewers[step.RoleID] = true
		}
	}
	if !reviewers[roles.EvidenceCritic] || !reviewers[roles.RiskContrarian] {
		t.Fatalf("material secondary intent requires both independent reviewers: %+v", reviewers)
	}
}

func TestGoldenComparisonUsesTwoBoundedContextWaves(t *testing.T) {
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA as long-term businesses under higher-for-longer interest rates and slower AI infrastructure spending. Include accounting, market behavior, DCF valuation, and the assumptions implied by market prices.",
		AsOf: time.Now().UTC(), RunID: "run-golden", RequestID: "request-golden",
	})
	if err != nil {
		t.Fatal(err)
	}
	plan, err := Default().Build(request)
	if err != nil {
		t.Fatal(err)
	}
	waves := map[int][]string{}
	for _, step := range plan.Steps {
		if step.Kind == "context" {
			waves[step.Wave] = append(waves[step.Wave], step.RoleID)
		}
	}
	if len(waves[1]) != 4 || len(waves[2]) != 2 {
		t.Fatalf("expected bounded 4+2 context waves, got %+v", waves)
	}
	wanted := map[string]bool{
		roles.BusinessStrategy: false, roles.AccountingReporting: false,
		roles.FinancialQuality: false, roles.EconomicsTransmission: false,
		roles.Valuation: false, roles.MarketBehavior: false,
	}
	for _, roleIDs := range waves {
		for _, roleID := range roleIDs {
			if _, exists := wanted[roleID]; exists {
				wanted[roleID] = true
			}
		}
	}
	for roleID, found := range wanted {
		if !found {
			t.Fatalf("golden plan omitted %s: %+v", roleID, plan)
		}
	}
	for _, required := range []string{
		"financial.revenue_growth", "financial.margin", "financial.free_cash_flow",
		"financial.cash_conversion", "financial.capex_intensity", "comparison.period_aligned",
		"valuation.fcff_dcf", "scenario.sensitivity_matrix", "valuation.peer_multiple",
		"economics.yield_curve",
	} {
		found := false
		for _, step := range plan.Steps {
			for _, operationID := range step.CapabilityIDs {
				if operationID == required {
					found = true
				}
			}
		}
		if !found {
			t.Fatalf("golden plan omitted operation %q", required)
		}
	}
}
