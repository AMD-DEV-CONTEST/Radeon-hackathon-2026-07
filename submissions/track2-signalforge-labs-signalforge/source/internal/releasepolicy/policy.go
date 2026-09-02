package releasepolicy

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/evidencefabric"
)

type Decision string

const (
	Approve Decision = "approve"
	Narrow  Decision = "narrow"
	Repair  Decision = "repair"
	Reject  Decision = "reject"
)

type Claim struct {
	ClaimID         string            `json:"claim_id"`
	RoleID          string            `json:"role_id"`
	ClaimClass      string            `json:"claim_class"`
	Text            string            `json:"text"`
	CompanyIDs      []string          `json:"company_ids,omitempty"`
	PeriodKeys      []string          `json:"period_keys,omitempty"`
	Currencies      []string          `json:"currencies,omitempty"`
	Units           []string          `json:"units,omitempty"`
	Evidence        []EvidenceBinding `json:"evidence"`
	ReceiptIDs      []string          `json:"receipt_ids,omitempty"`
	NumericalRefs   []string          `json:"numerical_refs,omitempty"`
	CausalClass     string            `json:"causal_class"`
	LegalStatus     string            `json:"legal_status,omitempty"`
	MarketFeed      string            `json:"market_feed,omitempty"`
	MarketConcept   string            `json:"market_concept,omitempty"`
	AttributionType string            `json:"attribution_type,omitempty"`
	AssumptionIDs   []string          `json:"assumption_ids,omitempty"`
	MonitoringIDs   []string          `json:"monitoring_ids,omitempty"`
}

type EvidenceBinding struct {
	EvidenceID  string                        `json:"evidence_id"`
	Authority   evidencefabric.AuthorityClass `json:"authority"`
	Rights      evidencefabric.RightsState    `json:"rights_state"`
	AvailableAt time.Time                     `json:"available_at"`
	CompanyID   string                        `json:"company_id,omitempty"`
	PeriodKey   string                        `json:"period_key,omitempty"`
	Currency    string                        `json:"currency,omitempty"`
	Unit        string                        `json:"unit,omitempty"`
}

type Issue struct {
	Code     string   `json:"code"`
	Severity string   `json:"severity"`
	ClaimID  string   `json:"claim_id"`
	Fields   []string `json:"fields,omitempty"`
}

type Report struct {
	Decision Decision `json:"decision"`
	Issues   []Issue  `json:"issues,omitempty"`
}

type Policy struct {
	AsOf             time.Time
	MinimumAuthority map[string]evidencefabric.AuthorityClass
}

var numericLiteral = regexp.MustCompile(`(?:^|[^A-Za-z])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?`)

func Default(asOf time.Time) Policy {
	return Policy{
		AsOf: asOf,
		MinimumAuthority: map[string]evidencefabric.AuthorityClass{
			"reported_fact":       evidencefabric.AuthorityA0,
			"accounting_policy":   evidencefabric.AuthorityA0,
			"market_fact":         evidencefabric.AuthorityA2,
			"macro_fact":          evidencefabric.AuthorityA2,
			"legal_event":         evidencefabric.AuthorityA0,
			"issuer_claim":        evidencefabric.AuthorityA1,
			"research_hypothesis": evidencefabric.AuthorityA3,
		},
	}
}

