package planner

import (
	"errors"
	"fmt"
	"strings"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/roles"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

var ErrClarificationRequired = errors.New("clarification required before planning")

type Builder struct {
	Roles              roles.Registry
	Capabilities       capability.Registry
	DeadlineMS         int
	ContextTimeoutMS   int
	ReviewTimeoutMS    int
	SynthesisTimeoutMS int
}

func Default() Builder {
	return Builder{Roles: roles.DefaultRegistry(), Capabilities: capability.Tier0Registry(), DeadlineMS: 90000}
}

func (builder Builder) Build(request contracts.ResearchRequest) (contracts.ResearchPlan, error) {
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return contracts.ResearchPlan{}, err
	}
	intent, err := taxonomy.ValidateAndReturnIntent(request.PrimaryIntent)
	if err != nil {
		return contracts.ResearchPlan{}, err
	}
	material := len(request.RiskFlags) > 0 || intent == taxonomy.Valuation || intent == taxonomy.ThesisReview ||
		containsIntent(request.SecondaryIntents, taxonomy.Valuation) || containsIntent(request.SecondaryIntents, taxonomy.ThesisReview)
	route, err := taxonomy.Plan(request.UserText, intent, material)
	if err != nil {
		return contracts.ResearchPlan{}, err
	}
	if route.ClarifyFirst || len(request.Ambiguities) > 0 {
		return contracts.ResearchPlan{}, ErrClarificationRequired
	}
	contextRoles := make([]string, 0, len(route.ContextRoles))
	reviewRoles := append([]string(nil), route.ReviewRoles...)
	for _, roleID := range route.ContextRoles {
		role, ok := builder.Roles.Get(roleID)
		if !ok {
			return contracts.ResearchPlan{}, fmt.Errorf("unknown role %q", roleID)
		}
		if role.Class == roles.ClassReview {
			reviewRoles = appendUnique(reviewRoles, roleID)
			continue
		}
		contextRoles = append(contextRoles, roleID)
	}
	if len(contextRoles) > 8 {
		return contracts.ResearchPlan{}, errors.New("route exceeds bounded context specialist capacity")
	}
	plan := contracts.ResearchPlan{
		SchemaVersion: contracts.SchemaVersionV1, PlanID: "plan-" + request.RequestID,
		RunID: request.RunID, RequestID: request.RequestID, MaxParallelSpecialists: 4,
		MaxRepairPasses: 1, DeadlineMS: builder.DeadlineMS,
		CompletionConditions: []string{"evidence_critic_approved", "single_final_answer"},
		AbstentionConditions: []string{"missing_primary_evidence", "unresolved_material_conflict", "deadline_exceeded"},
	}
	contextIDs := make([]string, 0, len(contextRoles))
	operations := detectOperations(request.UserText)
	for index, roleID := range contextRoles {
		role, ok := builder.Roles.Get(roleID)
		if !ok {
			return contracts.ResearchPlan{}, fmt.Errorf("unknown role %q", roleID)
		}
		stepID := fmt.Sprintf("context-%02d", index+1)
		contextIDs = append(contextIDs, stepID)
		wave := index/plan.MaxParallelSpecialists + 1
		step := contracts.PlanStep{
			StepID: stepID, Kind: "context", Objective: role.Mission, RoleID: roleID,
			Wave:                 wave,
			EvidenceRequirements: append([]string(nil), role.EvidenceClasses...), Mandatory: true,
			ContextBudget: role.ContextBudget, TimeoutMS: configuredTimeout(role.TimeoutMS, builder.ContextTimeoutMS),
		}
		if wave > 1 {
			step.DependsOn = append([]string(nil), contextIDs[:plan.MaxParallelSpecialists]...)
		}
		for _, operationID := range operations {
			if builder.Capabilities.Authorizes(roleID, operationID) {
				step.CapabilityIDs = append(step.CapabilityIDs, operationID)
			}
		}
		plan.Steps = append(plan.Steps, step)
	}
	reviewIDs := make([]string, 0, len(reviewRoles))
	for index, roleID := range reviewRoles {
		role, ok := builder.Roles.Get(roleID)
		if !ok || role.Class != roles.ClassReview {
			return contracts.ResearchPlan{}, fmt.Errorf("invalid review role %q", roleID)
		}
		stepID := fmt.Sprintf("review-%02d", index+1)
		reviewIDs = append(reviewIDs, stepID)
		plan.Steps = append(plan.Steps, contracts.PlanStep{
			StepID: stepID, Kind: "review", Objective: role.Mission, RoleID: roleID,
			DependsOn: append([]string(nil), contextIDs...), Mandatory: true,
			ContextBudget: role.ContextBudget, TimeoutMS: configuredTimeout(role.TimeoutMS, builder.ReviewTimeoutMS),
		})
	}
	finalRole, _ := builder.Roles.Get(roles.FinalResearchAnalyst)
	dependencies := reviewIDs
	if len(dependencies) == 0 {
		dependencies = contextIDs
	}
	plan.Steps = append(plan.Steps, contracts.PlanStep{
		StepID: "synthesis-01", Kind: "synthesis", Objective: finalRole.Mission,
		RoleID: roles.FinalResearchAnalyst, DependsOn: append([]string(nil), dependencies...), Mandatory: true,
		ContextBudget: finalRole.ContextBudget, TimeoutMS: configuredTimeout(finalRole.TimeoutMS, builder.SynthesisTimeoutMS),
	})
	if err := contracts.ValidateResearchPlan(plan); err != nil {
		return contracts.ResearchPlan{}, err
	}
	return plan, nil
}

