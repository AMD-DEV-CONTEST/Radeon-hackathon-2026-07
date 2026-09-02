package roleprofiles

import (
	"fmt"
	"sort"

	"github.com/rvbernucci/signalforge/internal/evidencefabric"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type Registry struct {
	profiles map[string]evidencefabric.RetrievalProfile
}

func DefaultRegistry() Registry {
	registry, err := NewRegistry(defaultProfiles())
	if err != nil {
		panic(err)
	}
	return registry
}

func NewRegistry(profiles []evidencefabric.RetrievalProfile) (Registry, error) {
	roleRegistry := roles.DefaultRegistry()
	result := Registry{profiles: make(map[string]evidencefabric.RetrievalProfile, len(profiles))}
	for _, profile := range profiles {
		if err := profile.Validate(); err != nil {
			return Registry{}, fmt.Errorf("profile %q: %w", profile.ProfileID, err)
		}
		role, ok := roleRegistry.Get(profile.RoleID)
		if !ok {
			return Registry{}, fmt.Errorf("profile %q references unknown role", profile.ProfileID)
		}
		for _, toolID := range profile.ToolAllowlist {
			if !contains(role.AllowedTools, toolID) {
				return Registry{}, fmt.Errorf("profile %q exceeds role tool authority with %q", profile.ProfileID, toolID)
			}
		}
		if _, exists := result.profiles[profile.RoleID]; exists {
			return Registry{}, fmt.Errorf("duplicate profile for role %q", profile.RoleID)
		}
		result.profiles[profile.RoleID] = clone(profile)
	}
	if len(result.profiles) != len(roleRegistry.List()) {
		return Registry{}, fmt.Errorf("profile coverage mismatch: got %d want %d", len(result.profiles), len(roleRegistry.List()))
	}
	return result, nil
}

func (registry Registry) Get(roleID string) (evidencefabric.RetrievalProfile, bool) {
	profile, ok := registry.profiles[roleID]
	return clone(profile), ok
}

func (registry Registry) List() []evidencefabric.RetrievalProfile {
	ids := make([]string, 0, len(registry.profiles))
	for id := range registry.profiles {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	result := make([]evidencefabric.RetrievalProfile, 0, len(ids))
	for _, id := range ids {
		result = append(result, clone(registry.profiles[id]))
	}
	return result
}

func defaultProfiles() []evidencefabric.RetrievalProfile {
	primary := []evidencefabric.AuthorityClass{
		evidencefabric.AuthorityA0,
		evidencefabric.AuthorityA1,
		evidencefabric.AuthorityA2,
		evidencefabric.AuthorityA3,
	}
	publicRights := []evidencefabric.RightsState{
		evidencefabric.RightsPublicDataReviewed,
		evidencefabric.RightsPublicAPITerms,
		evidencefabric.RightsPublicAuthorial,
		evidencefabric.RightsPublicMetadata,
	}
	none := func(roleID string) evidencefabric.RetrievalProfile {
		return evidencefabric.RetrievalProfile{
			SchemaVersion: evidencefabric.SchemaVersion,
			ProfileID:     roleID + ".retrieval/v1",
			RoleID:        roleID,
			Version:       "1.0.0",
			Mode:          evidencefabric.RetrievalNone,
			HyDE:          evidencefabric.HyDENone,
		}
	}
	active := func(roleID string, mode evidencefabric.RetrievalMode, hyde evidencefabric.HyDEPolicy,
		kinds, claims, tools []string, companyRequired bool, candidateBudget, tokenBudget int,
	) evidencefabric.RetrievalProfile {
		return evidencefabric.RetrievalProfile{
			SchemaVersion: evidencefabric.SchemaVersion,
			ProfileID:     roleID + ".retrieval/v1",
			RoleID:        roleID,
			Version:       "1.0.0",
			Mode:          mode,
			AllowedAuthorities: append([]evidencefabric.AuthorityClass(nil),
				primary...),
			AllowedRights:      append([]evidencefabric.RightsState(nil), publicRights...),
			AllowedSourceKinds: kinds,
			ClaimClasses:       claims,
			ToolAllowlist:      tools,
			CompanyRequired:    companyRequired,
			AsOfRequired:       true,
			HyDE:               hyde,
			CandidateBudget:    candidateBudget,
			ContextTokenBudget: tokenBudget,
		}
	}
	return []evidencefabric.RetrievalProfile{
		none(roles.RequestInterpreter),
		none(roles.ResearchOrchestrator),
		active(
			roles.BusinessStrategy,
			evidencefabric.RetrievalHybrid,
			evidencefabric.HyDEConditional,
			[]string{"sec_business", "sec_risk", "issuer_authorial", "industry_statistic", "patent_metadata", "competition_event", "research_card"},
			[]string{"business_fact", "issuer_claim", "industry_context", "strategy_hypothesis"},
			[]string{"evidence.retrieve"},
			true, 24, 5000,
		),
		active(
			roles.AccountingReporting,
			evidencefabric.RetrievalHybrid,
			evidencefabric.HyDEConditional,
			[]string{"sec_statement", "sec_footnote", "sec_amendment", "accounting_update_metadata", "audit_metadata", "authorial_accounting"},
			[]string{"reported_fact", "accounting_policy", "comparability_boundary", "disclosure_interpretation"},
			[]string{"evidence.retrieve", "engine.execute"},
			true, 24, 5000,
		),
		active(
			roles.FinancialQuality,
			evidencefabric.RetrievalLexical,
			evidencefabric.HyDENone,
			[]string{"sec_statement", "sec_footnote", "sec_mda", "issuer_authorial", "calculation_receipt"},
			[]string{"reported_fact", "calculation", "financial_interpretation", "quality_boundary"},
			[]string{"evidence.retrieve", "engine.execute"},
			true, 20, 5000,
		),
		active(
			roles.EconomicsTransmission,
			evidencefabric.RetrievalHybrid,
			evidencefabric.HyDEConditional,
			[]string{"macro_observation", "macro_methodology", "industry_statistic", "research_card", "sec_segment", "historical_episode"},
			[]string{"macro_fact", "transmission_mechanism", "association", "causal_boundary"},
			[]string{"evidence.retrieve", "macro.read", "engine.execute"},
			false, 24, 5000,
		),
		active(
			roles.Valuation,
			evidencefabric.RetrievalLexical,
			evidencefabric.HyDENone,
			[]string{"sec_statement", "market_observation", "treasury_observation", "calculation_receipt", "valuation_methodology", "peer_metadata"},
			[]string{"valuation_assumption", "calculation", "market_expectation", "valuation_boundary"},
			[]string{"evidence.retrieve", "engine.execute", "market.read"},
			true, 18, 5000,
		),
		active(
			roles.MarketBehavior,
			evidencefabric.RetrievalLexical,
			evidencefabric.HyDENone,
			[]string{"market_observation", "corporate_action", "issuer_event", "finra_observation", "market_methodology"},
			[]string{"market_fact", "market_statistic", "event_association", "causal_boundary"},
			[]string{"market.read", "engine.execute"},
			true, 18, 5000,
		),
		active(
			roles.RiskContrarian,
			evidencefabric.RetrievalHybrid,
			evidencefabric.HyDEConditional,
			[]string{"sec_risk", "legal_event", "regulatory_event", "governance_event", "cyber_vulnerability", "supply_chain_context", "research_card"},
			[]string{"risk_fact", "counterevidence", "invalidation_condition", "monitoring_signal"},
			[]string{"evidence.retrieve"},
			true, 28, 4000,
		),
		active(
			roles.EvidenceCritic,
			evidencefabric.RetrievalResolution,
			evidencefabric.HyDENone,
			[]string{"source_metadata", "evidence_locator", "calculation_receipt", "rights_record", "lineage_record"},
			[]string{"provenance_check", "rights_check", "temporal_check", "claim_disposition"},
			[]string{"evidence.resolve", "receipt.replay"},
			false, 32, 4000,
		),
		none(roles.FinalResearchAnalyst),
	}
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func clone(profile evidencefabric.RetrievalProfile) evidencefabric.RetrievalProfile {
	profile.AllowedAuthorities = append([]evidencefabric.AuthorityClass(nil), profile.AllowedAuthorities...)
	profile.AllowedRights = append([]evidencefabric.RightsState(nil), profile.AllowedRights...)
	profile.AllowedSourceKinds = append([]string(nil), profile.AllowedSourceKinds...)
	profile.ClaimClasses = append([]string(nil), profile.ClaimClasses...)
	profile.ToolAllowlist = append([]string(nil), profile.ToolAllowlist...)
	return profile
}
