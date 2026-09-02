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

	"github.com/rvbernucci/signalforge/internal/adapters/fred"
	"github.com/rvbernucci/signalforge/internal/macro"
	"github.com/rvbernucci/signalforge/internal/rawstore"
)

type seriesResult struct {
	SeriesID     string              `json:"series_id"`
	RawRecord    rawstore.Record     `json:"raw_record"`
	Observations []macro.Observation `json:"observations"`
}

func main() {
	seriesRaw := flag.String("series", "", "comma-separated FRED series IDs")
	startRaw := flag.String("start", "", "observation start date YYYY-MM-DD")
	endRaw := flag.String("end", "", "observation end date YYYY-MM-DD")
	vintageRaw := flag.String("vintage", "", "FRED realtime vintage date YYYY-MM-DD")
	storePath := flag.String("store", "", "raw-store directory")
	baseURL := flag.String("base-url", fred.DefaultBaseURL, "FRED API base URL")
	flag.Parse()
	series := splitValues(*seriesRaw)
	if len(series) == 0 || *storePath == "" {
		fatal(errors.New("--series and --store are required"))
	}
	start := parseDate("--start", *startRaw)
	end := parseDate("--end", *endRaw)
	vintage := parseDate("--vintage", *vintageRaw)
	client, err := fred.NewClient(*baseURL, os.Getenv("FRED_API_KEY"), nil)
	if err != nil {
		fatal(err)
	}
	store, err := rawstore.New(*storePath)
	if err != nil {
		fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	results := make([]seriesResult, 0, len(series))
	for _, seriesID := range series {
		snapshot, err := client.Snapshot(ctx, seriesID, start, end, vintage)
		if err != nil {
			fatal(err)
		}
		record, err := store.Put(rawstore.Input{
			SourceURI: snapshot.SourceURI, MediaType: "application/json", Content: snapshot.Content,
			ContentSHA: snapshot.ContentSHA, RetrievedAt: snapshot.RetrievedAt,
		})
		if err != nil {
			fatal(err)
		}
		results = append(results, seriesResult{SeriesID: seriesID, RawRecord: record, Observations: snapshot.Observations})
	}
	writeJSON(map[string]any{"schema_version": "signalforge/fred-ingestion-result/v1", "series": results})
}

func splitValues(value string) []string {
	seen := map[string]bool{}
	var result []string
	for _, item := range strings.Split(value, ",") {
		item = strings.TrimSpace(item)
		if item != "" && !seen[item] {
			seen[item] = true
			result = append(result, item)
		}
	}
	return result
}

func parseDate(name, value string) time.Time {
	parsed, err := time.Parse("2006-01-02", value)
	if err != nil {
		fatal(fmt.Errorf("%s must use YYYY-MM-DD", name))
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
