package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/runid"
)

type observation struct {
	Row          contracts.BenchmarkRow `json:"row"`
	Answer       string                 `json:"answer,omitempty"`
	ToolNames    []string               `json:"tool_names,omitempty"`
	ToolCalls    []benchmark.ToolCall   `json:"tool_calls,omitempty"`
	FinishReason string                 `json:"finish_reason,omitempty"`
	Error        string                 `json:"error,omitempty"`
}

type report struct {
	SchemaVersion string        `json:"schema_version"`
	RunID         string        `json:"run_id"`
	BenchmarkID   string        `json:"benchmark_id"`
	ModelID       string        `json:"model_id"`
	CasesSHA256   string        `json:"cases_sha256"`
	StartedAt     time.Time     `json:"started_at"`
	CompletedAt   time.Time     `json:"completed_at"`
	Repetitions   int           `json:"repetitions"`
	WarmupRuns    int           `json:"warmup_repetitions"`
	Concurrency   int           `json:"concurrency"`
	Observations  []observation `json:"observations"`
}

type benchmarkJob struct {
	index      int
	item       benchmark.Case
	repetition int
}

func main() {
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "OpenAI-compatible API base URL")
	model := flag.String("model", "", "served model identifier")
	casesPath := flag.String("cases", "fixtures/model-baseline-cases.json", "benchmark suite path")
	output := flag.String("output", "", "JSON report path")
	repetitions := flag.Int("repetitions", 1, "number of measured repetitions")
	warmupRuns := flag.Int("warmup-repetitions", 0, "unmeasured warmup repetitions")
	concurrency := flag.Int("concurrency", 1, "maximum concurrent benchmark requests")
	timeout := flag.Duration("request-timeout", 5*time.Minute, "timeout per request")
	enableThinking := flag.Bool("enable-thinking", false, "enable model-specific reasoning mode")
	flag.Parse()
	if *model == "" || *output == "" || *repetitions < 1 || *warmupRuns < 0 || *concurrency < 1 {
		fatal("--model, --output, positive --repetitions/--concurrency, and non-negative --warmup-repetitions are required")
	}

	suite, err := benchmark.LoadSuite(*casesPath)
	if err != nil {
		fatal(err.Error())
	}
	payload, err := os.ReadFile(*casesPath)
	if err != nil {
		fatal(err.Error())
	}
	digest := sha256.Sum256(payload)
	id, err := runid.New(time.Now())
	if err != nil {
		fatal(err.Error())
	}
	result := report{
		SchemaVersion: "signalforge/model-benchmark-report/v1",
		RunID:         id,
		BenchmarkID:   suite.BenchmarkID,
		ModelID:       *model,
		CasesSHA256:   hex.EncodeToString(digest[:]),
		StartedAt:     time.Now().UTC(),
		Repetitions:   *repetitions,
		WarmupRuns:    *warmupRuns,
		Concurrency:   *concurrency,
	}
	client := benchmark.Client{BaseURL: *baseURL}
	for range *warmupRuns {
		_ = runCases(client, suite.BenchmarkID, id, *model, suite.Cases, 1, *timeout,
			*casesPath, *enableThinking, *concurrency)
	}
	result.StartedAt = time.Now().UTC()
	result.Observations = runCases(client, suite.BenchmarkID, id, *model, suite.Cases,
		*repetitions, *timeout, *casesPath, *enableThinking, *concurrency)
	result.CompletedAt = time.Now().UTC()
	encoded, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fatal(err.Error())
	}
	if err := os.MkdirAll(parentDir(*output), 0o755); err != nil {
		fatal(err.Error())
	}
	if err := os.WriteFile(*output, append(encoded, '\n'), 0o644); err != nil {
		fatal(err.Error())
	}
}

func runCases(client benchmark.Client, benchmarkID, id, model string, cases []benchmark.Case,
	repetitions int, timeout time.Duration, artifact string, enableThinking bool, concurrency int) []observation {
	jobs := make(chan benchmarkJob)
	observations := make([]observation, len(cases)*repetitions)
	workers := min(concurrency, len(observations))
	var wait sync.WaitGroup
	wait.Add(workers)
	for range workers {
		go func() {
			defer wait.Done()
			for job := range jobs {
				observations[job.index] = runCase(client, benchmarkID, id, model, job.item,
					job.repetition, timeout, artifact, enableThinking)
			}
		}()
	}
	for repetition := 0; repetition < repetitions; repetition++ {
		for caseIndex, item := range cases {
			jobs <- benchmarkJob{index: repetition*len(cases) + caseIndex, item: item, repetition: repetition}
		}
	}
	close(jobs)
	wait.Wait()
	return observations
}

