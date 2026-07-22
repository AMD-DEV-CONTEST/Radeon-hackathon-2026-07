package finance

import (
	"errors"
	"math"
)

func validateFinite(values []float64, minimum int) error {
	if len(values) < minimum {
		return fmtSample(minimum)
	}
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return errors.New("series contains non-finite values")
		}
	}
	return nil
}

func fmtSample(minimum int) error {
	return errors.New("series does not meet minimum sample")
}

func TotalReturn(startPrice, endPrice, distributions float64) (float64, error) {
	if err := validateFinite([]float64{startPrice, endPrice, distributions}, 3); err != nil {
		return 0, err
	}
	if startPrice <= 0 || endPrice < 0 || distributions < 0 {
		return 0, errors.New("start price must be positive; end price and distributions cannot be negative")
	}
	return (endPrice + distributions - startPrice) / startPrice, nil
}

func Returns(prices []float64) ([]float64, error) {
	if err := validateFinite(prices, 2); err != nil {
		return nil, err
	}
	result := make([]float64, 0, len(prices)-1)
	for index := 1; index < len(prices); index++ {
		if prices[index-1] == 0 {
			return nil, errors.New("return base cannot be zero")
		}
		result = append(result, prices[index]/prices[index-1]-1)
	}
	return result, nil
}

func mean(values []float64) float64 {
	total := 0.0
	for _, value := range values {
		total += value
	}
	return total / float64(len(values))
}

func Covariance(left, right []float64, ddof int) (float64, error) {
	if len(left) != len(right) {
		return 0, errors.New("series lengths differ")
	}
	if err := validateFinite(left, 2); err != nil {
		return 0, err
	}
	if err := validateFinite(right, 2); err != nil {
		return 0, err
	}
	if ddof < 0 || len(left)-ddof <= 0 {
		return 0, errors.New("invalid degrees of freedom")
	}
	leftMean, rightMean := mean(left), mean(right)
	total := 0.0
	for index := range left {
		total += (left[index] - leftMean) * (right[index] - rightMean)
	}
	return total / float64(len(left)-ddof), nil
}

func Variance(values []float64, ddof int) (float64, error) {
	return Covariance(values, values, ddof)
}

func Volatility(returns []float64, periodsPerYear float64, ddof int) (float64, error) {
	if periodsPerYear <= 0 || math.IsNaN(periodsPerYear) || math.IsInf(periodsPerYear, 0) {
		return 0, errors.New("periods per year must be finite and positive")
	}
	variance, err := Variance(returns, ddof)
	if err != nil {
		return 0, err
	}
	return math.Sqrt(variance) * math.Sqrt(periodsPerYear), nil
}

type DrawdownResult struct {
	Series  []float64
	Maximum float64
}

func Drawdown(wealthIndex []float64) (DrawdownResult, error) {
	if err := validateFinite(wealthIndex, 1); err != nil {
		return DrawdownResult{}, err
	}
	peak := -math.MaxFloat64
	maximum := 0.0
	series := make([]float64, len(wealthIndex))
	for index, value := range wealthIndex {
		if value <= 0 {
			return DrawdownResult{}, errors.New("wealth index must remain positive")
		}
		if value > peak {
			peak = value
		}
		series[index] = value/peak - 1
		if series[index] < maximum {
			maximum = series[index]
		}
	}
	return DrawdownResult{Series: series, Maximum: maximum}, nil
}

func Beta(securityReturns, benchmarkReturns []float64, ddof int) (float64, int, error) {
	covariance, err := Covariance(securityReturns, benchmarkReturns, ddof)
	if err != nil {
		return 0, 0, err
	}
	benchmarkVariance, err := Variance(benchmarkReturns, ddof)
	if err != nil {
		return 0, 0, err
	}
	if benchmarkVariance == 0 {
		return 0, 0, errors.New("benchmark variance is zero")
	}
	return covariance / benchmarkVariance, len(securityReturns), nil
}

func Correlation(left, right []float64, ddof int) (float64, error) {
	covariance, err := Covariance(left, right, ddof)
	if err != nil {
		return 0, err
	}
	leftVariance, err := Variance(left, ddof)
	if err != nil {
		return 0, err
	}
	rightVariance, err := Variance(right, ddof)
	if err != nil {
		return 0, err
	}
	denominator := math.Sqrt(leftVariance * rightVariance)
	if denominator == 0 {
		return 0, errors.New("correlation is undefined for a constant series")
	}
	return covariance / denominator, nil
}

func RollingCorrelation(left, right []float64, window int) ([]float64, error) {
	if len(left) != len(right) {
		return nil, errors.New("series lengths differ")
	}
	if window < 2 || window > len(left) {
		return nil, errors.New("window must be between two and the series length")
	}
	result := make([]float64, 0, len(left)-window+1)
	for end := window; end <= len(left); end++ {
		value, err := Correlation(left[end-window:end], right[end-window:end], 1)
		if err != nil {
			return nil, err
		}
		result = append(result, value)
	}
	return result, nil
}
