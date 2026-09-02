package financialperiod

import (
	"errors"
	"fmt"
	"sort"
	"time"
)

type FactIssueCode string

const (
	IssueMissingComponent    FactIssueCode = "missing_component"
	IssueDuplicateFact       FactIssueCode = "duplicate_fact"
	IssueConflictingConcept  FactIssueCode = "conflicting_concept"
	IssueRestatedObservation FactIssueCode = "restated_observation"
)

type FactIssue struct {
	Code          FactIssueCode
	MetricID      string
	CompanyID     string
	PeriodLabel   string
	SourceFactIDs []string
	Detail        string
}

type FactAudit struct {
	Issues       []FactIssue
	Observations int
	Complete     bool
}

// AuditFacts detects objective statement-population defects without selecting
// or repairing an accounting concept on the caller's behalf.
func AuditFacts(observations []Observation, requiredMetrics []string, cutoff time.Time) (FactAudit, error) {
	if cutoff.IsZero() {
		return FactAudit{}, errors.New("cutoff is required")
	}
	audit := FactAudit{Observations: len(observations), Complete: true}
	seenMetrics := make(map[string]bool)
	type factKey struct {
		company string
		metric  string
		period  string
		class   ObservationClass
	}
	grouped := make(map[factKey][]Observation)
	for _, observation := range observations {
		if err := ValidateObservation(observation, cutoff); err != nil {
			return FactAudit{}, err
		}
		seenMetrics[observation.MetricID] = true
		key := factKey{
			company: observation.CompanyID,
			metric:  observation.MetricID,
			period:  observation.Period.Label,
			class:   observation.Class,
		}
		grouped[key] = append(grouped[key], observation)
		if len(observation.AmendmentChain) > 0 {
			audit.Issues = append(audit.Issues, FactIssue{
				Code: IssueRestatedObservation, MetricID: observation.MetricID,
				CompanyID: observation.CompanyID, PeriodLabel: observation.Period.Label,
				SourceFactIDs: append([]string(nil), observation.SourceFactIDs...),
				Detail:        "observation belongs to a disclosed amendment chain",
			})
		}
	}
	for _, metricID := range requiredMetrics {
		if !seenMetrics[metricID] {
			audit.Issues = append(audit.Issues, FactIssue{
				Code: IssueMissingComponent, MetricID: metricID,
				Detail: "required metric is absent from the point-in-time population",
			})
		}
	}
	for key, values := range grouped {
		if len(values) < 2 {
			continue
		}
		code := IssueDuplicateFact
		detail := "multiple observations share the same company, metric, class, and period"
		first := values[0].Value.String()
		for _, value := range values[1:] {
			if value.Value.String() != first {
				code = IssueConflictingConcept
				detail = "same governed concept and period contain conflicting values"
				break
			}
		}
		sources := make([]string, 0)
		for _, value := range values {
			sources = append(sources, value.SourceFactIDs...)
		}
		audit.Issues = append(audit.Issues, FactIssue{
			Code: code, MetricID: key.metric, CompanyID: key.company,
			PeriodLabel: key.period, SourceFactIDs: uniqueSorted(sources), Detail: detail,
		})
	}
	sort.Slice(audit.Issues, func(i, j int) bool {
		left, right := audit.Issues[i], audit.Issues[j]
		return fmt.Sprintf("%s:%s:%s:%s", left.Code, left.CompanyID, left.MetricID, left.PeriodLabel) <
			fmt.Sprintf("%s:%s:%s:%s", right.Code, right.CompanyID, right.MetricID, right.PeriodLabel)
	})
	audit.Complete = len(audit.Issues) == 0
	return audit, nil
}

type HistoricalWindow struct {
	MetricID     string
	CompanyID    string
	Years        int
	Observations []Observation
	Start        time.Time
	End          time.Time
}

// AnnualWindow releases only complete, contiguous 3-, 5-, or 10-year annual
// populations available at the requested cutoff.
func AnnualWindow(observations []Observation, years int, cutoff time.Time) (HistoricalWindow, error) {
	if years != 3 && years != 5 && years != 10 {
		return HistoricalWindow{}, errors.New("historical window must be 3, 5, or 10 years")
	}
	if len(observations) < years {
		return HistoricalWindow{}, errors.New("point-in-time population does not support requested window")
	}
	values := append([]Observation(nil), observations...)
	sort.Slice(values, func(i, j int) bool { return values[i].Period.End.Before(values[j].Period.End) })
	values = values[len(values)-years:]
	metricID, companyID := values[0].MetricID, values[0].CompanyID
	seenYears := make(map[int]bool, years)
	for index, observation := range values {
		if err := ValidateObservation(observation, cutoff); err != nil {
			return HistoricalWindow{}, err
		}
		if observation.Period.Kind != KindAnnual || observation.MetricID != metricID || observation.CompanyID != companyID {
			return HistoricalWindow{}, errors.New("historical window requires one aligned annual metric and company")
		}
		year := observation.Period.FiscalYear
		if year == 0 {
			year = observation.Period.End.Year()
		}
		if seenYears[year] {
			return HistoricalWindow{}, errors.New("historical window contains a duplicate fiscal year")
		}
		seenYears[year] = true
		if index > 0 {
			priorYear := values[index-1].Period.FiscalYear
			if priorYear == 0 {
				priorYear = values[index-1].Period.End.Year()
			}
			if year != priorYear+1 {
				return HistoricalWindow{}, errors.New("historical window is not contiguous")
			}
		}
	}
	return HistoricalWindow{
		MetricID: metricID, CompanyID: companyID, Years: years,
		Observations: values, Start: values[0].Period.End, End: values[len(values)-1].Period.End,
	}, nil
}