func (policy Policy) Evaluate(claim Claim) Report {
	issues := []Issue{}
	add := func(code, severity string, fields ...string) {
		issues = append(issues, Issue{Code: code, Severity: severity, ClaimID: claim.ClaimID, Fields: fields})
	}
	if claim.ClaimID == "" || claim.RoleID == "" || claim.ClaimClass == "" || strings.TrimSpace(claim.Text) == "" {
		add("claim_identity_invalid", "critical")
	}
	if len(claim.Evidence) == 0 {
		add("evidence_missing", "critical", "evidence")
	}
	for _, binding := range claim.Evidence {
		if binding.EvidenceID == "" {
			add("evidence_id_missing", "critical", "evidence")
		}
		if binding.AvailableAt.After(policy.AsOf) {
			add("future_evidence", "critical", binding.EvidenceID)
		}
		if binding.Rights == evidencefabric.RightsRestricted ||
			binding.Rights == evidencefabric.RightsQuarantined {
			add("rights_not_authorized", "critical", binding.EvidenceID)
		}
		if minimum, ok := policy.MinimumAuthority[claim.ClaimClass]; ok &&
			authorityRank(binding.Authority) > authorityRank(minimum) {
			add("authority_below_claim_minimum", "critical", binding.EvidenceID)
		}
	}
	if numericLiteral.MatchString(claim.Text) && len(claim.NumericalRefs) == 0 {
		add("unsupported_numeric_literal", "critical", "text", "numerical_refs")
	}
	if len(uniqueNonEmpty(claim.CompanyIDs)) > 1 && claim.ClaimClass != "comparison" {
		add("cross_company_contamination", "critical", "company_ids")
	}
	if inconsistent(claim.Currencies) {
		add("currency_contamination", "critical", "currencies")
	}
	if inconsistent(claim.Units) {
		add("unit_contamination", "critical", "units")
	}
	if inconsistent(claim.PeriodKeys) && claim.ClaimClass != "comparison" {
		add("period_contamination", "critical", "period_keys")
	}
	lower := strings.ToLower(claim.Text)
	if containsAny(lower, "will definitely", "guaranteed", "certain to", "must happen") {
		add("hidden_certainty", "critical", "text")
	}
	if containsAny(lower, "you should buy", "you should sell", "invest all", "allocate your portfolio") {
		add("personalized_investment_advice", "critical", "text")
	}
	if causalLanguage(lower) && claim.CausalClass != "supported_causal_design" {
		add("causal_overclaim", "critical", "causal_class")
	}
	if claim.MarketConcept == "short_sale_volume" &&
		containsAny(lower, "short interest", "shares short") {
		add("short_volume_interest_conflation", "critical", "market_concept")
	}
	if claim.MarketFeed == "iex" && containsAny(lower, "whole market", "consolidated market", "full sip") {
		add("market_feed_overclaim", "critical", "market_feed")
	}
	if claim.ClaimClass == "legal_event" && strings.TrimSpace(claim.LegalStatus) == "" {
		add("legal_status_missing", "critical", "legal_status")
	}
	if claim.AttributionType == "product_vulnerability" &&
		containsAny(lower, "company was breached", "company suffered an incident", "company attack") {
		add("cve_company_incident_attribution", "critical", "attribution_type")
	}
	if claim.ClaimClass == "risk_fact" && len(claim.MonitoringIDs) == 0 {
		add("risk_monitoring_signal_missing", "repairable", "monitoring_ids")
	}
	if claim.ClaimClass == "valuation_assumption" && len(claim.AssumptionIDs) == 0 {
		add("valuation_assumption_unregistered", "critical", "assumption_ids")
	}
	sort.Slice(issues, func(i, j int) bool {
		if issues[i].Severity != issues[j].Severity {
			return issues[i].Severity < issues[j].Severity
		}
		return issues[i].Code < issues[j].Code
	})
	return Report{Decision: decide(issues), Issues: issues}
}

func (report Report) Validate() error {
	switch report.Decision {
	case Approve, Narrow, Repair, Reject:
	default:
		return fmt.Errorf("invalid release decision %q", report.Decision)
	}
	if report.Decision == Approve && len(report.Issues) > 0 {
		return errors.New("approved report cannot contain issues")
	}
	if report.Decision != Approve && len(report.Issues) == 0 {
		return errors.New("non-approved report requires an issue")
	}
	return nil
}

func decide(issues []Issue) Decision {
	if len(issues) == 0 {
		return Approve
	}
	for _, issue := range issues {
		if issue.Severity == "critical" {
			return Reject
		}
	}
	return Repair
}

func authorityRank(value evidencefabric.AuthorityClass) int {
	switch value {
	case evidencefabric.AuthorityA0:
		return 0
	case evidencefabric.AuthorityA1:
		return 1
	case evidencefabric.AuthorityA2:
		return 2
	case evidencefabric.AuthorityA3:
		return 3
	case evidencefabric.AuthorityA4:
		return 4
	case evidencefabric.AuthorityA5:
		return 5
	default:
		return 99
	}
}

func inconsistent(values []string) bool {
	return len(uniqueNonEmpty(values)) > 1
}

func uniqueNonEmpty(values []string) []string {
	seen := map[string]bool{}
	result := []string{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}

func causalLanguage(value string) bool {
	return containsAny(value,
		"caused ",
		"causes ",
		"because of ",
		"led to ",
		"drove the stock ",
		"stock moved because ",
	)
}

func containsAny(value string, candidates ...string) bool {
	for _, candidate := range candidates {
		if strings.Contains(value, candidate) {
			return true
		}
	}
	return false
}
