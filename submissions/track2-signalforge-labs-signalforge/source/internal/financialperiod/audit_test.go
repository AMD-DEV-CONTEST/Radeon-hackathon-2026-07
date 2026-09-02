package financialperiod

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func annualAuditObservation(metric string, year int, value, source string) Observation {
	start := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
	return Observation{
		MetricID: metric, CompanyID: "sec-cik:0000789019", Class: ClassReported,
		Value: numeric.MustDecimal(value), Unit: "currency", Currency: "USD",
		Period:      Period{Kind: KindAnnual, Start: &start, End: time.Date(year, 12, 31, 0, 0, 0, 0, time.UTC), FiscalYear: year, Label: "FY" + time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC).Format("2006")},
		AvailableAt: time.Date(year+1, 2, 1, 0, 0, 0, 0, time.UTC), SourceFactIDs: []string{source},
		SignPolicy: SignPreserve,
	}
}

func TestAuditFactsDetectsMissingDuplicateConflictAndRestatement(t *testing.T) {
	cutoff := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	first := annualAuditObservation("revenue", 2024, "100", "fact-a")
	duplicate := annualAuditObservation("revenue", 2024, "100", "fact-b")
	conflict := annualAuditObservation("operating_income", 2024, "20", "fact-c")
	conflict2 := annualAuditObservation("operating_income", 2024, "21", "fact-d")
	conflict2.AmendmentChain = []string{"10-k", "10-k-a"}
	audit, err := AuditFacts([]Observation{first, duplicate, conflict, conflict2}, []string{"revenue", "operating_income", "cash"}, cutoff)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[FactIssueCode]int{}
	for _, issue := range audit.Issues {
		counts[issue.Code]++
	}
	for _, code := range []FactIssueCode{IssueMissingComponent, IssueDuplicateFact, IssueConflictingConcept, IssueRestatedObservation} {
		if counts[code] != 1 {
			t.Fatalf("expected one %s issue, got %+v", code, counts)
		}
	}
	if audit.Complete {
		t.Fatal("defective population must not be complete")
	}
}

func TestAnnualWindowRequiresSupportedContiguousPopulation(t *testing.T) {
	cutoff := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	values := []Observation{
		annualAuditObservation("revenue", 2022, "80", "fact-2022"),
		annualAuditObservation("revenue", 2023, "90", "fact-2023"),
		annualAuditObservation("revenue", 2024, "100", "fact-2024"),
	}
	window, err := AnnualWindow(values, 3, cutoff)
	if err != nil || window.Years != 3 || len(window.Observations) != 3 {
		t.Fatalf("unexpected window %+v: %v", window, err)
	}
	values[1].Period.FiscalYear = 2024
	if _, err := AnnualWindow(values, 3, cutoff); err == nil {
		t.Fatal("duplicate or non-contiguous fiscal years must fail closed")
	}
	if _, err := AnnualWindow(values[:2], 3, cutoff); err == nil {
		t.Fatal("insufficient history must fail closed")
	}
}
