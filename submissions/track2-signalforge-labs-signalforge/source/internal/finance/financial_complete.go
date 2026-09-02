package finance

import (
	"errors"
	"sort"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func ROCE(ebit, totalAssets, currentLiabilities numeric.Decimal) (numeric.Decimal, error) {
	capitalEmployed, err := subtract(totalAssets, currentLiabilities)
	if err != nil {
		return numeric.Decimal{}, err
	}
	if sign, _ := compare(capitalEmployed, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("capital employed must be positive")
	}
	return divide(ebit, capitalEmployed)
}

type CashConversionKind string

const (
	CashConversionEarnings        CashConversionKind = "operating_cash_flow_to_net_income"
	CashConversionEBITDA          CashConversionKind = "operating_cash_flow_to_ebitda"
	CashConversionOperatingProfit CashConversionKind = "operating_cash_flow_to_operating_profit"
)

type CashConversionResult struct {
	Kind  CashConversionKind
	Value numeric.Decimal
}

func TypedCashConversion(kind CashConversionKind, operatingCashFlow, denominator numeric.Decimal) (CashConversionResult, error) {
	switch kind {
	case CashConversionEarnings, CashConversionEBITDA, CashConversionOperatingProfit:
	default:
		return CashConversionResult{}, errors.New("unsupported cash-conversion definition")
	}
	value, err := positiveDenominatorRatio(operatingCashFlow, denominator, string(kind)+" denominator")
	if err != nil {
		return CashConversionResult{}, err
	}
	return CashConversionResult{Kind: kind, Value: value}, nil
}

type DebtMaturity struct {
	Year   int
	Amount numeric.Decimal
}

type DebtMaturityContext struct {
	TotalDebt       numeric.Decimal
	DueWithin1Year  numeric.Decimal
	DueWithin3Years numeric.Decimal
	NearTermShare   numeric.Decimal
	WeightedYear    numeric.Decimal
	Observations    int
}

func AnalyzeDebtMaturities(asOfYear int, maturities []DebtMaturity) (DebtMaturityContext, error) {
	if asOfYear < 1900 || len(maturities) == 0 {
		return DebtMaturityContext{}, errors.New("as-of year and at least one maturity are required")
	}
	seen := make(map[int]bool)
	total, oneYear, threeYears, weighted := zero, zero, zero, zero
	for _, maturity := range maturities {
		if maturity.Year < asOfYear || seen[maturity.Year] {
			return DebtMaturityContext{}, errors.New("maturity years must be unique and not precede the as-of year")
		}
		if sign, _ := compare(maturity.Amount, zero); sign < 0 {
			return DebtMaturityContext{}, errors.New("maturity amount cannot be negative")
		}
		seen[maturity.Year] = true
		var err error
		total, err = add(total, maturity.Amount)
		if err != nil {
			return DebtMaturityContext{}, err
		}
		if maturity.Year <= asOfYear+1 {
			oneYear, _ = add(oneYear, maturity.Amount)
		}
		if maturity.Year <= asOfYear+3 {
			threeYears, _ = add(threeYears, maturity.Amount)
		}
		yearsFromNow := numeric.MustDecimal(intString(maturity.Year - asOfYear))
		weightedPart, err := multiply(maturity.Amount, yearsFromNow)
		if err != nil {
			return DebtMaturityContext{}, err
		}
		weighted, err = add(weighted, weightedPart)
		if err != nil {
			return DebtMaturityContext{}, err
		}
	}
	if sign, _ := compare(total, zero); sign <= 0 {
		return DebtMaturityContext{}, errors.New("total scheduled debt must be positive")
	}
	nearTermShare, err := divide(threeYears, total)
	if err != nil {
		return DebtMaturityContext{}, err
	}
	weightedYear, err := divide(weighted, total)
	if err != nil {
		return DebtMaturityContext{}, err
	}
	return DebtMaturityContext{
		TotalDebt: total, DueWithin1Year: oneYear, DueWithin3Years: threeYears,
		NearTermShare: nearTermShare, WeightedYear: weightedYear, Observations: len(maturities),
	}, nil
}

func NetPayoutYield(netRepurchases, dividendsPaid, marketCapitalization numeric.Decimal) (numeric.Decimal, error) {
	total, err := add(netRepurchases, dividendsPaid)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return positiveDenominatorRatio(total, marketCapitalization, "market capitalization")
}

type EnterpriseToEquityBridge struct {
	EnterpriseValue      numeric.Decimal
	Debt                 numeric.Decimal
	Cash                 numeric.Decimal
	Investments          numeric.Decimal
	MinorityInterest     numeric.Decimal
	OptionValue          numeric.Decimal
	EquityValue          numeric.Decimal
	DilutedShares        numeric.Decimal
	ValuePerDilutedShare numeric.Decimal
}

func DetailedEnterpriseToEquity(
	enterpriseValue, debt, cash, investments, minorityInterest, optionValue, dilutedShares numeric.Decimal,
) (EnterpriseToEquityBridge, error) {
	for _, item := range []struct {
		name  string
		value numeric.Decimal
	}{
		{"debt", debt},
		{"cash", cash},
		{"investments", investments},
		{"minority interest", minorityInterest},
		{"option value", optionValue},
	} {
		name, value := item.name, item.value
		if sign, _ := compare(value, zero); sign < 0 {
			return EnterpriseToEquityBridge{}, errors.New(name + " cannot be negative")
		}
	}
	if sign, _ := compare(dilutedShares, zero); sign <= 0 {
		return EnterpriseToEquityBridge{}, errors.New("diluted shares must be positive")
	}
	equity, err := subtract(enterpriseValue, debt)
	if err != nil {
		return EnterpriseToEquityBridge{}, err
	}
	equity, err = add(equity, cash)
	if err != nil {
		return EnterpriseToEquityBridge{}, err
	}
	equity, err = add(equity, investments)
	if err != nil {
		return EnterpriseToEquityBridge{}, err
	}
	equity, err = subtract(equity, minorityInterest)
	if err != nil {
		return EnterpriseToEquityBridge{}, err
	}
	equity, err = subtract(equity, optionValue)
	if err != nil {
		return EnterpriseToEquityBridge{}, err
	}
	perShare, err := divide(equity, dilutedShares)
	if err != nil {
		return EnterpriseToEquityBridge{}, err
	}
	return EnterpriseToEquityBridge{
		EnterpriseValue: enterpriseValue, Debt: debt, Cash: cash, Investments: investments,
		MinorityInterest: minorityInterest, OptionValue: optionValue, EquityValue: equity,
		DilutedShares: dilutedShares, ValuePerDilutedShare: perShare,
	}, nil
}

type ValuationSanityInputs struct {
	TerminalValueShare numeric.Decimal
	TerminalGrowth     numeric.Decimal
	LongRunEconomyRate numeric.Decimal
	OperatingMargin    numeric.Decimal
	HistoricalMargin   numeric.Decimal
	ReinvestmentRate   numeric.Decimal
	ReturnOnCapital    numeric.Decimal
	GrowthRate         numeric.Decimal
}

func ValuationSanityChecks(inputs ValuationSanityInputs) ([]string, error) {
	for _, item := range []struct {
		name  string
		value numeric.Decimal
	}{
		{"terminal value share", inputs.TerminalValueShare},
		{"reinvestment rate", inputs.ReinvestmentRate},
	} {
		if err := validateUnitRate(item.value, item.name); err != nil {
			return nil, err
		}
	}
	warnings := make([]string, 0)
	if value, _ := compare(inputs.TerminalValueShare, numeric.MustDecimal("0.75")); value > 0 {
		warnings = append(warnings, "terminal_value_share_exceeds_75_percent")
	}
	if value, _ := compare(inputs.TerminalGrowth, inputs.LongRunEconomyRate); value > 0 {
		warnings = append(warnings, "terminal_growth_exceeds_long_run_economy")
	}
	marginGap, err := subtract(inputs.OperatingMargin, inputs.HistoricalMargin)
	if err != nil {
		return nil, err
	}
	marginGap, _ = absolute(marginGap)
	if value, _ := compare(marginGap, numeric.MustDecimal("0.10")); value > 0 {
		warnings = append(warnings, "operating_margin_departs_from_history_by_more_than_10_points")
	}
	impliedGrowth, err := multiply(inputs.ReinvestmentRate, inputs.ReturnOnCapital)
	if err != nil {
		return nil, err
	}
	growthGap, err := subtract(impliedGrowth, inputs.GrowthRate)
	if err != nil {
		return nil, err
	}
	growthGap, _ = absolute(growthGap)
	if value, _ := compare(growthGap, numeric.MustDecimal("0.02")); value > 0 {
		warnings = append(warnings, "growth_reinvestment_roic_identity_gap_exceeds_2_points")
	}
	sort.Strings(warnings)
	return warnings, nil
}

type DCFScenario struct {
	Name           string
	DiscountRate   numeric.Decimal
	TerminalGrowth numeric.Decimal
	Result         AdvancedDCFResult
}

type TornadoInput struct {
	Name       string
	LowValue   numeric.Decimal
	BaseValue  numeric.Decimal
	HighValue  numeric.Decimal
	LowImpact  numeric.Decimal
	HighImpact numeric.Decimal
}

func DCFTornado(
	forecast []numeric.Decimal,
	baseDiscountRate, baseTerminalGrowth numeric.Decimal,
	inputs map[string][3]numeric.Decimal,
) ([]TornadoInput, error) {
	base, err := MultiStageDCF(forecast, baseDiscountRate, TerminalAssumption{
		Method: TerminalPerpetuityGrowth, GrowthRate: baseTerminalGrowth,
	}, false)
	if err != nil {
		return nil, err
	}
	result := make([]TornadoInput, 0, len(inputs))
	names := make([]string, 0, len(inputs))
	for name := range inputs {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		values := inputs[name]
		lowToBase, _ := compare(values[0], values[1])
		baseToHigh, _ := compare(values[1], values[2])
		if lowToBase >= 0 || baseToHigh >= 0 {
			return nil, errors.New("DCF tornado values must be strictly ordered low, base, high")
		}
		lowRate, lowGrowth := baseDiscountRate, baseTerminalGrowth
		highRate, highGrowth := baseDiscountRate, baseTerminalGrowth
		switch name {
		case "discount_rate":
			if comparison, _ := compare(values[1], baseDiscountRate); comparison != 0 {
				return nil, errors.New("discount-rate tornado base must match the DCF base")
			}
			lowRate, highRate = values[0], values[2]
		case "terminal_growth":
			if comparison, _ := compare(values[1], baseTerminalGrowth); comparison != 0 {
				return nil, errors.New("terminal-growth tornado base must match the DCF base")
			}
			lowGrowth, highGrowth = values[0], values[2]
		default:
			return nil, errors.New("unsupported DCF tornado input")
		}
		low, err := MultiStageDCF(forecast, lowRate, TerminalAssumption{
			Method: TerminalPerpetuityGrowth, GrowthRate: lowGrowth,
		}, false)
		if err != nil {
			return nil, err
		}
		high, err := MultiStageDCF(forecast, highRate, TerminalAssumption{
			Method: TerminalPerpetuityGrowth, GrowthRate: highGrowth,
		}, false)
		if err != nil {
			return nil, err
		}
		lowImpact, err := subtract(low.EnterpriseValue, base.EnterpriseValue)
		if err != nil {
			return nil, err
		}
		highImpact, err := subtract(high.EnterpriseValue, base.EnterpriseValue)
		if err != nil {
			return nil, err
		}
		result = append(result, TornadoInput{
			Name: name, LowValue: values[0], BaseValue: values[1], HighValue: values[2],
			LowImpact: lowImpact, HighImpact: highImpact,
		})
	}
	sort.Slice(result, func(i, j int) bool {
		leftLow, _ := absolute(result[i].LowImpact)
		leftHigh, _ := absolute(result[i].HighImpact)
		rightLow, _ := absolute(result[j].LowImpact)
		rightHigh, _ := absolute(result[j].HighImpact)
		left, _ := add(leftLow, leftHigh)
		right, _ := add(rightLow, rightHigh)
		comparison, _ := compare(left, right)
		if comparison == 0 {
			return result[i].Name < result[j].Name
		}
		return comparison > 0
	})
	return result, nil
}

func DCFScenarios(forecast []numeric.Decimal, scenarios map[string][2]numeric.Decimal) ([]DCFScenario, error) {
	if len(scenarios) == 0 {
		return nil, errors.New("at least one scenario is required")
	}
	names := make([]string, 0, len(scenarios))
	for name := range scenarios {
		if name == "" {
			return nil, errors.New("scenario names cannot be empty")
		}
		names = append(names, name)
	}
	sort.Strings(names)
	result := make([]DCFScenario, 0, len(names))
	for _, name := range names {
		assumptions := scenarios[name]
		value, err := MultiStageDCF(forecast, assumptions[0], TerminalAssumption{
			Method: TerminalPerpetuityGrowth, GrowthRate: assumptions[1],
		}, false)
		if err != nil {
			return nil, err
		}
		result = append(result, DCFScenario{Name: name, DiscountRate: assumptions[0], TerminalGrowth: assumptions[1], Result: value})
	}
	return result, nil
}

func ReverseOperatingMargin(
	targetEnterpriseValue, baseRevenue, revenueGrowth, taxRate, reinvestmentRate,
	discountRate, terminalGrowth numeric.Decimal, years, maxIterations int, tolerance numeric.Decimal,
) (ReverseExpectationsResult, error) {
	return reverseFCFFAssumption(
		targetEnterpriseValue, numeric.MustDecimal("0"), numeric.MustDecimal("0.80"),
		maxIterations, tolerance, true,
		func(candidate numeric.Decimal) (numeric.Decimal, error) {
			forecast, err := fcffFromRevenuePath(baseRevenue, revenueGrowth, candidate, taxRate, reinvestmentRate, years)
			if err != nil {
				return numeric.Decimal{}, err
			}
			result, err := MultiStageDCF(forecast, discountRate, TerminalAssumption{
				Method: TerminalPerpetuityGrowth, GrowthRate: terminalGrowth,
			}, false)
			return result.EnterpriseValue, err
		},
	)
}

func ReverseReinvestmentRate(
	targetEnterpriseValue, baseRevenue, revenueGrowth, operatingMargin, taxRate,
	discountRate, terminalGrowth numeric.Decimal, years, maxIterations int, tolerance numeric.Decimal,
) (ReverseExpectationsResult, error) {
	return reverseFCFFAssumption(
		targetEnterpriseValue, numeric.MustDecimal("0"), numeric.MustDecimal("0.999999"),
		maxIterations, tolerance, false,
		func(candidate numeric.Decimal) (numeric.Decimal, error) {
			forecast, err := fcffFromRevenuePath(baseRevenue, revenueGrowth, operatingMargin, taxRate, candidate, years)
			if err != nil {
				return numeric.Decimal{}, err
			}
			result, err := MultiStageDCF(forecast, discountRate, TerminalAssumption{
				Method: TerminalPerpetuityGrowth, GrowthRate: terminalGrowth,
			}, false)
			return result.EnterpriseValue, err
		},
	)
}

func ImpliedReturnOnCapital(growthRate, reinvestmentRate numeric.Decimal) (numeric.Decimal, error) {
	if err := validateUnitRate(reinvestmentRate, "reinvestment rate"); err != nil {
		return numeric.Decimal{}, err
	}
	if sign, _ := compare(reinvestmentRate, zero); sign == 0 {
		return numeric.Decimal{}, errors.New("reinvestment rate must be non-zero")
	}
	return divide(growthRate, reinvestmentRate)
}

func reverseFCFFAssumption(
	target, low, high numeric.Decimal, maxIterations int, tolerance numeric.Decimal, increasing bool,
	valueAt func(numeric.Decimal) (numeric.Decimal, error),
) (ReverseExpectationsResult, error) {
	if maxIterations < 1 {
		return ReverseExpectationsResult{}, errors.New("iteration budget must be positive")
	}
	if sign, _ := compare(target, zero); sign <= 0 {
		return ReverseExpectationsResult{}, errors.New("target enterprise value must be positive")
	}
	for iteration := 1; iteration <= maxIterations; iteration++ {
		sum, err := add(low, high)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		candidate, err := divide(sum, numeric.MustDecimal("2"))
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		value, err := valueAt(candidate)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		difference, err := subtract(value, target)
		if err != nil {
			return ReverseExpectationsResult{}, err
		}
		absoluteDifference, _ := absolute(difference)
		if within, _ := compare(absoluteDifference, tolerance); within <= 0 {
			return ReverseExpectationsResult{ImpliedValue: candidate, Iterations: iteration, Converged: true}, nil
		}
		if direction, _ := compare(difference, zero); (direction > 0) == increasing {
			high = candidate
		} else {
			low = candidate
		}
	}
	return ReverseExpectationsResult{Iterations: maxIterations, Converged: false}, nil
}

func intString(value int) string {
	if value == 0 {
		return "0"
	}
	negative := value < 0
	if negative {
		value = -value
	}
	buffer := make([]byte, 0, 20)
	for value > 0 {
		buffer = append(buffer, byte('0'+value%10))
		value /= 10
	}
	if negative {
		buffer = append(buffer, '-')
	}
	for left, right := 0, len(buffer)-1; left < right; left, right = left+1, right-1 {
		buffer[left], buffer[right] = buffer[right], buffer[left]
	}
	return string(buffer)
}
