package finance

import (
	"errors"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

func NOPAT(operatingIncome, taxRate numeric.Decimal) (numeric.Decimal, error) {
	if err := validateUnitRate(taxRate, "tax rate"); err != nil {
		return numeric.Decimal{}, err
	}
	afterTaxRate, err := subtract(one, taxRate)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return multiply(operatingIncome, afterTaxRate)
}

type InvestedCapitalResult struct {
	OperatingApproach numeric.Decimal
	FinancingApproach numeric.Decimal
	Difference        numeric.Decimal
}

func InvestedCapital(
	operatingAssets, nonInterestBearingOperatingLiabilities,
	debt, equity, cashAndEquivalents, nonOperatingAssets numeric.Decimal,
) (InvestedCapitalResult, error) {
	operating, err := subtract(operatingAssets, nonInterestBearingOperatingLiabilities)
	if err != nil {
		return InvestedCapitalResult{}, err
	}
	financing, err := add(debt, equity)
	if err != nil {
		return InvestedCapitalResult{}, err
	}
	financing, err = subtract(financing, cashAndEquivalents)
	if err != nil {
		return InvestedCapitalResult{}, err
	}
	financing, err = subtract(financing, nonOperatingAssets)
	if err != nil {
		return InvestedCapitalResult{}, err
	}
	difference, err := subtract(operating, financing)
	if err != nil {
		return InvestedCapitalResult{}, err
	}
	return InvestedCapitalResult{OperatingApproach: operating, FinancingApproach: financing, Difference: difference}, nil
}

func AverageInvestedCapital(beginning, ending numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(beginning, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("beginning invested capital must be positive")
	}
	if sign, _ := compare(ending, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("ending invested capital must be positive")
	}
	sum, err := add(beginning, ending)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return divide(sum, numeric.MustDecimal("2"))
}

func OperatingWorkingCapital(accountsReceivable, inventory, otherOperatingCurrentAssets, accountsPayable, otherOperatingCurrentLiabilities numeric.Decimal) (numeric.Decimal, error) {
	assets, err := add(accountsReceivable, inventory)
	if err != nil {
		return numeric.Decimal{}, err
	}
	assets, err = add(assets, otherOperatingCurrentAssets)
	if err != nil {
		return numeric.Decimal{}, err
	}
	liabilities, err := add(accountsPayable, otherOperatingCurrentLiabilities)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return subtract(assets, liabilities)
}

func ChangeInWorkingCapital(ending, beginning numeric.Decimal) (numeric.Decimal, error) {
	return subtract(ending, beginning)
}

func NetCapitalExpenditure(capitalExpenditure, depreciationAndAmortization numeric.Decimal) (numeric.Decimal, error) {
	return subtract(capitalExpenditure, depreciationAndAmortization)
}

func Reinvestment(netCapitalExpenditure, changeInWorkingCapital, acquisitions numeric.Decimal) (numeric.Decimal, error) {
	value, err := add(netCapitalExpenditure, changeInWorkingCapital)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return add(value, acquisitions)
}

func FCFFFromNOPAT(nopat, reinvestment numeric.Decimal) (numeric.Decimal, error) {
	return subtract(nopat, reinvestment)
}

func FCFE(netIncome, capitalExpenditure, depreciationAndAmortization, changeInWorkingCapital, netBorrowing numeric.Decimal) (numeric.Decimal, error) {
	netCapex, err := NetCapitalExpenditure(capitalExpenditure, depreciationAndAmortization)
	if err != nil {
		return numeric.Decimal{}, err
	}
	value, err := subtract(netIncome, netCapex)
	if err != nil {
		return numeric.Decimal{}, err
	}
	value, err = subtract(value, changeInWorkingCapital)
	if err != nil {
		return numeric.Decimal{}, err
	}
	return add(value, netBorrowing)
}

func ROIC(nopat, investedCapital numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(investedCapital, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("invested capital must be positive")
	}
	return divide(nopat, investedCapital)
}

func IncrementalROIC(changeInNOPAT, changeInInvestedCapital numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(changeInInvestedCapital, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("change in invested capital must be positive")
	}
	return divide(changeInNOPAT, changeInInvestedCapital)
}

func ValueCreationSpread(roic, wacc numeric.Decimal) (numeric.Decimal, error) {
	return subtract(roic, wacc)
}

func ReinvestmentRate(reinvestment, nopat numeric.Decimal) (numeric.Decimal, error) {
	if sign, _ := compare(nopat, zero); sign <= 0 {
		return numeric.Decimal{}, errors.New("NOPAT must be positive for reinvestment rate")
	}
	return divide(reinvestment, nopat)
}

func FundamentalGrowth(returnOnCapital, reinvestmentRate numeric.Decimal) (numeric.Decimal, error) {
	return multiply(returnOnCapital, reinvestmentRate)
}

func SustainableEquityGrowth(returnOnEquity, retentionRatio numeric.Decimal) (numeric.Decimal, error) {
	if err := validateUnitRate(retentionRatio, "retention ratio"); err != nil {
		return numeric.Decimal{}, err
	}
	return multiply(returnOnEquity, retentionRatio)
}

func validateUnitRate(rate numeric.Decimal, name string) error {
	if lower, _ := compare(rate, zero); lower < 0 {
		return errors.New(name + " cannot be negative")
	}
	if upper, _ := compare(rate, one); upper > 0 {
		return errors.New(name + " cannot exceed one")
	}
	return nil
}
