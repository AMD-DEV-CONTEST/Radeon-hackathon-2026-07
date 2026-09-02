package entityresolver

import "testing"

func TestDefaultRegistryCoversTechnologyTwenty(t *testing.T) {
	registry := DefaultRegistry()
	if got := len(registry.Issuers()); got != 20 {
		t.Fatalf("issuer coverage got %d want 20", got)
	}
	seen := map[string]bool{}
	for _, issuer := range registry.Issuers() {
		if seen[issuer.CompanyID] || issuer.CIK == "" || len(issuer.Securities) == 0 {
			t.Fatalf("invalid issuer %+v", issuer)
		}
		seen[issuer.CompanyID] = true
	}
}

func TestIssuerAndSecurityRemainDistinct(t *testing.T) {
	registry := DefaultRegistry()
	goog := registry.ResolveMention("GOOG")
	googl := registry.ResolveMention("GOOGL")
	if !goog.Resolved || !googl.Resolved || goog.CompanyID != googl.CompanyID ||
		goog.SecurityID == googl.SecurityID || goog.Ticker == googl.Ticker {
		t.Fatalf("Alphabet securities were collapsed: GOOG=%+v GOOGL=%+v", goog, googl)
	}
}

func TestExactHistoricalAndBoundedFuzzyResolution(t *testing.T) {
	registry := DefaultRegistry()
	for _, test := range []struct {
		mention   string
		companyID string
		matchKind string
		review    bool
	}{
		{"Microsoft", "sec-cik:0000789019", "name_exact", false},
		{"Facebook", "sec-cik:0001326801", "name_exact", false},
		{"Microsft", "sec-cik:0000789019", "name_fuzzy_bounded", true},
		{"MSFT", "sec-cik:0000789019", "ticker_exact", false},
	} {
		result := registry.ResolveMention(test.mention)
		if !result.Resolved || result.CompanyID != test.companyID ||
			result.MatchKind != test.matchKind || result.NeedsReview != test.review {
			t.Fatalf("%q resolved unexpectedly: %+v", test.mention, result)
		}
	}
	if result := registry.ResolveMention("MSF"); result.Resolved {
		t.Fatalf("ticker fuzzy matching must remain disabled: %+v", result)
	}
}

func TestResolveTextDeduplicatesIssuerButPreservesSeparateSecurities(t *testing.T) {
	results := DefaultRegistry().ResolveText("Compare Alphabet, GOOG, and GOOGL with Microsoft MSFT.")
	companies := map[string]int{}
	securities := map[string]bool{}
	for _, result := range results {
		companies[result.CompanyID]++
		if result.SecurityID != "" {
			securities[result.SecurityID] = true
		}
	}
	if companies["sec-cik:0001652044"] != 3 || companies["sec-cik:0000789019"] != 2 {
		t.Fatalf("issuer/security mentions were not preserved: %+v", results)
	}
	if !securities["us-equity:GOOG"] || !securities["us-equity:GOOGL"] || !securities["us-equity:MSFT"] {
		t.Fatalf("security identities missing: %+v", results)
	}
}
