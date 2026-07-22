package market

import (
	"context"
	"testing"
	"time"
)

func TestFixtureProviderIsAProviderNeutralOfflineFallback(t *testing.T) {
	start := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	bar := Bar{
		Provider: "fixture", Symbol: "MSFT", Timestamp: start, Open: "420", High: "425", Low: "419", Close: "424", Volume: "1000",
		Currency: "USD", Venue: "fixture", Entitlement: "offline", Adjustment: "none", AvailableAt: start.Add(time.Hour),
		RetrievedAt: start.Add(2 * time.Hour), SourceURI: "fixture://msft", SourceSHA256: "hash",
	}
	provider := FixtureProvider{Values: map[string][]Bar{"MSFT": {bar}}}
	values, err := provider.Bars(context.Background(), Query{Symbol: "MSFT", Start: start, End: start.AddDate(0, 0, 1), Timeframe: "1Day"})
	if err != nil || len(values) != 1 {
		t.Fatalf("values=%#v err=%v", values, err)
	}
	if err := ValidateBar(values[0]); err != nil {
		t.Fatal(err)
	}
}

func TestMarketBarRejectsStaleOrImpossibleAuthority(t *testing.T) {
	observed := time.Date(2025, 1, 2, 21, 0, 0, 0, time.UTC)
	bar := Bar{
		Provider: "fixture", Symbol: "MSFT", Timestamp: observed, Open: "420", High: "425", Low: "419", Close: "424", Volume: "1000",
		Currency: "USD", Venue: "fixture", Entitlement: "offline", Adjustment: "none", AvailableAt: observed.Add(time.Minute),
		RetrievedAt: observed.Add(2 * time.Minute), SourceURI: "fixture://msft", SourceSHA256: "hash",
	}
	if AvailableAsOf(bar, observed) {
		t.Fatal("bar became available before its declared availability time")
	}
	if !AvailableAsOf(bar, bar.AvailableAt) {
		t.Fatal("bar should become available at its declared boundary")
	}

	impossible := bar
	impossible.High = "418"
	if err := ValidateBar(impossible); err == nil {
		t.Fatal("high below open, low, or close must be rejected")
	}
	malformedTime := bar
	malformedTime.AvailableAt = observed.Add(-time.Second)
	if err := ValidateBar(malformedTime); err == nil {
		t.Fatal("market data cannot be available before its observation timestamp")
	}
	malformedSymbol := bar
	malformedSymbol.Symbol = "msft"
	if err := ValidateBar(malformedSymbol); err == nil {
		t.Fatal("non-canonical market symbol must be rejected")
	}
}
