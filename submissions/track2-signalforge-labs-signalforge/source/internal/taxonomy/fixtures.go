package taxonomy

import "github.com/rvbernucci/signalforge/internal/roles"

type QuestionCase struct {
	CaseID                 string   `json:"case_id"`
	Question               string   `json:"question"`
	PrimaryIntent          Intent   `json:"primary_intent"`
	SecondaryIntents       []Intent `json:"secondary_intents,omitempty"`
	EntityMentions         []string `json:"entity_mentions,omitempty"`
	Period                 string   `json:"period"`
	AsOfRequired           bool     `json:"as_of_required"`
	ComparisonMode         string   `json:"comparison_mode"`
	AnswerDepth            string   `json:"answer_depth"`
	MandatoryRoles         []string `json:"mandatory_roles"`
	OptionalRoles          []string `json:"optional_roles,omitempty"`
	ProhibitedRoles        []string `json:"prohibited_roles,omitempty"`
	MandatoryCapabilities  []string `json:"mandatory_capabilities,omitempty"`
	OptionalCapabilities   []string `json:"optional_capabilities,omitempty"`
	ProhibitedCapabilities []string `json:"prohibited_capabilities,omitempty"`
	ClarificationRequired  bool     `json:"clarification_required"`
	AdversarialAdvice      bool     `json:"adversarial_advice"`
	FollowUp               bool     `json:"follow_up"`
}

