package roles

import (
	"errors"
	"fmt"
	"sort"
)

const (
	RequestInterpreter    = "request-interpreter/v1"
	ResearchOrchestrator  = "research-orchestrator/v1"
	BusinessStrategy      = "business-strategy/v1"
	AccountingReporting   = "accounting-reporting/v1"
	FinancialQuality      = "financial-quality/v1"
	EconomicsTransmission = "economics-transmission/v1"
	Valuation             = "valuation/v1"
	MarketBehavior        = "market-behavior/v1"
	RiskContrarian        = "risk-contrarian/v1"
	EvidenceCritic        = "evidence-critic/v1"
	FinalResearchAnalyst  = "final-research-analyst/v1"
)

type Class string

const (
	ClassControl   Class = "control"
	ClassContext   Class = "context"
	ClassReview    Class = "review"
	ClassSynthesis Class = "synthesis"
)

type ArtifactPermission struct {
	Request  []string `json:"request,omitempty"`
	Produce  []string `json:"produce,omitempty"`
	Validate []string `json:"validate,omitempty"`
	Repair   []string `json:"repair,omitempty"`
	Release  []string `json:"release,omitempty"`
	Remember []string `json:"remember,omitempty"`
}

type Role struct {
	ID              string             `json:"role_id"`
	Class           Class              `json:"class"`
	Mission         string             `json:"mission"`
	Triggers        []string           `json:"triggers"`
	AntiTriggers    []string           `json:"anti_triggers"`
	AllowedTools    []string           `json:"allowed_tools"`
	EvidenceClasses []string           `json:"evidence_classes"`
	ContextBudget   int                `json:"context_budget_tokens"`
	TimeoutMS       int                `json:"timeout_ms"`
	MaxRetries      int                `json:"max_retries"`
	OutputArtifact  string             `json:"output_artifact"`
	Permissions     ArtifactPermission `json:"permissions"`
}

type Registry struct {
	roles map[string]Role
}

func DefaultRegistry() Registry {
	registry, err := NewRegistry(defaultRoles())
	if err != nil {
		panic(err)
	}
	return registry
}

func NewRegistry(definitions []Role) (Registry, error) {
	registry := Registry{roles: make(map[string]Role, len(definitions))}
	for _, role := range definitions {
		if err := validateRole(role); err != nil {
			return Registry{}, fmt.Errorf("role %q: %w", role.ID, err)
		}
		if _, exists := registry.roles[role.ID]; exists {
			return Registry{}, fmt.Errorf("duplicate role %q", role.ID)
		}
		registry.roles[role.ID] = cloneRole(role)
	}
	return registry, nil
}

func (registry Registry) Get(roleID string) (Role, bool) {
	role, ok := registry.roles[roleID]
	return cloneRole(role), ok
}

