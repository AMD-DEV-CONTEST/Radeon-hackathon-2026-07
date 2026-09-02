package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/executionplan"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/modelapi"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
)

func main() {
	snapshotPath := flag.String("snapshot", "fixtures/golden/financial-snapshot.json", "frozen point-in-time financial snapshot")
	retrievalPath := flag.String("retrieval", "fixtures/retrieval/golden-eval.json", "frozen authoritative qualitative evidence")
	traceDir := flag.String("trace-dir", ".signalforge/traces", "private trace output directory")
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "loopback-local OpenAI-compatible endpoint")
	model := flag.String("model", "signalforge-gemma4-26b-q4", "local model identifier")
	codeCommit := flag.String("code-commit", "working-tree", "code revision recorded in calculation receipts")
	question := flag.String("question", golden.DefaultQuestion, "investor research question")
	runID := flag.String("run-id", "golden-run-20260721", "safe run identifier")
	requestID := flag.String("request-id", "golden-request-20260721", "safe request identifier")
	priceInputsPath := flag.String("price-inputs", "", "optional frozen point-in-time price-set JSON")
	msftPrice := flag.String("msft-price", "", "runtime MSFT market price in USD per share")
	nvdaPrice := flag.String("nvda-price", "", "runtime NVDA market price in USD per share")
	priceAsOfRaw := flag.String("price-as-of", "", "runtime market-price timestamp in RFC3339")
	priceSource := flag.String("price-source", "runtime://user-supplied", "source locator for runtime market prices")
	format := flag.String("format", "json", "output format: json or markdown")
	outputPath := flag.String("output", "", "optional output file; stdout when empty")
	safeReplayPath := flag.String("safe-replay-output", "", "optional privacy-safe decision replay JSON output")
	executionPlanPath := flag.String(
		"execution-plan-output", "",
		"optional privacy-safe execution-plan JSON output; enables the observational dashboard projection",
	)
	runtimeProfileID := flag.String("runtime-profile-id", "", "attested local runtime profile identifier")
	gpuArchitecture := flag.String("gpu-architecture", "", "attested GPU architecture, for example gfx1100")
	rocmVersion := flag.String("rocm-version", "", "attested ROCm version")
	inferenceRuntime := flag.String("inference-runtime", "", "attested local inference runtime")
	runtimeRevision := flag.String("runtime-revision", "", "attested inference runtime revision")
	quantization := flag.String("quantization", "", "attested model quantization")
	runtimeModelID := flag.String("runtime-model-id", "", "attested source model identifier; defaults to --model")
	modelRevision := flag.String("model-revision", "", "attested source model revision")
	runtimeEvidenceSHA := flag.String("runtime-evidence-sha", "", "SHA-256 of the runtime evidence artifact")
	timeout := flag.Duration("timeout", 2*time.Minute, "complete local orchestration timeout")
	contextConcurrency := flag.Int("context-concurrency", 2, "physical concurrent local specialist calls, from 1 to 4")
	flag.Parse()

	specialist, err := modelapi.LoadFromEnv()
	if err != nil {
		fatal(err)
	}
	prices, err := prices(*priceInputsPath, *msftPrice, *nvdaPrice, *priceAsOfRaw, *priceSource)
	if err != nil {
		fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()
	var executionSink *executionPlanSink
	if strings.TrimSpace(*executionPlanPath) != "" {
		executionSink = &executionPlanSink{}
	}
	report, err := golden.Run(ctx, golden.RunConfig{
		SnapshotPath: *snapshotPath, RetrievalPath: *retrievalPath, TraceDir: *traceDir,
		BaseURL: *baseURL, Model: *model, CodeCommit: *codeCommit, Question: *question,
		RunID: *runID, RequestID: *requestID, Timeout: *timeout, Prices: prices,
		ContextConcurrency: *contextConcurrency,
		SpecialistProvider: specialist.Provider, SpecialistBaseURL: specialist.BaseURL,
		SpecialistModel: specialist.TextModel, SpecialistAPIKey: specialist.APIKey,
		SpecialistHTTPClient: specialistHTTPClient(specialist),
		EventSink:            executionSink,
	})
	if err != nil {
		fatal(err)
	}
	if executionSink != nil {
		projection, projectionErr := executionSink.complete(time.Now().UTC())
		if projectionErr != nil {
			fatal(projectionErr)
		}
		projectionPayload, projectionErr := json.MarshalIndent(projection, "", "  ")
		if projectionErr != nil {
			fatal(projectionErr)
		}
		if projectionErr := writeFile(*executionPlanPath, append(projectionPayload, '\n')); projectionErr != nil {
			fatal(projectionErr)
		}
	}
	if *safeReplayPath != "" {
		profile, profileErr := runtimeProfile(runtimeProfileInput{
			ProfileID: *runtimeProfileID, GPUArchitecture: *gpuArchitecture,
			ROCmVersion: *rocmVersion, Runtime: *inferenceRuntime,
			RuntimeRevision: *runtimeRevision, Quantization: *quantization,
			ModelID: *runtimeModelID, ModelRevision: *modelRevision,
			RuntimeEvidenceSHA: *runtimeEvidenceSHA,
		}, *model)
		if profileErr != nil {
			fatal(profileErr)
		}
		replay, replayErr := golden.BuildSafeDecisionReplay(report, profile)
		if replayErr != nil {
			fatal(replayErr)
		}
		replayPayload, replayErr := json.MarshalIndent(replay, "", "  ")
		if replayErr != nil {
			fatal(replayErr)
		}
		if replayErr := writeFile(*safeReplayPath, append(replayPayload, '\n')); replayErr != nil {
			fatal(replayErr)
		}
	}
	var payload []byte
	switch strings.ToLower(strings.TrimSpace(*format)) {
	case "json":
		payload, err = json.MarshalIndent(report, "", "  ")
		payload = append(payload, '\n')
	case "markdown":
		payload = []byte(golden.RenderMarkdown(report))
	default:
		fatal(fmt.Errorf("unsupported --format %q", *format))
	}
	if err != nil {
		fatal(err)
	}
	if *outputPath == "" {
		fmt.Print(string(payload))
	} else {
		if err := writeFile(*outputPath, payload); err != nil {
			fatal(err)
		}
	}
	if report.Result.Failure != nil {
		os.Exit(2)
	}
}

