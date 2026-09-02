package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/normalize"
	"github.com/rvbernucci/signalforge/internal/rawstore"
	"github.com/rvbernucci/signalforge/internal/secparse"
)

type ingestionRecord struct {
	CIK       string          `json:"cik"`
	Dataset   string          `json:"dataset"`
	RawRecord rawstore.Record `json:"raw_record"`
}

type ingestionEnvelope struct {
	SchemaVersion string            `json:"schema_version"`
	Records       []ingestionRecord `json:"records"`
}

type transformed struct {
	Companies []data.Company
	Filings   []data.Filing
	Facts     []data.ReportedFact
	Metrics   []data.NormalizedMetric
	Issues    []secparse.FactIssue
}

func main() {
	ingestionPath := flag.String("ingestion-result", "", "path to signalforge-ingest-sec JSON output")
	rawStorePath := flag.String("raw-store", "", "raw-store directory")
	outputPath := flag.String("output", "", "derived dataset directory")
	asOfRaw := flag.String("as-of", "", "point-in-time cutoff in RFC3339")
	computedRaw := flag.String("computed-at", "", "reproducible computation time in RFC3339; defaults to as-of")
	flag.Parse()

	if *ingestionPath == "" || *rawStorePath == "" || *outputPath == "" || *asOfRaw == "" {
		fatal(errors.New("--ingestion-result, --raw-store, --output, and --as-of are required"))
	}
	asOf, err := time.Parse(time.RFC3339, *asOfRaw)
	if err != nil {
		fatal(fmt.Errorf("parse --as-of: %w", err))
	}
	computedAt := asOf
	if *computedRaw != "" {
		computedAt, err = time.Parse(time.RFC3339, *computedRaw)
		if err != nil {
			fatal(fmt.Errorf("parse --computed-at: %w", err))
		}
	}
	if computedAt.Before(asOf) {
		fatal(errors.New("--computed-at cannot precede --as-of"))
	}
	content, err := os.ReadFile(*ingestionPath)
	if err != nil {
		fatal(err)
	}
	var envelope ingestionEnvelope
	if err := json.Unmarshal(content, &envelope); err != nil {
		fatal(err)
	}
	if envelope.SchemaVersion != "signalforge/sec-ingestion-result/v1" {
		fatal(fmt.Errorf("unsupported ingestion schema %q", envelope.SchemaVersion))
	}
	store, err := rawstore.New(*rawStorePath)
	if err != nil {
		fatal(err)
	}
	result, err := transform(envelope.Records, store, asOf.UTC(), computedAt.UTC())
	if err != nil {
		fatal(err)
	}
	if err := writeDataset(*outputPath, result, asOf.UTC(), computedAt.UTC()); err != nil {
		fatal(err)
	}
}

func transform(records []ingestionRecord, store rawstore.Store, asOf, computedAt time.Time) (transformed, error) {
	grouped := map[string][]ingestionRecord{}
	for _, record := range records {
		cik, err := data.CanonicalCIK(record.CIK)
		if err != nil {
			return transformed{}, err
		}
		grouped[cik] = append(grouped[cik], record)
	}
	var output transformed
	for cik, group := range grouped {
		var root *ingestionRecord
		var factRecord *ingestionRecord
		var historical []ingestionRecord
		for index := range group {
			switch group[index].Dataset {
			case "submissions":
				if root != nil {
					return transformed{}, fmt.Errorf("CIK %s has multiple root submissions records", cik)
				}
				root = &group[index]
			case "submissions_historical":
				historical = append(historical, group[index])
			case "company_facts":
				if factRecord != nil {
					return transformed{}, fmt.Errorf("CIK %s has multiple company facts records", cik)
				}
				factRecord = &group[index]
			}
		}
		if root == nil || factRecord == nil {
			return transformed{}, fmt.Errorf("CIK %s requires submissions and company_facts records", cik)
		}
		rootContent, err := store.ReadPayload(root.RawRecord)
		if err != nil {
			return transformed{}, err
		}
		company, recent, _, err := secparse.ParseSubmissions(rootContent, root.RawRecord)
		if err != nil {
			return transformed{}, err
		}
		filingGroups := [][]data.Filing{recent}
		for _, record := range historical {
			content, err := store.ReadPayload(record.RawRecord)
			if err != nil {
				return transformed{}, err
			}
			filings, err := secparse.ParseHistoricalSubmissions(content, company.CompanyID, record.RawRecord)
			if err != nil {
				return transformed{}, err
			}
			filingGroups = append(filingGroups, filings)
		}
		filings, err := secparse.MergeFilings(filingGroups...)
		if err != nil {
			return transformed{}, err
		}
		index, err := secparse.FilingIndex(filings)
		if err != nil {
			return transformed{}, err
		}
		factContent, err := store.ReadPayload(factRecord.RawRecord)
		if err != nil {
			return transformed{}, err
		}
		facts, issues, err := secparse.ParseCompanyFacts(factContent, factRecord.RawRecord, index)
		if err != nil {
			return transformed{}, err
		}
		output.Companies = append(output.Companies, company)
		output.Filings = append(output.Filings, filings...)
		output.Facts = append(output.Facts, facts...)
		output.Issues = append(output.Issues, issues...)
		output.Metrics = append(output.Metrics, normalize.AsOf(facts, asOf, computedAt)...)
	}
	sort.Slice(output.Companies, func(i, j int) bool { return output.Companies[i].CIK < output.Companies[j].CIK })
	sort.Slice(output.Filings, func(i, j int) bool { return output.Filings[i].FilingID < output.Filings[j].FilingID })
	sort.Slice(output.Facts, func(i, j int) bool { return output.Facts[i].FactID < output.Facts[j].FactID })
	sort.Slice(output.Metrics, func(i, j int) bool { return output.Metrics[i].MetricID < output.Metrics[j].MetricID })
	return output, nil
}

func writeDataset(root string, result transformed, asOf, computedAt time.Time) error {
	if strings.TrimSpace(root) == "" {
		return errors.New("output directory is required")
	}
	if err := os.MkdirAll(root, 0o750); err != nil {
		return err
	}
	files := map[string]any{
		"companies.jsonl": result.Companies, "filings.jsonl": result.Filings,
		"reported_facts.jsonl": result.Facts, "normalized_metrics.jsonl": result.Metrics,
		"issues.jsonl": result.Issues,
	}
	hashes := map[string]string{}
	for name, rows := range files {
		path := filepath.Join(root, name)
		content, err := encodeJSONL(rows)
		if err != nil {
			return err
		}
		if err := os.WriteFile(path, content, 0o640); err != nil {
			return err
		}
		digest := sha256.Sum256(content)
		hashes[name] = hex.EncodeToString(digest[:])
	}
	manifest := map[string]any{
		"schema_version": "signalforge/sec-derived-manifest/v1", "as_of": asOf,
		"computed_at": computedAt, "normalization_policy": normalize.PolicyVersion, "files": hashes,
	}
	content, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(root, "manifest.json"), append(content, '\n'), 0o640)
}

func encodeJSONL(value any) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(raw, &rows); err != nil {
		return nil, err
	}
	var output []byte
	for _, row := range rows {
		output = append(output, row...)
		output = append(output, '\n')
	}
	return output, nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
