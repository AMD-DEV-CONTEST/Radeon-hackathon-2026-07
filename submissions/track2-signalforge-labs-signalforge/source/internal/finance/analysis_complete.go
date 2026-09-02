package finance

import (
	"errors"
	"math"
	"sort"
	"time"
)

type PeerObservation struct {
	CompanyID    string
	Value        float64
	ObservedAt   time.Time
	Currency     string
	FiscalPeriod string
	DefinitionID string
}

type PeerCohortPolicy struct {
	AsOf             time.Time
	Currency         string
	FiscalPeriod     string
	DefinitionID     string
	MinimumSample    int
	MaximumAgeDays   int
	WinsorizePercent float64
}

type PeerCohort struct {
	Values          []float64
	IncludedIDs     []string
	Excluded        map[string]string
	ObservationDate time.Time
}

func GovernPeerCohort(observations []PeerObservation, policy PeerCohortPolicy) (PeerCohort, error) {
	if policy.AsOf.IsZero() || policy.MinimumSample < 3 || policy.MaximumAgeDays < 0 ||
		policy.WinsorizePercent < 0 || policy.WinsorizePercent >= 0.5 ||
		policy.Currency == "" || policy.FiscalPeriod == "" || policy.DefinitionID == "" {
		return PeerCohort{}, errors.New("peer cohort policy is invalid")
	}
	result := PeerCohort{Excluded: make(map[string]string), ObservationDate: policy.AsOf}
	occurrences := make(map[string]int)
	for _, observation := range observations {
		occurrences[observation.CompanyID]++
	}
	ordered := append([]PeerObservation(nil), observations...)
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].CompanyID == ordered[j].CompanyID {
			return ordered[i].ObservedAt.Before(ordered[j].ObservedAt)
		}
		return ordered[i].CompanyID < ordered[j].CompanyID
	})
	for _, observation := range ordered {
		reason := ""
		switch {
		case observation.CompanyID == "":
			reason = "missing_company"
		case occurrences[observation.CompanyID] > 1:
			reason = "duplicate_or_missing_company"
		case observation.ObservedAt.After(policy.AsOf):
			reason = "future_observation"
		case policy.AsOf.Sub(observation.ObservedAt) > time.Duration(policy.MaximumAgeDays)*24*time.Hour:
			reason = "stale_observation"
		case observation.Currency != policy.Currency:
			reason = "currency_mismatch"
		case observation.FiscalPeriod != policy.FiscalPeriod:
			reason = "period_mismatch"
		case observation.DefinitionID != policy.DefinitionID:
			reason = "definition_mismatch"
		case !finite(observation.Value):
			reason = "non_finite_value"
		}
		if reason != "" {
			result.Excluded[observation.CompanyID] = reason
			continue
		}
		result.Values = append(result.Values, observation.Value)
		result.IncludedIDs = append(result.IncludedIDs, observation.CompanyID)
	}
	if len(result.Values) < policy.MinimumSample {
		return PeerCohort{}, errors.New("compatible peer population is below the declared minimum")
	}
	if policy.WinsorizePercent > 0 {
		order := append([]float64(nil), result.Values...)
		sort.Float64s(order)
		lowIndex := int(float64(len(order)-1) * policy.WinsorizePercent)
		highIndex := int(float64(len(order)-1) * (1 - policy.WinsorizePercent))
		for index, value := range result.Values {
			if value < order[lowIndex] {
				result.Values[index] = order[lowIndex]
			} else if value > order[highIndex] {
				result.Values[index] = order[highIndex]
			}
		}
	}
	return result, nil
}

type HistoricalBandResult struct {
	Current        float64
	Minimum        float64
	FirstQuartile  float64
	Median         float64
	ThirdQuartile  float64
	Maximum        float64
	Percentile     float64
	Observations   int
	Interpretation string
}

func HistoricalBand(history []float64, current float64, minimumSample int) (HistoricalBandResult, error) {
	if len(history) < minimumSample || minimumSample < 5 || !finite(current) {
		return HistoricalBandResult{}, errors.New("historical band sample is below the declared minimum")
	}
	values := append([]float64(nil), history...)
	for _, value := range values {
		if !finite(value) {
			return HistoricalBandResult{}, errors.New("historical band values must be finite")
		}
	}
	sort.Float64s(values)
	lessOrEqual := 0
	for _, value := range values {
		if value <= current {
			lessOrEqual++
		}
	}
	quantile := func(p float64) float64 {
		position := p * float64(len(values)-1)
		left := int(math.Floor(position))
		right := int(math.Ceil(position))
		if left == right {
			return values[left]
		}
		weight := position - float64(left)
		return values[left]*(1-weight) + values[right]*weight
	}
	return HistoricalBandResult{
		Current: current, Minimum: values[0], FirstQuartile: quantile(0.25), Median: quantile(0.5),
		ThirdQuartile: quantile(0.75), Maximum: values[len(values)-1],
		Percentile: float64(lessOrEqual) / float64(len(values)), Observations: len(values),
		Interpretation: "historical_position_only_not_mean_reversion",
	}, nil
}

