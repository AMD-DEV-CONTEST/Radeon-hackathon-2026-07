package releasepolicy

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/evidencefabric"
)

func TestSupportedClaimPasses(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	claim := validClaim(asOf)
	report := Default(asOf).Evaluate(claim)
	if report.Decision != Approve || len(report.Issues) != 0 {
		t.Fatalf("supported claim was not approved: %+v", report)
	}
	if err := report.Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestCriticalEvidenceAndNumericalFailuresReject(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	claim := validClaim(asOf)
	claim.Text = "Revenue was 25% higher."
	claim.NumericalRefs = nil
	claim.Evidence[0].AvailableAt = asOf.Add(time.Hour)
	claim.Evidence[0].Rights = evidencefabric.RightsRestricted
	report := Default(asOf).Evaluate(claim)
	if report.Decision != Reject {
		t.Fatalf("critical failures were not rejected: %+v", report)
	}
	requireCodes(t, report, "future_evidence", "rights_not_authorized", "unsupported_numeric_literal")
}

func TestDomainMisuseGuards(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	tests := []struct {
		name   string
		mutate func(*Claim)
		code   string
	}{
		{"causality", func(claim *Claim) { claim.Text = "The stock moved because rates changed." }, "causal_overclaim"},
		{"short volume", func(claim *Claim) {
			claim.ClaimClass = "market_fact"
			claim.Evidence[0].Authority = evidencefabric.AuthorityA2
			claim.MarketConcept = "short_sale_volume"
			claim.Text = "Short interest increased."
		}, "short_volume_interest_conflation"},
		{"IEX", func(claim *Claim) {
			claim.ClaimClass = "market_fact"
			claim.Evidence[0].Authority = evidencefabric.AuthorityA2
			claim.MarketFeed = "iex"
			claim.Text = "The whole market traded this volume."
		}, "market_feed_overclaim"},
		{"legal status", func(claim *Claim) {
			claim.ClaimClass = "legal_event"
			claim.Text = "The regulator filed a proceeding."
		}, "legal_status_missing"},
		{"CVE incident", func(claim *Claim) {
			claim.ClaimClass = "risk_fact"
			claim.Evidence[0].Authority = evidencefabric.AuthorityA0
			claim.AttributionType = "product_vulnerability"
			claim.Text = "The company suffered an incident."
			claim.MonitoringIDs = []string{"monitor-cve"}
		}, "cve_company_incident_attribution"},
		{"advice", func(claim *Claim) { claim.Text = "You should buy the shares." }, "personalized_investment_advice"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			claim := validClaim(asOf)
			test.mutate(&claim)
			report := Default(asOf).Evaluate(claim)
			if report.Decision != Reject {
				t.Fatalf("expected rejection: %+v", report)
			}
			requireCodes(t, report, test.code)
		})
	}
}

func TestContaminationAndRiskMonitoring(t *testing.T) {
	asOf := time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC)
	claim := validClaim(asOf)
	claim.ClaimClass = "risk_fact"
	claim.CompanyIDs = []string{"msft", "nvda"}
	claim.Currencies = []string{"USD", "EUR"}
	claim.Units = []string{"USD", "shares"}
	claim.PeriodKeys = []string{"FY2024", "FY2025"}
	claim.MonitoringIDs = nil
	report := Default(asOf).Evaluate(claim)
	if report.Decision != Reject {
		t.Fatalf("contamination should reject: %+v", report)
	}
	requireCodes(t, report,
		"cross_company_contamination",
		"currency_contamination",
		"unit_contamination",
		"period_contamination",
		"risk_monitoring_signal_missing",
	)
}

func validClaim(asOf time.Time) Claim {
	return Claim{
		ClaimID: "claim-1", RoleID: "accounting-reporting/v1", ClaimClass: "reported_fact",
		Text:       "Revenue increased relative to the prior aligned period.",
		CompanyIDs: []string{"sec-cik:0000789019"}, PeriodKeys: []string{"FY2025"},
		Currencies: []string{"USD"}, Units: []string{"USD"},
		Evidence: []EvidenceBinding{{
			EvidenceID: "evidence-1", Authority: evidencefabric.AuthorityA0,
			Rights: evidencefabric.RightsPublicDataReviewed, AvailableAt: asOf.Add(-time.Hour),
			CompanyID: "sec-cik:0000789019", PeriodKey: "FY2025", Currency: "USD", Unit: "USD",
		}},
		CausalClass: "association_only",
	}
}

func requireCodes(t *testing.T, report Report, expected ...string) {
	t.Helper()
	found := map[string]bool{}
	for _, issue := range report.Issues {
		found[issue.Code] = true
	}
	for _, code := range expected {
		if !found[code] {
			t.Fatalf("missing issue %q in %+v", code, report)
		}
	}
}
