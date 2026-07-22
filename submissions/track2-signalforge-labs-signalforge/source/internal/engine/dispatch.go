package engine

import (
	"errors"
	"fmt"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/finance"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

func dispatch(operationID string, inputs inputSet) ([]contracts.ReceiptOutput, []contracts.InvariantResult, []string, error) {
	currency := firstCurrency(inputs)
	scalar := func(name string) (numeric.Decimal, error) { return inputs.decimal(name) }
	ratioOutput := func(id string, value numeric.Decimal, err error) ([]contracts.ReceiptOutput, []contracts.InvariantResult, []string, error) {
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{decimalOutput(id, value, "ratio", "")}, nil, nil, nil
	}
	moneyOutput := func(id string, value numeric.Decimal, err error) ([]contracts.ReceiptOutput, []contracts.InvariantResult, []string, error) {
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{decimalOutput(id, value, "currency", currency)}, nil, nil, nil
	}

	switch operationID {
	case "accounting.balance_sheet_identity":
		assets, err := scalar("assets")
		if err != nil {
			return nil, nil, nil, err
		}
		liabilities, err := scalar("liabilities")
		if err != nil {
			return nil, nil, nil, err
		}
		equity, err := scalar("equity")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.BalanceSheetIdentity(assets, liabilities, equity, numeric.MustDecimal("0.01"))
		if err != nil {
			return nil, nil, nil, err
		}
		invariant := contracts.InvariantResult{InvariantID: "assets_equals_liabilities_plus_equity", Passed: result.WithinTolerance, Detail: "absolute difference must not exceed 0.01 source-currency units"}
		if !result.WithinTolerance {
			return nil, []contracts.InvariantResult{invariant}, nil, errors.New("invariant_failed: balance sheet does not reconcile")
		}
		return []contracts.ReceiptOutput{decimalOutput("difference", result.Difference, "currency", currency), boolOutput("within_tolerance", true)}, []contracts.InvariantResult{invariant}, nil, nil
	case "financial.revenue_growth":
		current, err := scalar("revenue_current")
		if err != nil {
			return nil, nil, nil, err
		}
		prior, err := scalar("revenue_prior")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.Growth(current, prior)
		return ratioOutput("growth_rate", value, calculationErr)
	case "financial.cagr":
		start, err := scalar("value_start")
		if err != nil {
			return nil, nil, nil, err
		}
		end, err := scalar("value_end")
		if err != nil {
			return nil, nil, nil, err
		}
		years, err := scalar("years")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.CAGR(start, end, years)
		return ratioOutput("cagr", value, calculationErr)
	case "financial.margin":
		numerator, err := scalar("numerator")
		if err != nil {
			return nil, nil, nil, err
		}
		revenue, err := scalar("revenue")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.Margin(numerator, revenue)
		return ratioOutput("margin", value, calculationErr)
	case "financial.free_cash_flow":
		ocf, err := scalar("operating_cash_flow")
		if err != nil {
			return nil, nil, nil, err
		}
		capex, err := scalar("capital_expenditure")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.FreeCashFlow(ocf, capex)
		return moneyOutput("free_cash_flow", value, calculationErr)
	case "financial.cash_conversion":
		ocf, err := scalar("operating_cash_flow")
		if err != nil {
			return nil, nil, nil, err
		}
		income, err := scalar("net_income")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.CashConversion(ocf, income)
		return ratioOutput("cash_conversion", value, calculationErr)
	case "financial.capex_intensity":
		capex, err := scalar("capital_expenditure")
		if err != nil {
			return nil, nil, nil, err
		}
		revenue, err := scalar("revenue")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.CapexIntensity(capex, revenue)
		return ratioOutput("capex_intensity", value, calculationErr)
	case "financial.net_debt":
		debt, err := scalar("debt")
		if err != nil {
			return nil, nil, nil, err
		}
		cash, err := scalar("cash_and_equivalents")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.NetDebt(debt, cash)
		return moneyOutput("net_debt", value, calculationErr)
	case "financial.dilution":
		current, err := scalar("shares_current")
		if err != nil {
			return nil, nil, nil, err
		}
		prior, err := scalar("shares_prior")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.Dilution(current, prior)
		return ratioOutput("dilution_rate", value, calculationErr)
	case "financial.roic_proxy":
		nopat, err := scalar("nopat")
		if err != nil {
			return nil, nil, nil, err
		}
		capital, err := scalar("invested_capital")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ROICProxy(nopat, capital)
		return ratioOutput("roic_proxy", value, calculationErr)
	case "financial.current_ratio":
		assets, err := scalar("current_assets")
		if err != nil {
			return nil, nil, nil, err
		}
		liabilities, err := scalar("current_liabilities")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.CurrentRatio(assets, liabilities)
		return ratioOutput("current_ratio", value, calculationErr)
	case "financial.debt_to_equity":
		debt, err := scalar("debt")
		if err != nil {
			return nil, nil, nil, err
		}
		equity, err := scalar("equity")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.DebtToEquity(debt, equity)
		return ratioOutput("debt_to_equity", value, calculationErr)
	case "financial.earnings_per_share":
		income, err := scalar("net_income")
		if err != nil {
			return nil, nil, nil, err
		}
		shares, err := scalar("diluted_shares")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.EarningsPerShare(income, shares)
		if calculationErr != nil {
			return nil, nil, nil, calculationErr
		}
		return []contracts.ReceiptOutput{decimalOutput("earnings_per_share", value, "currency_per_share", currency)}, nil, nil, nil
	case "financial.quality_of_earnings":
		ocf, err := scalar("operating_cash_flow")
		if err != nil {
			return nil, nil, nil, err
		}
		income, err := scalar("net_income")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.QualityOfEarnings(ocf, income)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{decimalOutput("accrual_gap", result.AccrualGap, "currency", currency), decimalOutput("cash_conversion", result.CashConversion, "ratio", "")}, nil, nil, nil
	case "valuation.fcff_dcf":
		forecast, err := inputs.decimalSeries("fcff_forecast")
		if err != nil {
			return nil, nil, nil, err
		}
		rate, err := scalar("discount_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		growth, err := scalar("terminal_growth")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.FCFFDCF(forecast, rate, growth)
		if err != nil {
			return nil, nil, nil, err
		}
		outputs := []contracts.ReceiptOutput{
			decimalOutput("enterprise_value", result.EnterpriseValue, "currency", currency),
			decimalOutput("explicit_present_value", result.ExplicitPresentValue, "currency", currency),
			decimalOutput("terminal_present_value", result.TerminalPresentValue, "currency", currency),
		}
		for index, value := range result.PresentValues {
			outputs = append(outputs, decimalOutput(fmt.Sprintf("present_values.%d", index), value, "currency", currency))
		}
		return outputs, nil, nil, nil
	case "valuation.reverse_dcf":
		target, err := scalar("enterprise_value")
		if err != nil {
			return nil, nil, nil, err
		}
		base, err := scalar("base_fcff")
		if err != nil {
			return nil, nil, nil, err
		}
		rate, err := scalar("discount_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		years, err := inputs.integer("years")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.ReverseDCF(target, base, rate, years, numeric.MustDecimal("0.00000001"), 256)
		if err != nil {
			return nil, nil, nil, err
		}
		if !result.Converged {
			return nil, nil, nil, errors.New("non_convergent: reverse DCF exhausted iteration budget")
		}
		return []contracts.ReceiptOutput{decimalOutput("implied_growth", result.ImpliedGrowth, "ratio", ""), intOutput("iterations", result.Iterations, "count")}, []contracts.InvariantResult{{InvariantID: "reverse_dcf_converged", Passed: true}}, nil, nil
	case "valuation.enterprise_to_equity":
		enterprise, err := scalar("enterprise_value")
		if err != nil {
			return nil, nil, nil, err
		}
		netDebt, err := scalar("net_debt")
		if err != nil {
			return nil, nil, nil, err
		}
		assets, err := scalar("non_operating_assets")
		if err != nil {
			return nil, nil, nil, err
		}
		shares, err := scalar("diluted_shares")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.EnterpriseToEquity(enterprise, netDebt, assets, shares)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{decimalOutput("equity_value", result.EquityValue, "currency", currency), decimalOutput("value_per_share", result.ValuePerShare, "currency_per_share", currency)}, nil, nil, nil
	case "valuation.peer_multiple":
		market, err := scalar("market_value")
		if err != nil {
			return nil, nil, nil, err
		}
		metric, err := scalar("metric_value")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.PeerMultiple(market, metric)
		return ratioOutput("multiple", value, calculationErr)
	case "valuation.wacc":
		equity, err := scalar("equity_value")
		if err != nil {
			return nil, nil, nil, err
		}
		debt, err := scalar("debt_value")
		if err != nil {
			return nil, nil, nil, err
		}
		costOfEquity, err := scalar("cost_of_equity")
		if err != nil {
			return nil, nil, nil, err
		}
		costOfDebt, err := scalar("pre_tax_cost_of_debt")
		if err != nil {
			return nil, nil, nil, err
		}
		taxRate, err := scalar("tax_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.WACC(equity, debt, costOfEquity, costOfDebt, taxRate)
		return ratioOutput("wacc", value, calculationErr)
	case "economics.real_rate":
		nominal, err := scalar("nominal_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		inflation, err := scalar("inflation_measure")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.RealRate(nominal, inflation)
		return ratioOutput("real_rate", value, calculationErr)
	case "economics.yield_curve":
		longYield, err := scalar("long_yield")
		if err != nil {
			return nil, nil, nil, err
		}
		shortYield, err := scalar("short_yield")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.YieldCurveSpread(longYield, shortYield)
		return ratioOutput("spread", value, calculationErr)
	case "market.total_return":
		start, err := inputs.float("start_price")
		if err != nil {
			return nil, nil, nil, err
		}
		end, err := inputs.float("end_price")
		if err != nil {
			return nil, nil, nil, err
		}
		distributions, err := inputs.float("distributions")
		if err != nil {
			return nil, nil, nil, err
		}
		value, err := finance.TotalReturn(start, end, distributions)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{floatOutput("total_return", value, "ratio")}, nil, nil, nil
	case "market.volatility":
		returns, err := inputs.floatSeries("returns")
		if err != nil {
			return nil, nil, nil, err
		}
		periods, err := inputs.float("periods_per_year")
		if err != nil {
			return nil, nil, nil, err
		}
		ddof := 1
		if inputs.has("ddof") {
			ddof, err = inputs.integer("ddof")
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, err := finance.Volatility(returns, periods, ddof)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{floatOutput("volatility", value, "ratio")}, nil, nil, nil
	case "market.drawdown":
		wealth, err := inputs.floatSeries("wealth_index")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.Drawdown(wealth)
		if err != nil {
			return nil, nil, nil, err
		}
		outputs := []contracts.ReceiptOutput{floatOutput("maximum_drawdown", result.Maximum, "ratio")}
		for index, value := range result.Series {
			outputs = append(outputs, floatOutput(fmt.Sprintf("drawdown_series.%d", index), value, "ratio"))
		}
		return outputs, nil, nil, nil
	case "market.beta":
		security, err := inputs.floatSeries("security_returns")
		if err != nil {
			return nil, nil, nil, err
		}
		benchmark, err := inputs.floatSeries("benchmark_returns")
		if err != nil {
			return nil, nil, nil, err
		}
		ddof := 1
		if inputs.has("ddof") {
			ddof, err = inputs.integer("ddof")
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, observations, err := finance.Beta(security, benchmark, ddof)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{floatOutput("beta", value, "ratio"), intOutput("observations", observations, "count")}, nil, nil, nil
	case "market.rolling_correlation":
		left, err := inputs.floatSeries("series_x")
		if err != nil {
			return nil, nil, nil, err
		}
		right, err := inputs.floatSeries("series_y")
		if err != nil {
			return nil, nil, nil, err
		}
		window, err := inputs.integer("window")
		if err != nil {
			return nil, nil, nil, err
		}
		values, err := finance.RollingCorrelation(left, right, window)
		if err != nil {
			return nil, nil, nil, err
		}
		outputs := make([]contracts.ReceiptOutput, 0, len(values))
		for index, value := range values {
			outputs = append(outputs, floatOutput(fmt.Sprintf("rolling_correlation.%d", index), value, "ratio"))
		}
		return outputs, nil, nil, nil
	case "comparison.period_aligned":
		series, err := inputs.series("company_metrics")
		if err != nil {
			return nil, nil, nil, err
		}
		metrics := make([]finance.ComparableMetric, len(series))
		for index, input := range series {
			value, err := numeric.ParseDecimal(input.Quantity.Value)
			if err != nil {
				return nil, nil, nil, err
			}
			metrics[index] = finance.ComparableMetric{Company: fmt.Sprintf("company-%d", index), Value: value, Period: input.Quantity.Period, Unit: input.Quantity.Unit, Currency: input.Quantity.Currency}
		}
		result, err := finance.PeriodAligned(metrics, "exact")
		if err != nil {
			return nil, nil, nil, err
		}
		if !result.Comparable {
			return nil, nil, result.Warnings, fmt.Errorf("incomparable_inputs: %v", result.Warnings)
		}
		return []contracts.ReceiptOutput{boolOutput("comparison", result.Comparable)}, nil, result.Warnings, nil
	case "scenario.sensitivity_matrix":
		forecast, err := inputs.decimalSeries("fcff_forecast")
		if err != nil {
			return nil, nil, nil, err
		}
		rates, err := inputs.decimalSeries("discount_rates")
		if err != nil {
			return nil, nil, nil, err
		}
		growths, err := inputs.decimalSeries("terminal_growth_rates")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.DCFGrid(forecast, rates, growths)
		if err != nil {
			return nil, nil, nil, err
		}
		outputs := []contracts.ReceiptOutput{intOutput("rows", result.Rows, "count"), intOutput("columns", result.Columns, "count"), boolOutput("monotonic_discount_rate", result.MonotonicDiscountRate), boolOutput("monotonic_terminal_growth", result.MonotonicTerminalGrowth)}
		for index, cell := range result.Cells {
			outputs = append(outputs, decimalOutput(fmt.Sprintf("scenario_matrix.%d", index), cell.EnterpriseValue, "currency", currency))
		}
		return outputs, nil, nil, nil
	default:
		return nil, nil, nil, errors.New("unsupported registered operation")
	}
}
