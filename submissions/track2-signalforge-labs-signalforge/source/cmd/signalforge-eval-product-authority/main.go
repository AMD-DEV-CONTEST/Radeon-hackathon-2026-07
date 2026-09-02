package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/rvbernucci/signalforge/internal/planner"
	"github.com/rvbernucci/signalforge/internal/productscope"
	"github.com/rvbernucci/signalforge/internal/requestparser"
)

const reportSchemaV1 = "signalforge/product-authority-preflight/v1"

type report struct {
	SchemaVersion       string         `json:"schema_version"`
	MeasuredAt          time.Time      `json:"measured_at"`
	Split               string         `json:"split"`
	Cases               int            `json:"cases"`
	ParserPassed        int            `json:"parser_passed"`
	AuthorityPassed     int            `json:"authority_passed"`
	PlannerPassed       int            `json:"planner_passed"`
	ExpectedRoutePassed int            `json:"expected_route_passed"`
	Failures            map[string]int `json:"failures"`
	ClaimBoundary       string         `json:"claim_boundary"`
	Passed              bool           `json:"passed"`
}

func main() {
	suitePath := flag.String("suite", "", "Standalone journey suite")
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "Technology 20 catalog")
	financialsPath := flag.String("financials", "fixtures/productscope/technology20-financial-summary.json", "Public financial summary")
	peersPath := flag.String("peers", "fixtures/productscope/technology20-peer-evaluation.json", "Peer evaluation suite")
	output := flag.String("output", "", "Preflight report output")
	measuredAtRaw := flag.String("measured-at", "", "Measurement time in RFC3339")
	flag.Parse()
	if *suitePath == "" || *output == "" || *measuredAtRaw == "" {
		fatal(fmt.Errorf("--suite, --output, and --measured-at are required"))
	}
	measuredAt, err := time.Parse(time.RFC3339, *measuredAtRaw)
	if err != nil {
		fatal(err)
	}
	var suite productscope.StandaloneJourneySuite
	readJSON(*suitePath, &suite)
	var catalog productscope.PublicCatalog
	readJSON(*catalogPath, &catalog)
	var financials productscope.PublicFinancialSummary
	readJSON(*financialsPath, &financials)
	var peers productscope.PeerEvaluationSuite
	readJSON(*peersPath, &peers)
	result := evaluate(suite, catalog, financials, peers, measuredAt)
	writeJSON(*output, result)
	fmt.Printf("authority preflight: %d/%d passed (%s)\n", result.ExpectedRoutePassed, result.Cases, result.Split)
	if !result.Passed {
		os.Exit(1)
	}
}

func evaluate(
	suite productscope.StandaloneJourneySuite,
	catalog productscope.PublicCatalog,
	financials productscope.PublicFinancialSummary,
	peers productscope.PeerEvaluationSuite,
	measuredAt time.Time,
) report {
	result := report{
		SchemaVersion: reportSchemaV1, MeasuredAt: measuredAt, Split: suite.Split,
		Cases: len(suite.Cases), Failures: map[string]int{},
		ClaimBoundary: "This preflight proves deterministic parsing, authority binding, planning, and expected receipt/abstention routing. It does not evaluate model answer quality or promote a company.",
	}
	financialByCompany := map[string]productscope.PublicCompanyFinancials{}
	for _, company := range financials.Companies {
		financialByCompany[company.CompanyID] = company
	}
	for index, item := range suite.Cases {
		request, err := requestparser.ParseDeterministic(requestparser.Input{
			Text: item.Question, AsOf: suite.AsOf,
			RunID:     fmt.Sprintf("preflight-%s-%03d", suite.Split, index),
			RequestID: fmt.Sprintf("preflight-request-%s-%03d", suite.Split, index),
		})
		if err != nil {
			result.Failures["parser"]++
			continue
		}
		result.ParserPassed++
		bound, err := productscope.BindRequestAuthority(request, catalog, peers)
		if err != nil {
			result.Failures["authority"]++
			continue
		}
		result.AuthorityPassed++
		if _, err := planner.Default().Build(bound); err != nil {
			result.Failures["planner"]++
			continue
		}
		result.PlannerPassed++
		if expectedAuthorityMatches(item, financialByCompany[item.CompanyID]) {
			result.ExpectedRoutePassed++
		} else {
			result.Failures["expected_route"]++
		}
	}
	result.Passed = result.Cases > 0 && result.ExpectedRoutePassed == result.Cases
	return result
}

func expectedAuthorityMatches(
	item productscope.StandaloneJourneyCase,
	financials productscope.PublicCompanyFinancials,
) bool {
	results := map[string]bool{}
	abstentions := map[string]bool{}
	for _, value := range financials.Results {
		results[value.OperationID] = true
	}
	for _, value := range financials.Abstentions {
		abstentions[value.OperationID] = true
	}
	for _, operation := range item.ExpectedReceipts {
		if !results[operation] {
			return false
		}
	}
	for _, operation := range item.ExpectedAbstentions {
		if operation == "narrative.investor_relations" || operation == "macro.transmission" {
			continue
		}
		if !abstentions[operation] {
			return false
		}
	}
	return true
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
