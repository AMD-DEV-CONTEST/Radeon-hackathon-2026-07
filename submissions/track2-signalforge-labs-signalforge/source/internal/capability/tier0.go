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

func FinancialIntelligenceRegistry() Registry {
	registry, err := NewRegistry(financialIntelligenceOperations())
	if err != nil {
		panic(err)
	}
	return registry
}

func RuntimeRegistry() Registry {
	operations := append(tier0Operations(), financialIntelligenceOperations()...)
	registry, err := NewRegistry(operations)
	if err != nil {
		panic(err)
	}
	return registry
}

func financialIntelligenceOperations() []Operation {
	financialRoles := []string{roles.AccountingReporting, roles.FinancialQuality, roles.Valuation, roles.EvidenceCritic}
	valuationRoles := []string{roles.Valuation, roles.EvidenceCritic}
	marketRoles := []string{roles.MarketBehavior, roles.EconomicsTransmission, roles.EvidenceCritic}
	return []Operation{
		op("financial.nopat", "financial", "Calculate after-tax operating profit from an explicit tax rate.", "money-decimal/v1", []string{"operating_income", "tax_rate"}, []string{"nopat"}, financialRoles, true),
		op("financial.invested_capital", "financial", "Reconcile operating and financing definitions of invested capital.", "mixed-numeric/v1", []string{"operating_assets", "non_interest_bearing_operating_liabilities", "debt", "equity", "cash_and_equivalents", "non_operating_assets"}, []string{"operating_approach", "financing_approach", "difference"}, financialRoles, false),
		op("financial.average_invested_capital", "financial", "Calculate average invested capital from beginning and ending balances.", "money-decimal/v1", []string{"invested_capital_beginning", "invested_capital_ending"}, []string{"average_invested_capital"}, financialRoles, false),
		op("financial.operating_working_capital", "financial", "Calculate operating working capital from registered operating components.", "money-decimal/v1", []string{"accounts_receivable", "inventory", "other_operating_current_assets", "accounts_payable", "other_operating_current_liabilities"}, []string{"operating_working_capital"}, financialRoles, false),
		op("financial.change_in_working_capital", "financial", "Calculate the period change in operating working capital.", "money-decimal/v1", []string{"operating_working_capital_ending", "operating_working_capital_beginning"}, []string{"change_in_working_capital"}, financialRoles, false),
		op("financial.net_capex", "financial", "Calculate net capital expenditure after depreciation and amortization.", "money-decimal/v1", []string{"capital_expenditure", "depreciation_and_amortization"}, []string{"net_capex"}, financialRoles, false),
		op("financial.reinvestment", "financial", "Calculate reinvestment from net capex, working-capital change, and acquisitions.", "money-decimal/v1", []string{"net_capex", "change_in_working_capital", "acquisitions"}, []string{"reinvestment"}, financialRoles, false),
		op("financial.fcff_from_nopat", "financial", "Calculate free cash flow to the firm from NOPAT and reinvestment.", "money-decimal/v1", []string{"nopat", "reinvestment"}, []string{"fcff"}, financialRoles, false),
		op("financial.fcfe", "financial", "Calculate free cash flow to equity from earnings, reinvestment, and borrowing.", "money-decimal/v1", []string{"net_income", "capital_expenditure", "depreciation_and_amortization", "change_in_working_capital", "net_borrowing"}, []string{"fcfe"}, financialRoles, false),
		op("financial.roic", "financial", "Calculate governed return on invested capital.", "ratio-decimal/v1", []string{"nopat", "average_invested_capital"}, []string{"roic"}, financialRoles, false),
		op("financial.incremental_roic", "financial", "Calculate incremental return on newly invested capital.", "ratio-decimal/v1", []string{"change_in_nopat", "change_in_invested_capital"}, []string{"incremental_roic"}, financialRoles, false),
		op("financial.roce", "financial", "Calculate EBIT relative to governed capital employed.", "ratio-decimal/v1", []string{"ebit", "total_assets", "current_liabilities"}, []string{"roce"}, financialRoles, false),
		op("financial.value_creation_spread", "financial", "Calculate ROIC less WACC under aligned definitions.", "ratio-decimal/v1", []string{"roic", "wacc"}, []string{"value_creation_spread"}, financialRoles, false),
		op("financial.reinvestment_rate", "financial", "Calculate reinvestment relative to positive NOPAT.", "ratio-decimal/v1", []string{"reinvestment", "nopat"}, []string{"reinvestment_rate"}, financialRoles, false),
		op("financial.fundamental_growth", "financial", "Calculate fundamental growth from return on capital and reinvestment rate.", "ratio-decimal/v1", []string{"return_on_capital", "reinvestment_rate"}, []string{"fundamental_growth"}, financialRoles, true),
		op("financial.operating_margin", "financial", "Calculate typed operating margin.", "ratio-decimal/v1", []string{"operating_income", "revenue"}, []string{"operating_margin"}, financialRoles, false),
		op("financial.incremental_margin", "financial", "Calculate incremental operating margin across aligned periods.", "ratio-decimal/v1", []string{"operating_income_current", "operating_income_prior", "revenue_current", "revenue_prior"}, []string{"incremental_margin"}, financialRoles, false),
		op("financial.accrual_intensity", "financial", "Calculate accrual intensity relative to average assets.", "ratio-decimal/v1", []string{"net_income", "operating_cash_flow", "average_assets"}, []string{"accrual_intensity"}, financialRoles, false),
		op("financial.cash_conversion_cycle", "financial", "Calculate the cash conversion cycle from DSO, DIO, and DPO.", "mixed-numeric/v1", []string{"days_sales_outstanding", "days_inventory_outstanding", "days_payables_outstanding"}, []string{"cash_conversion_cycle"}, financialRoles, false),
		op("financial.quick_ratio", "financial", "Calculate liquid current assets relative to current liabilities.", "ratio-decimal/v1", []string{"cash_and_equivalents", "marketable_securities", "accounts_receivable", "current_liabilities"}, []string{"quick_ratio"}, financialRoles, false),
		op("financial.cash_ratio", "financial", "Calculate cash and marketable securities relative to current liabilities.", "ratio-decimal/v1", []string{"cash_and_equivalents", "marketable_securities", "current_liabilities"}, []string{"cash_ratio"}, financialRoles, false),
		op("financial.interest_coverage", "financial", "Calculate EBIT coverage of positive interest expense.", "ratio-decimal/v1", []string{"ebit", "interest_expense"}, []string{"interest_coverage"}, financialRoles, false),
		op("financial.net_debt_to_ebitda", "financial", "Calculate net debt relative to positive EBITDA.", "ratio-decimal/v1", []string{"net_debt", "ebitda"}, []string{"net_debt_to_ebitda"}, financialRoles, false),
		op("financial.cash_conversion_ebitda", "financial", "Calculate operating-cash-flow conversion against EBITDA.", "ratio-decimal/v1", []string{"operating_cash_flow", "ebitda"}, []string{"cash_conversion_ebitda"}, financialRoles, false),
		op("financial.cash_conversion_operating_profit", "financial", "Calculate operating-cash-flow conversion against operating profit.", "ratio-decimal/v1", []string{"operating_cash_flow", "operating_profit"}, []string{"cash_conversion_operating_profit"}, financialRoles, false),
		op("financial.buyback_yield", "financial", "Calculate net repurchases relative to equity market value.", "ratio-decimal/v1", []string{"net_repurchases", "market_capitalization"}, []string{"buyback_yield"}, financialRoles, false),
		op("financial.dividend_yield", "financial", "Calculate dividends paid relative to equity market value.", "ratio-decimal/v1", []string{"dividends_paid", "market_capitalization"}, []string{"dividend_yield"}, financialRoles, false),
		op("financial.net_payout_yield", "financial", "Calculate dividends plus net repurchases relative to equity market value.", "ratio-decimal/v1", []string{"net_repurchases", "dividends_paid", "market_capitalization"}, []string{"net_payout_yield"}, financialRoles, false),
		op("financial.shareholder_yield", "financial", "Calculate dividends, net repurchases, and net debt reduction relative to market capitalization.", "ratio-decimal/v1", []string{"net_repurchases", "dividends_paid", "net_debt_reduction", "market_capitalization"}, []string{"shareholder_yield"}, financialRoles, false),
		op("financial.capital_allocation_bridge", "financial", "Reconcile cash sources, capital uses, and the reported change in cash.", "mixed-numeric/v1", []string{"operating_cash_flow", "debt_issuance", "equity_issuance", "asset_sales", "capital_expenditure", "acquisitions", "debt_repayment", "dividends", "repurchases", "reported_change_in_cash", "tolerance"}, []string{"total_sources", "total_uses", "implied_change_in_cash", "reconciliation_gap", "within_tolerance"}, financialRoles, false),
		op("valuation.capm", "valuation", "Calculate cost of equity from risk-free rate, beta, and equity risk premium.", "ratio-decimal/v1", []string{"risk_free_rate", "beta", "equity_risk_premium"}, []string{"cost_of_equity"}, valuationRoles, true),
		op("valuation.unlever_beta", "valuation", "Remove the registered debt and tax effect from levered beta.", "ratio-decimal/v1", []string{"levered_beta", "debt", "equity", "tax_rate"}, []string{"unlevered_beta"}, valuationRoles, true),
		op("valuation.relever_beta", "valuation", "Apply the registered debt and tax effect to unlevered beta.", "ratio-decimal/v1", []string{"unlevered_beta", "debt", "equity", "tax_rate"}, []string{"relevered_beta"}, valuationRoles, true),
		op("valuation.multistage_dcf_perpetuity", "valuation", "Calculate multi-stage DCF using a perpetuity-growth terminal value.", "mixed-numeric/v1", []string{"fcff_forecast", "discount_rate", "terminal_growth", "mid_year"}, []string{"enterprise_value", "explicit_present_value", "terminal_value", "terminal_present_value", "terminal_value_share"}, valuationRoles, true),
		op("valuation.multistage_dcf_exit", "valuation", "Calculate multi-stage DCF using an exit-multiple terminal value.", "mixed-numeric/v1", []string{"fcff_forecast", "discount_rate", "exit_metric", "exit_multiple", "mid_year"}, []string{"enterprise_value", "explicit_present_value", "terminal_value", "terminal_present_value", "terminal_value_share"}, valuationRoles, true),
		op("valuation.dividend_discount", "valuation", "Calculate an applicable multi-stage dividend discount model.", "mixed-numeric/v1", []string{"dividend_forecast", "cost_of_equity", "terminal_growth", "mid_year"}, []string{"equity_value", "explicit_present_value", "terminal_value", "terminal_present_value", "terminal_value_share"}, valuationRoles, true),
		op("valuation.reverse_revenue_growth", "valuation", "Solve the revenue growth implied by enterprise value under explicit operating assumptions.", "mixed-numeric/v1", []string{"enterprise_value", "base_revenue", "operating_margin", "tax_rate", "reinvestment_rate", "discount_rate", "terminal_growth", "years"}, []string{"implied_revenue_growth", "iterations"}, valuationRoles, true),
		op("valuation.reverse_operating_margin", "valuation", "Solve the operating margin implied by enterprise value.", "mixed-numeric/v1", []string{"enterprise_value", "base_revenue", "revenue_growth", "tax_rate", "reinvestment_rate", "discount_rate", "terminal_growth", "years"}, []string{"implied_operating_margin", "iterations"}, valuationRoles, true),
		op("valuation.reverse_reinvestment_rate", "valuation", "Solve the reinvestment rate implied by enterprise value.", "mixed-numeric/v1", []string{"enterprise_value", "base_revenue", "revenue_growth", "operating_margin", "tax_rate", "discount_rate", "terminal_growth", "years"}, []string{"implied_reinvestment_rate", "iterations"}, valuationRoles, true),
		op("valuation.implied_roic", "valuation", "Calculate return on capital implied by growth and reinvestment.", "ratio-decimal/v1", []string{"growth_rate", "reinvestment_rate"}, []string{"implied_roic"}, valuationRoles, true),
		op("valuation.enterprise_to_equity_detailed", "valuation", "Bridge enterprise value to diluted equity value with explicit debt, cash, investments, minority interest, and options.", "mixed-numeric/v1", []string{"enterprise_value", "debt", "cash", "investments", "minority_interest", "option_value", "diluted_shares"}, []string{"equity_value", "value_per_diluted_share"}, valuationRoles, true),
		op("valuation.ev_to_ebitda", "valuation", "Calculate enterprise value to positive EBITDA.", "ratio-decimal/v1", []string{"enterprise_value", "ebitda"}, []string{"ev_to_ebitda"}, valuationRoles, false),
		op("valuation.ev_to_revenue", "valuation", "Calculate enterprise value to positive revenue.", "ratio-decimal/v1", []string{"enterprise_value", "revenue"}, []string{"ev_to_revenue"}, valuationRoles, false),
		op("valuation.ev_to_ebit", "valuation", "Calculate enterprise value to positive EBIT.", "ratio-decimal/v1", []string{"enterprise_value", "ebit"}, []string{"ev_to_ebit"}, valuationRoles, false),
		op("valuation.price_to_earnings", "valuation", "Calculate equity market value to positive net income.", "ratio-decimal/v1", []string{"equity_market_value", "net_income"}, []string{"price_to_earnings"}, valuationRoles, false),
		op("valuation.price_to_book", "valuation", "Calculate equity market value to positive book equity.", "ratio-decimal/v1", []string{"equity_market_value", "book_equity"}, []string{"price_to_book"}, valuationRoles, false),
		op("valuation.price_to_fcf", "valuation", "Calculate equity market value to positive free cash flow to equity.", "ratio-decimal/v1", []string{"equity_market_value", "free_cash_flow_to_equity"}, []string{"price_to_fcf"}, valuationRoles, false),
		op("valuation.fcf_yield", "valuation", "Calculate free cash flow to equity relative to equity market value.", "ratio-decimal/v1", []string{"free_cash_flow_to_equity", "equity_market_value"}, []string{"fcf_yield"}, valuationRoles, false),
		op("valuation.earnings_yield", "valuation", "Calculate net income relative to equity market value.", "ratio-decimal/v1", []string{"net_income", "equity_market_value"}, []string{"earnings_yield"}, valuationRoles, false),
		op("comparison.dupont", "comparison", "Decompose return on equity into margin, turnover, and leverage.", "mixed-numeric/v1", []string{"net_income", "revenue", "average_assets", "average_equity"}, []string{"net_margin", "asset_turnover", "financial_leverage", "return_on_equity"}, financialRoles, false),
		op("comparison.peer_statistics", "comparison", "Calculate robust peer context for a subject multiple.", "statistics-float64/v1", []string{"peer_values", "subject_value", "minimum_sample"}, []string{"median", "percentile", "median_absolute_deviation", "robust_z_score", "observations"}, valuationRoles, false),
		op("economics.lagged_association", "economics", "Estimate a lagged linear association without causal attribution.", "statistics-float64/v1", []string{"driver_series", "outcome_series", "lag", "minimum_sample"}, []string{"slope", "intercept", "correlation", "r_squared", "observations", "lag"}, marketRoles, false),
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
