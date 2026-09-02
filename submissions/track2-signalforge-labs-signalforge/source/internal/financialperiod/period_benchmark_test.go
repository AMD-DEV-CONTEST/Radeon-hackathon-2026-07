package financialperiod

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func BenchmarkTrailingTwelveMonths(b *testing.B) {
	annual := durationObservation("revenue", "200", "FY2024", KindAnnual, "2024-01-01", "2024-12-31", "2025-02-01")
	current := durationObservation("revenue", "180", "YTD2025Q3", KindYearToDate, "2025-01-01", "2025-09-30", "2025-10-25")
	prior := durationObservation("revenue", "150", "YTD2024Q3", KindYearToDate, "2024-01-01", "2024-09-30", "2024-10-25")
	cutoff := date("2025-10-31")
	b.ReportAllocs()
	for range b.N {
		if _, err := TrailingTwelveMonths(annual, current, prior, cutoff, cutoff); err != nil {
			b.Fatal(err)
		}
	}
}

func FuzzCommonSizeRejectsNonPositiveDenominator(f *testing.F) {
	f.Add("0")
	f.Add("-100")
	f.Fuzz(func(t *testing.T, raw string) {
		value, err := numeric.ParseDecimal(raw)
		if err != nil {
			t.Skip()
		}
		revenue := durationObservation("revenue", "1", "FY2025", KindAnnual, "2025-01-01", "2025-12-31", "2026-02-01")
		revenue.Value = value
		profit := durationObservation("profit", "1", "FY2025", KindAnnual, "2025-01-01", "2025-12-31", "2026-02-01")
		_, commonSizeErr := CommonSize([]Observation{revenue, profit}, "revenue", date("2026-03-01"))
		if value.String() == "0" || value.String()[0] == '-' {
			if commonSizeErr == nil {
				t.Fatal("non-positive common-size denominator must fail")
			}
		}
	})
}
