package taxonomy

import "github.com/rvbernucci/signalforge/internal/roles"

type RoutePolicy struct {
	PolicyID      string
	Version       string
	ContextRoles  []string
	SelectionCode string
}

var routePolicies = map[Intent]RoutePolicy{
	CompanyUnderstanding: {
		PolicyID: "route-company-understanding", Version: "1.0.0",
		ContextRoles: []string{roles.BusinessStrategy}, SelectionCode: "PLAN_BUSINESS_MINIMAL",
	},
	FinancialQuality: {
		PolicyID: "route-financial-quality", Version: "1.0.0",
		ContextRoles:  []string{roles.FinancialQuality, roles.AccountingReporting},
		SelectionCode: "PLAN_FINANCIAL_QUALITY",
	},
	EconomicTransmission: {
		PolicyID: "route-economic-transmission", Version: "1.0.0",
		ContextRoles:  []string{roles.EconomicsTransmission, roles.BusinessStrategy},
		SelectionCode: "PLAN_MACRO_TRANSMISSION",
	},
	Valuation: {
		PolicyID: "route-valuation", Version: "1.0.0",
		ContextRoles:  []string{roles.Valuation, roles.FinancialQuality},
		SelectionCode: "PLAN_VALUATION_RECEIPTS",
	},
	CompanyComparison: {
		PolicyID: "route-company-comparison", Version: "1.0.0",
		ContextRoles:  []string{roles.BusinessStrategy, roles.FinancialQuality},
		SelectionCode: "PLAN_COMPARISON_CORE",
	},
	ConceptEducation: {
		PolicyID: "route-concept-education", Version: "1.0.0",
		ContextRoles: []string{roles.AccountingReporting}, SelectionCode: "PLAN_EDUCATION_GROUNDED",
	},
	MarketBehavior: {
		PolicyID: "route-market-behavior", Version: "1.0.0",
		ContextRoles: []string{roles.MarketBehavior}, SelectionCode: "PLAN_MARKET_CONTEXT",
	},
	ThesisReview: {
		PolicyID: "route-thesis-review", Version: "1.0.0",
		ContextRoles: []string{roles.BusinessStrategy}, SelectionCode: "PLAN_THESIS_CHALLENGE",
	},
}

func PolicyFor(intent Intent) (RoutePolicy, bool) {
	policy, exists := routePolicies[intent]
	policy.ContextRoles = append([]string(nil), policy.ContextRoles...)
	return policy, exists
}
