package finance

import (
	"errors"
	"fmt"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

var (
	zero = numeric.MustDecimal("0")
	one  = numeric.MustDecimal("1")
)

type BalanceSheetResult struct {
	Difference      numeric.Decimal
	WithinTolerance bool
}

func BalanceSheetIdentity(assets, liabilities, equity, tolerance numeric.Decimal) (BalanceSheetResult, error) {
	right, err := add(liabilities, equity)
	if err != nil {
		return BalanceSheetResult{}, err
	}
	difference, err := subtract(assets, right)
	if err != nil {
		return BalanceSheetResult{}, err
	}
	absDifference, err := absolute(difference)
	if err != nil {
		return BalanceSheetResult{}, err
	}
	if sign, err := compare(tolerance, zero); err != nil || sign < 0 {
		return BalanceSheetResult{}, errors.New("tolerance must be non-negative")
	}
	comparison, err := compare(absDifference, tolerance)
	if err != nil {
		return BalanceSheetResult{}, err
	}
	return BalanceSheetResult{Difference: difference, WithinTolerance: comparison <= 0}, nil
}

func Growth(current, prior numeric.Decimal) (numeric.Decimal, error) {
	delta, err := subtract(current, prior)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return ratio(delta, prior)
}

func CAGR(start, end, years numeric.Decimal) (numeric.Decimal, error) {
	if startSign, _ := compare(start, zero); startSign <= 0 {
		return numeric.Decimal{}, errors.New("CAGR start value must be positive")
	}
	if endSign, _ := compare(end, zero); endSign < 0 {
		return numeric.Decimal{}, errors.New("CAGR end value cannot be negative")
	}
	if yearSign, _ := compare(years, zero); yearSign <= 0 {
		return numeric.Decimal{}, errors.New("CAGR years must be positive")
	}
	base, err := divide(end, start)
	if err != nil {
		return numeric.Decimal{}, err
	}
	exponent, err := divide(one, years)
	if err != nil {
		return numeric.Decimal{}, err
	}
	compounded, err := power(base, exponent)
	if err != nil {
		return numeric.Decimal{}, fmt.Errorf("calculate CAGR: %w", err)
	}
	return subtract(compounded, one)
}

func Margin(numerator, revenue numeric.Decimal) (numeric.Decimal, error) {
	return ratio(numerator, revenue)
}

func FreeCashFlow(operatingCashFlow, capitalExpenditure numeric.Decimal) (numeric.Decimal, error) {
	return subtract(operatingCashFlow, capitalExpenditure)
}

func CashConversion(operatingCashFlow, netIncome numeric.Decimal) (numeric.Decimal, error) {
	return ratio(operatingCashFlow, netIncome)
}

func CapexIntensity(capitalExpenditure, revenue numeric.Decimal) (numeric.Decimal, error) {
	return ratio(capitalExpenditure, revenue)
}

func NetDebt(debt, cashAndEquivalents numeric.Decimal) (numeric.Decimal, error) {
	return subtract(debt, cashAndEquivalents)
}

func Dilution(currentShares, priorShares numeric.Decimal) (numeric.Decimal, error) {
	return Growth(currentShares, priorShares)
}

func ROICProxy(nopat, investedCapital numeric.Decimal) (numeric.Decimal, error) {
	return ratio(nopat, investedCapital)
}

func CurrentRatio(currentAssets, currentLiabilities numeric.Decimal) (numeric.Decimal, error) {
	return ratio(currentAssets, currentLiabilities)
}

func DebtToEquity(debt, equity numeric.Decimal) (numeric.Decimal, error) {
	return ratio(debt, equity)
}

func EarningsPerShare(netIncome, dilutedShares numeric.Decimal) (numeric.Decimal, error) {
	return ratio(netIncome, dilutedShares)
}

type QualityOfEarningsResult struct {
	AccrualGap     numeric.Decimal
	CashConversion numeric.Decimal
}

func QualityOfEarnings(operatingCashFlow, netIncome numeric.Decimal) (QualityOfEarningsResult, error) {
	gap, err := subtract(operatingCashFlow, netIncome)
	if err != nil {
		return QualityOfEarningsResult{}, err
	}
	conversion, err := ratio(operatingCashFlow, netIncome)
	if err != nil {
		return QualityOfEarningsResult{}, err
	}
	return QualityOfEarningsResult{AccrualGap: gap, CashConversion: conversion}, nil
}

type DCFResult struct {
	EnterpriseValue      numeric.Decimal
	ExplicitPresentValue numeric.Decimal
	TerminalPresentValue numeric.Decimal
	PresentValues        []numeric.Decimal
}

func FCFFDCF(forecast []numeric.Decimal, discountRate, terminalGrowth numeric.Decimal) (DCFResult, error) {
	if len(forecast) == 0 {
		return DCFResult{}, errors.New("FCFF forecast cannot be empty")
	}
	if rateSign, _ := compare(discountRate, numeric.MustDecimal("-1")); rateSign <= 0 {
		return DCFResult{}, errors.New("discount rate must be greater than -1")
	}
	if spread, _ := compare(discountRate, terminalGrowth); spread <= 0 {
		return DCFResult{}, errors.New("discount rate must exceed terminal growth")
	}

	onePlusRate, err := add(one, discountRate)
	if err != nil {
		return DCFResult{}, err
	}
	explicit := zero
	presentValues := make([]numeric.Decimal, 0, len(forecast))
	for index, flow := range forecast {
		period := numeric.MustDecimal(fmt.Sprintf("%d", index+1))
		factor, err := power(onePlusRate, period)
		if err != nil {
			return DCFResult{}, err
		}
		present, err := divide(flow, factor)
		if err != nil {
			return DCFResult{}, err
		}
		explicit, err = add(explicit, present)
		if err != nil {
			return DCFResult{}, err
		}
		presentValues = append(presentValues, present)
	}

	onePlusGrowth, err := add(one, terminalGrowth)
	if err != nil {
		return DCFResult{}, err
	}
	terminalFlow, err := multiply(forecast[len(forecast)-1], onePlusGrowth)
	if err != nil {
		return DCFResult{}, err
	}
	denominator, err := subtract(discountRate, terminalGrowth)
	if err != nil {
		return DCFResult{}, err
	}
	terminalValue, err := divide(terminalFlow, denominator)
	if err != nil {
		return DCFResult{}, err
	}
	terminalPeriod := numeric.MustDecimal(fmt.Sprintf("%d", len(forecast)))
	terminalFactor, err := power(onePlusRate, terminalPeriod)
	if err != nil {
		return DCFResult{}, err
	}
	terminalPresent, err := divide(terminalValue, terminalFactor)
	if err != nil {
		return DCFResult{}, err
	}
	enterprise, err := add(explicit, terminalPresent)
	if err != nil {
		return DCFResult{}, err
	}
	return DCFResult{EnterpriseValue: enterprise, ExplicitPresentValue: explicit, TerminalPresentValue: terminalPresent, PresentValues: presentValues}, nil
}

type ReverseDCFResult struct {
	ImpliedGrowth numeric.Decimal
	Iterations    int
	Converged     bool
}

func ReverseDCF(targetEnterpriseValue, baseFCFF, discountRate numeric.Decimal, years int, tolerance numeric.Decimal, maxIterations int) (ReverseDCFResult, error) {
	if years < 1 || maxIterations < 1 {
		return ReverseDCFResult{}, errors.New("years and max iterations must be positive")
	}
	if targetSign, _ := compare(targetEnterpriseValue, zero); targetSign <= 0 {
		return ReverseDCFResult{}, errors.New("target enterprise value must be positive")
	}
	low := numeric.MustDecimal("-0.99")
	high, err := subtract(discountRate, numeric.MustDecimal("0.0000000001"))
	if err != nil {
		return ReverseDCFResult{}, err
	}
	forecast := make([]numeric.Decimal, years)
	for index := range forecast {
		forecast[index] = baseFCFF
	}
	two := numeric.MustDecimal("2")
	for iteration := 1; iteration <= maxIterations; iteration++ {
		sum, err := add(low, high)
		if err != nil {
			return ReverseDCFResult{}, err
		}
		mid, err := divide(sum, two)
		if err != nil {
			return ReverseDCFResult{}, err
		}
		result, err := FCFFDCF(forecast, discountRate, mid)
		if err != nil {
			return ReverseDCFResult{}, err
		}
		difference, err := subtract(result.EnterpriseValue, targetEnterpriseValue)
		if err != nil {
			return ReverseDCFResult{}, err
		}
		absoluteDifference, err := absolute(difference)
		if err != nil {
			return ReverseDCFResult{}, err
		}
		if within, _ := compare(absoluteDifference, tolerance); within <= 0 {
			return ReverseDCFResult{ImpliedGrowth: mid, Iterations: iteration, Converged: true}, nil
		}
		if direction, _ := compare(difference, zero); direction > 0 {
			high = mid
		} else {
			low = mid
		}
	}
	return ReverseDCFResult{Iterations: maxIterations, Converged: false}, nil
}

type EquityBridgeResult struct {
	EquityValue   numeric.Decimal
	ValuePerShare numeric.Decimal
}

func EnterpriseToEquity(enterpriseValue, netDebt, nonOperatingAssets, dilutedShares numeric.Decimal) (EquityBridgeResult, error) {
	equity, err := subtract(enterpriseValue, netDebt)
	if err != nil {
		return EquityBridgeResult{}, err
	}
	equity, err = add(equity, nonOperatingAssets)
	if err != nil {
		return EquityBridgeResult{}, err
	}
	perShare, err := divide(equity, dilutedShares)
	if err != nil {
		return EquityBridgeResult{}, err
	}
	return EquityBridgeResult{EquityValue: equity, ValuePerShare: perShare}, nil
}

func PeerMultiple(marketValue, metricValue numeric.Decimal) (numeric.Decimal, error) {
	return ratio(marketValue, metricValue)
}

func WACC(equityValue, debtValue, costOfEquity, preTaxCostOfDebt, taxRate numeric.Decimal) (numeric.Decimal, error) {
	for name, value := range map[string]numeric.Decimal{"equity value": equityValue, "debt value": debtValue} {
		if sign, _ := compare(value, zero); sign < 0 {
			return numeric.Decimal{}, fmt.Errorf("%s cannot be negative", name)
		}
	}
	if rate, _ := compare(taxRate, zero); rate < 0 {
		return numeric.Decimal{}, errors.New("tax rate cannot be negative")
	}
	if rate, _ := compare(taxRate, one); rate > 0 {
		return numeric.Decimal{}, errors.New("tax rate cannot exceed one")
	}
	totalCapital, err := add(equityValue, debtValue)
	if err != nil {
		return numeric.Decimal{}, err
	}
	equityWeight, err := divide(equityValue, totalCapital)
	if err != nil {
		return numeric.Decimal{}, err
	}
	debtWeight, err := divide(debtValue, totalCapital)
	if err != nil {
		return numeric.Decimal{}, err
	}
	equityComponent, err := multiply(equityWeight, costOfEquity)
	if err != nil {
		return numeric.Decimal{}, err
	}
	oneMinusTax, err := subtract(one, taxRate)
	if err != nil {
		return numeric.Decimal{}, err
	}
	debtComponent, err := multiply(debtWeight, preTaxCostOfDebt)
	if err != nil {
		return numeric.Decimal{}, err
	}
	debtComponent, err = multiply(debtComponent, oneMinusTax)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return add(equityComponent, debtComponent)
}

func RealRate(nominalRate, inflation numeric.Decimal) (numeric.Decimal, error) {
	numerator, err := add(one, nominalRate)
	if err != nil {
		return numeric.Decimal{}, err
	}
	denominator, err := add(one, inflation)
	if err != nil {
		return numeric.Decimal{}, err
	}
	quotient, err := divide(numerator, denominator)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return subtract(quotient, one)
}

func YieldCurveSpread(longYield, shortYield numeric.Decimal) (numeric.Decimal, error) {
	return subtract(longYield, shortYield)
}
