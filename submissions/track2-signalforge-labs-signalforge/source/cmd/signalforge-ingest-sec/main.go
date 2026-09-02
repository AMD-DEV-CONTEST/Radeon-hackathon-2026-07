package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/adapters/sec"
	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/rawstore"
	"github.com/rvbernucci/signalforge/internal/secparse"
)

type result struct {
	CIK       string          `json:"cik"`
	Dataset   string          `json:"dataset"`
	RawRecord rawstore.Record `json:"raw_record"`
	Accession string          `json:"accession_number,omitempty"`
}

func main() {
	cikValues := flag.String("cik", "", "comma-separated SEC CIK values")
	storePath := flag.String("store", "", "raw-store directory")
	baseURL := flag.String("base-url", sec.DefaultBaseURL, "SEC data base URL")
	includeHistorical := flag.Bool("include-historical", true, "retrieve historical submission files referenced by the root payload")
	primaryDocuments := flag.Int("primary-documents", 0, "retrieve up to N latest primary 10-K/10-Q documents per company")
	flag.Parse()

	ciks, err := parseCIKs(*cikValues)
	if err != nil {
		fatal(err)
	}
	if strings.TrimSpace(*storePath) == "" {
		fatal(fmt.Errorf("--store is required"))
	}
	userAgent := strings.TrimSpace(os.Getenv("SIGNALFORGE_SEC_USER_AGENT"))
	if userAgent == "" {
		fatal(fmt.Errorf("SIGNALFORGE_SEC_USER_AGENT is required"))
	}
	client, err := sec.NewClient(*baseURL, userAgent, nil)
	if err != nil {
		fatal(err)
	}
	store, err := rawstore.New(*storePath)
	if err != nil {
		fatal(err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	results := make([]result, 0, len(ciks)*2)
	for _, cik := range ciks {
		submissions, err := client.CompanySubmissions(ctx, cik)
		if err != nil {
			fatal(fmt.Errorf("submissions for CIK %s: %w", cik, err))
		}
		submissionsRecord, err := store.Put(rawstore.Input{
			SourceURI: submissions.SourceURI, MediaType: "application/json", Content: submissions.Content,
			ContentSHA: submissions.ContentSHA, RetrievedAt: submissions.RetrievedAt,
		})
		if err != nil {
			fatal(fmt.Errorf("store submissions for CIK %s: %w", cik, err))
		}
		results = append(results, result{CIK: cik, Dataset: "submissions", RawRecord: submissionsRecord})
		company, recentFilings, historicalFiles, err := secparse.ParseSubmissions(submissions.Content, submissionsRecord)
		if err != nil {
			fatal(fmt.Errorf("parse submissions for CIK %s: %w", cik, err))
		}
		filingGroups := [][]data.Filing{recentFilings}
		if *includeHistorical {
			for _, historicalFile := range historicalFiles {
				document, err := client.HistoricalSubmissions(ctx, historicalFile.Name)
				if err != nil {
					fatal(fmt.Errorf("historical submissions %s: %w", historicalFile.Name, err))
				}
				record, err := store.Put(rawstore.Input{
					SourceURI: document.SourceURI, MediaType: "application/json", Content: document.Content,
					ContentSHA: document.ContentSHA, RetrievedAt: document.RetrievedAt,
				})
				if err != nil {
					fatal(fmt.Errorf("store historical submissions %s: %w", historicalFile.Name, err))
				}
				parsed, err := secparse.ParseHistoricalSubmissions(document.Content, company.CompanyID, record)
				if err != nil {
					fatal(fmt.Errorf("parse historical submissions %s: %w", historicalFile.Name, err))
				}
				filingGroups = append(filingGroups, parsed)
				results = append(results, result{CIK: cik, Dataset: "submissions_historical", RawRecord: record})
			}
		}
		filings, err := secparse.MergeFilings(filingGroups...)
		if err != nil {
			fatal(fmt.Errorf("merge filings for CIK %s: %w", cik, err))
		}
		if *primaryDocuments > 0 {
			sort.SliceStable(filings, func(i, j int) bool { return filings[i].AcceptedAt.After(filings[j].AcceptedAt) })
			captured := 0
			for _, filing := range filings {
				if captured >= *primaryDocuments {
					break
				}
				baseForm := strings.TrimSuffix(filing.FormType, "/A")
				if (baseForm != "10-K" && baseForm != "10-Q") || filing.PrimaryDocument == "" {
					continue
				}
				document, err := client.FilingDocument(ctx, cik, filing.AccessionNumber, filing.PrimaryDocument)
				if err != nil {
					fatal(fmt.Errorf("primary document %s: %w", filing.AccessionNumber, err))
				}
				record, err := store.Put(rawstore.Input{
					SourceURI: document.SourceURI, MediaType: "text/html", Content: document.Content,
					ContentSHA: document.ContentSHA, RetrievedAt: document.RetrievedAt,
				})
				if err != nil {
					fatal(fmt.Errorf("store primary document %s: %w", filing.AccessionNumber, err))
				}
				results = append(results, result{CIK: cik, Dataset: "filing_document", Accession: filing.AccessionNumber, RawRecord: record})
				captured++
			}
		}

		facts, err := client.CompanyFacts(ctx, cik)
		if err != nil {
			fatal(fmt.Errorf("company facts for CIK %s: %w", cik, err))
		}
		factsRecord, err := store.Put(rawstore.Input{
			SourceURI: facts.SourceURI, MediaType: "application/json", Content: facts.Content,
			ContentSHA: facts.ContentSHA, RetrievedAt: facts.RetrievedAt,
		})
		if err != nil {
			fatal(fmt.Errorf("store company facts for CIK %s: %w", cik, err))
		}
		results = append(results, result{CIK: cik, Dataset: "company_facts", RawRecord: factsRecord})
	}
	payload, err := json.MarshalIndent(map[string]any{
		"schema_version": "signalforge/sec-ingestion-result/v1",
		"records":        results,
	}, "", "  ")
	if err != nil {
		fatal(err)
	}
	fmt.Println(string(payload))
}

func parseCIKs(raw string) ([]string, error) {
	seen := map[string]bool{}
	var result []string
	for _, value := range strings.Split(raw, ",") {
		if strings.TrimSpace(value) == "" {
			continue
		}
		canonical, err := data.CanonicalCIK(value)
		if err != nil {
			return nil, err
		}
		if !seen[canonical] {
			seen[canonical] = true
			result = append(result, canonical)
		}
	}
	if len(result) == 0 {
		return nil, fmt.Errorf("at least one --cik value is required")
	}
	return result, nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
