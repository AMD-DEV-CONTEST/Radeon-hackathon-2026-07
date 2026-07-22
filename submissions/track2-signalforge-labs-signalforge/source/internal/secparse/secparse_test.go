package secparse

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/rawstore"
)

func fixture(t *testing.T, name string, retrievedAt time.Time) ([]byte, rawstore.Record) {
	t.Helper()
	path := filepath.Join("..", "..", "fixtures", "sec", name)
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	return content, rawstore.Record{
		SchemaVersion: "signalforge/raw-record/v1", RecordID: "record:" + hash,
		SourceURI: "https://data.sec.gov/test/" + name, MediaType: "application/json",
		ContentSHA: hash, ContentBytes: len(content), RetrievedAt: retrievedAt,
		PayloadPath: "fixtures/" + name, RecordPath: "records/" + name + ".json",
	}
}

func TestParseSubmissionsAndHistoricalFiles(t *testing.T) {
	retrieved := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	content, record := fixture(t, "submissions.json", retrieved)
	company, recent, historicalRefs, err := ParseSubmissions(content, record)
	if err != nil {
		t.Fatal(err)
	}
	if company.CIK != "0000789019" || len(recent) != 3 || len(historicalRefs) != 1 {
		t.Fatalf("unexpected parsed submissions: %#v filings=%d refs=%d", company, len(recent), len(historicalRefs))
	}
	if recent[1].AmendsFilingID != recent[0].FilingID {
		t.Fatalf("amendment was not linked: %#v", recent[1])
	}

	historicalContent, historicalRecord := fixture(t, "historical-submissions.json", retrieved)
	historical, err := ParseHistoricalSubmissions(historicalContent, company.CompanyID, historicalRecord)
	if err != nil {
		t.Fatal(err)
	}
	merged, err := MergeFilings(recent, historical)
	if err != nil || len(merged) != 4 {
		t.Fatalf("merge filings: count=%d err=%v", len(merged), err)
	}
}

func TestCompanyFactsPreserveIssuesAndFilingAvailability(t *testing.T) {
	retrieved := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	submissions, submissionRecord := fixture(t, "submissions.json", retrieved)
	company, recent, _, err := ParseSubmissions(submissions, submissionRecord)
	if err != nil {
		t.Fatal(err)
	}
	historicalContent, historicalRecord := fixture(t, "historical-submissions.json", retrieved)
	historical, _ := ParseHistoricalSubmissions(historicalContent, company.CompanyID, historicalRecord)
	filings, _ := MergeFilings(recent, historical)
	index, _ := FilingIndex(filings)
	factsContent, factsRecord := fixture(t, "companyfacts.json", retrieved)
	facts, issues, err := ParseCompanyFacts(factsContent, factsRecord, index)
	if err != nil {
		t.Fatal(err)
	}
	if len(facts) != 5 || len(issues) != 1 || issues[0].Reason != "filing_accession_not_found" {
		t.Fatalf("facts=%d issues=%#v", len(facts), issues)
	}
	for _, fact := range facts {
		filing := index["0000789019-25-000002"]
		if fact.FilingID == filing.FilingID && !fact.AvailableAt.Equal(filing.AcceptedAt) {
			t.Fatal("fact availability must come from filing acceptance")
		}
	}
}

func TestMisalignedFilingColumnsFailClosed(t *testing.T) {
	retrieved := time.Now().UTC()
	content, record := fixture(t, "submissions.json", retrieved)
	broken := append([]byte(nil), content...)
	broken = []byte(string(broken[:len(broken)-3]) + `]}}`)
	if _, _, _, err := ParseSubmissions(broken, record); err == nil {
		t.Fatal("malformed or misaligned submission must fail")
	}
}
