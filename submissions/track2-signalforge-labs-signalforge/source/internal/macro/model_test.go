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

func TestSelectVintageAsOfUsesLatestAvailableRevisionWithoutLookAhead(t *testing.T) {
	observationDate := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	firstRelease := observationDate.Add(24 * time.Hour)
	revisionRelease := firstRelease.Add(30 * 24 * time.Hour)
	values := []Observation{
		{SeriesID: "DFF", ObservationDate: observationDate, Value: "4.50", Unit: "Percent", RealtimeStart: firstRelease, RealtimeEnd: revisionRelease.Add(-time.Nanosecond), AvailableAt: firstRelease, RetrievedAt: firstRelease.Add(time.Hour), SourceURI: "fixture://fred", SourceSHA256: "first"},
		{SeriesID: "DFF", ObservationDate: observationDate, Value: "4.45", Unit: "Percent", RealtimeStart: revisionRelease, RealtimeEnd: time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC), AvailableAt: revisionRelease, RetrievedAt: revisionRelease.Add(time.Hour), SourceURI: "fixture://fred", SourceSHA256: "revision"},
	}
	selected, ok, err := SelectVintageAsOf(values, "DFF", observationDate, firstRelease.Add(time.Hour))
	if err != nil || !ok || selected.Value != "4.50" {
		t.Fatalf("initial vintage selection failed: selected=%+v ok=%v err=%v", selected, ok, err)
	}
	selected, ok, err = SelectVintageAsOf(values, "DFF", observationDate, revisionRelease)
	if err != nil || !ok || selected.Value != "4.45" {
		t.Fatalf("revision selection failed: selected=%+v ok=%v err=%v", selected, ok, err)
	}
}

func TestSelectVintageAsOfPreservesMissingObservationWithoutForwardFill(t *testing.T) {
	date := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	value := Observation{SeriesID: "DFF", ObservationDate: date, Value: "4.50", Unit: "Percent", RealtimeStart: date.Add(time.Hour), RealtimeEnd: time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC), AvailableAt: date.Add(time.Hour), RetrievedAt: date.Add(2 * time.Hour), SourceURI: "fixture://fred", SourceSHA256: "first"}
	if selected, ok, err := SelectVintageAsOf([]Observation{value}, "DFF", date.AddDate(0, 0, 1), date.AddDate(0, 0, 2)); err != nil || ok || selected.SeriesID != "" {
		t.Fatalf("missing observation was forward-filled: selected=%+v ok=%v err=%v", selected, ok, err)
	}
}

func TestValidateSeriesRejectsDuplicateVintageAndUnitDrift(t *testing.T) {
	date := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	value := Observation{SeriesID: "DFF", ObservationDate: date, Value: "4.50", Unit: "Percent", RealtimeStart: date.Add(time.Hour), RealtimeEnd: time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC), AvailableAt: date.Add(time.Hour), RetrievedAt: date.Add(2 * time.Hour), SourceURI: "fixture://fred", SourceSHA256: "first"}
	if err := ValidateSeries([]Observation{value, value}); err == nil {
		t.Fatal("duplicate vintage was accepted")
	}
	drift := value
	drift.ObservationDate = date.AddDate(0, 0, 1)
	drift.Unit = "BasisPoints"
	if err := ValidateSeries([]Observation{value, drift}); err == nil {
		t.Fatal("series unit drift was accepted")
	}
}
