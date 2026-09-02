package finance

import (
	"fmt"
	"testing"
	"testing/quick"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func TestBetaUnleverReleverProperty(t *testing.T) {
	property := func(betaRaw, debtRaw, equityRaw, taxRaw uint16) bool {
		beta := d(fmt.Sprintf("%d.%02d", 1+betaRaw%4, betaRaw%100))
		debt := d(fmt.Sprintf("%d", debtRaw%1000))
		equity := d(fmt.Sprintf("%d", 1+equityRaw%1000))
		tax := d(fmt.Sprintf("0.%02d", taxRaw%80))
		unlevered, err := UnleverBeta(beta, debt, equity, tax)
		if err != nil {
			return false
		}
		relevered, err := ReleverBeta(unlevered, debt, equity, tax)
		if err != nil {
			return false
		}
		difference, err := subtract(relevered, beta)
		if err != nil {
			return false
		}
		absoluteDifference, err := absolute(difference)
		if err != nil {
			return false
		}
		order, err := compare(absoluteDifference, d("0.000000000000000000000000000001"))
		return err == nil && order <= 0
	}
	if err := quick.Check(property, &quick.Config{MaxCount: 500}); err != nil {
		t.Fatal(err)
	}
}

func TestDCFMonotonicityProperties(t *testing.T) {
	forecast := []numeric.Decimal{d("10"), d("12"), d("14"), d("16"), d("18")}
	base, err := MultiStageDCF(forecast, d("0.10"), TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.03")}, false)
	if err != nil {
		t.Fatal(err)
	}
	higherDiscount, err := MultiStageDCF(forecast, d("0.12"), TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.03")}, false)
	if err != nil {
		t.Fatal(err)
	}
	higherGrowth, err := MultiStageDCF(forecast, d("0.10"), TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.04")}, false)
	if err != nil {
		t.Fatal(err)
	}
	if order, _ := compare(higherDiscount.EnterpriseValue, base.EnterpriseValue); order >= 0 {
		t.Fatal("higher discount rate must reduce enterprise value")
	}
	if order, _ := compare(higherGrowth.EnterpriseValue, base.EnterpriseValue); order <= 0 {
		t.Fatal("higher terminal growth must increase enterprise value")
	}
}

func TestCapitalAllocationBridgeConservationProperty(t *testing.T) {
	property := func(sourceRaw, useRaw uint16) bool {
		source := d(fmt.Sprintf("%d", sourceRaw))
		use := d(fmt.Sprintf("%d", useRaw))
		reported, err := subtract(source, use)
		if err != nil {
			return false
		}
		result, err := CapitalAllocationBridge(source, zero, zero, zero, use, zero, zero, zero, zero, reported, zero)
		return err == nil && result.WithinTolerance && result.ReconciliationGap.String() == "0"
	}
	if err := quick.Check(property, &quick.Config{MaxCount: 500}); err != nil {
		t.Fatal(err)
	}
}

func FuzzReturnEconomicsFailClosed(f *testing.F) {
	f.Add(int64(100), int64(25), int64(300))
	f.Add(int64(-100), int64(0), int64(0))
	f.Fuzz(func(t *testing.T, incomeRaw, taxPercentRaw, capitalRaw int64) {
		if incomeRaw > 1_000_000 || incomeRaw < -1_000_000 || taxPercentRaw > 200 || taxPercentRaw < -200 || capitalRaw > 1_000_000 || capitalRaw < -1_000_000 {
			t.Skip()
		}
		income := d(fmt.Sprintf("%d", incomeRaw))
		taxRate := d(fmt.Sprintf("%d", taxPercentRaw))
		taxRate, _ = divide(taxRate, d("100"))
		capital := d(fmt.Sprintf("%d", capitalRaw))
		nopat, err := NOPAT(income, taxRate)
		if taxPercentRaw < 0 || taxPercentRaw > 100 {
			if err == nil {
				t.Fatal("tax rate outside [0,1] must fail")
			}
			return
		}
		if err != nil {
			t.Fatal(err)
		}
		if _, err := ROIC(nopat, capital); capitalRaw <= 0 && err == nil {
			t.Fatal("non-positive invested capital must fail")
		}
	})
}

func BenchmarkMultiStageDCF(b *testing.B) {
	forecast := []numeric.Decimal{d("10"), d("12"), d("14"), d("16"), d("18")}
	terminal := TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.03")}
	b.ReportAllocs()
	for range b.N {
		if _, err := MultiStageDCF(forecast, d("0.10"), terminal, false); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkCashAndReturnJourney(b *testing.B) {
	b.ReportAllocs()
	for range b.N {
		nopat, err := NOPAT(d("100"), d("0.25"))
		if err != nil {
			b.Fatal(err)
		}
		reinvestment, err := Reinvestment(d("25"), d("5"), d("10"))
		if err != nil {
			b.Fatal(err)
		}
		if _, err := FCFFFromNOPAT(nopat, reinvestment); err != nil {
			b.Fatal(err)
		}
		if _, err := ROIC(nopat, d("300")); err != nil {
			b.Fatal(err)
		}
	}
}