func containsIntent(values []string, target taxonomy.Intent) bool {
	for _, value := range values {
		if value == string(target) {
			return true
		}
	}
	return false
}

func configuredTimeout(defaultValue, configured int) int {
	if configured > 0 {
		return configured
	}
	return defaultValue
}

func appendUnique(values []string, candidate string) []string {
	for _, value := range values {
		if value == candidate {
			return values
		}
	}
	return append(values, candidate)
}

func detectOperations(text string) []string {
	lower := strings.ToLower(text)
	rules := []struct {
		terms     []string
		operation string
	}{
		{[]string{"free cash flow"}, "financial.free_cash_flow"},
		{[]string{"cash conversion", "supported by cash", "backed by cash"}, "financial.cash_conversion"},
		{[]string{"margin", "operating leverage"}, "financial.margin"},
		{[]string{"dilution"}, "financial.dilution"},
		{[]string{"net debt", "balance sheet", "balance-sheet"}, "financial.net_debt"},
		{[]string{"reinvestment burden", "capex intensity"}, "financial.capex_intensity"},
		{[]string{"dcf", "value range"}, "valuation.fcff_dcf"},
		{[]string{"current price imply", "embedded in"}, "valuation.reverse_dcf"},
		{[]string{"wacc"}, "valuation.wacc"},
		{[]string{"sensitivity"}, "scenario.sensitivity_matrix"},
		{[]string{"drawdown"}, "market.drawdown"},
		{[]string{"volatility"}, "market.volatility"},
		{[]string{"beta", "sensitive"}, "market.beta"},
		{[]string{"rolling correlation", "sensitivity change"}, "market.rolling_correlation"},
		{[]string{"compare", "which company", "same fiscal periods"}, "comparison.period_aligned"},
	}
	result := []string{}
	seen := map[string]bool{}
	add := func(operation string) {
		if !seen[operation] {
			result = append(result, operation)
			seen[operation] = true
		}
	}
	if strings.Contains(lower, "compare") || strings.Contains(lower, "financial quality") || strings.Contains(lower, "long-term businesses") {
		for _, operation := range []string{
			"financial.revenue_growth",
			"financial.margin",
			"financial.free_cash_flow",
			"financial.cash_conversion",
			"financial.capex_intensity",
			"comparison.period_aligned",
		} {
			add(operation)
		}
	}
	if strings.Contains(lower, "valuation") || strings.Contains(lower, "dcf") || strings.Contains(lower, "value range") {
		add("valuation.fcff_dcf")
		add("scenario.sensitivity_matrix")
	}
	if strings.Contains(lower, "multiple") || strings.Contains(lower, "market price") || strings.Contains(lower, "market prices") {
		add("valuation.peer_multiple")
	}
	if strings.Contains(lower, "higher-for-longer") || strings.Contains(lower, "yield curve") {
		add("economics.yield_curve")
	}
	for _, rule := range rules {
		for _, term := range rule.terms {
			if strings.Contains(lower, term) {
				add(rule.operation)
				break
			}
		}
	}
	return result
}