func (registry Registry) List() []Role {
	ids := make([]string, 0, len(registry.roles))
	for id := range registry.roles {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	result := make([]Role, 0, len(ids))
	for _, id := range ids {
		result = append(result, cloneRole(registry.roles[id]))
	}
	return result
}

func validateRole(role Role) error {
	if role.ID == "" || role.Mission == "" || role.OutputArtifact == "" {
		return errors.New("role_id, mission, and output_artifact are required")
	}
	switch role.Class {
	case ClassControl, ClassContext, ClassReview, ClassSynthesis:
	default:
		return fmt.Errorf("invalid class %q", role.Class)
	}
	if len(role.Triggers) == 0 || len(role.AntiTriggers) == 0 {
		return errors.New("triggers and anti_triggers are required")
	}
	if role.ContextBudget <= 0 || role.TimeoutMS <= 0 || role.MaxRetries < 0 || role.MaxRetries > 1 {
		return errors.New("invalid context, timeout, or retry budget")
	}
	return nil
}

func cloneRole(role Role) Role {
	role.Triggers = append([]string(nil), role.Triggers...)
	role.AntiTriggers = append([]string(nil), role.AntiTriggers...)
	role.AllowedTools = append([]string(nil), role.AllowedTools...)
	role.EvidenceClasses = append([]string(nil), role.EvidenceClasses...)
	role.Permissions = ArtifactPermission{
		Request:  append([]string(nil), role.Permissions.Request...),
		Produce:  append([]string(nil), role.Permissions.Produce...),
		Validate: append([]string(nil), role.Permissions.Validate...),
		Repair:   append([]string(nil), role.Permissions.Repair...),
		Release:  append([]string(nil), role.Permissions.Release...),
		Remember: append([]string(nil), role.Permissions.Remember...),
	}
	return role
}

func defaultRoles() []Role {
	primary := []string{"sec_filing", "sec_xbrl", "official_macro", "licensed_market", "calculation_receipt"}
	context := func(id, mission string, triggers, anti, tools []string) Role {
		return Role{
			ID: id, Class: ClassContext, Mission: mission, Triggers: triggers, AntiTriggers: anti,
			AllowedTools: tools, EvidenceClasses: primary, ContextBudget: 5000, TimeoutMS: 30000,
			MaxRetries: 1, OutputArtifact: "ContextPacket",
			Permissions: ArtifactPermission{Request: []string{"EvidenceBundle", "ToolReceipt"}, Produce: []string{"ContextPacket"}, Repair: []string{"ContextPacket"}},
		}
	}
	return []Role{
		{
			ID: RequestInterpreter, Class: ClassControl,
			Mission:  "Convert user language into a bounded typed research request without answering it.",
			Triggers: []string{"new_user_request", "clarified_request"}, AntiTriggers: []string{"evidence_synthesis", "calculation"},
			ContextBudget: 2500, TimeoutMS: 15000, MaxRetries: 1, OutputArtifact: "ResearchRequest",
			Permissions: ArtifactPermission{Produce: []string{"ResearchRequest"}, Repair: []string{"ResearchRequest"}},
		},
		{
			ID: ResearchOrchestrator, Class: ClassControl,
			Mission:  "Transform an approved request into a bounded dependency-aware research plan.",
			Triggers: []string{"valid_research_request", "bounded_repair"}, AntiTriggers: []string{"final_answer", "authoritative_calculation"},
			AllowedTools: []string{"capability.registry.read", "role.registry.read"}, EvidenceClasses: primary,
			ContextBudget: 3500, TimeoutMS: 20000, MaxRetries: 1, OutputArtifact: "ResearchPlan",
			Permissions: ArtifactPermission{Request: []string{"ResearchRequest"}, Produce: []string{"ResearchPlan", "ContextRequest"}, Repair: []string{"ResearchPlan"}},
		},
		context(BusinessStrategy, "Explain the business and convert strategy narratives into testable claims.", []string{"business_model", "segments", "competition", "company_history"}, []string{"accounting_measurement", "market_only"}, []string{"evidence.retrieve"}),
		context(AccountingReporting, "Interpret reported figures, policy, presentation, and comparability boundaries.", []string{"accounting_policy", "non_gaap", "comparability", "filing_disclosure"}, []string{"price_prediction", "portfolio_allocation"}, []string{"evidence.retrieve", "engine.execute"}),
		context(FinancialQuality, "Interpret verified growth, cash generation, reinvestment, returns, leverage, and dilution.", []string{"financial_quality", "margins", "cash_flow", "returns"}, []string{"unsupported_accounting_opinion", "price_prediction"}, []string{"evidence.retrieve", "engine.execute"}),
		context(EconomicsTransmission, "Explain mechanisms connecting economic variables to operations and valuation.", []string{"rates", "inflation", "currency", "demand_regime"}, []string{"correlation_as_causation", "technical_price_only"}, []string{"evidence.retrieve", "macro.read", "engine.execute"}),
		context(Valuation, "Select valuation methods and explain explicit assumptions, sensitivities, and reverse expectations.", []string{"valuation", "dcf", "multiples", "implied_expectations"}, []string{"personalized_advice", "calculation_in_prose"}, []string{"evidence.retrieve", "engine.execute", "market.read"}),
		context(MarketBehavior, "Interpret price behavior and sensitivity without inventing business causality.", []string{"price", "return", "volatility", "drawdown", "beta"}, []string{"pure_accounting", "business_model_only"}, []string{"market.read", "engine.execute"}),
		{
			ID: RiskContrarian, Class: ClassReview,
			Mission:  "Challenge the research thesis with disconfirming evidence and alternative explanations.",
			Triggers: []string{"material_research_decision", "compiled_context"}, AntiTriggers: []string{"schema_only_validation", "calculation_execution"},
			AllowedTools: []string{"evidence.retrieve"}, EvidenceClasses: primary, ContextBudget: 4000,
			TimeoutMS: 25000, MaxRetries: 1, OutputArtifact: "CritiqueReport",
			Permissions: ArtifactPermission{Request: []string{"ContextPacket", "EvidenceBundle"}, Produce: []string{"CritiqueReport"}},
		},
		{
			ID: EvidenceCritic, Class: ClassReview,
			Mission:  "Approve, narrow, repair, or reject claims against evidence, receipts, and policy.",
			Triggers: []string{"compiled_context", "repair_result"}, AntiTriggers: []string{"investment_thesis_ownership", "new_calculation"},
			AllowedTools: []string{"evidence.resolve", "receipt.replay"}, EvidenceClasses: primary,
			ContextBudget: 4000, TimeoutMS: 25000, MaxRetries: 1, OutputArtifact: "CritiqueReport",
			Permissions: ArtifactPermission{Request: []string{"ContextPacket", "ToolReceipt", "EvidenceBundle"}, Produce: []string{"CritiqueReport"}, Validate: []string{"ContextPacket", "FinalAnswer"}},
		},
		{
			ID: FinalResearchAnalyst, Class: ClassSynthesis,
			Mission:  "Produce the sole normal user-facing answer from approved context and critique artifacts.",
			Triggers: []string{"approved_context"}, AntiTriggers: []string{"unapproved_claim", "receipt_mutation"},
			AllowedTools: []string{"evidence.resolve", "receipt.read"}, EvidenceClasses: primary,
			ContextBudget: 7000, TimeoutMS: 30000, MaxRetries: 1, OutputArtifact: "FinalAnswer",
			Permissions: ArtifactPermission{Request: []string{"ContextPacket", "CritiqueReport", "ToolReceipt"}, Produce: []string{"FinalAnswer", "MemoryCandidate"}, Repair: []string{"FinalAnswer"}, Release: []string{"FinalAnswer"}, Remember: []string{"MemoryCandidate"}},
		},
	}
}
