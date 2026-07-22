package taxonomy

import (
	"fmt"
	"strings"

	"github.com/rvbernucci/signalforge/internal/roles"
)

type Route struct {
	PrimaryIntent  Intent   `json:"primary_intent"`
	ContextRoles   []string `json:"context_roles"`
	ReviewRoles    []string `json:"review_roles"`
	ClarifyFirst   bool     `json:"clarify_first"`
	AdviceBoundary bool     `json:"advice_boundary"`
}

func Interpret(question string) (Intent, error) {
	text := strings.ToLower(question)
	rules := []struct {
		intent Intent
		terms  []string
	}{
		{ThesisReview, []string{"thesis", "contrary evidence", "invalidate"}},
		{ConceptEducation, []string{"explain", "teach me", "what is"}},
		{MarketBehavior, []string{"drawdown", "volatility", "nasdaq", "share price fell", "sensitivity change"}},
		{CompanyComparison, []string{"compare", "which company", "these two companies"}},
		{Valuation, []string{"value range", "current price imply", "embedded in", "price at which", "wacc", "terminal growth"}},
		{EconomicTransmission, []string{"interest rates", "inflation", "stronger us dollar", "economic"}},
		{FinancialQuality, []string{"free cash flow", "cash conversion", "margin improvement", "balance-sheet resilience", "reinvestment", "dilution"}},
		{CompanyUnderstanding, []string{"what does", "business model", "recurring revenue", "customer concentration", "who pays"}},
	}
	for _, rule := range rules {
		for _, term := range rule.terms {
			if strings.Contains(text, term) {
				return rule.intent, nil
			}
		}
	}
	return "", fmt.Errorf("intent is ambiguous")
}

func MinimalRoute(intent Intent, materialDecision bool) (Route, error) {
	if err := ValidateIntent(intent); err != nil {
		return Route{}, err
	}
	result := Route{PrimaryIntent: intent, ReviewRoles: []string{roles.EvidenceCritic}}
	switch intent {
	case CompanyUnderstanding:
		result.ContextRoles = []string{roles.BusinessStrategy}
	case FinancialQuality:
		result.ContextRoles = []string{roles.FinancialQuality, roles.AccountingReporting}
	case EconomicTransmission:
		result.ContextRoles = []string{roles.EconomicsTransmission, roles.BusinessStrategy}
	case Valuation:
		result.ContextRoles = []string{roles.Valuation, roles.FinancialQuality}
	case CompanyComparison:
		result.ContextRoles = []string{roles.BusinessStrategy, roles.FinancialQuality}
	case ConceptEducation:
		result.ContextRoles = []string{roles.AccountingReporting}
	case MarketBehavior:
		result.ContextRoles = []string{roles.MarketBehavior}
	case ThesisReview:
		result.ContextRoles = []string{roles.BusinessStrategy}
		result.ReviewRoles = appendUnique(result.ReviewRoles, roles.RiskContrarian)
	}
	if materialDecision && intent != ThesisReview {
		result.ReviewRoles = append(result.ReviewRoles, roles.RiskContrarian)
	}
	return result, nil
}

// Plan refines the intent route only when the question contains a documented
// domain trigger. It remains a deterministic Sprint 00 reference, not the
// production model-backed interpreter.
func Plan(question string, intent Intent, materialDecision bool) (Route, error) {
	result, err := MinimalRoute(intent, materialDecision)
	if err != nil {
		return Route{}, err
	}
	text := strings.ToLower(question)
	result.ClarifyFirst = !containsAny(text, "microsoft", "nvidia") && containsAny(text,
		"this company", "this stock", "the share price", "my thesis")
	result.AdviceBoundary = containsAny(text,
		"guarantee", "must buy", "tell me to sell", "invest all my savings")
	if intent == CompanyComparison && containsAny(text, "balance sheet", "same fiscal periods", "same definitions") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.AccountingReporting)
	}
	if intent == CompanyComparison && containsAny(text, "higher-for-longer", "interest rates", "economic") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.EconomicsTransmission)
	}
	if intent == CompanyComparison && containsAny(text, "valuation", "market price", "market prices", "dcf", "multiples") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.Valuation)
	}
	if intent == CompanyComparison && containsAny(text, "market behavior", "share price", "market price", "market prices") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.MarketBehavior)
	}
	if intent == CompanyComparison && containsAny(text, "slower ai infrastructure", "accounting", "reported", "fiscal") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.AccountingReporting)
	}
	if intent == ThesisReview && containsAny(text, "10-q", "10-k", "reported", "filing") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.AccountingReporting)
	}
	return result, nil
}

func containsAny(value string, terms ...string) bool {
	for _, term := range terms {
		if strings.Contains(value, term) {
			return true
		}
	}
	return false
}

func appendUnique(values []string, value string) []string {
	for _, item := range values {
		if item == value {
			return values
		}
	}
	return append(values, value)
}
