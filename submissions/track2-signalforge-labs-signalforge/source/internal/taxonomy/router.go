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
	PolicyCodes    []string `json:"policy_codes"`
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
		{ConceptEducation, []string{"explain stock-based compensation", "teach me", "what is"}},
		{MarketBehavior, []string{"drawdown", "volatility", "nasdaq", "share price fell", "sensitivity change"}},
		{CompanyComparison, []string{"compare", "comparison", "which company", "these two companies"}},
		{EconomicTransmission, []string{"macro", "interest rates", "inflation", "stronger us dollar", "economic"}},
		{Valuation, []string{"valuation", "value range", "current price imply", "embedded in", "price at which", "wacc", "terminal growth"}},
		{FinancialQuality, []string{"revenue growth", "operating margin", "margin improvement", "cash generation", "cash-generation", "simple fcf", "free cash flow", "cash conversion", "balance-sheet identity", "balance sheet identity", "earnings quality", "capex", "reinvestment", "dilution"}},
		{CompanyUnderstanding, []string{"makes money", "operating segments", "operating risks", "what does", "business model", "recurring revenue", "customer concentration", "who pays"}},
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
	policy, exists := PolicyFor(intent)
	if !exists {
		return Route{}, fmt.Errorf("no versioned route policy for %q", intent)
	}
	result := Route{
		PrimaryIntent: intent, ContextRoles: policy.ContextRoles,
		PolicyCodes: []string{policy.SelectionCode},
	}
	if materialDecision || intent == ThesisReview {
		result.ReviewRoles = append(result.ReviewRoles, roles.RiskContrarian)
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_RISK_REVIEW")
	}
	result.ReviewRoles = append(result.ReviewRoles, roles.EvidenceCritic)
	result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_EVIDENCE_RELEASE_GATE")
	result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_SINGLE_SYNTHESIS")
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
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_ACCOUNTING_COMPARABILITY")
	}
	if intent == CompanyComparison && containsAny(text, "higher-for-longer", "interest rates", "economic") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.EconomicsTransmission)
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_MACRO_TRANSMISSION")
	}
	if intent == CompanyComparison && containsAny(text, "valuation", "market price", "market prices", "dcf", "multiples") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.Valuation)
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_VALUATION_RECEIPTS")
	}
	if intent == CompanyComparison && containsAny(text, "market behavior", "share price", "market price", "market prices") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.MarketBehavior)
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_MARKET_CONTEXT")
	}
	if intent == CompanyComparison && containsAny(text, "slower ai infrastructure", "accounting", "reported", "fiscal") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.AccountingReporting)
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_ACCOUNTING_COMPARABILITY")
	}
	if intent == ThesisReview && containsAny(text, "10-q", "10-k", "reported", "filing") {
		result.ContextRoles = appendUnique(result.ContextRoles, roles.AccountingReporting)
		result.PolicyCodes = appendUnique(result.PolicyCodes, "PLAN_ACCOUNTING_COMPARABILITY")
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
