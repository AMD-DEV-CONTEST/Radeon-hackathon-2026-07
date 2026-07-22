package macro

import (
	"errors"
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
	if _, _, err := apd.NewFromString(strings.TrimSpace(value.Value)); err != nil {
		return errors.New("macro value must be decimal")
	}
	return nil
}
