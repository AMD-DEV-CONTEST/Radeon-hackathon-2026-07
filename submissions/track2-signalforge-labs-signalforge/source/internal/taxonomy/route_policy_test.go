package taxonomy

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestEveryIntentHasVersionedBoundedPolicy(t *testing.T) {
	intents := []Intent{
		CompanyUnderstanding, FinancialQuality, EconomicTransmission, Valuation,
		CompanyComparison, ConceptEducation, MarketBehavior, ThesisReview,
	}
	for _, intent := range intents {
		policy, exists := PolicyFor(intent)
		if !exists || policy.PolicyID == "" || policy.Version != "1.0.0" ||
			policy.SelectionCode == "" || len(policy.ContextRoles) == 0 || len(policy.ContextRoles) > 4 {
			t.Fatalf("invalid policy for %s: %+v", intent, policy)
		}
		for _, roleID := range policy.ContextRoles {
			role, ok := roles.DefaultRegistry().Get(roleID)
			if !ok || role.Class != roles.ClassContext {
				t.Fatalf("policy %s references invalid context role %q", intent, roleID)
			}
		}
	}
}

func TestRouteExposesPolicyCodesWithoutReasoningText(t *testing.T) {
	route, err := Plan(
		"Compare Microsoft and NVIDIA on valuation and market behavior.",
		CompanyComparison,
		true,
	)
	if err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{
		"PLAN_COMPARISON_CORE", "PLAN_VALUATION_RECEIPTS", "PLAN_MARKET_CONTEXT",
		"PLAN_RISK_REVIEW", "PLAN_EVIDENCE_RELEASE_GATE", "PLAN_SINGLE_SYNTHESIS",
	} {
		if !containsString(route.PolicyCodes, expected) {
			t.Fatalf("missing policy code %q: %+v", expected, route.PolicyCodes)
		}
	}
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
