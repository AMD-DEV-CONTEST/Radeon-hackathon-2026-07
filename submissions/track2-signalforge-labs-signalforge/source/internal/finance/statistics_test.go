package finance

import (
	"math"
	"testing"
)

func assertClose(t *testing.T, actual, expected, tolerance float64) {
	t.Helper()
	if math.Abs(actual-expected) > tolerance {
		t.Fatalf("got %.17g, want %.17g within %.3g", actual, expected, tolerance)
	}
}

func TestStatisticsGoldenCases(t *testing.T) {
	totalReturn, err := TotalReturn(100, 110, 2)
	if err != nil {
		t.Fatal(err)
	}
	assertClose(t, totalReturn, 0.12, 1e-12)

	volatility, err := Volatility([]float64{0.01, -0.01, 0.02, -0.02}, 252, 1)
	if err != nil {
		t.Fatal(err)
	}
	assertClose(t, volatility, 0.28982753492378877, 1e-12)

	drawdown, err := Drawdown([]float64{100, 120, 90, 110})
	if err != nil {
		t.Fatal(err)
	}
	for index, expected := range []float64{0, 0, -0.25, -0.08333333333333333} {
		assertClose(t, drawdown.Series[index], expected, 1e-12)
	}
	assertClose(t, drawdown.Maximum, -0.25, 1e-12)

	beta, observations, err := Beta([]float64{0.02, -0.01, 0.03, -0.02}, []float64{0.01, -0.02, 0.02, -0.01}, 1)
	if err != nil {
		t.Fatal(err)
	}
	assertClose(t, beta, 1.2, 1e-12)
	if observations != 4 {
		t.Fatalf("got %d observations", observations)
	}

	rolling, err := RollingCorrelation([]float64{1, 2, 3, 4}, []float64{2, 4, 6, 8}, 3)
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range rolling {
		assertClose(t, value, 1, 1e-12)
	}
}

func TestStatisticsBoundariesFailClosed(t *testing.T) {
	if _, err := TotalReturn(0, 1, 0); err == nil {
		t.Fatal("zero start price must fail")
	}
	if _, _, err := Beta([]float64{1, 2}, []float64{1, 1}, 1); err == nil {
		t.Fatal("zero benchmark variance must fail")
	}
	if _, err := RollingCorrelation([]float64{1, 2}, []float64{1}, 2); err == nil {
		t.Fatal("mismatched series must fail")
	}
	if _, err := Drawdown([]float64{100, 0}); err == nil {
		t.Fatal("non-positive wealth must fail")
	}
	if _, err := Returns([]float64{100, math.NaN()}); err == nil {
		t.Fatal("non-finite series must fail")
	}
}
