package engine

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/roles"
)

var testTime = time.Date(2026, 7, 21, 18, 30, 0, 0, time.UTC)

func quantityInput(id, value, unit, currency, period string) contracts.EngineInput {
	asOf := testTime.Add(-time.Hour)
	return contracts.EngineInput{InputID: id, Quantity: contracts.Quantity{Value: value, Unit: unit, Currency: currency, Period: period, AsOf: &asOf}, Status: "reported", EvidenceRefs: []string{"fixture:" + id}}
}

func requestFor(t *testing.T, operationID string, inputs []contracts.EngineInput) contracts.EngineRequest {
	t.Helper()
	operation, ok := capability.Tier0Registry().Get(operationID)
	if !ok {
		t.Fatalf("operation %s is not registered", operationID)
	}
	role := roles.AccountingReporting
	switch operation.Engine {
	case "valuation", "comparison":
		role = roles.Valuation
	case "economics":
		role = roles.EconomicsTransmission
	case "market":
		role = roles.MarketBehavior
	}
	return contracts.EngineRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: "request-" + operationID,
		RunID: "run-test", StepID: "step-test", RequestedBy: role, EngineID: operation.Engine,
		OperationID: operation.ID, FormulaVersion: operation.FormulaVersion,
		Scope: contracts.Scope{AsOf: testTime}, Inputs: inputs,
		PrecisionPolicy: operation.NumericalPolicy, RequestedOutputs: append([]string(nil), operation.Outputs...),
	}
}

