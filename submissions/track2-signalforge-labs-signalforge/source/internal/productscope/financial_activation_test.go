package productscope

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
)

func TestCompanyFinancialActivationReleasesAlignedReceiptsAndAbstainsOtherwise(t *testing.T) {
	asOf := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	companyID := "sec-cik:0000789019"
	annual := func(metric, value string, year int) data.NormalizedMetric {
		start := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
		end := time.Date(year, 12, 31, 0, 0, 0, 0, time.UTC)
		return data.NormalizedMetric{
			MetricID: "metric-" + metric + value, CompanyID: companyID, CanonicalMetric: metric,
			PeriodStart: start, PeriodEnd: end, PeriodType: "duration", Value: value,
			Unit: "USD", Currency: "USD", SourceFactIDs: []string{"fact-" + metric + value},
			TransformationID: "normalize/v1", NormalizationPolicy: "point-in-time/v1",
			ComparabilityStatus: "standardized", SourceAvailableAt: end.Add(60 * 24 * time.Hour),
			ComputedAt: asOf,
		}
	}
	instant := func(metric, value string) data.NormalizedMetric {
		end := time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC)
		item := annual(metric, value, 2025)
		item.PeriodStart, item.PeriodEnd, item.PeriodType = end, end, "instant"
		return item
	}
	metrics := []data.NormalizedMetric{
		annual("revenue", "100", 2024), annual("revenue", "120", 2025),
		annual("operating_income", "24", 2025), annual("operating_cash_flow", "30", 2025),
		annual("capital_expenditure", "10", 2025), annual("net_income", "20", 2025),
		instant("total_assets", "100"), instant("total_liabilities", "60"), instant("stockholders_equity", "40"),
	}
	facts := map[string]data.ReportedFact{}
	for _, metric := range metrics {
		fact := data.ReportedFact{
			FactID: metric.SourceFactIDs[0], CompanyID: companyID, Value: metric.Value,
			Unit: metric.Unit, FormType: "10-K", AvailableAt: metric.SourceAvailableAt,
			RetrievedAt: metric.ComputedAt,
		}
		if metric.CanonicalMetric == "capital_expenditure" {
			fact.Concept = "PaymentsToAcquirePropertyPlantAndEquipment"
		}
		if metric.PeriodType == "instant" {
			value := metric.PeriodEnd
			fact.InstantDate = &value
		} else {
			start, end := metric.PeriodStart, metric.PeriodEnd
			fact.StartDate, fact.EndDate = &start, &end
		}
		facts[fact.FactID] = fact
	}
	report, err := BuildCompanyFinancialActivation(companyID, metrics, facts, asOf, "test-commit")
	if err != nil {
		t.Fatal(err)
	}
	if len(report.Receipts) != len(companyOperationSpecs) {
		t.Fatalf("receipts = %d, want %d; abstentions=%+v", len(report.Receipts), len(companyOperationSpecs), report.Abstentions)
	}
	if len(report.Abstentions) != len(unavailableCompanyOperations) {
		t.Fatalf("abstentions = %d, want %d", len(report.Abstentions), len(unavailableCompanyOperations))
	}
}

func TestCompanyFinancialActivationRejectsAliasesAndLookAhead(t *testing.T) {
	asOf := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	metric := data.NormalizedMetric{
		MetricID: "metric-alias", CompanyID: "sec-cik:0000789019", CanonicalMetric: "revenue",
		PeriodStart: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC),
		PeriodEnd:   time.Date(2025, 12, 31, 0, 0, 0, 0, time.UTC), PeriodType: "duration",
		Value: "100", Unit: "USD", Currency: "USD", SourceFactIDs: []string{"fact-alias"},
		TransformationID: "normalize/v1", NormalizationPolicy: "point-in-time/v1",
		ComparabilityStatus: "concept_alias", SourceAvailableAt: asOf.Add(-time.Hour),
		ComputedAt: asOf,
	}
	report, err := BuildCompanyFinancialActivation(metric.CompanyID, []data.NormalizedMetric{metric}, nil, asOf, "test-commit")
	if err != nil {
		t.Fatal(err)
	}
	if report.Excluded["unreviewed_semantic_mapping"] != 1 || len(report.Receipts) != 0 {
		t.Fatalf("alias was not excluded: %+v", report)
	}
}

func TestCompanyFinancialActivationValidationRejectsUnauthorizedSourceAuthority(t *testing.T) {
	report := validFinancialActivationForValidation(t)
	report.SourceConcepts["capital_expenditure"] = []string{"PropertyPlantAndEquipment"}
	report.ReportSHA256 = financialActivationHashForTest(t, report)
	if err := ValidateCompanyFinancialActivation(report); err == nil {
		t.Fatal("expected unauthorized capex concept rejection")
	}

	report = validFinancialActivationForValidation(t)
	report.SourceForms["revenue"] = []string{"DEF 14A"}
	report.ReportSHA256 = financialActivationHashForTest(t, report)
	if err := ValidateCompanyFinancialActivation(report); err == nil {
		t.Fatal("expected non-periodic form rejection")
	}
}

func validFinancialActivationForValidation(t *testing.T) CompanyFinancialActivation {
	t.Helper()
	report, err := BuildCompanyFinancialActivation(
		"sec-cik:0000789019", nil, nil,
		time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC), "test-commit",
	)
	if err != nil {
		t.Fatal(err)
	}
	return report
}

func financialActivationHashForTest(t *testing.T, report CompanyFinancialActivation) string {
	t.Helper()
	hash, err := companyFinancialActivationHash(report)
	if err != nil {
		t.Fatal(err)
	}
	return hash
}
