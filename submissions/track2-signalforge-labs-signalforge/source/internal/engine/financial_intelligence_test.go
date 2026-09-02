package engine

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func runtimeRequest(t *testing.T, operationID string, inputs []contracts.EngineInput) contracts.EngineRequest {
	t.Helper()
	operation, ok := capability.RuntimeRegistry().Get(operationID)
	if !ok {
		t.Fatalf("operation %s is not registered", operationID)
	}
	role := roles.AccountingReporting
	switch operation.Engine {
	case "valuation", "comparison":
		role = roles.Valuation
	case "economics":
		role = roles.EconomicsTransmission
	}
	return contracts.EngineRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: "request-" + operationID,
		RunID: "run-sprint16b", StepID: "step-sprint16b", RequestedBy: role,
		EngineID: operation.Engine, OperationID: operation.ID, FormulaVersion: operation.FormulaVersion,
		Scope: contracts.Scope{CompanyIDs: []string{"company-msft"}, AsOf: testTime}, Inputs: inputs,
		PrecisionPolicy: operation.NumericalPolicy, RequestedOutputs: append([]string(nil), operation.Outputs...),
	}
}

func TestExecutorRunsEveryFinancialIntelligenceOperation(t *testing.T) {
	usd := func(id, value, period string) contracts.EngineInput {
		return quantityInput(id, value, "currency", "USD", period)
	}
	ratio := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "ratio", "", "") }
	days := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "days", "", "FY2025") }
	count := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "count", "", "") }
	shares := func(id, value, period string) contracts.EngineInput {
		return quantityInput(id, value, "shares", "", period)
	}
	years := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "years", "", "") }
	boolean := func(id, value string) contracts.EngineInput { return quantityInput(id, value, "boolean", "", "") }
	fy := func(id, value string) contracts.EngineInput { return usd(id, value, "FY2025") }

	cases := map[string][]contracts.EngineInput{
		"financial.nopat":                            {fy("operating_income", "100"), ratio("tax_rate", "0.25")},
		"financial.invested_capital":                 {fy("operating_assets", "500"), fy("non_interest_bearing_operating_liabilities", "120"), fy("debt", "200"), fy("equity", "250"), fy("cash_and_equivalents", "50"), fy("non_operating_assets", "20")},
		"financial.average_invested_capital":         {usd("invested_capital_beginning", "280", "FY2024"), fy("invested_capital_ending", "320")},
		"financial.operating_working_capital":        {fy("accounts_receivable", "80"), fy("inventory", "40"), fy("other_operating_current_assets", "10"), fy("accounts_payable", "60"), fy("other_operating_current_liabilities", "20")},
		"financial.change_in_working_capital":        {fy("operating_working_capital_ending", "50"), usd("operating_working_capital_beginning", "45", "FY2024")},
		"financial.net_capex":                        {fy("capital_expenditure", "40"), fy("depreciation_and_amortization", "15")},
		"financial.reinvestment":                     {fy("net_capex", "25"), fy("change_in_working_capital", "5"), fy("acquisitions", "10")},
		"financial.fcff_from_nopat":                  {fy("nopat", "75"), fy("reinvestment", "45")},
		"financial.fcfe":                             {fy("net_income", "100"), fy("capital_expenditure", "40"), fy("depreciation_and_amortization", "15"), fy("change_in_working_capital", "10"), fy("net_borrowing", "5")},
		"financial.roic":                             {fy("nopat", "75"), fy("average_invested_capital", "300")},
		"financial.incremental_roic":                 {fy("change_in_nopat", "12"), fy("change_in_invested_capital", "60")},
		"financial.roce":                             {fy("ebit", "30"), fy("total_assets", "250"), fy("current_liabilities", "50")},
		"financial.value_creation_spread":            {ratio("roic", "0.25"), ratio("wacc", "0.09")},
		"financial.reinvestment_rate":                {fy("reinvestment", "45"), fy("nopat", "75")},
		"financial.fundamental_growth":               {ratio("return_on_capital", "0.25"), ratio("reinvestment_rate", "0.60")},
		"financial.operating_margin":                 {fy("operating_income", "30"), fy("revenue", "100")},
		"financial.incremental_margin":               {fy("operating_income_current", "30"), usd("operating_income_prior", "20", "FY2024"), fy("revenue_current", "120"), usd("revenue_prior", "100", "FY2024")},
		"financial.accrual_intensity":                {fy("net_income", "30"), fy("operating_cash_flow", "25"), fy("average_assets", "200")},
		"financial.cash_conversion_cycle":            {days("days_sales_outstanding", "73"), days("days_inventory_outstanding", "91.25"), days("days_payables_outstanding", "60.83333333333333333333333333333335")},
		"financial.quick_ratio":                      {fy("cash_and_equivalents", "10"), fy("marketable_securities", "5"), fy("accounts_receivable", "20"), fy("current_liabilities", "25")},
		"financial.cash_ratio":                       {fy("cash_and_equivalents", "10"), fy("marketable_securities", "5"), fy("current_liabilities", "25")},
		"financial.interest_coverage":                {fy("ebit", "50"), fy("interest_expense", "5")},
		"financial.net_debt_to_ebitda":               {fy("net_debt", "80"), fy("ebitda", "40")},
		"financial.cash_conversion_ebitda":           {fy("operating_cash_flow", "120"), fy("ebitda", "100")},
		"financial.cash_conversion_operating_profit": {fy("operating_cash_flow", "120"), fy("operating_profit", "100")},
		"financial.buyback_yield":                    {fy("net_repurchases", "10"), fy("market_capitalization", "200")},
		"financial.dividend_yield":                   {fy("dividends_paid", "5"), fy("market_capitalization", "200")},
		"financial.net_payout_yield":                 {fy("net_repurchases", "10"), fy("dividends_paid", "5"), fy("market_capitalization", "200")},
		"financial.shareholder_yield":                {fy("net_repurchases", "10"), fy("dividends_paid", "5"), fy("net_debt_reduction", "2"), fy("market_capitalization", "200")},
		"financial.capital_allocation_bridge":        {fy("operating_cash_flow", "100"), fy("debt_issuance", "20"), fy("equity_issuance", "0"), fy("asset_sales", "5"), fy("capital_expenditure", "40"), fy("acquisitions", "10"), fy("debt_repayment", "20"), fy("dividends", "15"), fy("repurchases", "10"), fy("reported_change_in_cash", "30"), fy("tolerance", "0")},
		"valuation.capm":                             {ratio("risk_free_rate", "0.04"), ratio("beta", "1.2"), ratio("equity_risk_premium", "0.05")},
		"valuation.unlever_beta":                     {ratio("levered_beta", "1.2"), fy("debt", "40"), fy("equity", "100"), ratio("tax_rate", "0.25")},
		"valuation.relever_beta":                     {ratio("unlevered_beta", "0.9230769230769230769230769230769231"), fy("debt", "40"), fy("equity", "100"), ratio("tax_rate", "0.25")},
		"valuation.multistage_dcf_perpetuity":        {usd("fcff_forecast.0", "10", "FY2026"), usd("fcff_forecast.1", "11", "FY2027"), usd("fcff_forecast.2", "12", "FY2028"), ratio("discount_rate", "0.10"), ratio("terminal_growth", "0.03"), boolean("mid_year", "0")},
		"valuation.multistage_dcf_exit":              {usd("fcff_forecast.0", "10", "FY2026"), usd("fcff_forecast.1", "11", "FY2027"), usd("fcff_forecast.2", "12", "FY2028"), ratio("discount_rate", "0.10"), fy("exit_metric", "20"), ratio("exit_multiple", "8"), boolean("mid_year", "1")},
		"valuation.dividend_discount":                {usd("dividend_forecast.0", "2", "FY2026"), usd("dividend_forecast.1", "2.2", "FY2027"), usd("dividend_forecast.2", "2.4", "FY2028"), ratio("cost_of_equity", "0.10"), ratio("terminal_growth", "0.03"), boolean("mid_year", "0")},
		"valuation.reverse_revenue_growth":           {fy("enterprise_value", "200"), fy("base_revenue", "100"), ratio("operating_margin", "0.20"), ratio("tax_rate", "0.25"), ratio("reinvestment_rate", "0.40"), ratio("discount_rate", "0.10"), ratio("terminal_growth", "0.03"), years("years", "5")},
		"valuation.reverse_operating_margin":         {fy("enterprise_value", "200"), fy("base_revenue", "100"), ratio("revenue_growth", "0.08"), ratio("tax_rate", "0.25"), ratio("reinvestment_rate", "0.40"), ratio("discount_rate", "0.10"), ratio("terminal_growth", "0.03"), years("years", "5")},
		"valuation.reverse_reinvestment_rate":        {fy("enterprise_value", "200"), fy("base_revenue", "100"), ratio("revenue_growth", "0.08"), ratio("operating_margin", "0.25"), ratio("tax_rate", "0.25"), ratio("discount_rate", "0.10"), ratio("terminal_growth", "0.03"), years("years", "5")},
		"valuation.implied_roic":                     {ratio("growth_rate", "0.08"), ratio("reinvestment_rate", "0.40")},
		"valuation.enterprise_to_equity_detailed":    {fy("enterprise_value", "1000"), fy("debt", "200"), fy("cash", "80"), fy("investments", "40"), fy("minority_interest", "20"), fy("option_value", "10"), shares("diluted_shares", "100", "FY2025")},
		"valuation.ev_to_ebitda":                     {fy("enterprise_value", "100"), fy("ebitda", "20")},
		"valuation.ev_to_revenue":                    {fy("enterprise_value", "100"), fy("revenue", "50")},
		"valuation.ev_to_ebit":                       {fy("enterprise_value", "100"), fy("ebit", "10")},
		"valuation.price_to_earnings":                {fy("equity_market_value", "100"), fy("net_income", "10")},
		"valuation.price_to_book":                    {fy("equity_market_value", "100"), fy("book_equity", "40")},
		"valuation.price_to_fcf":                     {fy("equity_market_value", "100"), fy("free_cash_flow_to_equity", "8")},
		"valuation.fcf_yield":                        {fy("free_cash_flow_to_equity", "8"), fy("equity_market_value", "100")},
		"valuation.earnings_yield":                   {fy("net_income", "10"), fy("equity_market_value", "100")},
		"comparison.dupont":                          {fy("net_income", "10"), fy("revenue", "100"), fy("average_assets", "50"), fy("average_equity", "25")},
		"comparison.peer_statistics":                 {ratio("peer_values.0", "8"), ratio("peer_values.1", "10"), ratio("peer_values.2", "12"), ratio("peer_values.3", "14"), ratio("peer_values.4", "16"), ratio("subject_value", "13"), count("minimum_sample", "5")},
		"economics.lagged_association":               {ratio("driver_series.0", "1"), ratio("driver_series.1", "2"), ratio("driver_series.2", "3"), ratio("driver_series.3", "4"), ratio("driver_series.4", "5"), ratio("outcome_series.0", "0"), ratio("outcome_series.1", "2"), ratio("outcome_series.2", "4"), ratio("outcome_series.3", "6"), ratio("outcome_series.4", "8"), count("lag", "1"), count("minimum_sample", "4")},
	}

	if len(cases) != len(capability.FinancialIntelligenceRegistry().List()) {
		t.Fatalf("have %d cases for %d financial-intelligence operations", len(cases), len(capability.FinancialIntelligenceRegistry().List()))
	}
	executor, err := New("sprint16b-test")
	if err != nil {
		t.Fatal(err)
	}
	executor.now = func() time.Time { return testTime }
	for operationID, inputs := range cases {
		t.Run(operationID, func(t *testing.T) {
			result := executor.Execute(runtimeRequest(t, operationID, inputs))
			if result.Failure != nil {
				t.Fatalf("execution failed: %+v", result.Failure)
			}
			if result.Receipt == nil || len(result.Receipt.Outputs) == 0 {
				t.Fatal("missing receipt outputs")
			}
			if err := VerifyReceipt(*result.Receipt); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestEveryRuntimeOperationHasCompleteUnitRules(t *testing.T) {
	rules := governedUnitRules()
	for _, operation := range capability.RuntimeRegistry().List() {
		operationRules, exists := rules[operation.ID]
		if !exists {
			t.Errorf("operation %s has no unit contract", operation.ID)
			continue
		}
		for _, input := range operation.RequiredInputs {
			if _, exists := operationRules[input]; !exists {
				t.Errorf("operation %s has no unit rule for required input %s", operation.ID, input)
			}
		}
	}
}

func TestFinancialIntelligenceOperationsFailClosed(t *testing.T) {
	executor, _ := New("sprint16b-test")
	executor.now = func() time.Time { return testTime }
	request := runtimeRequest(t, "valuation.ev_to_ebitda", []contracts.EngineInput{
		quantityInput("enterprise_value", "100", "currency", "USD", "FY2025"),
		quantityInput("ebitda", "0", "currency", "USD", "FY2025"),
	})
	if failure := executor.Execute(request).Failure; failure == nil || failure.FailureCode != "invalid_request" {
		t.Fatalf("zero EBITDA must fail closed, got %+v", failure)
	}
	wrongShares := runtimeRequest(t, "valuation.enterprise_to_equity_detailed", []contracts.EngineInput{
		quantityInput("enterprise_value", "1000", "currency", "USD", "FY2025"),
		quantityInput("debt", "200", "currency", "USD", "FY2025"),
		quantityInput("cash", "80", "currency", "USD", "FY2025"),
		quantityInput("investments", "40", "currency", "USD", "FY2025"),
		quantityInput("minority_interest", "20", "currency", "USD", "FY2025"),
		quantityInput("option_value", "10", "currency", "USD", "FY2025"),
		quantityInput("diluted_shares", "100", "currency", "USD", "FY2025"),
	})
	if failure := executor.Execute(wrongShares).Failure; failure == nil ||
		failure.FailureCode != "unit_mismatch" {
		t.Fatalf("monetary diluted shares must fail the unit contract, got %+v", failure)
	}
	misalignedCashRatio := runtimeRequest(t, "financial.cash_ratio", []contracts.EngineInput{
		quantityInput("cash_and_equivalents", "10", "currency", "USD", "FY2025"),
		quantityInput("marketable_securities", "5", "currency", "USD", "FY2025"),
		quantityInput("current_liabilities", "25", "currency", "USD", "FY2024"),
	})
	if failure := executor.Execute(misalignedCashRatio).Failure; failure == nil ||
		failure.FailureCode != "period_mismatch" {
		t.Fatalf("misaligned cash-ratio periods must fail closed, got %+v", failure)
	}
}
