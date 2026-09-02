package finance

import (
	"math"
	"slices"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func TestROCEAndTypedCashConversion(t *testing.T) {
	roce, err := ROCE(d("30"), d("250"), d("50"))
	if err != nil || roce.String() != "0.15" {
		t.Fatalf("unexpected ROCE %s: %v", roce.String(), err)
	}
	for _, kind := range []CashConversionKind{CashConversionEarnings, CashConversionEBITDA, CashConversionOperatingProfit} {
		result, err := TypedCashConversion(kind, d("120"), d("100"))
		if err != nil || result.Kind != kind || result.Value.String() != "1.2" {
			t.Fatalf("unexpected conversion %+v: %v", result, err)
		}
	}
}

func TestDebtMaturityAndPayoutContext(t *testing.T) {
	context, err := AnalyzeDebtMaturities(2026, []DebtMaturity{
		{Year: 2027, Amount: d("20")}, {Year: 2029, Amount: d("30")}, {Year: 2031, Amount: d("50")},
	})
	if err != nil || context.TotalDebt.String() != "100" || context.NearTermShare.String() != "0.5" {
		t.Fatalf("unexpected maturity context %+v: %v", context, err)
	}
	yield, err := NetPayoutYield(d("10"), d("5"), d("300"))
	if err != nil || yield.String() != "0.05" {
		t.Fatalf("unexpected net payout yield %s: %v", yield.String(), err)
	}
}

func TestDetailedEnterpriseBridgeAndSanityChecks(t *testing.T) {
	bridge, err := DetailedEnterpriseToEquity(d("1000"), d("200"), d("80"), d("40"), d("20"), d("10"), d("100"))
	if err != nil || bridge.EquityValue.String() != "890" || bridge.ValuePerDilutedShare.String() != "8.9" {
		t.Fatalf("unexpected bridge %+v: %v", bridge, err)
	}
	warnings, err := ValuationSanityChecks(ValuationSanityInputs{
		TerminalValueShare: d("0.8"), TerminalGrowth: d("0.05"), LongRunEconomyRate: d("0.03"),
		OperatingMargin: d("0.30"), HistoricalMargin: d("0.15"), ReinvestmentRate: d("0.50"),
		ReturnOnCapital: d("0.20"), GrowthRate: d("0.04"),
	})
	if err != nil || len(warnings) != 4 {
		t.Fatalf("unexpected warnings %v: %v", warnings, err)
	}
}

func TestDCFScenarioGrid(t *testing.T) {
	scenarios, err := DCFScenarios([]numeric.Decimal{d("100"), d("110"), d("120")}, map[string][2]numeric.Decimal{
		"base": {d("0.10"), d("0.03")},
		"bear": {d("0.12"), d("0.02")},
		"bull": {d("0.09"), d("0.04")},
	})
	if err != nil || len(scenarios) != 3 || scenarios[0].Name != "base" {
		t.Fatalf("unexpected scenarios %+v: %v", scenarios, err)
	}
	tornado, err := DCFTornado(
		[]numeric.Decimal{d("100"), d("110"), d("120")},
		d("0.10"),
		d("0.03"),
		map[string][3]numeric.Decimal{
			"discount_rate":   {d("0.09"), d("0.10"), d("0.11")},
			"terminal_growth": {d("0.02"), d("0.03"), d("0.04")},
		},
	)
	if err != nil || len(tornado) != 2 || tornado[0].Name == "" {
		t.Fatalf("unexpected tornado %+v: %v", tornado, err)
	}
	if _, err := DCFTornado(
		[]numeric.Decimal{d("100"), d("110"), d("120")},
		d("0.10"),
		d("0.03"),
		map[string][3]numeric.Decimal{"discount_rate": {d("0.09"), d("0.11"), d("0.12")}},
	); err == nil {
		t.Fatal("tornado must reject a base value that differs from the governed DCF base")
	}
	if _, err := DCFTornado(
		[]numeric.Decimal{d("100"), d("110"), d("120")},
		d("0.10"),
		d("0.03"),
		map[string][3]numeric.Decimal{"terminal_growth": {d("0.04"), d("0.03"), d("0.02")}},
	); err == nil {
		t.Fatal("tornado must reject unordered low, base, and high assumptions")
	}
}

func TestReverseMarginReinvestmentAndROIC(t *testing.T) {
	base := d("100")
	growth := d("0.08")
	margin := d("0.25")
	tax := d("0.20")
	reinvestment := d("0.40")
	discount := d("0.10")
	terminal := d("0.03")
	forecast, err := fcffFromRevenuePath(base, growth, margin, tax, reinvestment, 5)
	if err != nil {
		t.Fatal(err)
	}
	valuation, err := MultiStageDCF(forecast, discount, TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: terminal}, false)
	if err != nil {
		t.Fatal(err)
	}
	impliedMargin, err := ReverseOperatingMargin(valuation.EnterpriseValue, base, growth, tax, reinvestment, discount, terminal, 5, 256, d("0.000001"))
	if err != nil || !impliedMargin.Converged {
		t.Fatalf("margin solve failed %+v: %v", impliedMargin, err)
	}
	impliedReinvestment, err := ReverseReinvestmentRate(valuation.EnterpriseValue, base, growth, margin, tax, discount, terminal, 5, 256, d("0.000001"))
	if err != nil || !impliedReinvestment.Converged {
		t.Fatalf("reinvestment solve failed %+v: %v", impliedReinvestment, err)
	}
	roic, err := ImpliedReturnOnCapital(d("0.08"), d("0.40"))
	if err != nil || roic.String() != "0.2" {
		t.Fatalf("unexpected implied ROIC %s: %v", roic.String(), err)
	}
}

