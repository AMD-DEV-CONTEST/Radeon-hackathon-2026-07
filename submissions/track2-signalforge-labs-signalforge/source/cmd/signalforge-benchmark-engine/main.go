package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/engine"
	"github.com/rvbernucci/signalforge/internal/finance"
	"github.com/rvbernucci/signalforge/internal/numeric"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type result struct {
	SchemaVersion string       `json:"schema_version"`
	GoVersion     string       `json:"go_version"`
	GOOS          string       `json:"goos"`
	GOARCH        string       `json:"goarch"`
	CodeRevision  string       `json:"code_revision"`
	Cases         []caseResult `json:"cases"`
}

type caseResult struct {
	Name       string  `json:"name"`
	Iterations int     `json:"iterations"`
	P50US      float64 `json:"p50_us"`
	P95US      float64 `json:"p95_us"`
	MaxUS      float64 `json:"max_us"`
	OutputSHA  string  `json:"output_sha256"`
}

func main() {
	output := flag.String("output", "-", "JSON output path, or - for stdout")
	codeRevision := flag.String("code-revision", "", "commit or worktree identity for the measured source")
	flag.Parse()
	if *codeRevision == "" {
		fmt.Fprintln(os.Stderr, "--code-revision is required")
		os.Exit(2)
	}
	report, err := benchmark(*codeRevision)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	encoded, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		panic(err)
	}
	encoded = append(encoded, '\n')
	if *output == "-" {
		os.Stdout.Write(encoded)
		return
	}
	if err := os.WriteFile(*output, encoded, 0o640); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func benchmark(codeRevision string) (result, error) {
	forecast := []numeric.Decimal{numeric.MustDecimal("10"), numeric.MustDecimal("11"), numeric.MustDecimal("12"), numeric.MustDecimal("13"), numeric.MustDecimal("14")}
	rates := make([]numeric.Decimal, 31)
	growths := make([]numeric.Decimal, 31)
	for index := range rates {
		rates[index] = numeric.MustDecimal(fmt.Sprintf("0.%03d", 80+index))
		growths[index] = numeric.MustDecimal(fmt.Sprintf("0.%03d", 10+index))
	}
	security := make([]float64, 10_000)
	market := make([]float64, 10_000)
	for index := range security {
		market[index] = float64((index%17)-8) / 10_000
		security[index] = 1.2*market[index] + float64((index%5)-2)/20_000
	}
	executor, err := engine.New(codeRevision)
	if err != nil {
		return result{}, err
	}
	operation, _ := capability.Tier0Registry().Get("financial.margin")
	asOf := time.Date(2026, 7, 21, 18, 30, 0, 0, time.UTC)
	observed := asOf.Add(-time.Hour)
	request := contracts.EngineRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: "benchmark-margin", RunID: "benchmark-run", StepID: "benchmark-step",
		RequestedBy: roles.AccountingReporting, EngineID: operation.Engine, OperationID: operation.ID, FormulaVersion: operation.FormulaVersion,
		Scope: contracts.Scope{AsOf: asOf}, PrecisionPolicy: operation.NumericalPolicy, RequestedOutputs: operation.Outputs,
		Inputs: []contracts.EngineInput{
			{InputID: "numerator", Quantity: contracts.Quantity{Value: "25", Unit: "currency", Currency: "USD", Period: "FY2025", AsOf: &observed}, Status: "reported", EvidenceRefs: []string{"benchmark:numerator"}},
			{InputID: "revenue", Quantity: contracts.Quantity{Value: "100", Unit: "currency", Currency: "USD", Period: "FY2025", AsOf: &observed}, Status: "reported", EvidenceRefs: []string{"benchmark:revenue"}},
		},
	}

	cases := []struct {
		name       string
		iterations int
		function   func() (any, error)
	}{
		{"scalar_decimal_margin", 2_000, func() (any, error) { return finance.Margin(numeric.MustDecimal("25"), numeric.MustDecimal("100")) }},
		{"five_year_fcff_dcf", 1_000, func() (any, error) {
			return finance.FCFFDCF(forecast, numeric.MustDecimal("0.10"), numeric.MustDecimal("0.03"))
		}},
		{"reverse_dcf", 500, func() (any, error) {
			return finance.ReverseDCF(numeric.MustDecimal("150"), numeric.MustDecimal("10"), numeric.MustDecimal("0.10"), 1, numeric.MustDecimal("0.00000001"), 256)
		}},
		{"beta_10000_observations", 200, func() (any, error) {
			value, count, err := finance.Beta(security, market, 1)
			return []any{value, count}, err
		}},
		{"dcf_sensitivity_961_cells", 30, func() (any, error) { return finance.DCFGrid(forecast, rates, growths) }},
		{"receipt_construction", 1_000, func() (any, error) {
			calculation := executor.Execute(request)
			if calculation.Failure != nil {
				return nil, fmt.Errorf("receipt benchmark failed: %s", calculation.Failure.Message)
			}
			return calculation.Receipt, nil
		}},
	}
	report := result{SchemaVersion: "signalforge/engine-benchmark/v1", GoVersion: runtime.Version(), GOOS: runtime.GOOS, GOARCH: runtime.GOARCH, CodeRevision: codeRevision}
	for _, benchmarkCase := range cases {
		measured, err := measure(benchmarkCase.name, benchmarkCase.iterations, benchmarkCase.function)
		if err != nil {
			return result{}, err
		}
		report.Cases = append(report.Cases, measured)
	}
	return report, nil
}

func measure(name string, iterations int, function func() (any, error)) (caseResult, error) {
	durations := make([]float64, iterations)
	var last any
	for index := 0; index < iterations; index++ {
		started := time.Now()
		value, err := function()
		durations[index] = float64(time.Since(started).Nanoseconds()) / 1_000
		if err != nil {
			return caseResult{}, err
		}
		last = value
	}
	sort.Float64s(durations)
	encoded, err := json.Marshal(last)
	if err != nil {
		return caseResult{}, err
	}
	digest := sha256.Sum256(encoded)
	return caseResult{
		Name: name, Iterations: iterations, P50US: percentile(durations, 0.50),
		P95US: percentile(durations, 0.95), MaxUS: durations[len(durations)-1], OutputSHA: hex.EncodeToString(digest[:]),
	}, nil
}

func percentile(sorted []float64, quantile float64) float64 {
	index := int(float64(len(sorted)-1) * quantile)
	return sorted[index]
}
