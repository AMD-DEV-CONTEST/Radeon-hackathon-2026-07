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

func filingFixture(id, accession, form string, published time.Time) Filing {
	return Filing{
		FilingID: id, CompanyID: "sec-cik:0000789019", AccessionNumber: accession, FormType: form,
		ReportPeriodEnd: time.Date(2026, 3, 31, 0, 0, 0, 0, time.UTC), FiledAt: published,
		AcceptedAt: published, PublishedAt: published, SourceRecordID: "record-" + id,
		SourceURI: "https://www.sec.gov/Archives/" + id, ContentSHA256: "sha-" + id,
		RetrievedAt: published.Add(time.Hour), ExtractorVersion: "sec/v1",
	}
}

func TestFilingSetPreservesAmendmentSupersessionAsOf(t *testing.T) {
	baseTime := time.Date(2026, 4, 20, 12, 0, 0, 0, time.UTC)
	base := filingFixture("filing-base", "0000789019-26-000001", "10-Q", baseTime)
	amendment := filingFixture("filing-amended", "0000789019-26-000002", "10-Q/A", baseTime.Add(24*time.Hour))
	amendment.AmendsFilingID = base.FilingID
	filings := []Filing{base, amendment}
	if err := ValidateFilingSet(filings); err != nil {
		t.Fatal(err)
	}
	active, err := ActiveFilingsAsOf(filings, baseTime.Add(time.Hour))
	if err != nil || len(active) != 1 || active[0].FilingID != base.FilingID {
		t.Fatalf("historical as-of selected wrong filing: active=%+v err=%v", active, err)
	}
	active, err = ActiveFilingsAsOf(filings, amendment.PublishedAt)
	if err != nil || len(active) != 1 || active[0].FilingID != amendment.FilingID {
		t.Fatalf("amendment did not supersede base: active=%+v err=%v", active, err)
	}
}

func TestFilingSetRejectsUnlinkedDuplicateAndCrossCompanyAmendment(t *testing.T) {
	baseTime := time.Date(2026, 4, 20, 12, 0, 0, 0, time.UTC)
	base := filingFixture("filing-base", "0000789019-26-000001", "10-Q", baseTime)
	duplicate := filingFixture("filing-duplicate", "0000789019-26-000002", "10-Q", baseTime.Add(time.Hour))
	if err := ValidateFilingSet([]Filing{base, duplicate}); err == nil {
		t.Fatal("unlinked duplicate period/form was accepted")
	}
	amendment := duplicate
	amendment.FormType = "10-Q/A"
	amendment.AmendsFilingID = base.FilingID
	amendment.CompanyID = "sec-cik:0001045810"
	if err := ValidateFilingSet([]Filing{base, amendment}); err == nil {
		t.Fatal("cross-company amendment was accepted")
	}
}

func TestReportedFactSetRejectsDuplicateAndUnitConflictButPreservesSegments(t *testing.T) {
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(2026, 3, 31, 0, 0, 0, 0, time.UTC)
	base := ReportedFact{
		FactID: "fact-cloud", FilingID: "filing-1", CompanyID: "sec-cik:0000789019", Taxonomy: "us-gaap",
		Concept: "Revenue", Value: "100", Unit: "USD", StartDate: &start, EndDate: &end, FormType: "10-Q",
		Dimensions: map[string]string{"segment": "cloud"}, SourceContextID: "context-cloud", SourceLocator: "xbrl:cloud",
		AvailableAt: end.Add(30 * 24 * time.Hour), RetrievedAt: end.Add(31 * 24 * time.Hour),
	}
	otherSegment := base
	otherSegment.FactID, otherSegment.SourceContextID = "fact-devices", "context-devices"
	otherSegment.Dimensions = map[string]string{"segment": "devices"}
	if err := ValidateReportedFactSet([]ReportedFact{base, otherSegment}); err != nil {
		t.Fatalf("distinct segment facts were rejected: %v", err)
	}
	duplicate := base
	duplicate.FactID = "fact-duplicate"
	if err := ValidateReportedFactSet([]ReportedFact{base, duplicate}); err == nil {
		t.Fatal("duplicate fact identity was accepted")
	}
	conflict := base
	conflict.FactID, conflict.Unit = "fact-conflict", "shares"
	if err := ValidateReportedFactSet([]ReportedFact{base, conflict}); err == nil {
		t.Fatal("same concept/period/dimension with conflicting unit was accepted")
	}
}
