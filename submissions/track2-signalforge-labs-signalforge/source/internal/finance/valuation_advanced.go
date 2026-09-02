package finance

import (
	"errors"
	"fmt"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func CAPM(riskFreeRate, beta, equityRiskPremium numeric.Decimal) (numeric.Decimal, error) {
	betaPremium, err := multiply(beta, equityRiskPremium)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return add(riskFreeRate, betaPremium)
}

func EnterpriseValueToEBITDA(enterpriseValue, ebitda numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(enterpriseValue, ebitda, "EBITDA")
}

func PriceToEarnings(equityMarketValue, netIncome numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(equityMarketValue, netIncome, "net income")
}

func EnterpriseValueToRevenue(enterpriseValue, revenue numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(enterpriseValue, revenue, "revenue")
}

func EnterpriseValueToEBIT(enterpriseValue, ebit numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(enterpriseValue, ebit, "EBIT")
}

func PriceToBook(equityMarketValue, bookEquity numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(equityMarketValue, bookEquity, "book equity")
}

func PriceToFreeCashFlow(equityMarketValue, freeCashFlowToEquity numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(equityMarketValue, freeCashFlowToEquity, "free cash flow to equity")
}

func FreeCashFlowYield(freeCashFlowToEquity, equityMarketValue numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(freeCashFlowToEquity, equityMarketValue, "equity market value")
}

func EarningsYield(netIncome, equityMarketValue numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(netIncome, equityMarketValue, "equity market value")
}

func UnleverBeta(leveredBeta, debt, equity, taxRate numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(equity, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("equity must be positive")
	}
	if err := validateUnitRate(taxRate, "tax rate"); err != nil {
		return numeric.Decimal{}, err
	}
	debtEquity, err := divide(debt, equity)
	if err != nil {
		return numeric.Decimal{}, err
	}
	oneMinusTax, err := subtract(one, taxRate)
	if err != nil {
		return numeric.Decimal{}, err
	}
	adjustment, err := multiply(oneMinusTax, debtEquity)
	if err != nil {
		return numeric.Decimal{}, err
	}
	denominator, err := add(one, adjustment)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return divide(leveredBeta, denominator)
}

func ReleverBeta(unleveredBeta, debt, equity, taxRate numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(equity, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("equity must be positive")
	}
	if err := validateUnitRate(taxRate, "tax rate"); err != nil {
		return numeric.Decimal{}, err
	}
	debtEquity, err := divide(debt, equity)
	if err != nil {
		return numeric.Decimal{}, err
	}
	oneMinusTax, err := subtract(one, taxRate)
	if err != nil {
		return numeric.Decimal{}, err
	}
	adjustment, err := multiply(oneMinusTax, debtEquity)
	if err != nil {
		return numeric.Decimal{}, err
	}
	multiplier, err := add(one, adjustment)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return multiply(unleveredBeta, multiplier)
}

type TerminalMethod string

const (
	TerminalPerpetuityGrowth TerminalMethod = "perpetuity_growth"
	TerminalExitMultiple     TerminalMethod = "exit_multiple"
)

type TerminalAssumption struct {
	Method       TerminalMethod
	GrowthRate   numeric.Decimal
	ExitMetric   numeric.Decimal
	ExitMultiple numeric.Decimal
}

type AdvancedDCFResult struct {
	EnterpriseValue      numeric.Decimal
	ExplicitPresentValue numeric.Decimal
	TerminalValue        numeric.Decimal
	TerminalPresentValue numeric.Decimal
	TerminalValueShare   numeric.Decimal
	PresentValues        []numeric.Decimal
	Warnings             []string
}

func MultiStageDCF(forecast []numeric.Decimal, discountRate numeric.Decimal, terminal TerminalAssumption, midYear bool) (AdvancedDCFResult, error) {
	if len(forecast) == 0 {
		return AdvancedDCFResult{}, errors.New("forecast cannot be empty")
	}
	if rateFloor, _ := compare(discountRate, numeric.MustDecimal("-1")); rateFloor <= 0 {
		return AdvancedDCFResult{}, errors.New("discount rate must exceed -1")
	}
	onePlusRate, err := add(one, discountRate)
	if err != nil {
		return AdvancedDCFResult{}, err
	}
	explicit := zero
	presentValues := make([]numeric.Decimal, 0, len(forecast))
	for index, flow := range forecast {
		exponent := numeric.MustDecimal(fmt.Sprintf("%d", index+1))
		if midYear {
			exponent, err = subtract(exponent, numeric.MustDecimal("0.5"))
			if err != nil {
				return AdvancedDCFResult{}, err
			}
		}
		factor, err := power(onePlusRate, exponent)
		if err != nil {
			return AdvancedDCFResult{}, err
		}
		present, err := divide(flow, factor)
		if err != nil {
			return AdvancedDCFResult{}, err
		}
		explicit, err = add(explicit, present)
		if err != nil {
			return AdvancedDCFResult{}, err
		}
		presentValues = append(presentValues, present)
	}

	terminalValue, err := calculateTerminalValue(forecast[len(forecast)-1], discountRate, terminal)
	if err != nil {
		return AdvancedDCFResult{}, err
	}
	terminalExponent := numeric.MustDecimal(fmt.Sprintf("%d", len(forecast)))
	terminalFactor, err := power(onePlusRate, terminalExponent)
	if err != nil {
		return AdvancedDCFResult{}, err
	}
	terminalPresent, err := divide(terminalValue, terminalFactor)
	if err != nil {
		return AdvancedDCFResult{}, err
	}
	enterprise, err := add(explicit, terminalPresent)
	if err != nil {
		return AdvancedDCFResult{}, err
	}
	if sign, _ := compare(enterprise, zero); sign == 0 {
		return AdvancedDCFResult{}, errors.New("enterprise value is zero")
	}
	terminalShare, err := divide(terminalPresent, enterprise)
	if err != nil {
		return AdvancedDCFResult{}, err
	}
	warnings := []string{}
	if high, _ := compare(terminalShare, numeric.MustDecimal("0.75")); high > 0 {
		warnings = append(warnings, "terminal_value_share_exceeds_75_percent")
	}
	return AdvancedDCFResult{
		EnterpriseValue: enterprise, ExplicitPresentValue: explicit, TerminalValue: terminalValue,
		TerminalPresentValue: terminalPresent, TerminalValueShare: terminalShare,
		PresentValues: presentValues, Warnings: warnings,
	}, nil
}

func DividendDiscountModel(dividends []numeric.Decimal, costOfEquity numeric.Decimal, terminalGrowth numeric.Decimal, midYear bool) (AdvancedDCFResult, error) {
	return MultiStageDCF(dividends, costOfEquity, TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: terminalGrowth}, midYear)
}

