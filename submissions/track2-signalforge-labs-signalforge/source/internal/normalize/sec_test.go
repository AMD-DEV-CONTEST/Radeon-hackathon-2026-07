package normalize

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/rawstore"
	"github.com/rvbernucci/signalforge/internal/secparse"
)

func loadFacts(t *testing.T) []byte {
	t.Helper()
	content, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "sec", "companyfacts.json"))
	if err != nil {
		t.Fatal(err)
	}
	return content
}

func TestAsOfPreventsFutureLeakageAndPreservesAmendmentState(t *testing.T) {
	retrieved := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	filings := fixtureFilings(retrieved)
	index, _ := secparse.FilingIndex(filings)
	content := loadFacts(t)
	digest := sha256.Sum256(content)
	record := rawstore.Record{RecordID: "facts-record", SourceURI: "https://data.sec.gov/companyfacts.json", ContentSHA: hex.EncodeToString(digest[:]), RetrievedAt: retrieved}
	facts, _, err := secparse.ParseCompanyFacts(content, record, index)
	if err != nil {
		t.Fatal(err)
	}

	beforeAmendment := time.Date(2025, 8, 1, 0, 0, 0, 0, time.UTC)
	metrics := AsOf(facts, beforeAmendment, retrieved)
	if value := metricValue(metrics, "revenue", "2025-06-30"); value != "100" {
		t.Fatalf("pre-amendment value = %q", value)
	}
	afterAmendment := time.Date(2025, 8, 6, 0, 0, 0, 0, time.UTC)
	metrics = AsOf(facts, afterAmendment, retrieved)
	if value := metricValue(metrics, "revenue", "2025-06-30"); value != "110" {
		t.Fatalf("post-amendment value = %q", value)
	}
	if value := metricValue(metrics, "revenue", "2025-12-31"); value != "" {
		t.Fatalf("future fact leaked with value %q", value)
	}
}

func TestAsOfMapsProductiveAssetsToConservativeCapexAlias(t *testing.T) {
	start := time.Date(2024, 1, 29, 0, 0, 0, 0, time.UTC)
	end := time.Date(2025, 1, 26, 0, 0, 0, 0, time.UTC)
	available := time.Date(2025, 2, 26, 21, 48, 33, 0, time.UTC)
	facts := []data.ReportedFact{{
		FactID: "fact-productive-assets", FilingID: "filing-nvda-2025",
		CompanyID: "sec-cik:0001045810", Taxonomy: "us-gaap",
		Concept: "PaymentsToAcquireProductiveAssets", Value: "3236000000", Unit: "USD",
		StartDate: &start, EndDate: &end, FormType: "10-K", AvailableAt: available,
	}}
	metrics := AsOf(facts, available.Add(time.Hour), available.Add(2*time.Hour))
	if len(metrics) != 1 || metrics[0].CanonicalMetric != "capital_expenditure" || metrics[0].Value != "3236000000" {
		t.Fatalf("unexpected productive-assets normalization: %+v", metrics)
	}
	if metrics[0].ComparabilityStatus != "concept_alias" || len(metrics[0].QualityFlags) != 1 || metrics[0].QualityFlags[0] != "canonical_concept_alias" {
		t.Fatalf("capex alias must remain visible: %+v", metrics[0])
	}
}

func fixtureFilings(retrieved time.Time) []data.Filing {
	timestamps := []time.Time{
		time.Date(2024, 7, 30, 16, 0, 0, 0, time.UTC), time.Date(2025, 7, 30, 16, 0, 0, 0, time.UTC),
		time.Date(2025, 8, 5, 16, 5, 0, 0, time.UTC), time.Date(2026, 1, 29, 16, 10, 0, 0, time.UTC),
	}
	accessions := []string{"0000789019-24-000001", "0000789019-25-000001", "0000789019-25-000002", "0000789019-26-000001"}
	forms := []string{"10-K", "10-K", "10-K/A", "10-Q"}
	result := make([]data.Filing, 0, len(accessions))
	for index := range accessions {
		result = append(result, data.Filing{FilingID: "sec-filing:" + accessions[index], CompanyID: "sec-cik:0000789019", AccessionNumber: accessions[index], FormType: forms[index], AcceptedAt: timestamps[index], RetrievedAt: retrieved})
	}
	return result
}

func metricValue(metrics []data.NormalizedMetric, name, end string) string {
	for _, metric := range metrics {
		if metric.CanonicalMetric == name && metric.PeriodEnd.Format("2006-01-02") == end {
			return metric.Value
		}
	}
	return ""
}
