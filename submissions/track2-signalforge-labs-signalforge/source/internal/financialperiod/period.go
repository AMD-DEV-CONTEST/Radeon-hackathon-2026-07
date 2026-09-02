package financialperiod

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/numeric"
)

type Kind string

type ObservationClass string

const (
	ClassReported   ObservationClass = "reported_fact"
	ClassNormalized ObservationClass = "normalized_fact"
	ClassDerived    ObservationClass = "derived_metric"
	ClassEstimate   ObservationClass = "estimate"
	ClassScenario   ObservationClass = "scenario"
)

type SignPolicy string

const (
	SignPreserve    SignPolicy = "preserve_reported_sign"
	SignPositiveUse SignPolicy = "normalize_cash_outflow_to_positive_use"
)

const (
	KindInstant    Kind = "instant"
	KindQuarter    Kind = "quarter"
	KindYearToDate Kind = "year_to_date"
	KindAnnual     Kind = "annual"
	KindTTM        Kind = "trailing_twelve_months"
)

type Period struct {
	Kind          Kind
	Start         *time.Time
	End           time.Time
	FiscalYear    int
	FiscalQuarter int
	Label         string
}

type Observation struct {
	MetricID         string
	CompanyID        string
	Class            ObservationClass
	Value            numeric.Decimal
	RawReportedValue *numeric.Decimal
	Unit             string
	Currency         string
	Scale            int32
	Period           Period
	AvailableAt      time.Time
	ComputedAt       time.Time
	SourceFactIDs    []string
	TransformationID string
	SignPolicy       SignPolicy
	AmendmentChain   []string
}

func ValidatePeriod(period Period) error {
	if period.End.IsZero() || strings.TrimSpace(period.Label) == "" {
		return errors.New("period end and label are required")
	}
	switch period.Kind {
	case KindInstant:
		if period.Start != nil {
			return errors.New("instant period cannot declare a start")
		}
	case KindQuarter, KindYearToDate, KindAnnual, KindTTM:
		if period.Start == nil || !period.Start.Before(period.End) {
			return errors.New("duration period requires an ordered start and end")
		}
	default:
		return fmt.Errorf("unsupported period kind %q", period.Kind)
	}
	if period.FiscalQuarter < 0 || period.FiscalQuarter > 4 {
		return errors.New("fiscal quarter must be between zero and four")
	}
	return nil
}

func ValidateObservation(observation Observation, cutoff time.Time) error {
	if observation.MetricID == "" || observation.CompanyID == "" || observation.Unit == "" {
		return errors.New("metric, company, and unit are required")
	}
	if err := ValidatePeriod(observation.Period); err != nil {
		return err
	}
	switch observation.Class {
	case ClassReported, ClassDerived, ClassEstimate, ClassScenario:
	case ClassNormalized:
		if observation.RawReportedValue == nil || observation.SignPolicy == "" || observation.TransformationID == "" {
			return errors.New("normalized fact requires raw value, sign policy, and transformation lineage")
		}
	default:
		return errors.New("observation class is required")
	}
	if observation.AvailableAt.IsZero() || observation.AvailableAt.After(cutoff) {
		return errors.New("look_ahead_detected: observation is unavailable at cutoff")
	}
	if observation.Unit == "currency" && len(observation.Currency) != 3 {
		return errors.New("currency observation requires a three-letter currency")
	}
	if observation.Unit != "currency" && observation.Currency != "" {
		return errors.New("non-currency observation cannot declare a currency")
	}
	if len(observation.SourceFactIDs) == 0 {
		return errors.New("source fact lineage is required")
	}
	return nil
}