type AssociationDiagnostics struct {
	Result            AssociationResult
	WindowStart       time.Time
	WindowEnd         time.Time
	MissingPairs      int
	InputPairs        int
	TrainObservations int
	TestObservations  int
	TestRMSE          float64
	StabilityGap      float64
	ConfidenceClass   string
	EvidenceClass     string
}

type TimedPair struct {
	At      time.Time
	Driver  *float64
	Outcome *float64
}

func TrainTestLaggedAssociation(pairs []TimedPair, lag, minimumTrain int, trainCutoff time.Time) (AssociationDiagnostics, error) {
	if trainCutoff.IsZero() || len(pairs) == 0 {
		return AssociationDiagnostics{}, errors.New("pairs and train cutoff are required")
	}
	values := append([]TimedPair(nil), pairs...)
	sort.Slice(values, func(i, j int) bool { return values[i].At.Before(values[j].At) })
	if lag < 0 || lag >= len(values) {
		return AssociationDiagnostics{}, errors.New("lag is outside the available population")
	}
	driver, outcome, times := make([]float64, 0), make([]float64, 0), make([]time.Time, 0)
	missing := 0
	for index, pair := range values {
		if pair.At.IsZero() || (index > 0 && pair.At.Equal(values[index-1].At)) {
			return AssociationDiagnostics{}, errors.New("association timestamps must be present and unique")
		}
		if pair.Driver != nil && !finite(*pair.Driver) {
			return AssociationDiagnostics{}, errors.New("association values must be finite")
		}
		if pair.Outcome != nil && !finite(*pair.Outcome) {
			return AssociationDiagnostics{}, errors.New("association values must be finite")
		}
	}
	for outcomeIndex := lag; outcomeIndex < len(values); outcomeIndex++ {
		driverIndex := outcomeIndex - lag
		if values[driverIndex].Driver == nil || values[outcomeIndex].Outcome == nil {
			missing++
			continue
		}
		driver = append(driver, *values[driverIndex].Driver)
		outcome = append(outcome, *values[outcomeIndex].Outcome)
		times = append(times, values[outcomeIndex].At)
	}
	trainEnd := 0
	for trainEnd < len(times) && !times[trainEnd].After(trainCutoff) {
		trainEnd++
	}
	if trainEnd < minimumTrain || trainEnd >= len(times) {
		return AssociationDiagnostics{}, errors.New("train/test population is insufficient")
	}
	train, err := LaggedAssociation(driver[:trainEnd], outcome[:trainEnd], 0, minimumTrain)
	if err != nil {
		return AssociationDiagnostics{}, err
	}
	train.Lag = lag
	testErrors := make([]float64, 0)
	for index := trainEnd; index < len(driver); index++ {
		predicted := train.Intercept + train.Slope*driver[index]
		delta := predicted - outcome[index]
		testErrors = append(testErrors, delta*delta)
	}
	if len(testErrors) == 0 {
		return AssociationDiagnostics{}, errors.New("test population is empty after lag alignment")
	}
	mse := 0.0
	for _, value := range testErrors {
		mse += value
	}
	rmse := math.Sqrt(mse / float64(len(testErrors)))
	full, err := LaggedAssociation(driver, outcome, 0, minimumTrain)
	if err != nil {
		return AssociationDiagnostics{}, err
	}
	full.Lag = lag
	stability := math.Abs(train.Correlation - full.Correlation)
	confidence := "exploratory"
	if len(testErrors) >= 10 && stability <= 0.10 {
		confidence = "stable_association"
	}
	return AssociationDiagnostics{
		Result: train, WindowStart: times[0], WindowEnd: times[len(times)-1], MissingPairs: missing,
		InputPairs: len(pairs), TrainObservations: train.Observations, TestObservations: len(testErrors),
		TestRMSE: rmse, StabilityGap: stability, ConfidenceClass: confidence,
		EvidenceClass: "statistical_association_not_mechanism_or_causality",
	}, nil
}
