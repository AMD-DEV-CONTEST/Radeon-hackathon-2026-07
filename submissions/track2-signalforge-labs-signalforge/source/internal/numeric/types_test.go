package numeric

import (
	"encoding/json"
	"math"
	"testing"
	"time"
)

func TestDecimalIsCanonicalAndStringEncoded(t *testing.T) {
	value, err := ParseDecimal("001.2300")
	if err != nil {
		t.Fatal(err)
	}
	if value.String() != "1.23" {
		t.Fatalf("unexpected canonical value %q", value.String())
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != "\"1.23\"" {
		t.Fatalf("decimal must be JSON-string encoded, got %s", encoded)
	}
	if err := json.Unmarshal([]byte("1.23"), &value); err == nil {
		t.Fatal("JSON number must be rejected to prevent binary-number ambiguity")
	}
}

func TestQuantityRejectsCurrencyAndPeriodMismatch(t *testing.T) {
	asOf := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	quantity := Quantity{
		Value: MustDecimal("10.25"), Unit: UnitCurrency, Currency: "USD",
		Period: FiscalPeriod{Kind: PeriodInstant, End: asOf}, AsOf: asOf, PrecisionPolicy: MoneyDecimalV1,
	}
	if err := ValidateQuantity(quantity); err != nil {
		t.Fatalf("valid quantity rejected: %v", err)
	}
	quantity.Currency = ""
	if err := ValidateQuantity(quantity); err == nil {
		t.Fatal("money without currency must fail")
	}
	quantity.Currency = "USD"
	start := asOf.Add(time.Hour)
	quantity.Period = FiscalPeriod{Kind: PeriodDuration, Start: &start, End: asOf}
	if err := ValidateQuantity(quantity); err == nil {
		t.Fatal("reversed period must fail")
	}
}

func TestFloat64PolicyFailsClosed(t *testing.T) {
	policy := StatisticalPolicy{Tolerance: 1e-9, MinimumSample: 3}
	if err := ValidateStatisticalPolicy(policy, []float64{1, 2, 3}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateStatisticalPolicy(policy, []float64{1, math.NaN(), 3}); err == nil {
		t.Fatal("NaN must fail")
	}
	if err := ValidateStatisticalPolicy(policy, []float64{1, 2}); err == nil {
		t.Fatal("undersized sample must fail")
	}
}
