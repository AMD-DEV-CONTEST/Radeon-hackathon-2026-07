package finance

import (
	"math"
	"testing"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func d(value string) numeric.Decimal { return numeric.MustDecimal(value) }

func TestCashGenerationAndReturnEconomics(t *testing.T) {
	nopat, err := NOPAT(d("100"), d("0.25"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, nopat, "75")

	capital, err := InvestedCapital(d("500"), d("120"), d("200"), d("250"), d("50"), d("20"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, capital.OperatingApproach, "380")
	assertDecimal(t, capital.FinancingApproach, "380")
	assertDecimal(t, capital.Difference, "0")

	workingCapital, err := OperatingWorkingCapital(d("80"), d("40"), d("10"), d("60"), d("20"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, workingCapital, "50")

	reinvestment, err := Reinvestment(d("30"), d("5"), d("10"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, reinvestment, "45")
	fcff, _ := FCFFFromNOPAT(nopat, reinvestment)
	assertDecimal(t, fcff, "30")

	roic, _ := ROIC(nopat, d("300"))
	spread, _ := ValueCreationSpread(roic, d("0.09"))
	rate, _ := ReinvestmentRate(reinvestment, nopat)
	growth, _ := FundamentalGrowth(roic, rate)
	assertDecimal(t, roic, "0.25")
	assertDecimal(t, spread, "0.16")
	assertDecimal(t, rate, "0.6")
	assertDecimal(t, growth, "0.15")
}

func TestFCFEAndIncrementalReturn(t *testing.T) {
	fcfe, err := FCFE(d("100"), d("40"), d("15"), d("10"), d("5"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, fcfe, "70")
	incremental, err := IncrementalROIC(d("12"), d("60"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, incremental, "0.2")
}

func TestReturnEconomicsFailClosed(t *testing.T) {
	if _, err := NOPAT(one, d("1.1")); err == nil {
		t.Fatal("tax rate above one must fail")
	}
	if _, err := ROIC(one, zero); err == nil {
		t.Fatal("non-positive capital must fail")
	}
	if _, err := IncrementalROIC(one, d("-1")); err == nil {
		t.Fatal("negative incremental capital must fail")
	}
	if _, err := ReinvestmentRate(one, zero); err == nil {
		t.Fatal("non-positive NOPAT must fail")
	}
}

func TestFinancialQualityMetrics(t *testing.T) {
	margin, err := ProfitMargin(MarginOperating, d("30"), d("100"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, margin.Value, "0.3")
	incremental, _ := IncrementalMargin(d("30"), d("20"), d("120"), d("100"))
	assertDecimal(t, incremental, "0.5")
	leverage, _ := OperatingLeverage(d("30"), d("20"), d("120"), d("100"))
	assertDecimal(t, leverage, "2.5")
	accruals, _ := AccrualIntensity(d("30"), d("25"), d("200"))
	assertDecimal(t, accruals, "0.025")

	dso, _ := DaysSalesOutstanding(d("20"), d("100"), d("365"))
	dio, _ := DaysInventoryOutstanding(d("15"), d("60"), d("365"))
	dpo, _ := DaysPayablesOutstanding(d("10"), d("60"), d("365"))
	cycle, _ := CashConversionCycle(dso, dio, dpo)
	assertDecimal(t, dso, "73")
	assertDecimal(t, dio, "91.25")
	assertDecimal(t, dpo, "60.83333333333333333333333333333335")
	assertDecimal(t, cycle, "103.4166666666666666666666666666666")

	quick, _ := QuickRatio(d("10"), d("5"), d("20"), d("25"))
	cash, _ := CashRatio(d("10"), d("5"), d("25"))
	coverage, _ := InterestCoverage(d("50"), d("5"))
	leverageRatio, _ := NetDebtToEBITDA(d("80"), d("40"))
	assertDecimal(t, quick, "1.4")
	assertDecimal(t, cash, "0.6")
	assertDecimal(t, coverage, "10")
	assertDecimal(t, leverageRatio, "2")
}

func TestStabilityAndCapitalAllocation(t *testing.T) {
	stability, err := Stability([]numeric.Decimal{d("0.20"), d("0.21"), d("0.19")})
	if err != nil {
		t.Fatal(err)
	}
	if stability.Observations != 3 || math.Abs(stability.Mean-0.20) > 1e-12 || math.Abs(stability.StandardDeviation-0.01) > 1e-12 {
		t.Fatalf("unexpected stability %+v", stability)
	}

	bridge, err := CapitalAllocationBridge(
		d("100"), d("20"), d("0"), d("5"),
		d("40"), d("10"), d("20"), d("15"), d("10"),
		d("30"), d("0"),
	)
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, bridge.TotalSources, "125")
	assertDecimal(t, bridge.TotalUses, "95")
	assertDecimal(t, bridge.ImpliedChangeInCash, "30")
	if !bridge.WithinTolerance {
		t.Fatal("bridge should reconcile")
	}
}

func TestQualityMetricsFailClosed(t *testing.T) {
	if _, err := ProfitMargin("invented", one, one); err == nil {
		t.Fatal("unsupported margin must fail")
	}
	if _, err := IncrementalMargin(one, zero, one, one); err == nil {
		t.Fatal("non-positive revenue change must fail")
	}
	if _, err := Stability([]numeric.Decimal{one, one}); err == nil {
		t.Fatal("short stability sample must fail")
	}
	if _, err := InterestCoverage(one, zero); err == nil {
		t.Fatal("zero interest expense must fail")
	}
}
