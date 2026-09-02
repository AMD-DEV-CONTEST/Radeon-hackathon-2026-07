package finance

import (
	"errors"
	"math"
	"strconv"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

type MarginKind string

const (
	MarginGross        MarginKind = "gross_margin"
	MarginOperating    MarginKind = "operating_margin"
	MarginEBITDA       MarginKind = "ebitda_margin"
	MarginPretax       MarginKind = "pretax_margin"
	MarginNet          MarginKind = "net_margin"
	MarginFreeCashFlow MarginKind = "free_cash_flow_margin"
)

type TypedMargin struct {
	Kind  MarginKind
	Value numeric.Decimal
}

func ProfitMargin(kind MarginKind, numerator, revenue numeric.Decimal) (TypedMargin, error) {
	switch kind {
	case MarginGross, MarginOperating, MarginEBITDA, MarginPretax, MarginNet, MarginFreeCashFlow:
	default:
		return TypedMargin{}, errors.New("unsupported margin kind")
	}
	if sign, _ := compare(revenue, zero); sign <= 0 {
		return TypedMargin{}, errors.New("revenue must be positive")
	}
	value, err := divide(numerator, revenue)
	if err != nil {
		return TypedMargin{}, err
	}
	return TypedMargin{Kind: kind, Value: value}, nil
}

func MarginChange(current, prior numeric.Decimal) (numeric.Decimal, error) {
	return subtract(current, prior)
}

func IncrementalMargin(currentProfit, priorProfit, currentRevenue, priorRevenue numeric.Decimal) (numeric.Decimal, error) {
	profitChange, err := subtract(currentProfit, priorProfit)
	if err != nil {
		return numeric.Decimal{}, err
	}
	revenueChange, err := subtract(currentRevenue, priorRevenue)
	if err != nil {
		return numeric.Decimal{}, err
	}
	if sign, _ := compare(revenueChange, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("revenue change must be positive")
	}
	return divide(profitChange, revenueChange)
}

func OperatingLeverage(currentOperatingIncome, priorOperatingIncome, currentRevenue, priorRevenue numeric.Decimal) (numeric.Decimal, error) {
	revenueGrowth, err := Growth(currentRevenue, priorRevenue)
	if err != nil {
		return numeric.Decimal{}, err
	}
	if revenueGrowth.String() == "0" {
		return numeric.Decimal{}, errors.New("revenue growth must be non-zero")
	}
	operatingGrowth, err := Growth(currentOperatingIncome, priorOperatingIncome)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return divide(operatingGrowth, revenueGrowth)
}

func AccrualIntensity(netIncome, operatingCashFlow, averageAssets numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(averageAssets, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("average assets must be positive")
	}
	accruals, err := subtract(netIncome, operatingCashFlow)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return divide(accruals, averageAssets)
}

type StabilityResult struct {
	Mean                 float64
	StandardDeviation    float64
	CoefficientVariation float64
	Observations         int
}

func Stability(values []numeric.Decimal) (StabilityResult, error) {
	if len(values) < 3 {
		return StabilityResult{}, errors.New("stability requires at least three observations")
	}
	converted := make([]float64, len(values))
	mean := 0.0
	for index, value := range values {
		parsed, err := strconv.ParseFloat(value.String(), 64)
		if err != nil || math.IsInf(parsed, 0) || math.IsNaN(parsed) {
			return StabilityResult{}, errors.New("stability values must be finite")
		}
		converted[index] = parsed
		mean += parsed
	}
	mean /= float64(len(converted))
	variance := 0.0
	for _, value := range converted {
		delta := value - mean
		variance += delta * delta
	}
	variance /= float64(len(converted) - 1)
	standardDeviation := math.Sqrt(variance)
	coefficient := math.Inf(1)
	if mean != 0 {
		coefficient = standardDeviation / math.Abs(mean)
	}
	return StabilityResult{Mean: mean, StandardDeviation: standardDeviation, CoefficientVariation: coefficient, Observations: len(values)}, nil
}

func DaysSalesOutstanding(averageReceivables, revenue, days numeric.Decimal) (numeric.Decimal, error) {
	return daysRatio(averageReceivables, revenue, days, "revenue")
}

func DaysInventoryOutstanding(averageInventory, costOfRevenue, days numeric.Decimal) (numeric.Decimal, error) {
	return daysRatio(averageInventory, costOfRevenue, days, "cost of revenue")
}

func DaysPayablesOutstanding(averagePayables, costOfRevenue, days numeric.Decimal) (numeric.Decimal, error) {
	return daysRatio(averagePayables, costOfRevenue, days, "cost of revenue")
}

func CashConversionCycle(dso, dio, dpo numeric.Decimal) (numeric.Decimal, error) {
	value, err := add(dso, dio)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return subtract(value, dpo)
}

func QuickRatio(cashAndEquivalents, marketableSecurities, accountsReceivable, currentLiabilities numeric.Decimal) (numeric.Decimal, error) {
	liquid, err := add(cashAndEquivalents, marketableSecurities)
	if err != nil {
		return numeric.Decimal{}, err
	}
	liquid, err = add(liquid, accountsReceivable)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return positiveDenominatorRatio(liquid, currentLiabilities, "current liabilities")
}

func CashRatio(cashAndEquivalents, marketableSecurities, currentLiabilities numeric.Decimal) (numeric.Decimal, error) {
	liquid, err := add(cashAndEquivalents, marketableSecurities)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return positiveDenominatorRatio(liquid, currentLiabilities, "current liabilities")
}

func InterestCoverage(ebit, interestExpense numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(ebit, interestExpense, "interest expense")
}

func NetDebtToEBITDA(netDebt, ebitda numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(netDebt, ebitda, "EBITDA")
}

func StockBasedCompensationIntensity(stockBasedCompensation, revenue numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(stockBasedCompensation, revenue, "revenue")
}

func BuybackYield(netRepurchases, marketCapitalization numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(netRepurchases, marketCapitalization, "market capitalization")
}

func DividendYield(dividendsPaid, marketCapitalization numeric.Decimal) (numeric.Decimal, error) {
	return positiveDenominatorRatio(dividendsPaid, marketCapitalization, "market capitalization")
}

func ShareholderYield(netRepurchases, dividendsPaid, netDebtReduction, marketCapitalization numeric.Decimal) (numeric.Decimal, error) {
	returned, err := add(netRepurchases, dividendsPaid)
	if err != nil {
		return numeric.Decimal{}, err
	}
	returned, err = add(returned, netDebtReduction)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return positiveDenominatorRatio(returned, marketCapitalization, "market capitalization")
}

type CapitalAllocationResult struct {
	TotalSources         numeric.Decimal
	TotalUses            numeric.Decimal
	ImpliedChangeInCash  numeric.Decimal
	ReportedChangeInCash numeric.Decimal
	ReconciliationGap    numeric.Decimal
	WithinTolerance      bool
}

func CapitalAllocationBridge(
	operatingCashFlow, debtIssuance, equityIssuance, assetSales,
	capitalExpenditure, acquisitions, debtRepayment, dividends, repurchases,
	reportedChangeInCash, tolerance numeric.Decimal,
) (CapitalAllocationResult, error) {
	if sign, _ := compare(tolerance, zero); sign < 0 {
		return CapitalAllocationResult{}, errors.New("tolerance cannot be negative")
	}
	totalSources, err := sumDecimals(operatingCashFlow, debtIssuance, equityIssuance, assetSales)
	if err != nil {
		return CapitalAllocationResult{}, err
	}
	totalUses, err := sumDecimals(capitalExpenditure, acquisitions, debtRepayment, dividends, repurchases)
	if err != nil {
		return CapitalAllocationResult{}, err
	}
	implied, err := subtract(totalSources, totalUses)
	if err != nil {
		return CapitalAllocationResult{}, err
	}
	gap, err := subtract(implied, reportedChangeInCash)
	if err != nil {
		return CapitalAllocationResult{}, err
	}
	absGap, err := absolute(gap)
	if err != nil {
		return CapitalAllocationResult{}, err
	}
	within, err := compare(absGap, tolerance)
	if err != nil {
		return CapitalAllocationResult{}, err
	}
	return CapitalAllocationResult{TotalSources: totalSources, TotalUses: totalUses, ImpliedChangeInCash: implied, ReportedChangeInCash: reportedChangeInCash, ReconciliationGap: gap, WithinTolerance: within <= 0}, nil
}

func daysRatio(balance, flow, days numeric.Decimal, denominatorName string) (numeric.Decimal, error) {
	ratio, err := positiveDenominatorRatio(balance, flow, denominatorName)
	if err != nil {
		return numeric.Decimal{}, err
	}
	if sign, _ := compare(days, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("days must be positive")
	}
	return multiply(ratio, days)
}

func positiveDenominatorRatio(numerator, denominator numeric.Decimal, denominatorName string) (numeric.Decimal, error) {
	if sign, _ := compare(denominator, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New(denominatorName + " must be positive")
	}
	return divide(numerator, denominator)
}

func sumDecimals(values ...numeric.Decimal) (numeric.Decimal, error) {
	result := zero
	var err error
	for _, value := range values {
		result, err = add(result, value)
		if err != nil {
			return numeric.Decimal{}, err
		}
	}
	return result, nil
}