func TestExecutorRunsEveryTierZeroOperation(t *testing.T) {
	period := "FY2025"
	usd := func(id, value string) contracts.EngineInput {
		return quantityInput(id, value, "currency", "USD", period)
	}
	ratio := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "ratio", "", "") }
	count := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "count", "", "") }
	shares := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "shares", "", period) }
	years := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "years", "", "") }
	index := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "index_point", "", "") }

	cases := map[string][]contracts.EngineInput{
		"accounting.balance_sheet_identity": {usd("assets", "100"), usd("liabilities", "60"), usd("equity", "40")},
		"financial.revenue_growth":          {usd("revenue_current", "120"), usd("revenue_prior", "100")},
		"financial.cagr":                    {usd("value_start", "100"), usd("value_end", "121"), years("years", "2")},
		"financial.margin":                  {usd("numerator", "25"), usd("revenue", "100")},
		"financial.free_cash_flow":          {usd("operating_cash_flow", "30"), usd("capital_expenditure", "10")},
		"financial.cash_conversion":         {usd("operating_cash_flow", "30"), usd("net_income", "25")},
		"financial.capex_intensity":         {usd("capital_expenditure", "10"), usd("revenue", "100")},
		"financial.net_debt":                {usd("debt", "50"), usd("cash_and_equivalents", "20")},
		"financial.dilution":                {shares("shares_current", "110"), shares("shares_prior", "100")},
		"financial.roic_proxy":              {usd("nopat", "15"), usd("invested_capital", "100")},
		"financial.current_ratio":           {usd("current_assets", "120"), usd("current_liabilities", "80")},
		"financial.debt_to_equity":          {usd("debt", "40"), usd("equity", "100")},
		"financial.earnings_per_share":      {usd("net_income", "25"), shares("diluted_shares", "10")},
		"financial.quality_of_earnings":     {usd("operating_cash_flow", "30"), usd("net_income", "25")},
		"valuation.fcff_dcf":                {usd("fcff_forecast.0", "10"), usd("fcff_forecast.1", "11"), usd("fcff_forecast.2", "12"), ratio("discount_rate", "0.10"), ratio("terminal_growth", "0.03")},
		"valuation.reverse_dcf":             {usd("enterprise_value", "150"), usd("base_fcff", "10"), ratio("discount_rate", "0.10"), years("years", "1")},
		"valuation.enterprise_to_equity":    {usd("enterprise_value", "100"), usd("net_debt", "20"), usd("non_operating_assets", "5"), shares("diluted_shares", "10")},
		"valuation.peer_multiple":           {usd("market_value", "100"), usd("metric_value", "20")},
		"valuation.wacc":                    {usd("equity_value", "80"), usd("debt_value", "20"), ratio("cost_of_equity", "0.10"), ratio("pre_tax_cost_of_debt", "0.05"), ratio("tax_rate", "0.25")},
		"economics.real_rate":               {ratio("nominal_rate", "0.06"), ratio("inflation_measure", "0.02")},
		"economics.yield_curve":             {ratio("long_yield", "0.05"), ratio("short_yield", "0.03")},
		"market.total_return":               {usd("start_price", "100"), usd("end_price", "110"), usd("distributions", "2")},
		"market.volatility":                 {ratio("returns.0", "0.01"), ratio("returns.1", "-0.01"), ratio("returns.2", "0.02"), ratio("returns.3", "-0.02"), count("periods_per_year", "252"), count("ddof", "1")},
		"market.drawdown":                   {index("wealth_index.0", "100"), index("wealth_index.1", "120"), index("wealth_index.2", "90"), index("wealth_index.3", "110")},
		"market.beta":                       {ratio("security_returns.0", "0.02"), ratio("security_returns.1", "-0.01"), ratio("security_returns.2", "0.03"), ratio("security_returns.3", "-0.02"), ratio("benchmark_returns.0", "0.01"), ratio("benchmark_returns.1", "-0.02"), ratio("benchmark_returns.2", "0.02"), ratio("benchmark_returns.3", "-0.01"), count("ddof", "1")},
		"market.rolling_correlation":        {index("series_x.0", "1"), index("series_x.1", "2"), index("series_x.2", "3"), index("series_x.3", "4"), index("series_y.0", "2"), index("series_y.1", "4"), index("series_y.2", "6"), index("series_y.3", "8"), count("window", "3")},
		"comparison.period_aligned":         {usd("company_metrics.0", "10"), usd("company_metrics.1", "12")},
		"scenario.sensitivity_matrix":       {usd("fcff_forecast.0", "10"), usd("fcff_forecast.1", "11"), usd("fcff_forecast.2", "12"), ratio("discount_rates.0", "0.09"), ratio("discount_rates.1", "0.10"), ratio("terminal_growth_rates.0", "0.02"), ratio("terminal_growth_rates.1", "0.03")},
	}

	executor, err := New("test-commit")
	if err != nil {
		t.Fatal(err)
	}
	executor.now = func() time.Time { return testTime }
	if len(cases) != len(capability.Tier0Registry().List()) {
		t.Fatalf("have %d executable cases for %d operations", len(cases), len(capability.Tier0Registry().List()))
	}
	for operationID, inputs := range cases {
		t.Run(operationID, func(t *testing.T) {
			result := executor.Execute(requestFor(t, operationID, inputs))
			if result.Failure != nil {
				t.Fatalf("execution failed: %+v", result.Failure)
			}
			if result.Receipt == nil || len(result.Receipt.Outputs) == 0 {
				t.Fatal("missing successful receipt")
			}
			if err := VerifyReceipt(*result.Receipt); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestExecutorFailsClosedAndIsDeterministic(t *testing.T) {
	executor, _ := New("test-commit")
	executor.now = func() time.Time { return testTime }
	request := requestFor(t, "financial.margin", []contracts.EngineInput{
		quantityInput("numerator", "25", "currency", "USD", "FY2025"),
		quantityInput("revenue", "100", "currency", "USD", "FY2025"),
	})
	first, second := executor.Execute(request), executor.Execute(request)
	if first.Receipt == nil || second.Receipt == nil || first.Receipt.ReceiptSHA != second.Receipt.ReceiptSHA {
		t.Fatal("fixed inputs and clock must produce identical receipts")
	}

	request.RequestedBy = roles.MarketBehavior
	if failure := executor.Execute(request).Failure; failure == nil || failure.FailureCode != "unauthorized_capability" {
		t.Fatalf("expected authorization failure, got %+v", failure)
	}
	request.RequestedBy = roles.AccountingReporting
	request.Inputs[1].Quantity.Currency = "EUR"
	if failure := executor.Execute(request).Failure; failure == nil || failure.FailureCode != "currency_mismatch" {
		t.Fatalf("expected currency failure, got %+v", failure)
	}
	request.Inputs[1].Quantity.Currency = "USD"
	request.Inputs[1].Quantity.Period = "Q1-2026"
	if failure := executor.Execute(request).Failure; failure == nil || failure.FailureCode != "period_mismatch" {
		t.Fatalf("expected period failure, got %+v", failure)
	}
}

func TestExecutorRequiresDeclaredAssumptionsOnlyForEligibleOperations(t *testing.T) {
	executor, _ := New("test-commit")
	executor.now = func() time.Time { return testTime }
	assumed := func(input contracts.EngineInput) contracts.EngineInput {
		input.Status = "assumed"
		input.EvidenceRefs = nil
		return input
	}

	dcf := requestFor(t, "valuation.fcff_dcf", []contracts.EngineInput{
		assumed(quantityInput("fcff_forecast.0", "10", "currency", "USD", "FY2026")),
		assumed(quantityInput("fcff_forecast.1", "11", "currency", "USD", "FY2027")),
		assumed(quantityInput("discount_rate", "0.10", "ratio", "", "")),
		assumed(quantityInput("terminal_growth", "0.03", "ratio", "", "")),
	})
	if failure := executor.Execute(dcf).Failure; failure == nil || failure.FailureCode != "invalid_request" {
		t.Fatalf("expected an explicit-assumption failure, got %+v", failure)
	}
	dcf.Assumptions = []string{"The forecast, discount rate, and terminal growth are scenario assumptions."}
	if result := executor.Execute(dcf); result.Failure != nil || result.Receipt == nil {
		t.Fatalf("eligible assumed DCF inputs must execute with disclosure: %+v", result.Failure)
	}

	margin := requestFor(t, "financial.margin", []contracts.EngineInput{
		assumed(quantityInput("numerator", "25", "currency", "USD", "FY2025")),
		quantityInput("revenue", "100", "currency", "USD", "FY2025"),
	})
	if failure := executor.Execute(margin).Failure; failure == nil || failure.FailureCode != "invalid_request" {
		t.Fatalf("non-scenario operation must reject assumed input, got %+v", failure)
	}
}

func TestPeerMultipleAcceptsAlignedPerShareInputs(t *testing.T) {
	executor, _ := New("test-commit")
	executor.now = func() time.Time { return testTime }
	result := executor.Execute(requestFor(t, "valuation.peer_multiple", []contracts.EngineInput{
		quantityInput("market_value", "398.10", "currency_per_share", "USD", "2026-07-21"),
		quantityInput("metric_value", "13.64", "currency_per_share", "USD", "FY2025"),
	}))
	if result.Failure != nil || result.Receipt == nil {
		t.Fatalf("expected a per-share multiple receipt, got %+v", result)
	}
	if result.Receipt.Outputs[0].OutputID != "multiple" || result.Receipt.Outputs[0].Quantity.Unit != "ratio" {
		t.Fatalf("unexpected multiple output: %+v", result.Receipt.Outputs)
	}
}

func TestReceiptStoreReplayAndSupersession(t *testing.T) {
	executor, _ := New("test-commit")
	executor.now = func() time.Time { return testTime }
	request := requestFor(t, "financial.net_debt", []contracts.EngineInput{
		quantityInput("debt", "50", "currency", "USD", "FY2025"),
		quantityInput("cash_and_equivalents", "20", "currency", "USD", "FY2025"),
	})
	first := executor.Execute(request).Receipt
	if first == nil {
		t.Fatal("missing first receipt")
	}
	store, err := NewReceiptStore(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.Save(*first); err != nil {
		t.Fatal(err)
	}
	loaded, err := store.Load(first.ReceiptSHA)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.ReceiptSHA != first.ReceiptSHA {
		t.Fatal("replay changed receipt")
	}

	executor.now = func() time.Time { return testTime.Add(time.Second) }
	request.Inputs[0].Quantity.Value = "45"
	replacement := executor.Execute(request).Receipt
	if replacement == nil {
		t.Fatal("missing replacement receipt")
	}
	if _, err := store.Save(*replacement); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Supersede(first.ReceiptSHA, replacement.ReceiptSHA, "corrected debt input", testTime.Add(2*time.Second)); err != nil {
		t.Fatal(err)
	}

	tampered := loaded
	tampered.Outputs[0].Quantity.Value = "999"
	if err := VerifyReceipt(tampered); err == nil {
		t.Fatal("tampered receipt must fail verification")
	}
}
