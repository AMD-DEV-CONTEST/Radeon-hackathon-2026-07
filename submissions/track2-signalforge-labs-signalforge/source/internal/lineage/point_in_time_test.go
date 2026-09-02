package lineage

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/macro"
	"github.com/rvbernucci/signalforge/internal/market"
)

func fixtureSet() PointInTimeSet {
	asOf := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	periodStart := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	periodEnd := time.Date(2026, 3, 31, 0, 0, 0, 0, time.UTC)
	filingAvailable := time.Date(2026, 4, 25, 20, 0, 0, 0, time.UTC)
	marketObserved := time.Date(2026, 7, 20, 20, 0, 0, 0, time.UTC)
	return PointInTimeSet{
		AsOf: asOf,
		Filings: []data.Filing{{
			FilingID: "filing-1", CompanyID: "sec-cik:0000789019", AccessionNumber: "0000789019-26-000001",
			FormType: "10-Q", ReportPeriodEnd: periodEnd, FiledAt: filingAvailable, AcceptedAt: filingAvailable,
			PublishedAt: filingAvailable, SourceRecordID: "record-1", SourceURI: "https://www.sec.gov/Archives/example",
			ContentSHA256: "fixture", RetrievedAt: filingAvailable.Add(time.Hour), ExtractorVersion: "sec/v1",
		}},
		ReportedFacts: []data.ReportedFact{{
			FactID: "fact-1", FilingID: "filing-1", CompanyID: "sec-cik:0000789019", Taxonomy: "us-gaap",
			Concept: "Revenue", Value: "100", Unit: "USD", StartDate: &periodStart, EndDate: &periodEnd,
			FormType: "10-Q", SourceContextID: "context-1", SourceLocator: "xbrl:context-1",
			AvailableAt: filingAvailable, RetrievedAt: filingAvailable.Add(time.Hour),
		}},
		Macro: []macro.Observation{{
			SeriesID: "DFF", ObservationDate: marketObserved, Value: "5.25", Unit: "Percent",
			RealtimeStart: marketObserved.Add(time.Hour), RealtimeEnd: marketObserved.Add(time.Hour),
			AvailableAt: marketObserved.Add(time.Hour), RetrievedAt: marketObserved.Add(2 * time.Hour),
			SourceURI: "https://api.stlouisfed.org", SourceSHA256: "fixture",
		}},
		MarketBars: []market.Bar{{
			Provider: "alpaca", Symbol: "MSFT", Timestamp: marketObserved, Open: "500", High: "505", Low: "495",
			Close: "502", Volume: "1000", Currency: "USD", Venue: "iex", Entitlement: "iex", Adjustment: "all",
			AvailableAt: marketObserved.Add(time.Minute), RetrievedAt: marketObserved.Add(2 * time.Minute),
			SourceURI: "https://data.alpaca.markets", SourceSHA256: "fixture",
		}},
	}
}

func TestPointInTimeSetAcceptsCompleteLineage(t *testing.T) {
	receipt, err := ValidatePointInTime(fixtureSet())
	if err != nil || !receipt.Passed || receipt.ReportedFactCount != 1 {
		t.Fatalf("receipt=%+v err=%v", receipt, err)
	}
}

func TestPointInTimeSetRejectsFutureSourceAndCrossCompanyFact(t *testing.T) {
	set := fixtureSet()
	set.Macro[0].AvailableAt = set.AsOf.Add(time.Second)
	set.Macro[0].RetrievedAt = set.AsOf.Add(time.Minute)
	if _, err := ValidatePointInTime(set); err == nil {
		t.Fatal("future macro vintage leaked into as-of set")
	}
	set = fixtureSet()
	set.ReportedFacts[0].CompanyID = "sec-cik:0001045810"
	if _, err := ValidatePointInTime(set); err == nil {
		t.Fatal("cross-company filing lineage was accepted")
	}
}

func TestPointInTimeSetRejectsDuplicateMarketObservation(t *testing.T) {
	set := fixtureSet()
	set.MarketBars = append(set.MarketBars, set.MarketBars[0])
	if _, err := ValidatePointInTime(set); err == nil {
		t.Fatal("duplicate market observation was accepted")
	}
}

func TestPointInTimeSetRejectsDuplicateReportedFactIdentity(t *testing.T) {
	set := fixtureSet()
	duplicate := set.ReportedFacts[0]
	duplicate.FactID = "fact-duplicate"
	set.ReportedFacts = append(set.ReportedFacts, duplicate)
	if _, err := ValidatePointInTime(set); err == nil {
		t.Fatal("duplicate reported-fact identity was accepted")
	}
}

func TestPointInTimeSetAcceptsValidMacroRevisionIdentity(t *testing.T) {
	set := fixtureSet()
	first := set.Macro[0]
	first.RealtimeEnd = first.RealtimeStart.Add(24*time.Hour - time.Nanosecond)
	revision := first
	revision.Value = "5.20"
	revision.RealtimeStart = first.RealtimeEnd.Add(time.Nanosecond)
	revision.RealtimeEnd = time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC)
	revision.AvailableAt = revision.RealtimeStart
	revision.RetrievedAt = revision.AvailableAt.Add(time.Hour)
	set.Macro = []macro.Observation{first, revision}
	set.AsOf = revision.AvailableAt.Add(time.Hour)
	receipt, err := ValidatePointInTime(set)
	if err != nil || !receipt.Passed || receipt.MacroCount != 2 {
		t.Fatalf("valid macro revision lineage failed: receipt=%+v err=%v", receipt, err)
	}
}

func FuzzPointInTimeSetNeverAcceptsFutureMarketAvailability(f *testing.F) {
	f.Add(int64(1))
	f.Add(int64(3600))
	f.Fuzz(func(t *testing.T, seconds int64) {
		if seconds <= 0 || seconds > 86400*365 {
			t.Skip()
		}
		set := fixtureSet()
		set.MarketBars[0].AvailableAt = set.AsOf.Add(time.Duration(seconds) * time.Second)
		set.MarketBars[0].RetrievedAt = set.MarketBars[0].AvailableAt.Add(time.Second)
		if _, err := ValidatePointInTime(set); err == nil {
			t.Fatal("future market data was accepted")
		}
	})
}
