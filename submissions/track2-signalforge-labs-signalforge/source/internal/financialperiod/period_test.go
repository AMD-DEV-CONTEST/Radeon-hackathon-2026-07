package financialperiod

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func date(value string) time.Time {
	parsed, err := time.Parse("2006-01-02", value)
	if err != nil {
		panic(err)
	}
	return parsed
}

func durationObservation(metric, value, label string, kind Kind, start, end, available string) Observation {
	periodStart := date(start)
	return Observation{
		MetricID: metric, CompanyID: "company-msft", Class: ClassReported, Value: numeric.MustDecimal(value), Unit: "currency", Currency: "USD",
		Period: Period{Kind: kind, Start: &periodStart, End: date(end), Label: label}, AvailableAt: date(available), SourceFactIDs: []string{"fact-" + label},
	}
}

func TestSignNormalizationPreservesReportedValueAndPolicy(t *testing.T) {
	reported := durationObservation("capital_expenditure", "-40", "FY2025", KindAnnual, "2025-01-01", "2025-12-31", "2026-02-01")
	normalized, err := NormalizeReportedSign(reported, SignPositiveUse, date("2026-03-01"))
	if err != nil {
		t.Fatal(err)
	}
	if normalized.Value.String() != "40" || normalized.RawReportedValue == nil || normalized.RawReportedValue.String() != "-40" {
		t.Fatalf("reported sign was not preserved: %+v", normalized)
	}
	if normalized.Class != ClassNormalized || normalized.SignPolicy != SignPositiveUse || normalized.TransformationID != "cash-outflow-positive-use/v1" {
		t.Fatalf("normalization lineage is incomplete: %+v", normalized)
	}
}

func TestTrailingTwelveMonthsUsesPointInTimeInputs(t *testing.T) {
	annual := durationObservation("revenue", "200", "FY2024", KindAnnual, "2024-01-01", "2024-12-31", "2025-02-01")
	current := durationObservation("revenue", "180", "YTD2025Q3", KindYearToDate, "2025-01-01", "2025-09-30", "2025-10-25")
	prior := durationObservation("revenue", "150", "YTD2024Q3", KindYearToDate, "2024-01-01", "2024-09-30", "2024-10-25")

	result, err := TrailingTwelveMonths(annual, current, prior, date("2025-10-31"), date("2025-10-31"))
	if err != nil {
		t.Fatal(err)
	}
	if result.Value.String() != "230" || result.Period.Kind != KindTTM || result.Period.Start.Format("2006-01-02") != "2024-10-01" {
		t.Fatalf("unexpected TTM result %+v", result)
	}
	if result.AvailableAt != current.AvailableAt || len(result.SourceFactIDs) != 3 {
		t.Fatalf("lineage not preserved: %+v", result)
	}
}

func TestTrailingTwelveMonthsRejectsLookAheadAndMisalignment(t *testing.T) {
	annual := durationObservation("revenue", "200", "FY2024", KindAnnual, "2024-01-01", "2024-12-31", "2025-02-01")
	current := durationObservation("revenue", "180", "YTD2025Q3", KindYearToDate, "2025-01-01", "2025-09-30", "2025-10-25")
	prior := durationObservation("revenue", "150", "YTD2024Q2", KindYearToDate, "2024-01-01", "2024-06-30", "2024-07-25")
	if _, err := TrailingTwelveMonths(annual, current, prior, date("2025-10-31"), date("2025-10-31")); err == nil {
		t.Fatal("misaligned YTD periods must fail")
	}
	prior.Period.End = date("2024-09-30")
	if _, err := TrailingTwelveMonths(annual, current, prior, date("2025-01-01"), date("2025-10-31")); err == nil {
		t.Fatal("future observations must fail")
	}
}

func TestCommonSizeRequiresExactPeriodAndLineage(t *testing.T) {
	revenue := durationObservation("revenue", "100", "FY2025", KindAnnual, "2025-01-01", "2025-12-31", "2026-02-01")
	grossProfit := durationObservation("gross_profit", "60", "FY2025", KindAnnual, "2025-01-01", "2025-12-31", "2026-02-01")
	result, err := CommonSize([]Observation{revenue, grossProfit}, "revenue", date("2026-03-01"))
	if err != nil {
		t.Fatal(err)
	}
	if len(result) != 2 || result[0].MetricID != "gross_profit" || result[0].Ratio.String() != "0.6" {
		t.Fatalf("unexpected common-size result %+v", result)
	}
	grossProfit.Period.End = date("2025-09-30")
	if _, err := CommonSize([]Observation{revenue, grossProfit}, "revenue", date("2026-03-01")); err == nil {
		t.Fatal("period mismatch must fail")
	}
}

func TestDescribeTrendReleasesOnlyDeterministicDirection(t *testing.T) {
	values := []Observation{
		durationObservation("operating_margin", "0.20", "FY2023", KindAnnual, "2023-01-01", "2023-12-31", "2024-02-01"),
		durationObservation("operating_margin", "0.22", "FY2024", KindAnnual, "2024-01-01", "2024-12-31", "2025-02-01"),
		durationObservation("operating_margin", "0.25", "FY2025", KindAnnual, "2025-01-01", "2025-12-31", "2026-02-01"),
	}
	for index := range values {
		values[index].Unit = "ratio"
		values[index].Currency = ""
	}
	descriptor, err := DescribeTrend(values, date("2026-03-01"), numeric.MustDecimal("0.001"))
	if err != nil {
		t.Fatal(err)
	}
	if descriptor.Direction != TrendIncreasing || descriptor.PositiveChanges != 2 || descriptor.Observations != 3 {
		t.Fatalf("unexpected trend %+v", descriptor)
	}
}
