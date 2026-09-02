package finance

import (
	"errors"
	"math"
	"sort"
)

type ValueLevel string

const (
	ValueLevelEquity     ValueLevel = "equity_value"
	ValueLevelEnterprise ValueLevel = "enterprise_value"
)

type MultipleKind string

const (
	MultiplePE        MultipleKind = "price_to_earnings"
	MultiplePriceBook MultipleKind = "price_to_book"
	MultiplePriceFCF  MultipleKind = "price_to_fcfe"
	MultipleEVRevenue MultipleKind = "ev_to_revenue"
	MultipleEVEBITDA  MultipleKind = "ev_to_ebitda"
	MultipleEVEBIT    MultipleKind = "ev_to_ebit"
)

func TypedMultiple(kind MultipleKind, level ValueLevel, numerator, denominator float64) (float64, error) {
	expected := map[MultipleKind]ValueLevel{
		MultiplePE: ValueLevelEquity, MultiplePriceBook: ValueLevelEquity, MultiplePriceFCF: ValueLevelEquity,
		MultipleEVRevenue: ValueLevelEnterprise, MultipleEVEBITDA: ValueLevelEnterprise, MultipleEVEBIT: ValueLevelEnterprise,
	}
	expectedLevel, exists := expected[kind]
	if !exists {
		return 0, errors.New("unsupported multiple kind")
	}
	if level != expectedLevel {
		return 0, errors.New("value_level_mismatch: numerator and denominator belong to different value levels")
	}
	if denominator <= 0 || math.IsNaN(numerator) || math.IsNaN(denominator) || math.IsInf(numerator, 0) || math.IsInf(denominator, 0) {
		return 0, errors.New("multiple requires finite numerator and positive denominator")
	}
	return numerator / denominator, nil
}

type PeerStatisticsResult struct {
	SubjectValue            float64
	Median                  float64
	Percentile              float64
	MedianAbsoluteDeviation float64
	RobustZScore            float64
	Observations            int
}

func PeerStatistics(peers []float64, subject float64, minimumSample int) (PeerStatisticsResult, error) {
	if minimumSample < 3 || len(peers) < minimumSample {
		return PeerStatisticsResult{}, errors.New("peer sample is below the declared minimum")
	}
	values := append([]float64(nil), peers...)
	for _, value := range append(values, subject) {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return PeerStatisticsResult{}, errors.New("peer values must be finite")
		}
	}
	sort.Float64s(values)
	medianValue := median(values)
	deviations := make([]float64, len(values))
	lessOrEqual := 0
	for index, value := range values {
		deviations[index] = math.Abs(value - medianValue)
		if value <= subject {
			lessOrEqual++
		}
	}
	sort.Float64s(deviations)
	mad := median(deviations)
	robustZ := 0.0
	if mad != 0 {
		robustZ = 0.6744897501960817 * (subject - medianValue) / mad
	}
	return PeerStatisticsResult{
		SubjectValue: subject, Median: medianValue, Percentile: float64(lessOrEqual) / float64(len(values)),
		MedianAbsoluteDeviation: mad, RobustZScore: robustZ, Observations: len(values),
	}, nil
}

type DuPontResult struct {
	NetMargin         float64
	AssetTurnover     float64
	FinancialLeverage float64
	ReturnOnEquity    float64
}

func DuPont(netIncome, revenue, averageAssets, averageEquity float64) (DuPontResult, error) {
	if revenue <= 0 || averageAssets <= 0 || averageEquity <= 0 {
		return DuPontResult{}, errors.New("DuPont denominators must be positive")
	}
	margin := netIncome / revenue
	turnover := revenue / averageAssets
	leverage := averageAssets / averageEquity
	return DuPontResult{NetMargin: margin, AssetTurnover: turnover, FinancialLeverage: leverage, ReturnOnEquity: margin * turnover * leverage}, nil
}

type AssociationResult struct {
	Label        string
	Slope        float64
	Intercept    float64
	Correlation  float64
	RSquared     float64
	Observations int
	Lag          int
}

func LinearAssociation(x, y []float64, minimumSample int) (AssociationResult, error) {
	return LaggedAssociation(x, y, 0, minimumSample)
}

func LaggedAssociation(x, y []float64, lag, minimumSample int) (AssociationResult, error) {
	if len(x) != len(y) || lag < 0 || lag >= len(x) {
		return AssociationResult{}, errors.New("aligned equal-length series and a valid non-negative lag are required")
	}
	left, right := x[:len(x)-lag], y[lag:]
	if len(left) < minimumSample || minimumSample < 3 {
		return AssociationResult{}, errors.New("association sample is below the declared minimum")
	}
	meanX, meanY := 0.0, 0.0
	for index := range left {
		if !finite(left[index]) || !finite(right[index]) {
			return AssociationResult{}, errors.New("association values must be finite")
		}
		meanX += left[index]
		meanY += right[index]
	}
	meanX /= float64(len(left))
	meanY /= float64(len(right))
	covariance, varianceX, varianceY := 0.0, 0.0, 0.0
	for index := range left {
		dx, dy := left[index]-meanX, right[index]-meanY
		covariance += dx * dy
		varianceX += dx * dx
		varianceY += dy * dy
	}
	if varianceX == 0 || varianceY == 0 {
		return AssociationResult{}, errors.New("association requires non-zero variance")
	}
	slope := covariance / varianceX
	correlation := covariance / math.Sqrt(varianceX*varianceY)
	return AssociationResult{
		Label: "statistical_association_not_causality", Slope: slope, Intercept: meanY - slope*meanX,
		Correlation: correlation, RSquared: correlation * correlation, Observations: len(left), Lag: lag,
	}, nil
}

func median(values []float64) float64 {
	middle := len(values) / 2
	if len(values)%2 == 1 {
		return values[middle]
	}
	return (values[middle-1] + values[middle]) / 2
}

func finite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
