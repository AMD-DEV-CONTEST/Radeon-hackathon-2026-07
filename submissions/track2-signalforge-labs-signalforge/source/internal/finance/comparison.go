package finance

import (
	"errors"
	"sort"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

type ComparableMetric struct {
	Company  string
	Value    numeric.Decimal
	Period   string
	Unit     string
	Currency string
}

type ComparisonResult struct {
	Comparable bool
	Warnings   []string
}

func PeriodAligned(metrics []ComparableMetric, policy string) (ComparisonResult, error) {
	if len(metrics) < 2 {
		return ComparisonResult{}, errors.New("at least two company metrics are required")
	}
	if policy != "exact" {
		return ComparisonResult{}, errors.New("unsupported alignment policy")
	}
	reference := metrics[0]
	if reference.Company == "" || reference.Period == "" || reference.Unit == "" {
		return ComparisonResult{}, errors.New("company, period, and unit are required")
	}
	warnings := make([]string, 0)
	for _, metric := range metrics[1:] {
		if metric.Company == "" || metric.Period == "" || metric.Unit == "" {
			return ComparisonResult{}, errors.New("company, period, and unit are required")
		}
		if metric.Period != reference.Period {
			warnings = append(warnings, "period_mismatch")
		}
		if metric.Unit != reference.Unit {
			warnings = append(warnings, "unit_mismatch")
		}
		if metric.Currency != reference.Currency {
			warnings = append(warnings, "currency_mismatch")
		}
	}
	sort.Strings(warnings)
	warnings = unique(warnings)
	return ComparisonResult{Comparable: len(warnings) == 0, Warnings: warnings}, nil
}

func unique(values []string) []string {
	if len(values) == 0 {
		return values
	}
	result := values[:1]
	for _, value := range values[1:] {
		if value != result[len(result)-1] {
			result = append(result, value)
		}
	}
	return result
}

type SensitivityCell struct {
	DiscountRate    numeric.Decimal
	TerminalGrowth  numeric.Decimal
	EnterpriseValue numeric.Decimal
}

type SensitivityResult struct {
	Rows                    int
	Columns                 int
	Cells                   []SensitivityCell
	MonotonicDiscountRate   bool
	MonotonicTerminalGrowth bool
}

func DCFGrid(forecast []numeric.Decimal, discountRates, terminalGrowthRates []numeric.Decimal) (SensitivityResult, error) {
	if len(discountRates) == 0 || len(terminalGrowthRates) == 0 {
		return SensitivityResult{}, errors.New("both sensitivity axes are required")
	}
	result := SensitivityResult{Rows: len(discountRates), Columns: len(terminalGrowthRates), MonotonicDiscountRate: true, MonotonicTerminalGrowth: true}
	for row, rate := range discountRates {
		for column, growth := range terminalGrowthRates {
			calculation, err := FCFFDCF(forecast, rate, growth)
			if err != nil {
				return SensitivityResult{}, err
			}
			result.Cells = append(result.Cells, SensitivityCell{DiscountRate: rate, TerminalGrowth: growth, EnterpriseValue: calculation.EnterpriseValue})
			if row > 0 {
				above := result.Cells[(row-1)*len(terminalGrowthRates)+column]
				if order, _ := compare(calculation.EnterpriseValue, above.EnterpriseValue); order >= 0 {
					result.MonotonicDiscountRate = false
				}
			}
			if column > 0 {
				left := result.Cells[row*len(terminalGrowthRates)+column-1]
				if order, _ := compare(calculation.EnterpriseValue, left.EnterpriseValue); order <= 0 {
					result.MonotonicTerminalGrowth = false
				}
			}
		}
	}
	return result, nil
}
