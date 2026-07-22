package macro

import (
	"testing"
	"time"
)

func TestObservationRequiresVintageAndDecimal(t *testing.T) {
	date := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	value := Observation{
		SeriesID: "DFF", ObservationDate: date, Value: "4.33", Unit: "Percent",
		RealtimeStart: date.AddDate(0, 0, 1), RealtimeEnd: date.AddDate(0, 0, 1),
		AvailableAt: date.AddDate(0, 0, 1), RetrievedAt: date.AddDate(0, 0, 2),
		SourceURI: "https://api.stlouisfed.org", SourceSHA256: "hash",
	}
	if err := ValidateObservation(value); err != nil {
		t.Fatal(err)
	}
	value.Value = "."
	if err := ValidateObservation(value); err == nil {
		t.Fatal("missing-value marker must fail")
	}
}
