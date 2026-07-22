package market

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"time"

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