func NormalizeReportedSign(observation Observation, policy SignPolicy, computedAt time.Time) (Observation, error) {
	if observation.Class != ClassReported {
		return Observation{}, errors.New("sign normalization requires a reported fact")
	}
	if err := ValidateObservation(observation, observation.AvailableAt); err != nil {
		return Observation{}, err
	}
	normalized := observation
	raw := observation.Value
	normalized.RawReportedValue = &raw
	normalized.Class = ClassNormalized
	normalized.SignPolicy = policy
	normalized.ComputedAt = computedAt
	switch policy {
	case SignPreserve:
		normalized.TransformationID = "sign-preserve/v1"
	case SignPositiveUse:
		if sign, err := decimalCompare(normalized.Value, numeric.MustDecimal("0")); err != nil {
			return Observation{}, err
		} else if sign < 0 {
			normalized.Value, err = decimalBinary(numeric.MustDecimal("0"), normalized.Value, numeric.DecimalContext.Sub)
			if err != nil {
				return Observation{}, err
			}
		}
		normalized.TransformationID = "cash-outflow-positive-use/v1"
	default:
		return Observation{}, fmt.Errorf("unsupported sign policy %q", policy)
	}
	return normalized, nil
}

func TrailingTwelveMonths(priorAnnual, currentYTD, priorYTD Observation, cutoff, computedAt time.Time) (Observation, error) {
	for name, observation := range map[string]Observation{
		"prior annual": priorAnnual,
		"current YTD":  currentYTD,
		"prior YTD":    priorYTD,
	} {
		if err := ValidateObservation(observation, cutoff); err != nil {
			return Observation{}, fmt.Errorf("%s: %w", name, err)
		}
	}
	if priorAnnual.Period.Kind != KindAnnual || currentYTD.Period.Kind != KindYearToDate || priorYTD.Period.Kind != KindYearToDate {
		return Observation{}, errors.New("period_mismatch: TTM requires one annual and two YTD observations")
	}
	if err := compatible(priorAnnual, currentYTD, priorYTD); err != nil {
		return Observation{}, err
	}
	if !currentYTD.Period.End.After(priorAnnual.Period.End) || !sameMonthDay(currentYTD.Period.End, priorYTD.Period.End) {
		return Observation{}, errors.New("period_mismatch: current and comparative YTD periods are not aligned")
	}
	if currentYTD.Period.Start == nil || priorYTD.Period.Start == nil || !sameMonthDay(*currentYTD.Period.Start, *priorYTD.Period.Start) {
		return Observation{}, errors.New("period_mismatch: YTD starts are not aligned")
	}

	annualPlusCurrent, err := decimalBinary(priorAnnual.Value, currentYTD.Value, numeric.DecimalContext.Add)
	if err != nil {
		return Observation{}, err
	}
	value, err := decimalBinary(annualPlusCurrent, priorYTD.Value, numeric.DecimalContext.Sub)
	if err != nil {
		return Observation{}, err
	}
	start := priorYTD.Period.End.AddDate(0, 0, 1)
	return Observation{
		MetricID: priorAnnual.MetricID, CompanyID: priorAnnual.CompanyID, Class: ClassDerived, Value: value,
		Unit: priorAnnual.Unit, Currency: priorAnnual.Currency, Scale: priorAnnual.Scale,
		Period:      Period{Kind: KindTTM, Start: &start, End: currentYTD.Period.End, FiscalYear: currentYTD.Period.FiscalYear, Label: "TTM-" + currentYTD.Period.End.Format("2006-01-02")},
		AvailableAt: latest(priorAnnual.AvailableAt, currentYTD.AvailableAt, priorYTD.AvailableAt),
		ComputedAt:  computedAt, SourceFactIDs: uniqueSorted(append(append(append([]string(nil), priorAnnual.SourceFactIDs...), currentYTD.SourceFactIDs...), priorYTD.SourceFactIDs...)),
		TransformationID: "ttm-annual-plus-current-ytd-minus-prior-ytd/v1",
		AmendmentChain:   uniqueSorted(append(append(append([]string(nil), priorAnnual.AmendmentChain...), currentYTD.AmendmentChain...), priorYTD.AmendmentChain...)),
	}, nil
}

