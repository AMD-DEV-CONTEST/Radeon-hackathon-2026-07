package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/rawstore"
)

func TestTransformBuildsPointInTimeDatasetFromRawRecords(t *testing.T) {
	root := t.TempDir()
	store, err := rawstore.New(root)
	if err != nil {
		t.Fatal(err)
	}
	retrieved := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	records := []ingestionRecord{
		fixtureRecord(t, store, "submissions.json", "submissions", retrieved),
		fixtureRecord(t, store, "historical-submissions.json", "submissions_historical", retrieved),
		fixtureRecord(t, store, "companyfacts.json", "company_facts", retrieved),
	}
	asOf := time.Date(2025, 8, 6, 0, 0, 0, 0, time.UTC)
	result, err := transform(records, store, asOf, retrieved)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Companies) != 1 || len(result.Filings) != 4 || len(result.Facts) != 5 || len(result.Issues) != 1 {
		t.Fatalf("unexpected result sizes: companies=%d filings=%d facts=%d issues=%d", len(result.Companies), len(result.Filings), len(result.Facts), len(result.Issues))
	}
	if err := writeDataset(filepath.Join(root, "derived"), result, asOf, retrieved); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"companies.jsonl", "filings.jsonl", "reported_facts.jsonl", "normalized_metrics.jsonl", "issues.jsonl", "manifest.json"} {
		if info, err := os.Stat(filepath.Join(root, "derived", name)); err != nil || info.Size() == 0 {
			t.Fatalf("missing output %s: %v", name, err)
		}
	}
}

func fixtureRecord(t *testing.T, store rawstore.Store, name, dataset string, retrieved time.Time) ingestionRecord {
	t.Helper()
	content, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "sec", name))
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(content)
	record, err := store.Put(rawstore.Input{
		SourceURI: "https://data.sec.gov/test/" + name, MediaType: "application/json", Content: content,
		ContentSHA: hex.EncodeToString(digest[:]), RetrievedAt: retrieved,
	})
	if err != nil {
		t.Fatal(err)
	}
	return ingestionRecord{CIK: "0000789019", Dataset: dataset, RawRecord: record}
}
