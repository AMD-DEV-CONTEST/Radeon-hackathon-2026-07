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
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
	"github.com/rvbernucci/signalforge/internal/runid"
)

type callObservation struct {
	RoleID           string  `json:"role_id"`
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	DurationMS       float64 `json:"duration_ms"`
	FinishReason     string  `json:"finish_reason,omitempty"`
	Error            string  `json:"error,omitempty"`
}

type report struct {
	SchemaVersion string                    `json:"schema_version"`
	ModelID       string                    `json:"model_id"`
	StartedAt     time.Time                 `json:"started_at"`
	CompletedAt   time.Time                 `json:"completed_at"`
	Request       contracts.ResearchRequest `json:"request"`
	Result        orchestrator.Result       `json:"result"`
	Calls         []callObservation         `json:"calls"`
}

func main() {
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "OpenAI-compatible local endpoint")
	model := flag.String("model", "", "served local model identifier")
	output := flag.String("output", "", "evaluation report path")
	traceDir := flag.String("trace-dir", "", "private orchestration trace directory")
	timeout := flag.Duration("timeout", 2*time.Minute, "complete path timeout")
	flag.Parse()
	if *model == "" || *output == "" || *traceDir == "" || *timeout <= 0 {
		fatal("--model, --output, --trace-dir, and a positive --timeout are required")
	}

	started := time.Now().UTC()
	id, err := runid.New(started)
	if err != nil {
		fatal(err.Error())
	}
	client := newTelemetryCompleter(benchmark.Client{BaseURL: *baseURL})
	interpreter, err := localagent.NewInterpreter(client, *model)
	if err != nil {
		fatal(err.Error())
	}
	request, err := interpreter.Interpret(context.Background(), requestparser.Input{
		Text: "What does Microsoft sell and how does its cloud revenue mechanism work?",
		AsOf: started, RunID: id, RequestID: "request-" + id,
	})
	if err != nil {
		fatal(err.Error())
	}
	adapters, err := localagent.New(client, *model, frozenMaterialProvider{})
	if err != nil {
		fatal(err.Error())
	}
	runtime, err := orchestrator.New(orchestrator.Dependencies{
		Specialist: adapters, Reviewer: adapters, Synthesizer: adapters,
		TraceStore: orchestrator.FileTraceStore{Directory: *traceDir},
	})
	if err != nil {
		fatal(err.Error())
	}
	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()
	result := runtime.Run(ctx, request)
	resultReport := report{
		SchemaVersion: "signalforge/local-orchestration-evaluation/v1", ModelID: *model,
		StartedAt: started, CompletedAt: time.Now().UTC(), Request: request, Result: result, Calls: client.snapshot(),
	}
	if err := writeReport(*output, resultReport); err != nil {
		fatal(err.Error())
	}
	if result.Failure != nil || result.Answer == nil {
		fatal("local orchestration path did not produce an approved answer")
	}
}

type frozenMaterialProvider struct{}

func (frozenMaterialProvider) Load(_ context.Context, request contracts.ContextRequest) (localagent.Material, error) {
	statements := map[string]string{
		roles.BusinessStrategy:      "Microsoft sells productivity software, cloud infrastructure, and enterprise services; Azure revenue is generated through consumption and subscription arrangements.",
		roles.AccountingReporting:   "The supplied filing distinguishes cloud service revenue from software license revenue.",
		roles.FinancialQuality:      "No calculation receipt is supplied for this business-model explanation.",
		roles.EconomicsTransmission: "No economic scenario is required for this business-model explanation.",
		roles.Valuation:             "No valuation request or calculation receipt is present.",
		roles.MarketBehavior:        "No market-behavior measurement is required for this request.",
	}
	statement, ok := statements[request.SpecialistRole]
	if !ok {
		return localagent.Material{}, fmt.Errorf("no frozen material for role %q", request.SpecialistRole)
	}
	evidenceID := "evidence-" + request.StepID
	digest := sha256.Sum256([]byte(statement))
	return localagent.Material{Evidence: contracts.EvidenceBundle{
		SchemaVersion: contracts.SchemaVersionV1, BundleID: "bundle-" + request.StepID,
		RunID: request.RunID, StepID: request.StepID, AsOf: request.Scope.AsOf,
		Items: []contracts.EvidenceItem{{
			EvidenceRef: contracts.EvidenceRef{
				EvidenceID: evidenceID, SourceType: "frozen_local_fixture", Locator: request.StepID,
				ContentSHA: hex.EncodeToString(digest[:]), AsOf: request.Scope.AsOf,
			},
			State: contracts.EvidenceAvailable, Statement: statement,
		}},
	}}, nil
}

type telemetryCompleter struct {
	next         benchmark.Client
	roleByPrompt map[string]string
	mu           sync.Mutex
	calls        []callObservation
}

func newTelemetryCompleter(next benchmark.Client) *telemetryCompleter {
	roleByPrompt := map[string]string{}
	for _, prompt := range localagent.DefaultPromptRegistry().List() {
		roleByPrompt[prompt.System] = prompt.RoleID
	}
	return &telemetryCompleter{next: next, roleByPrompt: roleByPrompt}
}

func (client *telemetryCompleter) Complete(ctx context.Context, request benchmark.Request) (benchmark.Completion, error) {
	started := time.Now()
	completion, err := client.next.Complete(ctx, request)
	roleID := "unknown"
	if len(request.Messages) > 0 {
		if matched, ok := client.roleByPrompt[request.Messages[0].Content]; ok {
			roleID = matched
		}
	}
	observation := callObservation{
		RoleID: roleID, PromptTokens: completion.Usage.PromptTokens,
		CompletionTokens: completion.Usage.CompletionTokens,
		DurationMS:       float64(time.Since(started).Microseconds()) / 1000,
		FinishReason:     completion.FinishReason,
	}
	if err != nil {
		observation.Error = err.Error()
	}
	client.mu.Lock()
	client.calls = append(client.calls, observation)
	client.mu.Unlock()
	return completion, err
}

func (client *telemetryCompleter) snapshot() []callObservation {
	client.mu.Lock()
	defer client.mu.Unlock()
	return append([]callObservation(nil), client.calls...)
}

func writeReport(path string, value report) error {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, append(encoded, '\n'), 0o644)
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(1)
}
