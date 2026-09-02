package finance

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func assertDecimal(t *testing.T, actual numeric.Decimal, expected string) {
	t.Helper()
	if actual.String() != expected {
		t.Fatalf("got %s, want %s", actual.String(), expected)
	}
}

func TestScalarGoldenCases(t *testing.T) {
	t.Run("balance sheet", func(t *testing.T) {
		result, err := BalanceSheetIdentity(numeric.MustDecimal("100"), numeric.MustDecimal("60"), numeric.MustDecimal("40"), zero)
		if err != nil || !result.WithinTolerance {
			t.Fatalf("unexpected result %+v: %v", result, err)
		}
		assertDecimal(t, result.Difference, "0")
	})

	tests := []struct {
		name     string
		function func() (numeric.Decimal, error)
		expected string
	}{
		{"growth", func() (numeric.Decimal, error) { return Growth(numeric.MustDecimal("120"), numeric.MustDecimal("100")) }, "0.2"},
		{"cagr", func() (numeric.Decimal, error) {
			return CAGR(numeric.MustDecimal("100"), numeric.MustDecimal("121"), numeric.MustDecimal("2"))
		}, "0.1"},
		{"margin", func() (numeric.Decimal, error) { return Margin(numeric.MustDecimal("25"), numeric.MustDecimal("100")) }, "0.25"},
		{"free cash flow", func() (numeric.Decimal, error) {
			return FreeCashFlow(numeric.MustDecimal("30"), numeric.MustDecimal("10"))
		}, "20"},
		{"cash conversion", func() (numeric.Decimal, error) {
			return CashConversion(numeric.MustDecimal("30"), numeric.MustDecimal("25"))
		}, "1.2"},
		{"capex intensity", func() (numeric.Decimal, error) {
			return CapexIntensity(numeric.MustDecimal("10"), numeric.MustDecimal("100"))
		}, "0.1"},
		{"net debt", func() (numeric.Decimal, error) { return NetDebt(numeric.MustDecimal("50"), numeric.MustDecimal("20")) }, "30"},
		{"dilution", func() (numeric.Decimal, error) {
			return Dilution(numeric.MustDecimal("110"), numeric.MustDecimal("100"))
		}, "0.1"},
		{"roic", func() (numeric.Decimal, error) {
			return ROICProxy(numeric.MustDecimal("15"), numeric.MustDecimal("100"))
		}, "0.15"},
		{"current ratio", func() (numeric.Decimal, error) {
			return CurrentRatio(numeric.MustDecimal("120"), numeric.MustDecimal("80"))
		}, "1.5"},
		{"debt to equity", func() (numeric.Decimal, error) {
			return DebtToEquity(numeric.MustDecimal("40"), numeric.MustDecimal("100"))
		}, "0.4"},
		{"earnings per share", func() (numeric.Decimal, error) {
			return EarningsPerShare(numeric.MustDecimal("25"), numeric.MustDecimal("10"))
		}, "2.5"},
		{"multiple", func() (numeric.Decimal, error) {
			return PeerMultiple(numeric.MustDecimal("100"), numeric.MustDecimal("20"))
		}, "5"},
		{"wacc", func() (numeric.Decimal, error) {
			return WACC(numeric.MustDecimal("80"), numeric.MustDecimal("20"), numeric.MustDecimal("0.10"), numeric.MustDecimal("0.05"), numeric.MustDecimal("0.25"))
		}, "0.0875"},
		{"real rate", func() (numeric.Decimal, error) {
			return RealRate(numeric.MustDecimal("0.06"), numeric.MustDecimal("0.02"))
		}, "0.03921568627450980392156862745098"},
		{"yield spread", func() (numeric.Decimal, error) {
			return YieldCurveSpread(numeric.MustDecimal("0.05"), numeric.MustDecimal("0.03"))
		}, "0.02"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			actual, err := test.function()
			if err != nil {
				t.Fatal(err)
			}
			assertDecimal(t, actual, test.expected)
		})
	}
}

