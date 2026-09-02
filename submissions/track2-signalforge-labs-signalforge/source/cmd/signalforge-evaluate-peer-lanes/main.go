package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/rvbernucci/signalforge/internal/productscope"
)

func main() {
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "Technology 20 catalog")
	reportsDir := flag.String("reports-dir", "", "Company financial activation reports")
	output := flag.String("output", "", "Peer evaluation output")
	generatedAtRaw := flag.String("generated-at", "", "Evaluation time in RFC3339")
	flag.Parse()
	if *reportsDir == "" || *output == "" || *generatedAtRaw == "" {
		fatal(fmt.Errorf("--reports-dir, --output, and --generated-at are required"))
	}
	generatedAt, err := time.Parse(time.RFC3339, *generatedAtRaw)
	if err != nil {
		fatal(err)
	}
	var catalog productscope.PublicCatalog
	readJSON(*catalogPath, &catalog)
	reports := map[string]productscope.CompanyFinancialActivation{}
	for _, company := range catalog.Companies {
		var report productscope.CompanyFinancialActivation
		readJSON(filepath.Join(*reportsDir, company.PrimaryTicker+".json"), &report)
		reports[company.CompanyID] = report
	}
	suite, err := productscope.BuildPeerEvaluationSuite(catalog, reports, generatedAt)
	if err != nil {
		fatal(err)
	}
	payload, err := json.MarshalIndent(suite, "", "  ")
	if err != nil {
		fatal(err)
	}
	if err := os.WriteFile(*output, append(payload, '\n'), 0o644); err != nil {
		fatal(err)
	}
	fmt.Printf("peer evaluation: %d lanes\n", len(suite.Lanes))
}

func readJSON(path string, target any) {
	payload, err := os.ReadFile(path)
	if err != nil {
		fatal(err)
	}
	if err := json.Unmarshal(payload, target); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
