package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/roleeval"
)

func main() {
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "OpenAI-compatible local endpoint")
	model := flag.String("model", "", "served local model identifier")
	suitePath := flag.String("suite", "fixtures/roles/held-out-cases.json", "frozen held-out role suite")
	output := flag.String("output", "", "role evaluation report path")
	workers := flag.Int("workers", 1, "maximum concurrent role requests (1-8)")
	requestTimeout := flag.Duration("request-timeout", 3*time.Minute, "timeout for each local completion")
	overallTimeout := flag.Duration("overall-timeout", 45*time.Minute, "timeout for the complete suite")
	flag.Parse()

	if *model == "" || *output == "" || *requestTimeout <= 0 || *overallTimeout <= 0 {
		fatal("--model, --output, and positive timeout values are required")
	}
	payload, err := os.ReadFile(*suitePath)
	if err != nil {
		fatal(err.Error())
	}
	suite, err := roleeval.LoadSuite(*suitePath)
	if err != nil {
		fatal(err.Error())
	}
	digest := sha256.Sum256(payload)
	client := timeoutCompleter{
		next:    benchmark.Client{BaseURL: *baseURL},
		timeout: *requestTimeout,
	}
	ctx, cancel := context.WithTimeout(context.Background(), *overallTimeout)
	defer cancel()
	report, err := (roleeval.Evaluator{
		Client: client, Model: *model, Workers: *workers,
	}).Evaluate(ctx, suite)
	if err != nil {
		fatal(err.Error())
	}
	report.SuiteSHA256 = hex.EncodeToString(digest[:])
	encoded, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fatal(err.Error())
	}
	if err := os.MkdirAll(filepath.Dir(*output), 0o755); err != nil {
		fatal(err.Error())
	}
	if err := os.WriteFile(*output, append(encoded, '\n'), 0o644); err != nil {
		fatal(err.Error())
	}
	if ctx.Err() != nil {
		fatal(ctx.Err().Error())
	}
}

type timeoutCompleter struct {
	next    benchmark.Client
	timeout time.Duration
}

func (client timeoutCompleter) Complete(ctx context.Context, request benchmark.Request) (benchmark.Completion, error) {
	requestContext, cancel := context.WithTimeout(ctx, client.timeout)
	defer cancel()
	return client.next.Complete(requestContext, request)
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(1)
}
