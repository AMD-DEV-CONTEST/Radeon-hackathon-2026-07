package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/productscope"
)

const manifestSchemaV1 = "signalforge/technology20-financial-activation-manifest/v1"

type manifest struct {
	SchemaVersion          string            `json:"schema_version"`
	UniverseID             string            `json:"universe_id"`
	AsOf                   time.Time         `json:"as_of"`
	CodeCommit             string            `json:"code_commit"`
	SourceMetricsSHA256    string            `json:"source_metrics_sha256"`
	SourceFactsSHA256      string            `json:"source_facts_sha256"`
	ProductCatalogSHA256   string            `json:"product_catalog_sha256"`
	Companies              int               `json:"companies"`
	SuccessfulReceipts     int               `json:"successful_receipts"`
	TypedAbstentions       int               `json:"typed_abstentions"`
	ReceiptsByOperation    map[string]int    `json:"receipts_by_operation"`
	AbstentionsByOperation map[string]int    `json:"abstentions_by_operation"`
	Reports                []reportReference `json:"reports"`
	ClaimBoundary          string            `json:"claim_boundary"`
	ManifestSHA256         string            `json:"manifest_sha256"`
}

type reportReference struct {
	CompanyID   string `json:"company_id"`
	Path        string `json:"path"`
	ReportSHA   string `json:"report_sha256"`
	FileSHA256  string `json:"file_sha256"`
	Receipts    int    `json:"receipts"`
	Abstentions int    `json:"abstentions"`
}

func main() {
	metricsPath := flag.String("metrics", "", "Frozen normalized_metrics.jsonl path")
	factsPath := flag.String("facts", "", "Frozen reported_facts.jsonl path")
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "Public-safe Technology 20 catalog")
	outputDir := flag.String("output-dir", "", "Output directory for immutable company reports")
	publicSummaryOutput := flag.String("public-summary-output", "", "Optional public-safe summary JSON output")
	asOfRaw := flag.String("as-of", "", "Point-in-time cutoff in RFC3339")
	codeCommit := flag.String("code-commit", "", "Source revision recorded in receipts")
	flag.Parse()
	if *metricsPath == "" || *factsPath == "" || *catalogPath == "" || *outputDir == "" || *asOfRaw == "" || *codeCommit == "" {
		exit(fmt.Errorf("--metrics, --facts, --catalog, --output-dir, --as-of, and --code-commit are required"))
	}
	asOf, err := time.Parse(time.RFC3339, *asOfRaw)
	if err != nil {
		exit(err)
	}
	catalogPayload, err := os.ReadFile(*catalogPath)
	if err != nil {
		exit(err)
	}
	var catalog productscope.PublicCatalog
	if err := json.Unmarshal(catalogPayload, &catalog); err != nil {
		exit(err)
	}
	if err := productscope.ValidatePublicCatalog(catalog); err != nil {
		exit(err)
	}
	metrics, metricsSHA, err := readMetrics(*metricsPath)
	if err != nil {
		exit(err)
	}
	facts, factsSHA, err := readFacts(*factsPath, referencedFactIDs(metrics))
	if err != nil {
		exit(err)
	}
	if err := os.MkdirAll(*outputDir, 0o755); err != nil {
		exit(err)
	}
	result := manifest{
		SchemaVersion: manifestSchemaV1, UniverseID: productscope.UniverseID, AsOf: asOf.UTC(),
		CodeCommit: *codeCommit, SourceMetricsSHA256: metricsSHA,
		SourceFactsSHA256:    factsSHA,
		ProductCatalogSHA256: hashBytes(catalogPayload),
		ReceiptsByOperation:  map[string]int{}, AbstentionsByOperation: map[string]int{},
		ClaimBoundary: "A successful receipt proves only the named deterministic formula over aligned, fresh, consolidated, standardized periodic-filing inputs. Capex means the exact US-GAAP PaymentsToAcquirePropertyPlantAndEquipment perimeter. OCF minus that capex is labeled simple FCF and is never promoted to FCFF or total economic reinvestment. Missing inputs, semantic aliases, market observations, or professional review produce abstentions.",
	}
	reports := map[string]productscope.CompanyFinancialActivation{}
	for _, company := range catalog.Companies {
		report, buildErr := productscope.BuildCompanyFinancialActivation(
			company.CompanyID, metrics[company.CompanyID], facts, asOf, *codeCommit,
		)
		if buildErr != nil {
			exit(fmt.Errorf("%s: %w", company.CompanyID, buildErr))
		}
		reports[company.CompanyID] = report
		payload, marshalErr := json.MarshalIndent(report, "", "  ")
		if marshalErr != nil {
			exit(marshalErr)
		}
		payload = append(payload, '\n')
		name := company.PrimaryTicker + ".json"
		if writeErr := atomicWrite(filepath.Join(*outputDir, name), payload); writeErr != nil {
			exit(writeErr)
		}
		result.Reports = append(result.Reports, reportReference{
			CompanyID: company.CompanyID, Path: name, ReportSHA: report.ReportSHA256,
			FileSHA256: hashBytes(payload), Receipts: len(report.Receipts), Abstentions: len(report.Abstentions),
		})
		result.SuccessfulReceipts += len(report.Receipts)
		result.TypedAbstentions += len(report.Abstentions)
		for _, receipt := range report.Receipts {
			result.ReceiptsByOperation[receipt.OperationID]++
		}
		for _, abstention := range report.Abstentions {
			result.AbstentionsByOperation[abstention.MetricIDs[0]]++
		}
	}
	result.Companies = len(result.Reports)
	sort.Slice(result.Reports, func(i, j int) bool { return result.Reports[i].CompanyID < result.Reports[j].CompanyID })
	result.ManifestSHA256 = manifestHash(result)
	payload, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		exit(err)
	}
	if err := atomicWrite(filepath.Join(*outputDir, "manifest.json"), append(payload, '\n')); err != nil {
		exit(err)
	}
	if *publicSummaryOutput != "" {
		summary, summaryErr := productscope.BuildPublicFinancialSummary(catalog, reports)
		if summaryErr != nil {
			exit(summaryErr)
		}
		summaryPayload, marshalErr := json.MarshalIndent(summary, "", "  ")
		if marshalErr != nil {
			exit(marshalErr)
		}
		if writeErr := atomicWrite(*publicSummaryOutput, append(summaryPayload, '\n')); writeErr != nil {
			exit(writeErr)
		}
	}
	fmt.Printf("financial activation: %d companies, %d receipts, %d abstentions\n",
		result.Companies, result.SuccessfulReceipts, result.TypedAbstentions)
}

