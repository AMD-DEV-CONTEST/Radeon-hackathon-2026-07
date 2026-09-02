package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/productscope"
)

func main() {
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "Technology 20 catalog")
	financialsPath := flag.String("financials", "fixtures/productscope/technology20-financial-summary.json", "Public financial authority")
	developmentOutput := flag.String("development-output", "fixtures/productscope/technology20-standalone-development.json", "Development population output")
	sealedOutput := flag.String("sealed-output", "", "Sealed population output outside public fixtures")
	flag.Parse()
	if *sealedOutput == "" {
		fatal(fmt.Errorf("--sealed-output is required"))
	}
	var catalog productscope.PublicCatalog
	readJSON(*catalogPath, &catalog)
	var financials productscope.PublicFinancialSummary
	readJSON(*financialsPath, &financials)
	development, sealed, err := productscope.BuildStandaloneJourneySuites(catalog, financials)
	if err != nil {
		fatal(err)
	}
	writeJSON(*developmentOutput, development)
	writeJSON(*sealedOutput, sealed)
	fmt.Printf("standalone population: %d development, %d sealed\n", len(development.Cases), len(sealed.Cases))
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