func TestQualityOfEarningsGoldenCase(t *testing.T) {
	result, err := QualityOfEarnings(numeric.MustDecimal("30"), numeric.MustDecimal("25"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, result.AccrualGap, "5")
	assertDecimal(t, result.CashConversion, "1.2")
}

func TestDCFAndEquityBridgeGoldenCases(t *testing.T) {
	result, err := FCFFDCF([]numeric.Decimal{numeric.MustDecimal("10"), numeric.MustDecimal("11"), numeric.MustDecimal("12")}, numeric.MustDecimal("0.10"), numeric.MustDecimal("0.03"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, result.ExplicitPresentValue, "27.19759579263711495116453794139744")
	assertDecimal(t, result.TerminalPresentValue, "132.6607277020500160996028764623806")
	assertDecimal(t, result.EnterpriseValue, "159.858323494687131050767414403778")

	bridge, err := EnterpriseToEquity(numeric.MustDecimal("100"), numeric.MustDecimal("20"), numeric.MustDecimal("5"), numeric.MustDecimal("10"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, bridge.EquityValue, "85")
	assertDecimal(t, bridge.ValuePerShare, "8.5")
}

func TestReverseDCFConvergesAndReprices(t *testing.T) {
	target := numeric.MustDecimal("150")
	result, err := ReverseDCF(target, numeric.MustDecimal("10"), numeric.MustDecimal("0.10"), 1, numeric.MustDecimal("0.00000001"), 256)
	if err != nil {
		t.Fatal(err)
	}
	if !result.Converged {
		t.Fatal("reverse DCF did not converge")
	}
	repriced, err := FCFFDCF([]numeric.Decimal{numeric.MustDecimal("10")}, numeric.MustDecimal("0.10"), result.ImpliedGrowth)
	if err != nil {
		t.Fatal(err)
	}
	difference, err := subtract(repriced.EnterpriseValue, target)
	if err != nil {
		t.Fatal(err)
	}
	abs, err := absolute(difference)
	if err != nil {
		t.Fatal(err)
	}
	if comparison, _ := compare(abs, numeric.MustDecimal("0.00000001")); comparison > 0 {
		t.Fatalf("repriced target differs by %s", abs.String())
	}
}

func TestFinancialBoundariesFailClosed(t *testing.T) {
	if _, err := Margin(one, zero); err == nil {
		t.Fatal("zero denominator must fail")
	}
	if _, err := CAGR(zero, one, one); err == nil {
		t.Fatal("non-positive start must fail")
	}
	if _, err := FCFFDCF([]numeric.Decimal{one}, numeric.MustDecimal("0.03"), numeric.MustDecimal("0.03")); err == nil {
		t.Fatal("discount rate equal to terminal growth must fail")
	}
	if _, err := EnterpriseToEquity(one, zero, zero, zero); err == nil {
		t.Fatal("zero diluted shares must fail")
	}
}

func FuzzGrowthRoundTrip(f *testing.F) {
	f.Add("120", "100")
	f.Add("80", "100")
	f.Fuzz(func(t *testing.T, currentText, priorText string) {
		current, err := numeric.ParseDecimal(currentText)
		if err != nil {
			t.Skip()
		}
		prior, err := numeric.ParseDecimal(priorText)
		if err != nil || prior.String() == "0" {
			t.Skip()
		}
		growth, err := Growth(current, prior)
		if err != nil {
			t.Fatal(err)
		}
		onePlusGrowth, err := add(one, growth)
		if err != nil {
			t.Fatal(err)
		}
		rebuilt, err := multiply(prior, onePlusGrowth)
		if err != nil {
			t.Fatal(err)
		}
		difference, err := subtract(rebuilt, current)
		if err != nil {
			t.Fatal(err)
		}
		abs, err := absolute(difference)
		if err != nil {
			t.Fatal(err)
		}
		if order, _ := compare(abs, numeric.MustDecimal("1e-25")); order > 0 {
			t.Fatalf("round trip drift %s", abs.String())
		}
	})
}
