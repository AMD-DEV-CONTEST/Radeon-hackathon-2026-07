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

const reportSchemaV1 = "signalforge/peer-authority-preflight/v1"

type report struct {
	SchemaVersion     string         `json:"schema_version"`
	MeasuredAt        time.Time      `json:"measured_at"`
	Split             string         `json:"split"`
	Cases             int            `json:"cases"`
	ParserPassed      int            `json:"parser_passed"`
	AuthorityPassed   int            `json:"authority_passed"`
	PlannerPassed     int            `json:"planner_passed"`
	DispositionPassed int            `json:"disposition_passed"`
	Failures          map[string]int `json:"failures"`
	ClaimBoundary     string         `json:"claim_boundary"`
	Passed            bool           `json:"passed"`
}

func main() {
	suitePath := flag.String("suite", "", "Peer journey suite")
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "Technology 20 catalog")
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
	var suite productscope.PeerJourneySuite
	readJSON(*suitePath, &suite)
	var catalog productscope.PublicCatalog
	readJSON(*catalogPath, &catalog)
	var peers productscope.PeerEvaluationSuite
	readJSON(*peersPath, &peers)
	result := evaluate(suite, catalog, peers, measuredAt)
	writeJSON(*output, result)
	fmt.Printf("peer authority preflight: %d/%d passed (%s)\n", result.DispositionPassed, result.Cases, result.Split)
	if !result.Passed {
		os.Exit(1)
	}
}

func evaluate(
	suite productscope.PeerJourneySuite,
	catalog productscope.PublicCatalog,
	peers productscope.PeerEvaluationSuite,
	measuredAt time.Time,
) report {
	result := report{
		SchemaVersion: reportSchemaV1, MeasuredAt: measuredAt, Split: suite.Split,
		Cases: len(suite.Cases), Failures: map[string]int{},
		ClaimBoundary: "This preflight proves deterministic parsing, pair authority binding, planning, and frozen metric dispositions. It does not evaluate answer quality or promote a peer lane.",
	}
	dispositions := map[string]map[string]string{}
	for _, lane := range peers.Lanes {
		dispositions[lane.LaneID] = map[string]string{}
		for _, receipt := range lane.Receipts {
			dispositions[lane.LaneID][receipt.Operands[0].CanonicalMetricID] = string(receipt.Disposition)
		}
		for _, abstention := range lane.Abstentions {
			dispositions[lane.LaneID][abstention.MetricIDs[0]] = "unavailable"
		}
	}
	for index, item := range suite.Cases {
		request, err := requestparser.ParseDeterministic(requestparser.Input{
			Text: item.Question, AsOf: suite.AsOf,
			RunID:     fmt.Sprintf("peer-preflight-%s-%03d", suite.Split, index),
			RequestID: fmt.Sprintf("peer-preflight-request-%s-%03d", suite.Split, index),
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
		if sameMap(item.ExpectedMetrics, dispositions[item.LaneID]) && bound.AuthorityState == "limited" {
			result.DispositionPassed++
		} else {
			result.Failures["disposition"]++
		}
	}
	result.Passed = result.Cases > 0 && result.DispositionPassed == result.Cases
	return result
}

func sameMap(left, right map[string]string) bool {
	if len(left) != len(right) {
		return false
	}
	for key, value := range left {
		if right[key] != value {
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