type ReverseExpectationsResult struct {
	ImpliedValue numeric.Decimal
	Iterations   int
	Converged    bool
}

func ReverseRevenueGrowth(
	targetEnterpriseValue, baseRevenue, operatingMargin, taxRate, reinvestmentRate,
	discountRate, terminalGrowth numeric.Decimal,
	years, maxIterations int, tolerance numeric.Decimal,
) (ReverseExpectationsResult, error) {
	if years < 1 || maxIterations < 1 {
		return ReverseExpectationsResult{}, errors.New("years and iterations must be positive")
	}
	if sign, _ := compare(targetEnterpriseValue, zero); sign <= 0 {
		return ReverseExpectationsResult{}, errors.New("target enterprise value must be positive")
	}
	if sign, _ := compare(baseRevenue, zero); sign <= 0 {
		return ReverseExpectationsResult{}, errors.New("base revenue must be positive")
	}
	if err := validateUnitRate(taxRate, "tax rate"); err != nil {
		return ReverseExpectationsResult{}, err
	}
	if err := validateUnitRate(reinvestmentRate, "reinvestment rate"); err != nil {
		return ReverseExpectationsResult{}, err
	}

	low := numeric.MustDecimal("-0.50")
	high := numeric.MustDecimal("1.00")
	for iteration := 1; iteration <= maxIterations; iteration++ {
		sum, err := add(low, high)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		candidate, err := divide(sum, numeric.MustDecimal("2"))
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		forecast, err := fcffFromRevenuePath(baseRevenue, candidate, operatingMargin, taxRate, reinvestmentRate, years)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		valuation, err := MultiStageDCF(forecast, discountRate, TerminalAssumption{Method: TerminalPerpetuityGrowth, GrowthRate: terminalGrowth}, false)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		difference, err := subtract(valuation.EnterpriseValue, targetEnterpriseValue)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		absDifference, _ := absolute(difference)
		if within, _ := compare(absDifference, tolerance); within <= 0 {
			return ReverseExpectationsResult{ImpliedValue: candidate, Iterations: iteration, Converged: true}, nil
		}
		if direction, _ := compare(difference, zero); direction > 0 {
			high = candidate
		} else {
			low = candidate
		}
	}
	return ReverseExpectationsResult{Iterations: maxIterations, Converged: false}, nil
}

func calculateTerminalValue(lastFlow, discountRate numeric.Decimal, terminal TerminalAssumption) (numeric.Decimal, error) {
	switch terminal.Method {
	case TerminalPerpetuityGrowth:
		if spread, _ := compare(discountRate, terminal.GrowthRate); spread <= 0 {
			return numeric.Decimal{}, errors.New("discount rate must exceed terminal growth")
		}
		onePlusGrowth, err := add(one, terminal.GrowthRate)
		if err != nil {
			return numeric.Decimal{}, err
		}
		terminalFlow, err := multiply(lastFlow, onePlusGrowth)
		if err != nil {
			return numeric.Decimal{}, err
		}
		spread, err := subtract(discountRate, terminal.GrowthRate)
		if err != nil {
			return numeric.Decimal{}, err
		}
		return divide(terminalFlow, spread)
	case TerminalExitMultiple:
		if sign, _ := compare(terminal.ExitMetric, zero); sign < 0 {
			return numeric.Decimal{}, errors.New("exit metric cannot be negative")
		}
		if sign, _ := compare(terminal.ExitMultiple, zero); sign <= 0 {
			return numeric.Decimal{}, errors.New("exit multiple must be positive")
		}
		return multiply(terminal.ExitMetric, terminal.ExitMultiple)
	default:
		return numeric.Decimal{}, errors.New("unsupported terminal method")
	}
}

func fcffFromRevenuePath(baseRevenue, growth, operatingMargin, taxRate, reinvestmentRate numeric.Decimal, years int) ([]numeric.Decimal, error) {
	onePlusGrowth, err := add(one, growth)
	if err != nil {
		return nil, err
	}
	afterTax, err := subtract(one, taxRate)
	if err != nil {
		return nil, err
	}
	retained, err := subtract(one, reinvestmentRate)
	if err != nil {
		return nil, err
	}
	forecast := make([]numeric.Decimal, years)
	revenue := baseRevenue
	for index := range forecast {
		revenue, err = multiply(revenue, onePlusGrowth)
		if err != nil {
			return nil, err
		}
		nopat, err := multiply(revenue, operatingMargin)
		if err != nil {
			return nil, err
		}
		nopat, err = multiply(nopat, afterTax)
		if err != nil {
			return nil, err
		}
		forecast[index], err = multiply(nopat, retained)
		if err != nil {
			return nil, err
		}
	}
	return forecast, nil
}
