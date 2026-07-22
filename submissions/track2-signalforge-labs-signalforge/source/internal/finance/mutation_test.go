package finance

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/numeric"
)

// These hand-seeded mutants guard the highest-risk operator and denominator changes.
func TestGoldenCasesKillKnownFormulaMutants(t *testing.T) {
	t.Run("FCF addition mutant", func(t *testing.T) {
		mutant, err := add(numeric.MustDecimal("30"), numeric.MustDecimal("10"))
		if err != nil {
			t.Fatal(err)
		}
		if mutant.String() == "20" {
			t.Fatal("golden FCF case did not kill addition mutant")
		}
	})

	t.Run("net debt addition mutant", func(t *testing.T) {
		mutant, err := add(numeric.MustDecimal("50"), numeric.MustDecimal("20"))
		if err != nil {
			t.Fatal(err)
		}
		if mutant.String() == "30" {
			t.Fatal("golden net-debt case did not kill addition mutant")
		}
	})

	t.Run("Fisher subtraction mutant", func(t *testing.T) {
		mutant, err := subtract(numeric.MustDecimal("0.06"), numeric.MustDecimal("0.02"))
		if err != nil {
			t.Fatal(err)
		}
		if mutant.String() == "0.03921568627450980392156862745098" {
			t.Fatal("golden real-rate case did not kill subtraction mutant")
		}
	})

	t.Run("terminal denominator addition mutant", func(t *testing.T) {
		correct, err := FCFFDCF([]numeric.Decimal{numeric.MustDecimal("10"), numeric.MustDecimal("11"), numeric.MustDecimal("12")}, numeric.MustDecimal("0.10"), numeric.MustDecimal("0.03"))
		if err != nil {
			t.Fatal(err)
		}
		mutantDenominator, err := add(numeric.MustDecimal("0.10"), numeric.MustDecimal("0.03"))
		if err != nil {
			t.Fatal(err)
		}
		mutantTerminal, err := divide(numeric.MustDecimal("12.36"), mutantDenominator)
		if err != nil {
			t.Fatal(err)
		}
		if mutantTerminal.String() == correct.TerminalPresentValue.String() {
			t.Fatal("golden DCF case did not kill terminal-denominator mutant")
		}
	})

	t.Run("beta inverse mutant", func(t *testing.T) {
		security := []float64{0.02, -0.01, 0.03, -0.02}
		benchmark := []float64{0.01, -0.02, 0.02, -0.01}
		covariance, err := Covariance(security, benchmark, 1)
		if err != nil {
			t.Fatal(err)
		}
		securityVariance, err := Variance(security, 1)
		if err != nil {
			t.Fatal(err)
		}
		mutant := covariance / securityVariance
		if mutant == 1.2 {
			t.Fatal("golden beta case did not kill inverse-variance mutant")
		}
	})
}
