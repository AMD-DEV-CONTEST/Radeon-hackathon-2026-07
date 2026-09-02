package market

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	_ "time/tzdata"

	"github.com/cockroachdb/apd/v3"
)

var symbolPattern = regexp.MustCompile(`^[A-Z0-9][A-Z0-9.-]{0,15}$`)

type Query struct {
	Symbol    string
	Start     time.Time
	End       time.Time
	Timeframe string
}

type Bar struct {
	Provider     string    `json:"provider"`
	Symbol       string    `json:"symbol"`
	Timestamp    time.Time `json:"timestamp"`
	Open         string    `json:"open"`
	High         string    `json:"high"`
	Low          string    `json:"low"`
	Close        string    `json:"close"`
	Volume       string    `json:"volume"`
	TradeCount   int64     `json:"trade_count,omitempty"`
	VWAP         string    `json:"vwap,omitempty"`
	Currency     string    `json:"currency"`
	Venue        string    `json:"venue"`
	Entitlement  string    `json:"entitlement"`
	Adjustment   string    `json:"adjustment"`
	AvailableAt  time.Time `json:"available_at"`
	RetrievedAt  time.Time `json:"retrieved_at"`
	SourceURI    string    `json:"source_uri"`
	SourceSHA256 string    `json:"source_sha256"`
}

type Provider interface {
	Bars(context.Context, Query) ([]Bar, error)
}

type SeriesPolicy struct {
	CanonicalSymbol  string
	Aliases          map[string]string
	Adjustment       string
	TimeZone         string
	AsOf             time.Time
	MaxAge           time.Duration
	ExpectedSessions []time.Time
}

type SeriesReceipt struct {
	CanonicalSymbol  string   `json:"canonical_symbol"`
	Adjustment       string   `json:"adjustment"`
	TimeZone         string   `json:"time_zone"`
	ObservedSessions []string `json:"observed_sessions"`
	BarCount         int      `json:"bar_count"`
	Passed           bool     `json:"passed"`
}

func ValidateQuery(query Query) error {
	if !symbolPattern.MatchString(strings.TrimSpace(query.Symbol)) || query.Start.IsZero() || query.End.IsZero() || !query.End.After(query.Start) {
		return errors.New("symbol and increasing start/end are required")
	}
	if query.Timeframe != "1Day" {
		return errors.New("only 1Day is supported in the initial contract")
	}
	return nil
}

func ValidateBar(bar Bar) error {
	if bar.Provider == "" || !symbolPattern.MatchString(bar.Symbol) || bar.Currency == "" || bar.Venue == "" ||
		bar.Entitlement == "" || bar.Adjustment == "" || bar.SourceURI == "" || bar.SourceSHA256 == "" {
		return errors.New("market identity, entitlement, and source lineage are required")
	}
	if bar.Timestamp.IsZero() || bar.AvailableAt.IsZero() || bar.RetrievedAt.IsZero() ||
		bar.AvailableAt.Before(bar.Timestamp) || bar.RetrievedAt.Before(bar.AvailableAt) {
		return errors.New("market temporal fields are invalid")
	}
	values := make([]*apd.Decimal, 0, 5)
	for _, value := range []string{bar.Open, bar.High, bar.Low, bar.Close, bar.Volume} {
		parsed, _, err := apd.NewFromString(value)
		if err != nil {
			return errors.New("OHLCV values must be decimal")
		}
		values = append(values, parsed)
	}
	open, high, low, close, volume := values[0], values[1], values[2], values[3], values[4]
	zero := apd.New(0, 0)
	if high.Cmp(open) < 0 || high.Cmp(low) < 0 || high.Cmp(close) < 0 ||
		low.Cmp(open) > 0 || low.Cmp(close) > 0 || volume.Cmp(zero) < 0 || bar.TradeCount < 0 {
		return errors.New("market OHLCV invariants are invalid")
	}
	return nil
}

func AvailableAsOf(bar Bar, asOf time.Time) bool {
	return !asOf.IsZero() && !bar.AvailableAt.IsZero() && !bar.AvailableAt.After(asOf)
}

func ValidateSeries(bars []Bar, policy SeriesPolicy) (SeriesReceipt, error) {
	receipt := SeriesReceipt{CanonicalSymbol: policy.CanonicalSymbol, Adjustment: policy.Adjustment, TimeZone: policy.TimeZone, BarCount: len(bars)}
	if !symbolPattern.MatchString(policy.CanonicalSymbol) || policy.Adjustment == "" || policy.TimeZone == "" || policy.AsOf.IsZero() {
		return receipt, errors.New("canonical symbol, adjustment, time zone, and as_of are required")
	}
	location, err := time.LoadLocation(policy.TimeZone)
	if err != nil {
		return receipt, fmt.Errorf("invalid market time zone: %w", err)
	}
	seen := map[string]bool{}
	sessions := map[string]bool{}
	latest := time.Time{}
	for index, bar := range bars {
		if err := ValidateBar(bar); err != nil {
			return receipt, fmt.Errorf("bars[%d]: %w", index, err)
		}
		canonical := bar.Symbol
		if alias, exists := policy.Aliases[bar.Symbol]; exists {
			canonical = alias
		}
		if canonical != policy.CanonicalSymbol {
			return receipt, fmt.Errorf("bars[%d] has unauthorized symbol lineage %q", index, bar.Symbol)
		}
		if bar.Adjustment != policy.Adjustment {
			return receipt, fmt.Errorf("bars[%d] mixes adjustment policy %q with %q", index, bar.Adjustment, policy.Adjustment)
		}
		if !AvailableAsOf(bar, policy.AsOf) {
			return receipt, fmt.Errorf("bars[%d] was unavailable at as_of", index)
		}
		key := strings.Join([]string{bar.Provider, canonical, bar.Timestamp.Format(time.RFC3339Nano), bar.Adjustment}, "|")
		if seen[key] {
			return receipt, fmt.Errorf("bars[%d] duplicates a canonical market observation", index)
		}
		seen[key] = true
		session := bar.Timestamp.In(location).Format("2006-01-02")
		sessions[session] = true
		if bar.AvailableAt.After(latest) {
			latest = bar.AvailableAt
		}
	}
	for _, expected := range policy.ExpectedSessions {
		session := expected.In(location).Format("2006-01-02")
		if !sessions[session] {
			return receipt, fmt.Errorf("missing expected market session %s", session)
		}
	}
	if policy.MaxAge > 0 && (latest.IsZero() || policy.AsOf.Sub(latest) > policy.MaxAge) {
		return receipt, fmt.Errorf("latest market observation exceeds the %s freshness budget", policy.MaxAge)
	}
	for session := range sessions {
		receipt.ObservedSessions = append(receipt.ObservedSessions, session)
	}
	sort.Strings(receipt.ObservedSessions)
	receipt.Passed = true
	return receipt, nil
}
