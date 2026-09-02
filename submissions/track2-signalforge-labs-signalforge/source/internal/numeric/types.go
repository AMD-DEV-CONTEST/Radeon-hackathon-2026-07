package numeric

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
)

const (
	MoneyDecimalV1      = "money-decimal/v1"
	RatioDecimalV1      = "ratio-decimal/v1"
	MixedNumericV1      = "mixed-numeric/v1"
	StatisticsFloat64V1 = "statistics-float64/v1"
	DecimalPrecision    = uint32(34)
)

var DecimalContext = apd.Context{
	Precision:   DecimalPrecision,
	MaxExponent: apd.MaxExponent,
	MinExponent: apd.MinExponent,
	Traps:       apd.DefaultTraps,
	Rounding:    apd.RoundHalfEven,
}

type Decimal struct {
	value string
}

func ParseDecimal(value string) (Decimal, error) {
	parsed, _, err := apd.NewFromString(strings.TrimSpace(value))
	if err != nil {
		return Decimal{}, fmt.Errorf("parse decimal: %w", err)
	}
	if parsed.Form != apd.Finite {
		return Decimal{}, errors.New("decimal must be finite")
	}
	var reduced apd.Decimal
	reduced.Reduce(parsed)
	return Decimal{value: reduced.Text('f')}, nil
}

func MustDecimal(value string) Decimal {
	parsed, err := ParseDecimal(value)
	if err != nil {
		panic(err)
	}
	return parsed
}

func (value Decimal) String() string {
	return value.value
}

func (value Decimal) MarshalJSON() ([]byte, error) {
	if value.value == "" {
		return nil, errors.New("empty decimal")
	}
	return json.Marshal(value.value)
}

func (value *Decimal) UnmarshalJSON(data []byte) error {
	var encoded string
	if err := json.Unmarshal(data, &encoded); err != nil {
		return errors.New("decimal must be encoded as a JSON string")
	}
	parsed, err := ParseDecimal(encoded)
	if err != nil {
		return err
	}
	*value = parsed
	return nil
}

type Unit string

const (
	UnitCurrency   Unit = "currency"
	UnitRatio      Unit = "ratio"
	UnitPercent    Unit = "percent"
	UnitShares     Unit = "shares"
	UnitCount      Unit = "count"
	UnitPerShare   Unit = "currency_per_share"
	UnitDays       Unit = "days"
	UnitYears      Unit = "years"
	UnitIndexPoint Unit = "index_point"
)

type PeriodKind string

const (
	PeriodInstant  PeriodKind = "instant"
	PeriodDuration PeriodKind = "duration"
	PeriodSeries   PeriodKind = "series"
)

type FiscalPeriod struct {
	Kind       PeriodKind `json:"kind"`
	Start      *time.Time `json:"start,omitempty"`
	End        time.Time  `json:"end"`
	FiscalYear int        `json:"fiscal_year,omitempty"`
	FiscalCode string     `json:"fiscal_code,omitempty"`
}

type Quantity struct {
	Value           Decimal      `json:"value"`
	Unit            Unit         `json:"unit"`
	Currency        string       `json:"currency,omitempty"`
	Scale           int32        `json:"scale"`
	Period          FiscalPeriod `json:"period"`
	AsOf            time.Time    `json:"as_of"`
	PrecisionPolicy string       `json:"precision_policy"`
}

type StatisticalPolicy struct {
	Tolerance     float64 `json:"tolerance"`
	MinimumSample int     `json:"minimum_sample"`
	Annualization int     `json:"annualization,omitempty"`
}

func ValidateQuantity(quantity Quantity) error {
	if quantity.Value.value == "" || quantity.AsOf.IsZero() || quantity.Period.End.IsZero() {
		return errors.New("value, period.end, and as_of are required")
	}
	switch quantity.Unit {
	case UnitCurrency, UnitRatio, UnitPercent, UnitShares, UnitCount, UnitPerShare, UnitDays, UnitYears, UnitIndexPoint:
	default:
		return fmt.Errorf("unsupported unit %q", quantity.Unit)
	}
	if (quantity.Unit == UnitCurrency || quantity.Unit == UnitPerShare) && len(quantity.Currency) != 3 {
		return errors.New("monetary quantities require a three-letter currency")
	}
	if quantity.Unit != UnitCurrency && quantity.Unit != UnitPerShare && quantity.Currency != "" {
		return errors.New("non-monetary quantities cannot declare currency")
	}
	switch quantity.Period.Kind {
	case PeriodInstant:
		if quantity.Period.Start != nil {
			return errors.New("instant periods cannot have a start")
		}
	case PeriodDuration, PeriodSeries:
		if quantity.Period.Start == nil || quantity.Period.Start.After(quantity.Period.End) {
			return errors.New("duration and series periods require an ordered start")
		}
	default:
		return fmt.Errorf("unsupported period kind %q", quantity.Period.Kind)
	}
	switch quantity.PrecisionPolicy {
	case MoneyDecimalV1, RatioDecimalV1, MixedNumericV1:
	default:
		return fmt.Errorf("unsupported decimal precision policy %q", quantity.PrecisionPolicy)
	}
	return nil
}

func ValidateStatisticalPolicy(policy StatisticalPolicy, values []float64) error {
	if policy.Tolerance <= 0 || policy.MinimumSample < 2 {
		return errors.New("positive tolerance and minimum sample of at least two are required")
	}
	if len(values) < policy.MinimumSample {
		return errors.New("sample is smaller than the declared minimum")
	}
	for _, value := range values {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return errors.New("statistical inputs must be finite")
		}
	}
	return nil
}