type CommonSizeValue struct {
	MetricID        string
	Ratio           numeric.Decimal
	NumeratorFact   []string
	DenominatorFact []string
}

func CommonSize(observations []Observation, denominatorMetric string, cutoff time.Time) ([]CommonSizeValue, error) {
	if len(observations) == 0 || denominatorMetric == "" {
		return nil, errors.New("observations and denominator metric are required")
	}
	var denominator *Observation
	for index := range observations {
		if err := ValidateObservation(observations[index], cutoff); err != nil {
			return nil, err
		}
		if observations[index].MetricID == denominatorMetric {
			if denominator != nil {
				return nil, errors.New("definition_conflict: duplicate common-size denominator")
			}
			denominator = &observations[index]
		}
	}
	if denominator == nil {
		return nil, errors.New("insufficient_evidence: common-size denominator is missing")
	}
	denominatorSign, err := decimalCompare(denominator.Value, numeric.MustDecimal("0"))
	if err != nil {
		return nil, err
	}
	if denominatorSign <= 0 {
		return nil, errors.New("invalid_denominator: common-size denominator must be positive")
	}
	result := make([]CommonSizeValue, 0, len(observations))
	for _, observation := range observations {
		if err := compatibleDimensions(*denominator, observation); err != nil {
			return nil, err
		}
		if !samePeriod(denominator.Period, observation.Period) {
			return nil, errors.New("period_mismatch: common-size observations use different periods")
		}
		ratio, err := decimalBinary(observation.Value, denominator.Value, numeric.DecimalContext.Quo)
		if err != nil {
			return nil, err
		}
		result = append(result, CommonSizeValue{MetricID: observation.MetricID, Ratio: ratio, NumeratorFact: append([]string(nil), observation.SourceFactIDs...), DenominatorFact: append([]string(nil), denominator.SourceFactIDs...)})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].MetricID < result[j].MetricID })
	return result, nil
}

type TrendDirection string

const (
	TrendIncreasing TrendDirection = "increasing"
	TrendDecreasing TrendDirection = "decreasing"
	TrendMixed      TrendDirection = "mixed"
	TrendFlat       TrendDirection = "flat"
)

type TrendDescriptor struct {
	MetricID        string
	Direction       TrendDirection
	Observations    int
	PositiveChanges int
	NegativeChanges int
	FlatChanges     int
	StartPeriod     string
	EndPeriod       string
	SourceFactIDs   []string
}

func DescribeTrend(observations []Observation, cutoff time.Time, tolerance numeric.Decimal) (TrendDescriptor, error) {
	if len(observations) < 2 {
		return TrendDescriptor{}, errors.New("insufficient_evidence: trend requires at least two observations")
	}
	ordered := append([]Observation(nil), observations...)
	for _, observation := range ordered {
		if err := ValidateObservation(observation, cutoff); err != nil {
			return TrendDescriptor{}, err
		}
	}
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].Period.End.Before(ordered[j].Period.End) })
	for index := 1; index < len(ordered); index++ {
		if err := compatible(ordered[0], ordered[index]); err != nil {
			return TrendDescriptor{}, err
		}
		if ordered[index-1].Period.End.Equal(ordered[index].Period.End) {
			return TrendDescriptor{}, errors.New("definition_conflict: trend contains duplicate period ends")
		}
	}

	descriptor := TrendDescriptor{MetricID: ordered[0].MetricID, Observations: len(ordered), StartPeriod: ordered[0].Period.Label, EndPeriod: ordered[len(ordered)-1].Period.Label}
	for index := 1; index < len(ordered); index++ {
		difference, err := decimalBinary(ordered[index].Value, ordered[index-1].Value, numeric.DecimalContext.Sub)
		if err != nil {
			return TrendDescriptor{}, err
		}
		absolute, err := decimalAbs(difference)
		if err != nil {
			return TrendDescriptor{}, err
		}
		within, err := decimalCompare(absolute, tolerance)
		if err != nil {
			return TrendDescriptor{}, err
		}
		if within <= 0 {
			descriptor.FlatChanges++
			continue
		}
		direction, _ := decimalCompare(difference, numeric.MustDecimal("0"))
		if direction > 0 {
			descriptor.PositiveChanges++
		} else {
			descriptor.NegativeChanges++
		}
	}
	switch {
	case descriptor.PositiveChanges > 0 && descriptor.NegativeChanges == 0:
		descriptor.Direction = TrendIncreasing
	case descriptor.NegativeChanges > 0 && descriptor.PositiveChanges == 0:
		descriptor.Direction = TrendDecreasing
	case descriptor.PositiveChanges == 0 && descriptor.NegativeChanges == 0:
		descriptor.Direction = TrendFlat
	default:
		descriptor.Direction = TrendMixed
	}
	for _, observation := range ordered {
		descriptor.SourceFactIDs = append(descriptor.SourceFactIDs, observation.SourceFactIDs...)
	}
	descriptor.SourceFactIDs = uniqueSorted(descriptor.SourceFactIDs)
	return descriptor, nil
}