func TestPeerGovernanceHistoricalBandAndTrainTestDiagnostics(t *testing.T) {
	asOf := time.Date(2026, 1, 31, 0, 0, 0, 0, time.UTC)
	peers := make([]PeerObservation, 0, 6)
	for index, value := range []float64{10, 11, 12, 13, 14, 100} {
		peers = append(peers, PeerObservation{
			CompanyID: "peer-" + intString(index), Value: value, ObservedAt: asOf.Add(-24 * time.Hour),
			Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "valuation.ev_to_ebitda@1.0.0",
		})
	}
	cohort, err := GovernPeerCohort(peers, PeerCohortPolicy{
		AsOf: asOf, Currency: "USD", FiscalPeriod: "TTM-2025",
		DefinitionID: "valuation.ev_to_ebitda@1.0.0", MinimumSample: 5,
		MaximumAgeDays: 30, WinsorizePercent: 0.20,
	})
	if err != nil || len(cohort.Values) != 6 || cohort.Values[5] == 100 {
		t.Fatalf("unexpected cohort %+v: %v", cohort, err)
	}
	band, err := HistoricalBand([]float64{8, 9, 10, 11, 12, 13}, 12, 5)
	if err != nil || band.Interpretation != "historical_position_only_not_mean_reversion" {
		t.Fatalf("unexpected band %+v: %v", band, err)
	}
	pairs := make([]TimedPair, 0, 24)
	for index := 0; index < 24; index++ {
		driver := float64(index)
		outcome := 2*driver + 1
		pairs = append(pairs, TimedPair{At: asOf.AddDate(0, -24+index, 0), Driver: &driver, Outcome: &outcome})
	}
	diagnostics, err := TrainTestLaggedAssociation(pairs, 0, 12, pairs[15].At)
	if err != nil || diagnostics.TestObservations != 8 || diagnostics.EvidenceClass == "" {
		t.Fatalf("unexpected diagnostics %+v: %v", diagnostics, err)
	}
}

