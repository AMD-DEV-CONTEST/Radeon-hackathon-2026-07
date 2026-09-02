package lineage

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/macro"
	"github.com/rvbernucci/signalforge/internal/market"
)

type PointInTimeSet struct {
	AsOf          time.Time           `json:"as_of"`
	Filings       []data.Filing       `json:"filings,omitempty"`
	ReportedFacts []data.ReportedFact `json:"reported_facts,omitempty"`
	Macro         []macro.Observation `json:"macro_observations,omitempty"`
	MarketBars    []market.Bar        `json:"market_bars,omitempty"`
}

type Receipt struct {
	AsOf              time.Time `json:"as_of"`
	FilingCount       int       `json:"filing_count"`
	ReportedFactCount int       `json:"reported_fact_count"`
	MacroCount        int       `json:"macro_count"`
	MarketBarCount    int       `json:"market_bar_count"`
	Passed            bool      `json:"passed"`
}

func ValidatePointInTime(set PointInTimeSet) (Receipt, error) {
	receipt := Receipt{
		AsOf: set.AsOf, FilingCount: len(set.Filings), ReportedFactCount: len(set.ReportedFacts),
		MacroCount: len(set.Macro), MarketBarCount: len(set.MarketBars),
	}
	if set.AsOf.IsZero() {
		return receipt, errors.New("point-in-time set requires as_of")
	}
	if err := data.ValidateFilingSet(set.Filings); err != nil {
		return receipt, fmt.Errorf("filing set: %w", err)
	}
	if err := data.ValidateReportedFactSet(set.ReportedFacts); err != nil {
		return receipt, fmt.Errorf("reported fact set: %w", err)
	}
	if err := macro.ValidateSeries(set.Macro); err != nil {
		return receipt, fmt.Errorf("macro series: %w", err)
	}
	filings := make(map[string]data.Filing, len(set.Filings))
	accessions := make(map[string]bool, len(set.Filings))
	for i, filing := range set.Filings {
		if err := data.ValidateFiling(filing); err != nil {
			return receipt, fmt.Errorf("filings[%d]: %w", i, err)
		}
		if filing.PublishedAt.After(set.AsOf) {
			return receipt, fmt.Errorf("filings[%d] was unavailable at as_of", i)
		}
		if _, duplicate := filings[filing.FilingID]; duplicate || accessions[filing.AccessionNumber] {
			return receipt, fmt.Errorf("filings[%d] duplicates filing or accession identity", i)
		}
		filings[filing.FilingID] = filing
		accessions[filing.AccessionNumber] = true
	}
	for i, fact := range set.ReportedFacts {
		if err := data.ValidateReportedFact(fact); err != nil {
			return receipt, fmt.Errorf("reported_facts[%d]: %w", i, err)
		}
		filing, ok := filings[fact.FilingID]
		if !ok || filing.CompanyID != fact.CompanyID {
			return receipt, fmt.Errorf("reported_facts[%d] has no same-company filing lineage", i)
		}
		if fact.AvailableAt.After(set.AsOf) {
			return receipt, fmt.Errorf("reported_facts[%d] was unavailable at as_of", i)
		}
	}
	macroKeys := map[string]bool{}
	for i, observation := range set.Macro {
		if err := macro.ValidateObservation(observation); err != nil {
			return receipt, fmt.Errorf("macro_observations[%d]: %w", i, err)
		}
		if !macro.AvailableAsOf(observation, set.AsOf) {
			return receipt, fmt.Errorf("macro_observations[%d] was unavailable at as_of", i)
		}
		key := strings.Join([]string{observation.SeriesID, observation.ObservationDate.Format(time.RFC3339Nano), observation.RealtimeStart.Format(time.RFC3339Nano)}, "|")
		if macroKeys[key] {
			return receipt, fmt.Errorf("macro_observations[%d] duplicates a vintage identity", i)
		}
		macroKeys[key] = true
	}
	barKeys := map[string]bool{}
	for i, bar := range set.MarketBars {
		if err := market.ValidateBar(bar); err != nil {
			return receipt, fmt.Errorf("market_bars[%d]: %w", i, err)
		}
		if !market.AvailableAsOf(bar, set.AsOf) {
			return receipt, fmt.Errorf("market_bars[%d] was unavailable at as_of", i)
		}
		key := strings.Join([]string{bar.Provider, bar.Symbol, bar.Timestamp.Format(time.RFC3339Nano), bar.Adjustment}, "|")
		if barKeys[key] {
			return receipt, fmt.Errorf("market_bars[%d] duplicates a provider observation", i)
		}
		barKeys[key] = true
	}
	receipt.Passed = true
	return receipt, nil
}
