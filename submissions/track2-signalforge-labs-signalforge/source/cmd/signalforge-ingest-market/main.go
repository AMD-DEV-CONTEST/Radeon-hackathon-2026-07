package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/adapters/alpaca"
	"github.com/rvbernucci/signalforge/internal/market"
	"github.com/rvbernucci/signalforge/internal/rawstore"
)

type symbolResult struct {
	Symbol     string            `json:"symbol"`
	RawRecords []rawstore.Record `json:"raw_records"`
	Bars       []market.Bar      `json:"bars"`
}

func main() {
	symbolsRaw := flag.String("symbols", "", "comma-separated US ticker symbols")
	startRaw := flag.String("start", "", "inclusive start timestamp RFC3339")
	endRaw := flag.String("end", "", "exclusive end timestamp RFC3339")
	storePath := flag.String("store", "", "raw-store directory")
	baseURL := flag.String("base-url", alpaca.DefaultBaseURL, "Alpaca market-data base URL")
	flag.Parse()
	symbols := splitValues(*symbolsRaw)
	if len(symbols) == 0 || *storePath == "" {
		fatal(errors.New("--symbols and --store are required"))
	}
	start := parseTime("--start", *startRaw)
	end := parseTime("--end", *endRaw)
	client, err := alpaca.NewClient(*baseURL, os.Getenv("ALPACA_API_KEY_ID"), os.Getenv("ALPACA_API_SECRET_KEY"), nil)
	if err != nil {
		fatal(err)
	}
	store, err := rawstore.New(*storePath)
	if err != nil {
		fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	results := make([]symbolResult, 0, len(symbols))
	for _, symbol := range symbols {
		bars, snapshots, err := client.BarsWithSnapshots(ctx, market.Query{Symbol: symbol, Start: start, End: end, Timeframe: "1Day"})
		if err != nil {
			fatal(err)
		}
		result := symbolResult{Symbol: symbol, Bars: bars}
		for _, snapshot := range snapshots {
			record, err := store.Put(rawstore.Input{
				SourceURI: snapshot.SourceURI, MediaType: "application/json", Content: snapshot.Content,
				ContentSHA: snapshot.ContentSHA, RetrievedAt: snapshot.RetrievedAt,
			})
			if err != nil {
				fatal(err)
			}
			result.RawRecords = append(result.RawRecords, record)
		}
		results = append(results, result)
	}
	writeJSON(map[string]any{"schema_version": "signalforge/market-ingestion-result/v1", "symbols": results})
}

func splitValues(value string) []string {
	seen := map[string]bool{}
	var result []string
	for _, item := range strings.Split(value, ",") {
		item = strings.ToUpper(strings.TrimSpace(item))
		if item != "" && !seen[item] {
			seen[item] = true
			result = append(result, item)
		}
	}
	return result
}

func parseTime(name, value string) time.Time {
	parsed, err := time.Parse(time.RFC3339, value)
	if err != nil {
		fatal(fmt.Errorf("%s must use RFC3339", name))
	}
	return parsed.UTC()
}

func writeJSON(value any) {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		fatal(err)
	}
	fmt.Println(string(encoded))
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