func TestPeerCohortRejectsEveryDuplicateWithoutOrderDependence(t *testing.T) {
	asOf := time.Date(2026, 1, 31, 0, 0, 0, 0, time.UTC)
	observations := []PeerObservation{
		{CompanyID: "duplicate", Value: 10, ObservedAt: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1"},
		{CompanyID: "peer-a", Value: 11, ObservedAt: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1"},
		{CompanyID: "duplicate", Value: 12, ObservedAt: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1"},
		{CompanyID: "peer-b", Value: 13, ObservedAt: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1"},
		{CompanyID: "peer-c", Value: 14, ObservedAt: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1"},
	}
	cohort, err := GovernPeerCohort(observations, PeerCohortPolicy{
		AsOf: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1",
		MinimumSample: 3, MaximumAgeDays: 0,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(cohort.Values) != 3 || cohort.Excluded["duplicate"] != "duplicate_or_missing_company" {
		t.Fatalf("duplicate peer was not fully quarantined: %+v", cohort)
	}
	for _, companyID := range cohort.IncludedIDs {
		if companyID == "duplicate" {
			t.Fatal("duplicate peer must never enter the governed cohort")
		}
	}
	reversed := append([]PeerObservation(nil), observations...)
	slices.Reverse(reversed)
	replayed, err := GovernPeerCohort(reversed, PeerCohortPolicy{
		AsOf: asOf, Currency: "USD", FiscalPeriod: "TTM-2025", DefinitionID: "metric-v1",
		MinimumSample: 3, MaximumAgeDays: 0,
	})
	if err != nil || !slices.Equal(cohort.IncludedIDs, replayed.IncludedIDs) ||
		!slices.Equal(cohort.Values, replayed.Values) {
		t.Fatalf("peer cohort depends on source ordering: forward=%+v reverse=%+v err=%v", cohort, replayed, err)
	}
}

func TestLaggedAssociationPreservesTimeAlignmentAcrossMissingRows(t *testing.T) {
	asOf := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	pairs := make([]TimedPair, 0, 10)
	drivers := make([]float64, 10)
	outcomes := make([]float64, 10)
	for index := range drivers {
		drivers[index] = float64(index)
		if index > 0 {
			outcomes[index] = 3*drivers[index-1] + 2
		}
		pairs = append(pairs, TimedPair{
			At: asOf.AddDate(0, index, 0), Driver: &drivers[index], Outcome: &outcomes[index],
		})
	}
	pairs[3].Driver = nil
	diagnostics, err := TrainTestLaggedAssociation(pairs, 1, 4, pairs[6].At)
	if err != nil {
		t.Fatal(err)
	}
	if diagnostics.Result.Lag != 1 || diagnostics.MissingPairs != 1 ||
		math.Abs(diagnostics.Result.Slope-3) > 1e-9 || math.Abs(diagnostics.Result.Intercept-2) > 1e-9 {
		t.Fatalf("missing row changed lag alignment: %+v", diagnostics)
	}
}

func TestLaggedAssociationRejectsAmbiguousTimestamps(t *testing.T) {
	at := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	driverA, driverB, driverC := 1.0, 2.0, 3.0
	outcomeA, outcomeB, outcomeC := 2.0, 4.0, 6.0
	pairs := []TimedPair{
		{At: at, Driver: &driverA, Outcome: &outcomeA},
		{At: at, Driver: &driverB, Outcome: &outcomeB},
		{At: at.Add(time.Hour), Driver: &driverC, Outcome: &outcomeC},
	}
	if _, err := TrainTestLaggedAssociation(pairs, 0, 1, at); err == nil {
		t.Fatal("duplicate timestamps must fail closed")
	}
}

func TestRollingMarketStatisticsUsesAlignedWindows(t *testing.T) {
	benchmark := []float64{0.01, -0.02, 0.03, 0.04, -0.01, 0.02}
	security := []float64{0.02, -0.04, 0.06, 0.08, -0.02, 0.04}
	windows, err := RollingMarketStatistics(security, benchmark, 4)
	if err != nil || len(windows) != 3 {
		t.Fatalf("unexpected rolling windows %+v: %v", windows, err)
	}
	for _, window := range windows {
		if window.Observations != 4 || window.Beta < 1.999999 || window.Beta > 2.000001 ||
			window.Slope < 1.999999 || window.Slope > 2.000001 || window.RSquared < 0.999999 {
			t.Fatalf("misaligned rolling result %+v", window)
		}
	}
}