func referencedFactIDs(metrics map[string][]data.NormalizedMetric) map[string]bool {
	result := map[string]bool{}
	for _, companyMetrics := range metrics {
		for _, metric := range companyMetrics {
			for _, factID := range metric.SourceFactIDs {
				result[factID] = true
			}
		}
	}
	return result
}

func readFacts(path string, wanted map[string]bool) (map[string]data.ReportedFact, string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, "", err
	}
	defer file.Close()
	hasher := sha256.New()
	scanner := bufio.NewScanner(io.TeeReader(file, hasher))
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	result := map[string]data.ReportedFact{}
	for scanner.Scan() {
		var fact data.ReportedFact
		if err := json.Unmarshal(scanner.Bytes(), &fact); err != nil {
			return nil, "", err
		}
		if wanted[fact.FactID] {
			result[fact.FactID] = fact
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, "", err
	}
	return result, hex.EncodeToString(hasher.Sum(nil)), nil
}

func readMetrics(path string) (map[string][]data.NormalizedMetric, string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, "", err
	}
	defer file.Close()
	hasher := sha256.New()
	reader := io.TeeReader(file, hasher)
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	result := map[string][]data.NormalizedMetric{}
	for scanner.Scan() {
		var metric data.NormalizedMetric
		if err := json.Unmarshal(scanner.Bytes(), &metric); err != nil {
			return nil, "", err
		}
		result[metric.CompanyID] = append(result[metric.CompanyID], metric)
	}
	if err := scanner.Err(); err != nil {
		return nil, "", err
	}
	return result, hex.EncodeToString(hasher.Sum(nil)), nil
}

func atomicWrite(path string, payload []byte) error {
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, payload, 0o644); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

func manifestHash(value manifest) string {
	value.ManifestSHA256 = ""
	payload, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return hashBytes(payload)
}

func hashBytes(payload []byte) string {
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}

func exit(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