func runCase(client benchmark.Client, benchmarkID, id, model string, item benchmark.Case,
	repetition int, timeout time.Duration, artifact string, enableThinking bool) observation {
	started := time.Now().UTC()
	caseID := fmt.Sprintf("%s-r%02d", item.CaseID, repetition+1)
	row := contracts.BenchmarkRow{
		SchemaVersion: contracts.SchemaVersionV1,
		RunID:         id,
		BenchmarkID:   benchmarkID,
		CaseID:        caseID,
		WorkloadClass: item.WorkloadClass,
		ModelID:       model,
		StartedAt:     started,
		Quality:       map[string]float64{},
		Runtime:       map[string]float64{},
		ArtifactRefs:  []string{artifact},
	}
	request := benchmark.Request{
		Model: model, Messages: item.Messages, MaxTokens: item.MaxTokens,
		Temperature: item.Temperature, Tools: item.Tools, ResponseFormat: item.ResponseFormat,
		ChatTemplateKwargs: map[string]any{"enable_thinking": enableThinking},
	}
	if item.RequiredTool != "" {
		request.ToolChoice = map[string]any{"type": "function", "function": map[string]string{"name": item.RequiredTool}}
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	completion, err := client.Complete(ctx, request)
	if err != nil {
		row.DurationMS = float64(time.Since(started).Microseconds()) / 1000
		return observation{Row: row, Error: err.Error()}
	}
	row.DurationMS = float64(completion.Duration.Microseconds()) / 1000
	row.Runtime = runtimeMetrics(completion)
	row.Quality, row.Success = qualityMetrics(item, completion)
	return observation{
		Row: row, Answer: completion.Answer, ToolNames: completion.ToolNames, ToolCalls: completion.ToolCalls,
		FinishReason: completion.FinishReason,
	}
}

func runtimeMetrics(completion benchmark.Completion) map[string]float64 {
	metrics := map[string]float64{
		"ttft_ms":                float64(completion.TTFT.Microseconds()) / 1000,
		"inter_token_latency_ms": float64(completion.InterTokenLatency().Microseconds()) / 1000,
		"prompt_tokens":          float64(completion.Usage.PromptTokens),
		"completion_tokens":      float64(completion.Usage.CompletionTokens),
		"stream_content_chunks":  float64(len(completion.ChunkTimes)),
	}
	decode := completion.Duration - completion.TTFT
	if decode > 0 && completion.Usage.CompletionTokens > 0 {
		metrics["decode_tokens_per_second"] = float64(completion.Usage.CompletionTokens) / decode.Seconds()
	}
	return metrics
}

func qualityMetrics(item benchmark.Case, completion benchmark.Completion) (map[string]float64, bool) {
	lower := strings.ToLower(completion.Answer)
	requiredFound := 0
	for _, term := range item.RequiredTerms {
		if strings.Contains(lower, strings.ToLower(term)) {
			requiredFound++
		}
	}
	recall := 1.0
	if len(item.RequiredTerms) > 0 {
		recall = float64(requiredFound) / float64(len(item.RequiredTerms))
	}
	forbiddenClear := 1.0
	for _, term := range item.ForbiddenTerms {
		if strings.Contains(lower, strings.ToLower(term)) {
			forbiddenClear = 0
		}
	}
	toolValid := 1.0
	if item.RequiredTool != "" && !slices.Contains(completion.ToolNames, item.RequiredTool) {
		toolValid = 0
	}
	argumentsValid := 1.0
	if len(item.RequiredToolArguments) > 0 && !hasToolArguments(completion.ToolCalls, item.RequiredTool, item.RequiredToolArguments) {
		argumentsValid = 0
	}
	jsonValid := 1.0
	if item.RequireJSON && !json.Valid([]byte(completion.Answer)) {
		jsonValid = 0
	}
	nonempty := 0.0
	if strings.TrimSpace(completion.Answer) != "" || len(completion.ToolNames) > 0 {
		nonempty = 1
	}
	metrics := map[string]float64{
		"required_term_recall":  recall,
		"forbidden_terms_clear": forbiddenClear,
		"required_tool_valid":   toolValid,
		"tool_arguments_valid":  argumentsValid,
		"json_valid":            jsonValid,
		"nonempty":              nonempty,
	}
	return metrics, recall == 1 && forbiddenClear == 1 && toolValid == 1 && argumentsValid == 1 && jsonValid == 1 && nonempty == 1
}

func hasToolArguments(calls []benchmark.ToolCall, name string, expected map[string]any) bool {
	for _, call := range calls {
		if call.Name != name {
			continue
		}
		var actual map[string]any
		if json.Unmarshal([]byte(call.Arguments), &actual) != nil {
			continue
		}
		actualJSON, actualErr := json.Marshal(actual)
		expectedJSON, expectedErr := json.Marshal(expected)
		if actualErr == nil && expectedErr == nil && string(actualJSON) == string(expectedJSON) {
			return true
		}
	}
	return false
}

func parentDir(path string) string {
	index := strings.LastIndex(path, string(os.PathSeparator))
	if index < 0 {
		return "."
	}
	return path[:index]
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(1)
}
