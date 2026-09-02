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
	case "financial.nopat":
		operatingIncome, err := scalar("operating_income")
		if err != nil {
			return nil, nil, nil, err
		}
		taxRate, err := scalar("tax_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.NOPAT(operatingIncome, taxRate)
		return moneyOutput("nopat", value, calculationErr)
	case "financial.invested_capital":
		values := make([]numeric.Decimal, 6)
		var err error
		for index, name := range []string{"operating_assets", "non_interest_bearing_operating_liabilities", "debt", "equity", "cash_and_equivalents", "non_operating_assets"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		result, err := finance.InvestedCapital(values[0], values[1], values[2], values[3], values[4], values[5])
		if err != nil {
			return nil, nil, nil, err
		}
		absoluteDifference, err := finance.AbsoluteDecimal(result.Difference)
		if err != nil {
			return nil, nil, nil, err
		}
		reconciles, err := finance.DecimalLessThanOrEqual(absoluteDifference, numeric.MustDecimal("0.01"))
		if err != nil {
			return nil, nil, nil, err
		}
		invariant := contracts.InvariantResult{InvariantID: "invested_capital_approaches_reconcile", Passed: reconciles, Detail: "absolute difference must not exceed 0.01 source-currency units"}
		if !reconciles {
			return nil, []contracts.InvariantResult{invariant}, nil, errors.New("invariant_failed: invested-capital approaches do not reconcile")
		}
		return []contracts.ReceiptOutput{
			decimalOutput("operating_approach", result.OperatingApproach, "currency", currency),
			decimalOutput("financing_approach", result.FinancingApproach, "currency", currency),
			decimalOutput("difference", result.Difference, "currency", currency),
		}, []contracts.InvariantResult{invariant}, nil, nil
	case "financial.average_invested_capital":
		beginning, err := scalar("invested_capital_beginning")
		if err != nil {
			return nil, nil, nil, err
		}
		ending, err := scalar("invested_capital_ending")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.AverageInvestedCapital(beginning, ending)
		return moneyOutput("average_invested_capital", value, calculationErr)
	case "financial.operating_working_capital":
		values := make([]numeric.Decimal, 5)
		var err error
		for index, name := range []string{"accounts_receivable", "inventory", "other_operating_current_assets", "accounts_payable", "other_operating_current_liabilities"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, calculationErr := finance.OperatingWorkingCapital(values[0], values[1], values[2], values[3], values[4])
		return moneyOutput("operating_working_capital", value, calculationErr)
	case "financial.change_in_working_capital":
		ending, err := scalar("operating_working_capital_ending")
		if err != nil {
			return nil, nil, nil, err
		}
		beginning, err := scalar("operating_working_capital_beginning")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ChangeInWorkingCapital(ending, beginning)
		return moneyOutput("change_in_working_capital", value, calculationErr)
	case "financial.net_capex":
		capex, err := scalar("capital_expenditure")
		if err != nil {
			return nil, nil, nil, err
		}
		depreciation, err := scalar("depreciation_and_amortization")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.NetCapitalExpenditure(capex, depreciation)
		return moneyOutput("net_capex", value, calculationErr)
	case "financial.reinvestment":
		netCapex, err := scalar("net_capex")
		if err != nil {
			return nil, nil, nil, err
		}
		workingCapital, err := scalar("change_in_working_capital")
		if err != nil {
			return nil, nil, nil, err
		}
		acquisitions, err := scalar("acquisitions")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.Reinvestment(netCapex, workingCapital, acquisitions)
		return moneyOutput("reinvestment", value, calculationErr)
	case "financial.fcff_from_nopat":
		nopat, err := scalar("nopat")
		if err != nil {
			return nil, nil, nil, err
		}
		reinvestment, err := scalar("reinvestment")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.FCFFFromNOPAT(nopat, reinvestment)
		return moneyOutput("fcff", value, calculationErr)
	case "financial.fcfe":
		values := make([]numeric.Decimal, 5)
		var err error
		for index, name := range []string{"net_income", "capital_expenditure", "depreciation_and_amortization", "change_in_working_capital", "net_borrowing"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, calculationErr := finance.FCFE(values[0], values[1], values[2], values[3], values[4])
		return moneyOutput("fcfe", value, calculationErr)
	case "financial.roic":
		nopat, err := scalar("nopat")
		if err != nil {
			return nil, nil, nil, err
		}
		capital, err := scalar("average_invested_capital")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ROIC(nopat, capital)
		return ratioOutput("roic", value, calculationErr)
	case "financial.incremental_roic":
		nopat, err := scalar("change_in_nopat")
		if err != nil {
			return nil, nil, nil, err
		}
		capital, err := scalar("change_in_invested_capital")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.IncrementalROIC(nopat, capital)
		return ratioOutput("incremental_roic", value, calculationErr)
	case "financial.roce":
		ebit, err := scalar("ebit")
		if err != nil {
			return nil, nil, nil, err
		}
		assets, err := scalar("total_assets")
		if err != nil {
			return nil, nil, nil, err
		}
		liabilities, err := scalar("current_liabilities")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ROCE(ebit, assets, liabilities)
		return ratioOutput("roce", value, calculationErr)
	case "financial.value_creation_spread":
		roic, err := scalar("roic")
		if err != nil {
			return nil, nil, nil, err
		}
		wacc, err := scalar("wacc")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ValueCreationSpread(roic, wacc)
		return ratioOutput("value_creation_spread", value, calculationErr)
	case "financial.reinvestment_rate":
		reinvestment, err := scalar("reinvestment")
		if err != nil {
			return nil, nil, nil, err
		}
		nopat, err := scalar("nopat")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ReinvestmentRate(reinvestment, nopat)
		return ratioOutput("reinvestment_rate", value, calculationErr)
	case "financial.fundamental_growth":
		returnOnCapital, err := scalar("return_on_capital")
		if err != nil {
			return nil, nil, nil, err
		}
		reinvestmentRate, err := scalar("reinvestment_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.FundamentalGrowth(returnOnCapital, reinvestmentRate)
		return ratioOutput("fundamental_growth", value, calculationErr)
	case "financial.operating_margin":
		operatingIncome, err := scalar("operating_income")
		if err != nil {
			return nil, nil, nil, err
		}
		revenue, err := scalar("revenue")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.ProfitMargin(finance.MarginOperating, operatingIncome, revenue)
		if err != nil {
			return nil, nil, nil, err
		}
		return ratioOutput("operating_margin", result.Value, nil)
	case "financial.incremental_margin":
		values := make([]numeric.Decimal, 4)
		var err error
		for index, name := range []string{"operating_income_current", "operating_income_prior", "revenue_current", "revenue_prior"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, calculationErr := finance.IncrementalMargin(values[0], values[1], values[2], values[3])
		return ratioOutput("incremental_margin", value, calculationErr)
	case "financial.accrual_intensity":
		income, err := scalar("net_income")
		if err != nil {
			return nil, nil, nil, err
		}
		cashFlow, err := scalar("operating_cash_flow")
		if err != nil {
			return nil, nil, nil, err
		}
		assets, err := scalar("average_assets")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.AccrualIntensity(income, cashFlow, assets)
		return ratioOutput("accrual_intensity", value, calculationErr)
	case "financial.cash_conversion_cycle":
		dso, err := scalar("days_sales_outstanding")
		if err != nil {
			return nil, nil, nil, err
		}
		dio, err := scalar("days_inventory_outstanding")
		if err != nil {
			return nil, nil, nil, err
		}
		dpo, err := scalar("days_payables_outstanding")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.CashConversionCycle(dso, dio, dpo)
		if calculationErr != nil {
			return nil, nil, nil, calculationErr
		}
		return []contracts.ReceiptOutput{decimalOutput("cash_conversion_cycle", value, "days", "")}, nil, nil, nil
	case "financial.quick_ratio":
		values := make([]numeric.Decimal, 4)
		var err error
		for index, name := range []string{"cash_and_equivalents", "marketable_securities", "accounts_receivable", "current_liabilities"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, calculationErr := finance.QuickRatio(values[0], values[1], values[2], values[3])
		return ratioOutput("quick_ratio", value, calculationErr)
	case "financial.cash_ratio":
		values := make([]numeric.Decimal, 3)
		var err error
		for index, name := range []string{"cash_and_equivalents", "marketable_securities", "current_liabilities"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, calculationErr := finance.CashRatio(values[0], values[1], values[2])
		return ratioOutput("cash_ratio", value, calculationErr)
	case "financial.interest_coverage":
		ebit, err := scalar("ebit")
		if err != nil {
			return nil, nil, nil, err
		}
		interest, err := scalar("interest_expense")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.InterestCoverage(ebit, interest)
		return ratioOutput("interest_coverage", value, calculationErr)
	case "financial.net_debt_to_ebitda":
		netDebt, err := scalar("net_debt")
		if err != nil {
			return nil, nil, nil, err
		}
		ebitda, err := scalar("ebitda")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.NetDebtToEBITDA(netDebt, ebitda)
		return ratioOutput("net_debt_to_ebitda", value, calculationErr)
	case "financial.cash_conversion_ebitda", "financial.cash_conversion_operating_profit":
		cashFlow, err := scalar("operating_cash_flow")
		if err != nil {
			return nil, nil, nil, err
		}
		denominatorName := "ebitda"
		kind := finance.CashConversionEBITDA
		outputID := "cash_conversion_ebitda"
		if operationID == "financial.cash_conversion_operating_profit" {
			denominatorName = "operating_profit"
			kind = finance.CashConversionOperatingProfit
			outputID = "cash_conversion_operating_profit"
		}
		denominator, err := scalar(denominatorName)
		if err != nil {
			return nil, nil, nil, err
		}
		result, calculationErr := finance.TypedCashConversion(kind, cashFlow, denominator)
		return ratioOutput(outputID, result.Value, calculationErr)
	case "financial.buyback_yield", "financial.dividend_yield":
		marketCapitalization, err := scalar("market_capitalization")
		if err != nil {
			return nil, nil, nil, err
		}
		inputName, outputID := "net_repurchases", "buyback_yield"
		if operationID == "financial.dividend_yield" {
			inputName, outputID = "dividends_paid", "dividend_yield"
		}
		amount, err := scalar(inputName)
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.BuybackYield(amount, marketCapitalization)
		if operationID == "financial.dividend_yield" {
			value, calculationErr = finance.DividendYield(amount, marketCapitalization)
		}
		return ratioOutput(outputID, value, calculationErr)
	case "financial.net_payout_yield":
		repurchases, err := scalar("net_repurchases")
		if err != nil {
			return nil, nil, nil, err
		}
		dividends, err := scalar("dividends_paid")
		if err != nil {
			return nil, nil, nil, err
		}
		marketCapitalization, err := scalar("market_capitalization")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.NetPayoutYield(repurchases, dividends, marketCapitalization)
		return ratioOutput("net_payout_yield", value, calculationErr)
	case "financial.shareholder_yield":
		values := make([]numeric.Decimal, 4)
		var err error
		for index, name := range []string{"net_repurchases", "dividends_paid", "net_debt_reduction", "market_capitalization"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		value, calculationErr := finance.ShareholderYield(values[0], values[1], values[2], values[3])
		return ratioOutput("shareholder_yield", value, calculationErr)
	case "financial.capital_allocation_bridge":
		values := make([]numeric.Decimal, 11)
		var err error
		for index, name := range []string{"operating_cash_flow", "debt_issuance", "equity_issuance", "asset_sales", "capital_expenditure", "acquisitions", "debt_repayment", "dividends", "repurchases", "reported_change_in_cash", "tolerance"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		result, err := finance.CapitalAllocationBridge(values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7], values[8], values[9], values[10])
		if err != nil {
			return nil, nil, nil, err
		}
		invariant := contracts.InvariantResult{InvariantID: "capital_allocation_reconciles", Passed: result.WithinTolerance, Detail: "cash sources less uses must reconcile to reported change within tolerance"}
		if !result.WithinTolerance {
			return nil, []contracts.InvariantResult{invariant}, nil, errors.New("invariant_failed: capital allocation bridge does not reconcile")
		}
		return []contracts.ReceiptOutput{
			decimalOutput("total_sources", result.TotalSources, "currency", currency),
			decimalOutput("total_uses", result.TotalUses, "currency", currency),
			decimalOutput("implied_change_in_cash", result.ImpliedChangeInCash, "currency", currency),
			decimalOutput("reconciliation_gap", result.ReconciliationGap, "currency", currency),
			boolOutput("within_tolerance", result.WithinTolerance),
		}, []contracts.InvariantResult{invariant}, nil, nil
	case "valuation.capm":
		riskFree, err := scalar("risk_free_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		beta, err := scalar("beta")
		if err != nil {
			return nil, nil, nil, err
		}
		premium, err := scalar("equity_risk_premium")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.CAPM(riskFree, beta, premium)
		return ratioOutput("cost_of_equity", value, calculationErr)
	case "valuation.unlever_beta", "valuation.relever_beta":
		betaName := "levered_beta"
		outputID := "unlevered_beta"
		if operationID == "valuation.relever_beta" {
			betaName = "unlevered_beta"
			outputID = "relevered_beta"
		}
		beta, err := scalar(betaName)
		if err != nil {
			return nil, nil, nil, err
		}
		debt, err := scalar("debt")
		if err != nil {
			return nil, nil, nil, err
		}
		equity, err := scalar("equity")
		if err != nil {
			return nil, nil, nil, err
		}
		taxRate, err := scalar("tax_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.UnleverBeta(beta, debt, equity, taxRate)
		if operationID == "valuation.relever_beta" {
			value, calculationErr = finance.ReleverBeta(beta, debt, equity, taxRate)
		}
		return ratioOutput(outputID, value, calculationErr)
	case "valuation.multistage_dcf_perpetuity", "valuation.multistage_dcf_exit":
		forecast, err := inputs.decimalSeries("fcff_forecast")
		if err != nil {
			return nil, nil, nil, err
		}
		discountRate, err := scalar("discount_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		midYearValue, err := inputs.integer("mid_year")
		if err != nil || (midYearValue != 0 && midYearValue != 1) {
			return nil, nil, nil, errors.New("mid_year must be encoded as zero or one")
		}
		terminal := finance.TerminalAssumption{Method: finance.TerminalPerpetuityGrowth}
		if operationID == "valuation.multistage_dcf_perpetuity" {
			terminal.GrowthRate, err = scalar("terminal_growth")
		} else {
			terminal.Method = finance.TerminalExitMultiple
			terminal.ExitMetric, err = scalar("exit_metric")
			if err == nil {
				terminal.ExitMultiple, err = scalar("exit_multiple")
			}
		}
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.MultiStageDCF(forecast, discountRate, terminal, midYearValue == 1)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{
			decimalOutput("enterprise_value", result.EnterpriseValue, "currency", currency),
			decimalOutput("explicit_present_value", result.ExplicitPresentValue, "currency", currency),
			decimalOutput("terminal_value", result.TerminalValue, "currency", currency),
			decimalOutput("terminal_present_value", result.TerminalPresentValue, "currency", currency),
			decimalOutput("terminal_value_share", result.TerminalValueShare, "ratio", ""),
		}, nil, result.Warnings, nil
	case "valuation.dividend_discount":
		dividends, err := inputs.decimalSeries("dividend_forecast")
		if err != nil {
			return nil, nil, nil, err
		}
		costOfEquity, err := scalar("cost_of_equity")
		if err != nil {
			return nil, nil, nil, err
		}
		terminalGrowth, err := scalar("terminal_growth")
		if err != nil {
			return nil, nil, nil, err
		}
		midYearValue, err := inputs.integer("mid_year")
		if err != nil || (midYearValue != 0 && midYearValue != 1) {
			return nil, nil, nil, errors.New("mid_year must be encoded as zero or one")
		}
		result, err := finance.DividendDiscountModel(dividends, costOfEquity, terminalGrowth, midYearValue == 1)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{
			decimalOutput("equity_value", result.EnterpriseValue, "currency", currency),
			decimalOutput("explicit_present_value", result.ExplicitPresentValue, "currency", currency),
			decimalOutput("terminal_value", result.TerminalValue, "currency", currency),
			decimalOutput("terminal_present_value", result.TerminalPresentValue, "currency", currency),
			decimalOutput("terminal_value_share", result.TerminalValueShare, "ratio", ""),
		}, nil, result.Warnings, nil
	case "valuation.reverse_revenue_growth":
		values := make([]numeric.Decimal, 7)
		var err error
		for index, name := range []string{"enterprise_value", "base_revenue", "operating_margin", "tax_rate", "reinvestment_rate", "discount_rate", "terminal_growth"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		years, err := inputs.integer("years")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.ReverseRevenueGrowth(values[0], values[1], values[2], values[3], values[4], values[5], values[6], years, 256, numeric.MustDecimal("0.00000001"))
		if err != nil {
			return nil, nil, nil, err
		}
		if !result.Converged {
			return nil, nil, nil, errors.New("non_convergent: reverse revenue growth exhausted iteration budget")
		}
		return []contracts.ReceiptOutput{decimalOutput("implied_revenue_growth", result.ImpliedValue, "ratio", ""), intOutput("iterations", result.Iterations, "count")}, []contracts.InvariantResult{{InvariantID: "reverse_revenue_growth_converged", Passed: true}}, nil, nil
	case "valuation.reverse_operating_margin", "valuation.reverse_reinvestment_rate":
		values := make(map[string]numeric.Decimal)
		for _, name := range []string{"enterprise_value", "base_revenue", "revenue_growth", "tax_rate", "discount_rate", "terminal_growth"} {
			value, err := scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
			values[name] = value
		}
		years, err := inputs.integer("years")
		if err != nil {
			return nil, nil, nil, err
		}
		outputID := "implied_operating_margin"
		var result finance.ReverseExpectationsResult
		if operationID == "valuation.reverse_operating_margin" {
			reinvestmentRate, err := scalar("reinvestment_rate")
			if err != nil {
				return nil, nil, nil, err
			}
			result, err = finance.ReverseOperatingMargin(
				values["enterprise_value"], values["base_revenue"], values["revenue_growth"],
				values["tax_rate"], reinvestmentRate, values["discount_rate"], values["terminal_growth"],
				years, 256, numeric.MustDecimal("0.00000001"),
			)
			if err != nil {
				return nil, nil, nil, err
			}
		} else {
			outputID = "implied_reinvestment_rate"
			operatingMargin, err := scalar("operating_margin")
			if err != nil {
				return nil, nil, nil, err
			}
			result, err = finance.ReverseReinvestmentRate(
				values["enterprise_value"], values["base_revenue"], values["revenue_growth"],
				operatingMargin, values["tax_rate"], values["discount_rate"], values["terminal_growth"],
				years, 256, numeric.MustDecimal("0.00000001"),
			)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		if !result.Converged {
			return nil, nil, nil, errors.New("non_convergent: reverse expectation exhausted iteration budget")
		}
		return []contracts.ReceiptOutput{decimalOutput(outputID, result.ImpliedValue, "ratio", ""), intOutput("iterations", result.Iterations, "count")}, []contracts.InvariantResult{{InvariantID: outputID + "_converged", Passed: true}}, nil, nil
	case "valuation.implied_roic":
		growth, err := scalar("growth_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		reinvestment, err := scalar("reinvestment_rate")
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.ImpliedReturnOnCapital(growth, reinvestment)
		return ratioOutput("implied_roic", value, calculationErr)
	case "valuation.enterprise_to_equity_detailed":
		values := make([]numeric.Decimal, 7)
		var err error
		for index, name := range []string{"enterprise_value", "debt", "cash", "investments", "minority_interest", "option_value", "diluted_shares"} {
			values[index], err = scalar(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		result, err := finance.DetailedEnterpriseToEquity(values[0], values[1], values[2], values[3], values[4], values[5], values[6])
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{
			decimalOutput("equity_value", result.EquityValue, "currency", currency),
			decimalOutput("value_per_diluted_share", result.ValuePerDilutedShare, "currency_per_share", currency),
		}, nil, nil, nil
	case "valuation.ev_to_ebitda", "valuation.ev_to_revenue", "valuation.ev_to_ebit":
		enterprise, err := scalar("enterprise_value")
		if err != nil {
			return nil, nil, nil, err
		}
		denominatorName, outputID := "ebitda", "ev_to_ebitda"
		if operationID == "valuation.ev_to_revenue" {
			denominatorName, outputID = "revenue", "ev_to_revenue"
		} else if operationID == "valuation.ev_to_ebit" {
			denominatorName, outputID = "ebit", "ev_to_ebit"
		}
		denominator, err := scalar(denominatorName)
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.EnterpriseValueToEBITDA(enterprise, denominator)
		if operationID == "valuation.ev_to_revenue" {
			value, calculationErr = finance.EnterpriseValueToRevenue(enterprise, denominator)
		} else if operationID == "valuation.ev_to_ebit" {
			value, calculationErr = finance.EnterpriseValueToEBIT(enterprise, denominator)
		}
		return ratioOutput(outputID, value, calculationErr)
	case "valuation.price_to_earnings", "valuation.price_to_book", "valuation.price_to_fcf", "valuation.fcf_yield", "valuation.earnings_yield":
		marketValue, err := scalar("equity_market_value")
		if err != nil {
			return nil, nil, nil, err
		}
		inputName, outputID := "net_income", "price_to_earnings"
		if operationID == "valuation.price_to_book" {
			inputName, outputID = "book_equity", "price_to_book"
		} else if operationID == "valuation.price_to_fcf" || operationID == "valuation.fcf_yield" {
			inputName = "free_cash_flow_to_equity"
			if operationID == "valuation.price_to_fcf" {
				outputID = "price_to_fcf"
			} else {
				outputID = "fcf_yield"
			}
		} else if operationID == "valuation.earnings_yield" {
			outputID = "earnings_yield"
		}
		denominator, err := scalar(inputName)
		if err != nil {
			return nil, nil, nil, err
		}
		value, calculationErr := finance.PriceToEarnings(marketValue, denominator)
		switch operationID {
		case "valuation.price_to_book":
			value, calculationErr = finance.PriceToBook(marketValue, denominator)
		case "valuation.price_to_fcf":
			value, calculationErr = finance.PriceToFreeCashFlow(marketValue, denominator)
		case "valuation.fcf_yield":
			value, calculationErr = finance.FreeCashFlowYield(denominator, marketValue)
		case "valuation.earnings_yield":
			value, calculationErr = finance.EarningsYield(denominator, marketValue)
		}
		return ratioOutput(outputID, value, calculationErr)
	case "comparison.dupont":
		values := make([]float64, 4)
		var err error
		for index, name := range []string{"net_income", "revenue", "average_assets", "average_equity"} {
			values[index], err = inputs.float(name)
			if err != nil {
				return nil, nil, nil, err
			}
		}
		result, err := finance.DuPont(values[0], values[1], values[2], values[3])
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{floatOutput("net_margin", result.NetMargin, "ratio"), floatOutput("asset_turnover", result.AssetTurnover, "ratio"), floatOutput("financial_leverage", result.FinancialLeverage, "ratio"), floatOutput("return_on_equity", result.ReturnOnEquity, "ratio")}, nil, nil, nil
	case "comparison.peer_statistics":
		peers, err := inputs.floatSeries("peer_values")
		if err != nil {
			return nil, nil, nil, err
		}
		subject, err := inputs.float("subject_value")
		if err != nil {
			return nil, nil, nil, err
		}
		minimum, err := inputs.integer("minimum_sample")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.PeerStatistics(peers, subject, minimum)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{floatOutput("median", result.Median, "ratio"), floatOutput("percentile", result.Percentile, "ratio"), floatOutput("median_absolute_deviation", result.MedianAbsoluteDeviation, "ratio"), floatOutput("robust_z_score", result.RobustZScore, "ratio"), intOutput("observations", result.Observations, "count")}, nil, nil, nil
	case "economics.lagged_association":
		driver, err := inputs.floatSeries("driver_series")
		if err != nil {
			return nil, nil, nil, err
		}
		outcome, err := inputs.floatSeries("outcome_series")
		if err != nil {
			return nil, nil, nil, err
		}
		lag, err := inputs.integer("lag")
		if err != nil {
			return nil, nil, nil, err
		}
		minimum, err := inputs.integer("minimum_sample")
		if err != nil {
			return nil, nil, nil, err
		}
		result, err := finance.LaggedAssociation(driver, outcome, lag, minimum)
		if err != nil {
			return nil, nil, nil, err
		}
		return []contracts.ReceiptOutput{floatOutput("slope", result.Slope, "ratio"), floatOutput("intercept", result.Intercept, "ratio"), floatOutput("correlation", result.Correlation, "ratio"), floatOutput("r_squared", result.RSquared, "ratio"), intOutput("observations", result.Observations, "count"), intOutput("lag", result.Lag, "count")}, nil, []string{"statistical_association_not_causality"}, nil
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
