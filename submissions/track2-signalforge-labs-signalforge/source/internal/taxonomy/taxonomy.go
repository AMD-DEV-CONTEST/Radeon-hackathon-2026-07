package taxonomy

import (
	"fmt"
	"sort"
)

const Version = "question-taxonomy/v1"

type Intent string

const (
	CompanyUnderstanding Intent = "company_understanding"
	FinancialQuality     Intent = "financial_quality"
	EconomicTransmission Intent = "economic_transmission"
	Valuation            Intent = "valuation"
	CompanyComparison    Intent = "company_comparison"
	ConceptEducation     Intent = "concept_education"
	MarketBehavior       Intent = "market_behavior"
	ThesisReview         Intent = "thesis_review"
)

type Definition struct {
	Intent           Intent   `json:"intent"`
	PersonaJob       string   `json:"persona_job"`
	Decision         string   `json:"decision"`
	PositiveExamples []string `json:"positive_examples"`
	NegativeExamples []string `json:"negative_examples"`
}

var definitions = map[Intent]Definition{
	CompanyUnderstanding: {
		Intent: CompanyUnderstanding, PersonaJob: "Understand the business",
		Decision:         "Determine whether the business is understandable and merits deeper research.",
		PositiveExamples: []string{"What does Microsoft sell?", "How does NVIDIA make money?"},
		NegativeExamples: []string{"What is Microsoft's beta?", "Estimate NVIDIA's fair value."},
	},
	FinancialQuality: {
		Intent: FinancialQuality, PersonaJob: "Assess financial quality",
		Decision:         "Judge growth, margins, cash conversion, reinvestment, returns, leverage, and dilution.",
		PositiveExamples: []string{"Why did free cash flow decline?", "Are margins and returns durable?"},
		NegativeExamples: []string{"What products does it sell?", "Should I buy it today?"},
	},
	EconomicTransmission: {
		Intent: EconomicTransmission, PersonaJob: "Understand external economic exposure",
		Decision:         "Trace an external variable through operations, financing, and valuation without claiming causality from correlation.",
		PositiveExamples: []string{"How do higher rates affect Microsoft?", "How could a stronger dollar affect NVIDIA?"},
		NegativeExamples: []string{"Calculate the current gross margin.", "Predict tomorrow's share price."},
	},
	Valuation: {
		Intent: Valuation, PersonaJob: "Estimate a defensible value range",
		Decision:         "Estimate a scenario-dependent range and expose assumptions, sensitivity, and implied expectations.",
		PositiveExamples: []string{"Build an FCFF valuation range.", "What growth does the current price imply?"},
		NegativeExamples: []string{"Explain deferred revenue.", "Tell me exactly when to buy."},
	},
	CompanyComparison: {
		Intent: CompanyComparison, PersonaJob: "Compare alternatives",
		Decision:         "Compare companies on aligned definitions, periods, quality, resilience, valuation, and risk.",
		PositiveExamples: []string{"Compare Microsoft and NVIDIA.", "Which has stronger cash conversion?"},
		NegativeExamples: []string{"Summarize Microsoft's history.", "Define operating leverage."},
	},
	ConceptEducation: {
		Intent: ConceptEducation, PersonaJob: "Learn in context",
		Decision:         "Teach accounting, finance, or economics using cited company evidence without turning education into advice.",
		PositiveExamples: []string{"Explain stock-based compensation using NVIDIA.", "Teach me operating leverage with Microsoft."},
		NegativeExamples: []string{"Update my existing thesis.", "Calculate a five-year beta."},
	},
	MarketBehavior: {
		Intent: MarketBehavior, PersonaJob: "Understand observed market behavior",
		Decision:         "Measure returns, volatility, drawdowns, beta, and price sensitivity without inventing business causality.",
		PositiveExamples: []string{"Compare their drawdowns.", "How sensitive has NVIDIA been to the Nasdaq?"},
		NegativeExamples: []string{"Explain revenue recognition.", "Forecast next quarter's earnings."},
	},
	ThesisReview: {
		Intent: ThesisReview, PersonaJob: "Monitor and reassess a thesis",
		Decision:         "Challenge a saved thesis against current evidence, disconfirming facts, and explicit invalidation conditions.",
		PositiveExamples: []string{"What would invalidate my Microsoft thesis?", "Reassess my thesis after the latest filing."},
		NegativeExamples: []string{"What does the company sell?", "Guarantee that my position will rise."},
	},
}

func Definitions() []Definition {
	intents := make([]string, 0, len(definitions))
	for intent := range definitions {
		intents = append(intents, string(intent))
	}
	sort.Strings(intents)
	result := make([]Definition, 0, len(intents))
	for _, value := range intents {
		definition := definitions[Intent(value)]
		definition.PositiveExamples = append([]string(nil), definition.PositiveExamples...)
		definition.NegativeExamples = append([]string(nil), definition.NegativeExamples...)
		result = append(result, definition)
	}
	return result
}

func ValidateIntent(intent Intent) error {
	if _, ok := definitions[intent]; !ok {
		return fmt.Errorf("unknown intent %q", intent)
	}
	return nil
}

func ValidateAndReturnIntent(value string) (Intent, error) {
	intent := Intent(value)
	if err := ValidateIntent(intent); err != nil {
		return "", err
	}
	return intent, nil
}
