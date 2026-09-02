package finance

import (
	"math"
	"testing"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func TestCAPMAndBetaRoundTrip(t *testing.T) {
	cost, err := CAPM(d("0.04"), d("1.2"), d("0.05"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, cost, "0.1")
	unlevered, err := UnleverBeta(d("1.2"), d("40"), d("100"), d("0.25"))
	if err != nil {
		t.Fatal(err)
	}
	relevered, err := ReleverBeta(unlevered, d("40"), d("100"), d("0.25"))
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, relevered, "1.2")
}

func TestAdvancedDCFSupportsDistinctTerminalMethods(t *testing.T) {
	forecast := []numeric.Decimal{d("10"), d("11"), d("12")}
	perpetuity, err := MultiStageDCF(forecast, d("0.10"), TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.03")}, false)
	if err != nil {
		t.Fatal(err)
	}
	assertDecimal(t, perpetuity.EnterpriseValue, "159.858323494687131050767414403778")
	if len(perpetuity.Warnings) != 1 {
		t.Fatalf("expected terminal-share warning: %+v", perpetuity)
	}
	exit, err := MultiStageDCF(forecast, d("0.10"), TerminalAssumption{Method: TerminalExitMultiple, ExitMetric: d("20"), ExitMultiple: d("8")}, true)
	if err != nil {
		t.Fatal(err)
	}
	if sign, _ := compare(exit.EnterpriseValue, zero); sign <= 0 {
		t.Fatal("exit-multiple valuation must be positive")
	}
	if same, _ := compare(exit.EnterpriseValue, perpetuity.EnterpriseValue); same == 0 {
		t.Fatal("distinct terminal conventions must not collapse to the same result")
	}
}

func TestReverseRevenueGrowthRepricesTarget(t *testing.T) {
	baseRevenue := d("100")
	expectedGrowth := d("0.08")
	forecast, err := fcffFromRevenuePath(baseRevenue, expectedGrowth, d("0.20"), d("0.25"), d("0.40"), 5)
	if err != nil {
		t.Fatal(err)
	}
	target, err := MultiStageDCF(forecast, d("0.10"), TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.03")}, false)
	if err != nil {
		t.Fatal(err)
	}
	implied, err := ReverseRevenueGrowth(target.EnterpriseValue, baseRevenue, d("0.20"), d("0.25"), d("0.40"), d("0.10"), d("0.03"), 5, 256, d("0.00000001"))
	if err != nil || !implied.Converged {
		t.Fatalf("reverse growth failed: %+v %v", implied, err)
	}
	difference, _ := subtract(implied.ImpliedValue, expectedGrowth)
	absDifference, _ := absolute(difference)
	if order, _ := compare(absDifference, d("0.00000001")); order > 0 {
		t.Fatalf("implied growth drift %s", absDifference.String())
	}
}

func TestTypedMultiplesRejectValueLevelMismatch(t *testing.T) {
	value, err := TypedMultiple(MultipleEVEBITDA, ValueLevelEnterprise, 100, 20)
	if err != nil || value != 5 {
		t.Fatalf("EV/EBITDA = %v, %v", value, err)
	}
	if _, err := TypedMultiple(MultiplePE, ValueLevelEnterprise, 100, 20); err == nil {
		t.Fatal("enterprise value divided by earnings must fail")
	}
}

func TestPeerStatisticsDuPontAndAssociation(t *testing.T) {
	peers, err := PeerStatistics([]float64{8, 10, 12, 14, 16}, 13, 5)
	if err != nil {
		t.Fatal(err)
	}
	if peers.Median != 12 || peers.Percentile != 0.6 || peers.Observations != 5 {
		t.Fatalf("unexpected peer statistics %+v", peers)
	}
	dupont, err := DuPont(10, 100, 50, 25)
	if err != nil || math.Abs(dupont.ReturnOnEquity-0.4) > 1e-12 {
		t.Fatalf("unexpected DuPont %+v %v", dupont, err)
	}
	association, err := LaggedAssociation([]float64{1, 2, 3, 4, 5}, []float64{0, 2, 4, 6, 8}, 1, 4)
	if err != nil {
		t.Fatal(err)
	}
	if association.Label != "statistical_association_not_causality" || association.Observations != 4 || math.Abs(association.RSquared-1) > 1e-12 {
		t.Fatalf("unexpected association %+v", association)
	}
}

func TestAdvancedValuationFailsClosed(t *testing.T) {
	if _, err := MultiStageDCF([]numeric.Decimal{one}, d("0.03"), TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: d("0.03")}, false); err == nil {
		t.Fatal("discount rate equal to terminal growth must fail")
	}
	if _, err := PeerStatistics([]float64{1, 2}, 1, 3); err == nil {
		t.Fatal("small peer sample must fail")
	}
	if _, err := LinearAssociation([]float64{1, 1, 1}, []float64{1, 2, 3}, 3); err == nil {
		t.Fatal("zero-variance association must fail")
	}
}