func compatible(observations ...Observation) error {
	first := observations[0]
	for _, observation := range observations[1:] {
		if observation.MetricID != first.MetricID || observation.CompanyID != first.CompanyID {
			return errors.New("definition_conflict: metric or company differs")
		}
	}
	return compatibleDimensions(observations...)
}

func compatibleDimensions(observations ...Observation) error {
	first := observations[0]
	for _, observation := range observations[1:] {
		if observation.CompanyID != first.CompanyID {
			return errors.New("definition_conflict: company differs")
		}
		if observation.Unit != first.Unit || observation.Currency != first.Currency || observation.Scale != first.Scale {
			return errors.New("unit_mismatch: unit, currency, or scale differs")
		}
	}
	return nil
}

func samePeriod(left, right Period) bool {
	if left.Kind != right.Kind || !left.End.Equal(right.End) || (left.Start == nil) != (right.Start == nil) {
		return false
	}
	return left.Start == nil || left.Start.Equal(*right.Start)
}

func sameMonthDay(left, right time.Time) bool {
	return left.Month() == right.Month() && left.Day() == right.Day()
}

func latest(values ...time.Time) time.Time {
	result := values[0]
	for _, value := range values[1:] {
		if value.After(result) {
			result = value
		}
	}
	return result
}

func uniqueSorted(values []string) []string {
	set := make(map[string]bool)
	for _, value := range values {
		if value != "" {
			set[value] = true
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func decimalBinary(left, right numeric.Decimal, operation func(*apd.Decimal, *apd.Decimal, *apd.Decimal) (apd.Condition, error)) (numeric.Decimal, error) {
	x, _, err := apd.NewFromString(left.String())
	if err != nil {
		return numeric.Decimal{}, err
	}
	y, _, err := apd.NewFromString(right.String())
	if err != nil {
		return numeric.Decimal{}, err
	}
	var result apd.Decimal
	if _, err := operation(&result, x, y); err != nil {
		return numeric.Decimal{}, err
	}
	return numeric.ParseDecimal(result.String())
}

func decimalAbs(value numeric.Decimal) (numeric.Decimal, error) {
	parsed, _, err := apd.NewFromString(value.String())
	if err != nil {
		return numeric.Decimal{}, err
	}
	var result apd.Decimal
	if _, err := numeric.DecimalContext.Abs(&result, parsed); err != nil {
		return numeric.Decimal{}, err
	}
	return numeric.ParseDecimal(result.String())
}

func decimalCompare(left, right numeric.Decimal) (int, error) {
	x, _, err := apd.NewFromString(left.String())
	if err != nil {
		return 0, err
	}
	y, _, err := apd.NewFromString(right.String())
	if err != nil {
		return 0, err
	}
	return x.Cmp(y), nil
}