type executionPlanSink struct {
	mu         sync.Mutex
	projection *executionplan.Projection
	err        error
}

func (sink *executionPlanSink) AcceptPlan(plan contracts.ResearchPlan, at time.Time) {
	sink.mu.Lock()
	defer sink.mu.Unlock()
	if sink.err != nil {
		return
	}
	projection, err := executionplan.FromPlan(plan, at)
	if err != nil {
		sink.err = err
		return
	}
	sink.projection = &projection
}

func (sink *executionPlanSink) Emit(event orchestrator.Event) {
	sink.mu.Lock()
	defer sink.mu.Unlock()
	if sink.err != nil {
		return
	}
	if sink.projection == nil {
		sink.err = fmt.Errorf("execution event arrived before the accepted plan")
		return
	}
	sink.err = executionplan.Apply(sink.projection, executionplan.Event{
		Sequence: event.Sequence, StepID: event.StepID, Type: event.Type,
		Status: event.Status, At: event.At, Attributes: event.Attributes,
	})
}

func (sink *executionPlanSink) complete(at time.Time) (executionplan.Projection, error) {
	sink.mu.Lock()
	defer sink.mu.Unlock()
	if sink.err != nil {
		return executionplan.Projection{}, sink.err
	}
	if sink.projection == nil {
		return executionplan.Projection{}, fmt.Errorf("execution projection was not created")
	}
	if err := executionplan.Apply(sink.projection, executionplan.Event{
		Sequence: sink.projection.LastSequence + 1,
		Type:     "workspace", Status: "completed", At: at,
	}); err != nil {
		return executionplan.Projection{}, err
	}
	payload, err := json.Marshal(sink.projection)
	if err != nil {
		return executionplan.Projection{}, err
	}
	var projection executionplan.Projection
	if err := json.Unmarshal(payload, &projection); err != nil {
		return executionplan.Projection{}, err
	}
	return projection, executionplan.Validate(projection)
}

func specialistHTTPClient(config modelapi.Config) *http.Client {
	if !config.Enabled {
		return nil
	}
	return &http.Client{Timeout: config.Timeout}
}

type runtimeProfileInput struct {
	ProfileID          string
	GPUArchitecture    string
	ROCmVersion        string
	Runtime            string
	RuntimeRevision    string
	Quantization       string
	ModelID            string
	ModelRevision      string
	RuntimeEvidenceSHA string
}

func runtimeProfile(input runtimeProfileInput, defaultModelID string) (golden.RuntimeProfile, error) {
	if strings.TrimSpace(input.ModelID) == "" {
		input.ModelID = defaultModelID
	}
	values := []string{
		input.ProfileID, input.GPUArchitecture, input.ROCmVersion, input.Runtime,
		input.RuntimeRevision, input.Quantization, input.ModelRevision, input.RuntimeEvidenceSHA,
	}
	provided := 0
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			provided++
		}
	}
	if provided != 0 && provided != len(values) {
		return golden.RuntimeProfile{}, fmt.Errorf("Radeon runtime attestation flags must be supplied together")
	}
	return golden.RuntimeProfile{
		Attested: provided == len(values), ProfileID: input.ProfileID,
		GPUArchitecture: input.GPUArchitecture, ROCmVersion: input.ROCmVersion,
		Runtime: input.Runtime, RuntimeRevision: input.RuntimeRevision,
		Quantization: input.Quantization, ModelID: input.ModelID,
		ModelRevision: input.ModelRevision, RuntimeEvidenceSHA: input.RuntimeEvidenceSHA,
	}, nil
}

func writeFile(path string, payload []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return err
	}
	return os.WriteFile(path, payload, 0o640)
}

func prices(priceInputsPath, msft, nvda, asOfRaw, source string) ([]golden.PriceInput, error) {
	if priceInputsPath != "" {
		if msft != "" || nvda != "" || asOfRaw != "" {
			return nil, fmt.Errorf("--price-inputs cannot be combined with individual price flags")
		}
		set, err := golden.LoadPriceSet(priceInputsPath)
		if err != nil {
			return nil, err
		}
		return set.Prices, nil
	}
	if (msft == "") != (nvda == "") {
		return nil, fmt.Errorf("--msft-price and --nvda-price must be supplied together")
	}
	if msft == "" {
		return nil, nil
	}
	if strings.TrimSpace(asOfRaw) == "" {
		return nil, fmt.Errorf("--price-as-of is required with runtime prices")
	}
	asOf, err := time.Parse(time.RFC3339, asOfRaw)
	if err != nil {
		return nil, fmt.Errorf("parse --price-as-of: %w", err)
	}
	return []golden.PriceInput{
		{Ticker: "MSFT", Value: msft, Currency: "USD", AsOf: asOf, Source: source},
		{Ticker: "NVDA", Value: nvda, Currency: "USD", AsOf: asOf, Source: source},
	}, nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
