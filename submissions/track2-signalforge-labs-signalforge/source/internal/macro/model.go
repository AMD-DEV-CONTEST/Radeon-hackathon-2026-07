package macro

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
)

type Observation struct {
	SeriesID        string    `json:"series_id"`
	ObservationDate time.Time `json:"observation_date"`
	Value           string    `json:"value"`
	Unit            string    `json:"unit"`
	RealtimeStart   time.Time `json:"realtime_start"`
	RealtimeEnd     time.Time `json:"realtime_end"`
	AvailableAt     time.Time `json:"available_at"`
	RetrievedAt     time.Time `json:"retrieved_at"`
	SourceURI       string    `json:"source_uri"`
	SourceSHA256    string    `json:"source_sha256"`
}

func ValidateObservation(value Observation) error {
	if value.SeriesID == "" || value.Unit == "" || value.SourceURI == "" || value.SourceSHA256 == "" {
		return errors.New("series, unit, source URI, and source hash are required")
	}
	if value.ObservationDate.IsZero() || value.RealtimeStart.IsZero() || value.RealtimeEnd.IsZero() || value.AvailableAt.IsZero() || value.RetrievedAt.IsZero() {
		return errors.New("all macro temporal fields are required")
	}
	if value.RealtimeEnd.Before(value.RealtimeStart) || value.RetrievedAt.Before(value.AvailableAt) {
		return errors.New("macro temporal ordering is invalid")
	}
	if value.AvailableAt.Before(value.ObservationDate) || value.AvailableAt.Before(value.RealtimeStart) {
		return errors.New("macro observation cannot be available before observation or vintage start")
	}
	if _, _, err := apd.NewFromString(strings.TrimSpace(value.Value)); err != nil {
		return errors.New("macro value must be decimal")
	}
	return nil
}

func AvailableAsOf(value Observation, asOf time.Time) bool {
	return !asOf.IsZero() && !value.AvailableAt.IsZero() && !value.AvailableAt.After(asOf)
}

func ValidateSeries(values []Observation) error {
	identities := make(map[string]bool, len(values))
	units := make(map[string]string)
	for index, value := range values {
		if err := ValidateObservation(value); err != nil {
			return fmt.Errorf("observations[%d]: %w", index, err)
		}
		identity := strings.Join([]string{
			value.SeriesID, value.ObservationDate.Format(time.RFC3339Nano), value.RealtimeStart.Format(time.RFC3339Nano),
		}, "|")
		if identities[identity] {
			return fmt.Errorf("observations[%d] duplicates a vintage identity", index)
		}
		identities[identity] = true
		if unit, exists := units[value.SeriesID]; exists && unit != value.Unit {
			return fmt.Errorf("observations[%d] changes unit from %q to %q", index, unit, value.Unit)
		}
		units[value.SeriesID] = value.Unit
	}
	return nil
}

func SelectVintageAsOf(values []Observation, seriesID string, observationDate, asOf time.Time) (Observation, bool, error) {
	if strings.TrimSpace(seriesID) == "" || observationDate.IsZero() || asOf.IsZero() {
		return Observation{}, false, errors.New("series_id, observation_date, and as_of are required")
	}
	if err := ValidateSeries(values); err != nil {
		return Observation{}, false, err
	}
	candidates := make([]Observation, 0)
	for _, value := range values {
		if value.SeriesID == seriesID && value.ObservationDate.Equal(observationDate) &&
			AvailableAsOf(value, asOf) && !asOf.Before(value.RealtimeStart) && !asOf.After(value.RealtimeEnd) {
			candidates = append(candidates, value)
		}
	}
	if len(candidates) == 0 {
		return Observation{}, false, nil
	}
	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].RealtimeStart.After(candidates[j].RealtimeStart)
	})
	return candidates[0], true, nil
}
