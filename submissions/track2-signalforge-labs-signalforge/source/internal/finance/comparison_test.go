package finance

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func TestComparisonAndSensitivityGoldenCases(t *testing.T) {
	comparison, err := PeriodAligned([]ComparableMetric{
		{Company: "A", Value: numeric.MustDecimal("10"), Period: "FY2025", Unit: "currency", Currency: "USD"},
		{Company: "B", Value: numeric.MustDecimal("12"), Period: "FY2025", Unit: "currency", Currency: "USD"},
	}, "exact")
	if err != nil || !comparison.Comparable || len(comparison.Warnings) != 0 {
		t.Fatalf("unexpected comparison %+v: %v", comparison, err)
	}

	grid, err := DCFGrid(
		[]numeric.Decimal{numeric.MustDecimal("10"), numeric.MustDecimal("11"), numeric.MustDecimal("12")},
		[]numeric.Decimal{numeric.MustDecimal("0.09"), numeric.MustDecimal("0.10")},
		[]numeric.Decimal{numeric.MustDecimal("0.02"), numeric.MustDecimal("0.03")},
	)
	if err != nil {
		t.Fatal(err)
	}
	if grid.Rows != 2 || grid.Columns != 2 || !grid.MonotonicDiscountRate || !grid.MonotonicTerminalGrowth {
		t.Fatalf("unexpected grid %+v", grid)
	}
}

func TestComparisonReportsIncompatibility(t *testing.T) {
	comparison, err := PeriodAligned([]ComparableMetric{
		{Company: "A", Value: one, Period: "FY2025", Unit: "currency", Currency: "USD"},
		{Company: "B", Value: one, Period: "Q1-2026", Unit: "ratio"},
	}, "exact")
	if err != nil {
		t.Fatal(err)
	}
	if comparison.Comparable || len(comparison.Warnings) != 3 {
		t.Fatalf("expected three incompatibilities, got %+v", comparison)
	}
}

func BenchmarkFCFFDCF(b *testing.B) {
	forecast := []numeric.Decimal{numeric.MustDecimal("10"), numeric.MustDecimal("11"), numeric.MustDecimal("12"), numeric.MustDecimal("13"), numeric.MustDecimal("14")}
	rate, growth := numeric.MustDecimal("0.10"), numeric.MustDecimal("0.03")
	for index := 0; index < b.N; index++ {
		if _, err := FCFFDCF(forecast, rate, growth); err != nil {
			b.Fatal(err)
		}
	}
}
