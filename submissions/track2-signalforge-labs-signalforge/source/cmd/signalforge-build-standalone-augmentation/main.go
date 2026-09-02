package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/productscope"
)

func main() {
	catalogPath := flag.String(
		"catalog",
		"fixtures/productscope/technology20-catalog.json",
		"Technology 20 catalog",
	)
	financialsPath := flag.String(
		"financials",
		"fixtures/productscope/technology20-financial-summary.json",
		"public financial authority",
	)
	outputPath := flag.String(
		"output",
		"fixtures/productscope/technology20-standalone-domain-augmentation.json",
		"public development-only augmentation output",
	)
	flag.Parse()

	var catalog productscope.PublicCatalog
	readJSON(*catalogPath, &catalog)
	var financials productscope.PublicFinancialSummary
	readJSON(*financialsPath, &financials)
	suite, err := productscope.BuildStandaloneDevelopmentAugmentationSuite(catalog, financials)
	if err != nil {
		fatal(err)
	}
	writeJSON(*outputPath, suite)
	fmt.Printf("standalone development augmentation: %d cases\n", len(suite.Cases))
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

func writeJSON(path string, value any) {
	payload, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		fatal(err)
	}
	if err := os.WriteFile(path, append(payload, '\n'), 0o644); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