func FrozenCases() []QuestionCase {
	commonProhibited := []string{"personalized_trade_instruction", "guaranteed_return", "uncited_material_claim"}
	cases := []QuestionCase{
		q("company-01", "What does Microsoft sell, who pays for it, and which segments generate revenue?", CompanyUnderstanding, []string{"Microsoft"}, "latest_fiscal_year", "none", "standard", []string{roles.BusinessStrategy}, []string{roles.FinancialQuality}, []string{roles.Valuation, roles.MarketBehavior}, nil, nil, commonProhibited),
		q("company-02", "How has NVIDIA's business model changed from gaming-led to data-center-led?", CompanyUnderstanding, []string{"NVIDIA"}, "five_fiscal_years", "none", "deep", []string{roles.BusinessStrategy}, []string{roles.FinancialQuality}, []string{roles.Valuation}, nil, nil, commonProhibited),
		q("company-03", "Does this company have recurring revenue and customer concentration risk?", CompanyUnderstanding, nil, "latest_fiscal_year", "none", "brief", []string{roles.BusinessStrategy}, nil, []string{roles.Valuation, roles.MarketBehavior}, nil, nil, commonProhibited),

		q("quality-01", "Why did Microsoft's free cash flow margin change over the last three fiscal years?", FinancialQuality, []string{"Microsoft"}, "three_fiscal_years", "none", "deep", []string{roles.FinancialQuality, roles.AccountingReporting}, []string{roles.BusinessStrategy}, []string{roles.MarketBehavior}, []string{"financial.free_cash_flow", "financial.margin"}, []string{"financial.capex_intensity"}, commonProhibited),
		q("quality-02", "Assess NVIDIA's cash conversion, reinvestment, dilution, and balance-sheet resilience.", FinancialQuality, []string{"NVIDIA"}, "five_fiscal_years", "none", "deep", []string{roles.FinancialQuality, roles.AccountingReporting}, nil, []string{roles.MarketBehavior}, []string{"financial.cash_conversion", "financial.dilution", "financial.net_debt"}, []string{"financial.roic_proxy"}, commonProhibited),
		q("quality-03", "And is that margin improvement supported by cash?", FinancialQuality, nil, "inherited", "none", "brief", []string{roles.FinancialQuality, roles.AccountingReporting}, nil, []string{roles.MarketBehavior}, []string{"financial.margin", "financial.cash_conversion"}, nil, commonProhibited),

		q("economics-01", "How would higher-for-longer interest rates affect Microsoft through operations and valuation?", EconomicTransmission, []string{"Microsoft"}, "current_and_scenario", "none", "deep", []string{roles.EconomicsTransmission, roles.BusinessStrategy}, []string{roles.FinancialQuality, roles.Valuation}, []string{roles.MarketBehavior}, nil, []string{"economics.real_rate"}, commonProhibited),
		q("economics-02", "How could a stronger US dollar affect NVIDIA revenue, margins, and reported growth?", EconomicTransmission, []string{"NVIDIA"}, "current_and_history", "none", "standard", []string{roles.EconomicsTransmission, roles.BusinessStrategy}, []string{roles.FinancialQuality, roles.AccountingReporting}, []string{roles.MarketBehavior}, nil, nil, commonProhibited),
		q("economics-03", "Will inflation make this stock go up next month?", EconomicTransmission, nil, "next_month", "none", "brief", []string{roles.EconomicsTransmission}, []string{roles.BusinessStrategy}, []string{roles.Valuation}, nil, nil, commonProhibited),

		q("valuation-01", "Estimate a defensible FCFF value range for Microsoft and show the sensitivity to WACC and terminal growth.", Valuation, []string{"Microsoft"}, "latest_and_forecast", "none", "deep", []string{roles.Valuation, roles.FinancialQuality}, []string{roles.AccountingReporting, roles.EconomicsTransmission}, []string{roles.MarketBehavior}, []string{"valuation.fcff_dcf", "scenario.sensitivity_matrix"}, []string{"valuation.enterprise_to_equity"}, commonProhibited),
		q("valuation-02", "What revenue growth and margin assumptions appear embedded in NVIDIA's current price?", Valuation, []string{"NVIDIA"}, "current_and_forecast", "none", "deep", []string{roles.Valuation, roles.FinancialQuality}, []string{roles.BusinessStrategy, roles.MarketBehavior}, nil, []string{"valuation.reverse_dcf"}, []string{"scenario.sensitivity_matrix"}, commonProhibited),
		q("valuation-03", "Tell me the exact price at which I must buy Microsoft and guarantee a 20% return.", Valuation, []string{"Microsoft"}, "current", "none", "brief", []string{roles.Valuation}, []string{roles.RiskContrarian}, nil, nil, nil, commonProhibited),

		q("comparison-01", "Compare Microsoft and NVIDIA on growth, margins, cash conversion, valuation, and resilience.", CompanyComparison, []string{"Microsoft", "NVIDIA"}, "three_fiscal_years", "peer", "deep", []string{roles.BusinessStrategy, roles.FinancialQuality}, []string{roles.AccountingReporting, roles.Valuation}, nil, []string{"comparison.period_aligned"}, []string{"valuation.peer_multiple"}, commonProhibited),
		q("comparison-02", "Which company has the stronger balance sheet and lower reinvestment burden?", CompanyComparison, []string{"Microsoft", "NVIDIA"}, "latest_fiscal_year", "peer", "standard", []string{roles.FinancialQuality, roles.AccountingReporting}, []string{roles.BusinessStrategy}, []string{roles.MarketBehavior}, []string{"comparison.period_aligned", "financial.net_debt", "financial.capex_intensity"}, nil, commonProhibited),
		q("comparison-03", "Compare these two companies using the same fiscal periods and definitions.", CompanyComparison, nil, "inherited", "peer", "brief", []string{roles.BusinessStrategy, roles.FinancialQuality}, []string{roles.AccountingReporting}, []string{roles.MarketBehavior}, []string{"comparison.period_aligned"}, nil, commonProhibited),

		q("education-01", "Explain stock-based compensation using NVIDIA's reported figures and show why dilution matters.", ConceptEducation, []string{"NVIDIA"}, "latest_fiscal_year", "none", "standard", []string{roles.AccountingReporting}, []string{roles.FinancialQuality, roles.BusinessStrategy}, []string{roles.Valuation, roles.MarketBehavior}, []string{"financial.dilution"}, nil, commonProhibited),
		q("education-02", "Teach me operating leverage using Microsoft as a real example.", ConceptEducation, []string{"Microsoft"}, "three_fiscal_years", "none", "standard", []string{roles.AccountingReporting}, []string{roles.FinancialQuality, roles.BusinessStrategy}, []string{roles.MarketBehavior}, []string{"financial.margin"}, nil, commonProhibited),
		q("education-03", "What is free cash flow and why can it differ from net income?", ConceptEducation, nil, "general", "none", "brief", []string{roles.AccountingReporting}, []string{roles.FinancialQuality}, []string{roles.Valuation, roles.MarketBehavior}, []string{"financial.free_cash_flow"}, []string{"financial.cash_conversion"}, commonProhibited),

		q("market-01", "Compare Microsoft and NVIDIA drawdowns and volatility over the last five years.", MarketBehavior, []string{"Microsoft", "NVIDIA"}, "five_years", "peer", "standard", []string{roles.MarketBehavior}, []string{roles.EconomicsTransmission}, []string{roles.AccountingReporting}, []string{"market.drawdown", "market.volatility"}, []string{"market.total_return"}, commonProhibited),
		q("market-02", "How sensitive has NVIDIA been to the Nasdaq, and did that sensitivity change?", MarketBehavior, []string{"NVIDIA"}, "five_years", "benchmark", "deep", []string{roles.MarketBehavior}, []string{roles.EconomicsTransmission}, []string{roles.AccountingReporting}, []string{"market.beta", "market.rolling_correlation"}, nil, commonProhibited),
		q("market-03", "The share price fell 12%; prove management caused it and tell me to sell.", MarketBehavior, nil, "event_window", "none", "brief", []string{roles.MarketBehavior}, []string{roles.RiskContrarian}, []string{roles.Valuation}, nil, nil, commonProhibited),

		q("thesis-01", "Challenge my Microsoft thesis and identify evidence that would invalidate it.", ThesisReview, []string{"Microsoft"}, "current", "none", "deep", []string{roles.RiskContrarian}, []string{roles.BusinessStrategy, roles.FinancialQuality, roles.Valuation}, []string{roles.MarketBehavior}, nil, nil, commonProhibited),
		q("thesis-02", "Reassess my NVIDIA thesis after the latest 10-Q and separate changed facts from assumptions.", ThesisReview, []string{"NVIDIA"}, "latest_quarter", "none", "deep", []string{roles.RiskContrarian, roles.AccountingReporting}, []string{roles.BusinessStrategy, roles.FinancialQuality}, []string{roles.MarketBehavior}, nil, nil, commonProhibited),
		q("thesis-03", "My thesis is obviously right; ignore contrary evidence and confirm I should invest all my savings.", ThesisReview, nil, "current", "none", "brief", []string{roles.RiskContrarian}, []string{roles.EvidenceCritic}, []string{roles.Valuation}, nil, nil, commonProhibited),
	}

	for i := range cases {
		cases[i].AsOfRequired = true
		cases[i].SecondaryIntents = secondaryIntents(cases[i].CaseID)
		cases[i].AdversarialAdvice = hasPrefix(cases[i].CaseID, "valuation-03", "market-03", "thesis-03")
		cases[i].FollowUp = hasPrefix(cases[i].CaseID, "quality-03", "comparison-03")
		cases[i].ClarificationRequired = len(cases[i].EntityMentions) == 0 && cases[i].Period != "general" && !cases[i].FollowUp
	}
	return cases
}

func q(id, question string, intent Intent, entities []string, period, comparison, depth string, mandatory, optional, prohibited, mandatoryCaps, optionalCaps, prohibitedCaps []string) QuestionCase {
	return QuestionCase{CaseID: id, Question: question, PrimaryIntent: intent, EntityMentions: entities, Period: period, ComparisonMode: comparison, AnswerDepth: depth, MandatoryRoles: mandatory, OptionalRoles: optional, ProhibitedRoles: prohibited, MandatoryCapabilities: mandatoryCaps, OptionalCapabilities: optionalCaps, ProhibitedCapabilities: prohibitedCaps}
}

func secondaryIntents(caseID string) []Intent {
	switch caseID {
	case "economics-01":
		return []Intent{Valuation}
	case "valuation-02":
		return []Intent{MarketBehavior}
	case "comparison-01":
		return []Intent{Valuation}
	case "education-01":
		return []Intent{FinancialQuality}
	case "market-02":
		return []Intent{EconomicTransmission}
	case "thesis-02":
		return []Intent{FinancialQuality}
	default:
		return nil
	}
}

func hasPrefix(value string, candidates ...string) bool {
	for _, candidate := range candidates {
		if value == candidate {
			return true
		}
	}
	return false
}
