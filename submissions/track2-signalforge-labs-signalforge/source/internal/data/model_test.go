package data

import (
	"testing"
	"time"
)

func TestGoldenCompaniesUseCanonicalCIKs(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	for _, company := range []Company{
		{CompanyID: "sec-cik:0000789019", CIK: "0000789019", LegalName: "Microsoft Corporation", Status: "active", ValidFrom: now, RetrievedAt: now, SourceRecordIDs: []string{"sec:submissions:0000789019"}},
		{CompanyID: "sec-cik:0001045810", CIK: "0001045810", LegalName: "NVIDIA Corporation", Status: "active", ValidFrom: now, RetrievedAt: now, SourceRecordIDs: []string{"sec:submissions:0001045810"}},
	} {
		if err := ValidateCompany(company); err != nil {
			t.Fatalf("golden company %s is invalid: %v", company.LegalName, err)
		}
	}
}

func TestCanonicalCIKPadsWithoutChangingIdentity(t *testing.T) {
	got, err := CanonicalCIK("789019")
	if err != nil {
		t.Fatalf("canonicalize CIK: %v", err)
	}
	if got != "0000789019" {
		t.Fatalf("expected Microsoft CIK, got %q", got)
	}
	if _, err := CanonicalCIK("CIK789019"); err == nil {
		t.Fatal("non-numeric CIK must be rejected")
	}
}

func TestFutureEvidenceIsUnavailableInHistoricalReplay(t *testing.T) {
	published := time.Date(2026, 7, 20, 18, 0, 0, 0, time.UTC)
	availability := Availability{ObservedAt: published.AddDate(0, -3, 0), AvailableAt: published, RetrievedAt: published.Add(time.Hour)}
	if IsAvailableAsOf(availability, published.Add(-time.Second)) {
		t.Fatal("future evidence leaked into historical replay")
	}
	if !IsAvailableAsOf(availability, published) {
		t.Fatal("evidence should become available at its publication time")
	}
}

func TestFilingDateDoesNotOverrideExactAcceptanceTimestamp(t *testing.T) {
	filedDate := time.Date(2026, 3, 24, 0, 0, 0, 0, time.UTC)
	accepted := time.Date(2026, 3, 23, 21, 59, 18, 0, time.UTC)
	filing := Filing{
		FilingID: "sec-filing:0001193125-26-120090", CompanyID: "sec-cik:0000789019",
		AccessionNumber: "0001193125-26-120090", FormType: "11-K", ReportPeriodEnd: filedDate,
		FiledAt: filedDate, AcceptedAt: accepted, PublishedAt: accepted,
		SourceRecordID: "record-1", SourceURI: "https://data.sec.gov/submissions/CIK0000789019.json",
		ContentSHA256: "hash", RetrievedAt: filedDate.Add(time.Hour), ExtractorVersion: "sec-json/v1",
	}
	if err := ValidateFiling(filing); err != nil {
		t.Fatalf("exact acceptance timestamp may fall on the prior UTC date: %v", err)
	}
}

func TestReportedFactRequiresExclusivePeriodShape(t *testing.T) {
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(2026, 3, 31, 0, 0, 0, 0, time.UTC)
	fact := ReportedFact{
		FactID: "fact-1", FilingID: "filing-1", CompanyID: "sec-cik:0000789019",
		Taxonomy: "us-gaap", Concept: "RevenueFromContractWithCustomerExcludingAssessedTax",
		Value: "100", Unit: "USD", FormType: "10-Q", SourceContextID: "context-1", SourceLocator: "xbrl:context-1",
		StartDate: &start, EndDate: &end, AvailableAt: end.AddDate(0, 1, 0), RetrievedAt: end.AddDate(0, 1, 1),
	}
	if err := ValidateReportedFact(fact); err != nil {
		t.Fatalf("duration fact should pass: %v", err)
	}
	fact.InstantDate = &end
	if err := ValidateReportedFact(fact); err == nil {
		t.Fatal("fact cannot be both duration and instant")
	}
}

func TestNormalizedMetricRequiresReplayLineage(t *testing.T) {
	start := time.Date(2025, 7, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)
	metric := NormalizedMetric{
		MetricID: "metric-1", CompanyID: "sec-cik:0000789019", CanonicalMetric: "revenue",
		PeriodStart: start, PeriodEnd: end, PeriodType: "fiscal_year", Value: "100", Unit: "USD", Currency: "USD",
		TransformationID: "normalize.revenue/v1", NormalizationPolicy: "us-gaap-company-facts/v1",
		ComparabilityStatus: "comparable", SourceAvailableAt: end.AddDate(0, 1, 0), ComputedAt: end.AddDate(0, 1, 1),
	}
	if err := ValidateNormalizedMetric(metric); err == nil {
		t.Fatal("metric without source facts must be rejected")
	}
	metric.SourceFactIDs = []string{"fact-1"}
	if err := ValidateNormalizedMetric(metric); err != nil {
		t.Fatalf("lineage-complete metric should pass: %v", err)
	}
}
