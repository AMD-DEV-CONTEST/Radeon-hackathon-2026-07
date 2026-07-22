package architectureeval

import (
	"fmt"
	"slices"

	"github.com/rvbernucci/signalforge/internal/roles"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

type Metrics struct {
	Cases                     int     `json:"cases"`
	IntentAccuracy            float64 `json:"intent_accuracy"`
	MandatorySpecialistRecall float64 `json:"mandatory_specialist_recall"`
	UnnecessaryActivationRate float64 `json:"unnecessary_activation_rate"`
	ClarificationAccuracy     float64 `json:"clarification_accuracy"`
	AdviceBoundaryRecall      float64 `json:"advice_boundary_recall"`
	MaxContextRoles           int     `json:"max_context_roles"`
	RecursiveTransitions      int     `json:"recursive_transitions"`
}

type Candidate struct {
	Name             string  `json:"name"`
	LogicalRoleCount int     `json:"logical_role_count"`
	Metrics          Metrics `json:"metrics"`
	Accepted         bool    `json:"accepted"`
	RejectionReason  string  `json:"rejection_reason,omitempty"`
}

type Report struct {
	SchemaVersion string      `json:"schema_version"`
	Taxonomy      string      `json:"taxonomy"`
	Candidates    []Candidate `json:"candidates"`
	Selected      string      `json:"selected"`
	SelectionRule string      `json:"selection_rule"`
}

type routeFunction func(taxonomy.QuestionCase, taxonomy.Intent) (taxonomy.Route, error)

func Evaluate() (Report, error) {
	cases := taxonomy.FrozenCases()
	candidates := []Candidate{
		evaluateCandidate("separate-interpreter-orchestrator", 11, cases, separateRoute),
		evaluateCandidate("fused-broad-route", 11, cases, fusedBroadRoute),
		evaluateCandidate("nine-role-ablation", 9, cases, smallerAblationRoute),
	}
	selected := ""
	for _, candidate := range candidates {
		if candidate.Accepted && (selected == "" || candidate.LogicalRoleCount < roleCount(candidates, selected)) {
			selected = candidate.Name
		}
	}
	if selected == "" {
		return Report{}, fmt.Errorf("no architecture candidate passed the frozen acceptance gates: %+v", candidates)
	}
	return Report{
		SchemaVersion: "architecture-evaluation/v1",
		Taxonomy:      taxonomy.Version,
		Candidates:    candidates,
		Selected:      selected,
		SelectionRule: "smallest bench with 100% intent accuracy, mandatory-role recall, clarification accuracy, and advice-boundary recall; <=10% unnecessary activation; <=4 context roles; no recursion",
	}, nil
}

func evaluateCandidate(name string, logicalRoles int, cases []taxonomy.QuestionCase, route routeFunction) Candidate {
	var intentCorrect, mandatory, mandatoryFound, unnecessary, roleOpportunities int
	var clarificationCorrect, adviceCases, adviceFound, maxRoles int
	for _, item := range cases {
		intent, err := taxonomy.Interpret(item.Question)
		if err == nil && intent == item.PrimaryIntent {
			intentCorrect++
		}
		selected, routeErr := route(item, intent)
		if routeErr != nil {
			continue
		}
		if len(selected.ContextRoles) > maxRoles {
			maxRoles = len(selected.ContextRoles)
		}
		activeRoles := append(append([]string(nil), selected.ContextRoles...), selected.ReviewRoles...)
		for _, required := range item.MandatoryRoles {
			mandatory++
			if slices.Contains(activeRoles, required) {
				mandatoryFound++
			}
		}
		for _, active := range selected.ContextRoles {
			if !slices.Contains(item.MandatoryRoles, active) && !slices.Contains(item.OptionalRoles, active) {
				unnecessary++
			}
		}
		roleOpportunities += 6
		if selected.ClarifyFirst == item.ClarificationRequired {
			clarificationCorrect++
		}
		if item.AdversarialAdvice {
			adviceCases++
			if selected.AdviceBoundary {
				adviceFound++
			}
		}
	}
	metrics := Metrics{
		Cases:                     len(cases),
		IntentAccuracy:            ratio(intentCorrect, len(cases)),
		MandatorySpecialistRecall: ratio(mandatoryFound, mandatory),
		UnnecessaryActivationRate: ratio(unnecessary, roleOpportunities),
		ClarificationAccuracy:     ratio(clarificationCorrect, len(cases)),
		AdviceBoundaryRecall:      ratio(adviceFound, adviceCases),
		MaxContextRoles:           maxRoles,
	}
	accepted := metrics.IntentAccuracy == 1 && metrics.MandatorySpecialistRecall == 1 &&
		metrics.UnnecessaryActivationRate <= 0.10 && metrics.ClarificationAccuracy == 1 &&
		metrics.AdviceBoundaryRecall == 1 && metrics.MaxContextRoles <= 4 &&
		metrics.RecursiveTransitions == 0
	reason := ""
	if !accepted {
		reason = "one or more frozen acceptance gates failed"
	}
	return Candidate{Name: name, LogicalRoleCount: logicalRoles, Metrics: metrics, Accepted: accepted, RejectionReason: reason}
}

func separateRoute(item taxonomy.QuestionCase, intent taxonomy.Intent) (taxonomy.Route, error) {
	return taxonomy.Plan(item.Question, intent, false)
}

func fusedBroadRoute(item taxonomy.QuestionCase, intent taxonomy.Intent) (taxonomy.Route, error) {
	result, err := taxonomy.Plan(item.Question, intent, false)
	if err != nil {
		return result, err
	}
	result.ContextRoles = []string{
		roles.BusinessStrategy, roles.AccountingReporting, roles.FinancialQuality,
		roles.EconomicsTransmission, roles.Valuation, roles.MarketBehavior,
	}
	return result, nil
}

func smallerAblationRoute(item taxonomy.QuestionCase, intent taxonomy.Intent) (taxonomy.Route, error) {
	result, err := taxonomy.Plan(item.Question, intent, false)
	if err != nil {
		return result, err
	}
	result.ContextRoles = slices.DeleteFunc(result.ContextRoles, func(role string) bool {
		return role == roles.AccountingReporting || role == roles.MarketBehavior
	})
	return result, nil
}

func ratio(numerator, denominator int) float64 {
	if denominator == 0 {
		return 1
	}
	return float64(numerator) / float64(denominator)
}

func roleCount(candidates []Candidate, name string) int {
	for _, candidate := range candidates {
		if candidate.Name == name {
			return candidate.LogicalRoleCount
		}
	}
	return int(^uint(0) >> 1)
}
