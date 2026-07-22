package capability

import "github.com/rvbernucci/signalforge/internal/roles"

func Tier0Registry() Registry {
	registry, err := NewRegistry(tier0Operations())
	if err != nil {
		panic(err)
	}
	return registry
}

func tier0Operations() []Operation {
	financialRoles := []string{roles.AccountingReporting, roles.FinancialQuality, roles.Valuation, roles.EvidenceCritic}
	valuationRoles := []string{roles.Valuation, roles.EvidenceCritic}
	marketRoles := []string{roles.MarketBehavior, roles.EconomicsTransmission, roles.EvidenceCritic}
	return []Operation{
		op("accounting.balance_sheet_identity", "accounting", "Validate assets against liabilities plus equity.", "money-decimal/v1", []string{"assets", "liabilities", "equity"}, []string{"difference", "within_tolerance"}, financialRoles, false),
		op("financial.revenue_growth", "financial", "Calculate period-aligned revenue growth.", "ratio-decimal/v1", []string{"revenue_current", "revenue_prior"}, []string{"growth_rate"}, financialRoles, false),
		op("financial.cagr", "financial", "Calculate compound annual growth over a valid duration.", "ratio-decimal/v1", []string{"value_start", "value_end", "years"}, []string{"cagr"}, financialRoles, false),
		op("financial.margin", "financial", "Calculate a named profit or cash-flow margin.", "ratio-decimal/v1", []string{"numerator", "revenue"}, []string{"margin"}, financialRoles, false),
		op("financial.free_cash_flow", "financial", "Calculate normalized free cash flow from registered inputs.", "money-decimal/v1", []string{"operating_cash_flow", "capital_expenditure"}, []string{"free_cash_flow"}, financialRoles, false),
		op("financial.cash_conversion", "financial", "Compare cash generation with earnings on aligned periods.", "ratio-decimal/v1", []string{"operating_cash_flow", "net_income"}, []string{"cash_conversion"}, financialRoles, false),
		op("financial.capex_intensity", "financial", "Calculate capital expenditure relative to revenue.", "ratio-decimal/v1", []string{"capital_expenditure", "revenue"}, []string{"capex_intensity"}, financialRoles, false),
		op("financial.net_debt", "financial", "Bridge gross debt and cash to net debt.", "money-decimal/v1", []string{"debt", "cash_and_equivalents"}, []string{"net_debt"}, financialRoles, false),
		op("financial.dilution", "financial", "Calculate period-aligned change in diluted shares.", "ratio-decimal/v1", []string{"shares_current", "shares_prior"}, []string{"dilution_rate"}, financialRoles, false),
		op("financial.roic_proxy", "financial", "Calculate the disclosed Tier 0 return-on-invested-capital proxy.", "ratio-decimal/v1", []string{"nopat", "invested_capital"}, []string{"roic_proxy"}, financialRoles, false),
		op("financial.current_ratio", "financial", "Calculate current assets relative to current liabilities.", "ratio-decimal/v1", []string{"current_assets", "current_liabilities"}, []string{"current_ratio"}, financialRoles, false),
		op("financial.debt_to_equity", "financial", "Calculate debt relative to equity on an aligned balance-sheet date.", "ratio-decimal/v1", []string{"debt", "equity"}, []string{"debt_to_equity"}, financialRoles, false),
		op("financial.earnings_per_share", "financial", "Calculate earnings per diluted share on an aligned period.", "money-decimal/v1", []string{"net_income", "diluted_shares"}, []string{"earnings_per_share"}, financialRoles, false),
		op("financial.quality_of_earnings", "financial", "Bridge operating cash flow to net income and cash conversion.", "mixed-numeric/v1", []string{"operating_cash_flow", "net_income"}, []string{"accrual_gap", "cash_conversion"}, financialRoles, false),
		op("valuation.fcff_dcf", "valuation", "Calculate enterprise value from explicit FCFF forecasts and terminal assumptions.", "money-decimal/v1", []string{"fcff_forecast", "discount_rate", "terminal_growth"}, []string{"enterprise_value", "present_values"}, valuationRoles, true),
		op("valuation.reverse_dcf", "valuation", "Solve for the terminal-growth assumption implied by an enterprise value.", "mixed-numeric/v1", []string{"enterprise_value", "base_fcff", "discount_rate", "years"}, []string{"implied_growth"}, valuationRoles, true),
		op("valuation.enterprise_to_equity", "valuation", "Bridge enterprise value to equity value and per-share value.", "money-decimal/v1", []string{"enterprise_value", "net_debt", "non_operating_assets", "diluted_shares"}, []string{"equity_value", "value_per_share"}, valuationRoles, true),
		op("valuation.peer_multiple", "valuation", "Calculate aligned P/E or EV-based comparison statistics.", "mixed-numeric/v1", []string{"market_value", "metric_value"}, []string{"multiple"}, valuationRoles, false),
		op("valuation.wacc", "valuation", "Calculate capital-weighted after-tax cost of capital from explicit inputs.", "ratio-decimal/v1", []string{"equity_value", "debt_value", "cost_of_equity", "pre_tax_cost_of_debt", "tax_rate"}, []string{"wacc"}, valuationRoles, true),
		op("economics.real_rate", "economics", "Calculate an explicitly defined real-rate transform.", "ratio-float64/v1", []string{"nominal_rate", "inflation_measure"}, []string{"real_rate"}, []string{roles.EconomicsTransmission, roles.Valuation, roles.EvidenceCritic}, false),
		op("economics.yield_curve", "economics", "Calculate a named yield-curve spread.", "ratio-float64/v1", []string{"long_yield", "short_yield"}, []string{"spread"}, []string{roles.EconomicsTransmission, roles.Valuation, roles.EvidenceCritic}, false),
		op("market.total_return", "market", "Calculate point-to-point total return from start price, end price, and distributions.", "statistics-float64/v1", []string{"start_price", "end_price", "distributions"}, []string{"total_return"}, marketRoles, false),
		op("market.volatility", "market", "Calculate annualized volatility from an aligned return series.", "statistics-float64/v1", []string{"returns", "periods_per_year"}, []string{"volatility"}, marketRoles, false),
		op("market.drawdown", "market", "Calculate drawdown and maximum drawdown under the registered convention.", "statistics-float64/v1", []string{"wealth_index"}, []string{"drawdown_series", "maximum_drawdown"}, marketRoles, false),
		op("market.beta", "market", "Calculate beta against an aligned benchmark return series.", "statistics-float64/v1", []string{"security_returns", "benchmark_returns"}, []string{"beta", "observations"}, marketRoles, false),
		op("market.rolling_correlation", "market", "Calculate rolling correlation over an explicit window.", "statistics-float64/v1", []string{"series_x", "series_y", "window"}, []string{"rolling_correlation"}, marketRoles, false),
		op("comparison.period_aligned", "comparison", "Compare company metrics under the exact period, unit, and currency policy.", "mixed-numeric/v1", []string{"company_metrics"}, []string{"comparison", "warnings"}, []string{roles.FinancialQuality, roles.Valuation, roles.EvidenceCritic}, false),
		op("scenario.sensitivity_matrix", "comparison", "Evaluate FCFF DCF across explicit discount-rate and terminal-growth axes.", "mixed-numeric/v1", []string{"fcff_forecast", "discount_rates", "terminal_growth_rates"}, []string{"scenario_matrix"}, valuationRoles, true),
	}
}

func op(id, engine, description, policy string, inputs, outputs, roles []string, assumptions bool) Operation {
	return Operation{
		ID: id, Engine: engine, FormulaVersion: "1.0.0", Description: description,
		NumericalPolicy: policy, RequiredInputs: inputs, Outputs: outputs,
		AllowedRoles: roles, AssumptionsAllowed: assumptions,
		InputSchema: "contracts/engine-request.schema.json", OutputSchema: "contracts/calculation-receipt.schema.json",
		TimeoutMS: 5000, SideEffectClass: "none",
	}
}
