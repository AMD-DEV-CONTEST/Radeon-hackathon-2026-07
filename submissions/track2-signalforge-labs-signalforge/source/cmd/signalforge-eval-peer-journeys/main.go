package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/modelapi"
	"github.com/rvbernucci/signalforge/internal/producteval"
	"github.com/rvbernucci/signalforge/internal/productscope"
	"github.com/rvbernucci/signalforge/internal/requestparser"
)

func main() {
	suitePath := flag.String("suite", "fixtures/productscope/technology20-peer-development.json", "peer journey suite")
	catalogPath := flag.String("catalog", "fixtures/productscope/technology20-catalog.json", "Technology 20 catalog")
	peerPath := flag.String("peers", "fixtures/productscope/technology20-peer-evaluation.json", "peer authority")
	financialDirectory := flag.String("financial-directory", "", "private company financial activation reports")
	outputDirectory := flag.String("output-directory", "", "private checkpoint and report directory")
	baseURL := flag.String("base-url", "http://127.0.0.1:8000/v1", "loopback local inference endpoint")
	model := flag.String("model", "signalforge-gemma4-26b-q4", "local model identifier")
	sourceCommit := flag.String("source-commit", "working-tree", "source revision under evaluation")
	timeout := flag.Duration("timeout-per-case", 4*time.Minute, "complete orchestration timeout per case")
	contextConcurrency := flag.Int("context-concurrency", 4, "local specialist concurrency")
	maxCases := flag.Int("max-cases", 0, "maximum cases to execute; zero means all")
	startIndex := flag.Int("start-index", 0, "zero-based first case index")
	caseID := flag.String("case-id", "", "optional exact journey ID")
	resume := flag.Bool("resume", true, "reuse completed private case reports")
	flag.Parse()

	if strings.TrimSpace(*financialDirectory) == "" || strings.TrimSpace(*outputDirectory) == "" {
		fatal(fmt.Errorf("--financial-directory and --output-directory are required"))
	}
	specialist, err := modelapi.LoadFromEnv()
	if err != nil {
		fatal(err)
	}
	var suite productscope.PeerJourneySuite
	readJSON(*suitePath, &suite)
	expectedCases := 40
	if suite.Split == "sealed_holdout" {
		expectedCases = 20
	}
	if err := productscope.ValidatePeerJourneySuite(suite, expectedCases); err != nil {
		fatal(err)
	}
	provider, err := producteval.LoadProvider(*catalogPath, *financialDirectory, *peerPath)
	if err != nil {
		fatal(err)
	}
	suiteSHA, err := fileSHA256(*suitePath)
	if err != nil {
		fatal(err)
	}
	selected := selectCases(suite.Cases, *startIndex, *maxCases, *caseID)
	if len(selected) == 0 {
		fatal(fmt.Errorf("case selection is empty"))
	}
	if err := os.MkdirAll(filepath.Join(*outputDirectory, "cases"), 0o750); err != nil {
		fatal(err)
	}
	catalog := loadCatalog(*catalogPath)
	peers := loadPeers(*peerPath)
	evaluation := producteval.PeerEvaluation{
		SchemaVersion: producteval.PeerEvaluationSchemaV1,
		UniverseID:    productscope.UniverseID, Split: suite.Split, SuiteSHA256: suiteSHA,
		SourceCommit: *sourceCommit, ModelID: *model, BaseURL: *baseURL,
		SpecialistProvider: specialist.Provider, SpecialistModel: specialist.TextModel,
		StartedAt: time.Now().UTC(), CasesSelected: len(selected),
		ClaimBoundary: "Private development execution measures typed peer authority and answer contracts. " +
			"Prompts, responses, reports, and sealed material must not enter the public repository or image.",
		ReleaseDisposition: "evaluation_only_not_promoted",
	}
	for index, item := range selected {
		casePath := filepath.Join(*outputDirectory, "cases", item.JourneyID+".json")
		var result producteval.PeerCaseResult
		if *resume && readOptionalJSON(casePath, &result) == nil && result.JourneyID == item.JourneyID {
			appendResult(&evaluation, result)
			writeCheckpoint(*outputDirectory, evaluation)
			fmt.Printf("[%d/%d] %s resumed contract=%t\n", index+1, len(selected), item.JourneyID, result.ContractPassed)
			continue
		}
		request, parseErr := requestparser.ParseDeterministic(requestparser.Input{
			Text: item.Question, AsOf: suite.AsOf,
			RunID:     fmt.Sprintf("sprint32-peer-%s-%03d", suite.Split, *startIndex+index),
			RequestID: fmt.Sprintf("sprint32-peer-request-%s-%03d", suite.Split, *startIndex+index),
		})
		if parseErr != nil {
			result = failedCase(item, "request_parse_failed")
		} else {
			request, parseErr = productscope.BindRequestAuthority(request, catalog, peers)
			if parseErr != nil {
				result = failedCase(item, "authority_binding_failed")
			} else {
				caseContext, cancel := context.WithTimeout(context.Background(), *timeout)
				report, runErr := golden.Run(caseContext, golden.RunConfig{
					TraceDir: filepath.Join(*outputDirectory, "traces", item.JourneyID),
					BaseURL:  *baseURL, Model: *model, CodeCommit: *sourceCommit,
					Question: item.Question, RunID: request.RunID, RequestID: request.RequestID,
					Timeout: *timeout, ContextConcurrency: *contextConcurrency,
					RequestOverride: &request, MaterialProvider: provider,
					SpecialistProvider: specialist.Provider, SpecialistBaseURL: specialist.BaseURL,
					SpecialistModel: specialist.TextModel, SpecialistAPIKey: specialist.APIKey,
					SpecialistHTTPClient: specialistHTTPClient(specialist),
				})
				cancel()
				if runErr != nil {
					result = failedCase(item, "runner_failed")
				} else {
					result = producteval.ScorePeerCase(item, report, true)
				}
			}
		}
		writeJSON(casePath, result)
		appendResult(&evaluation, result)
		writeCheckpoint(*outputDirectory, evaluation)
		fmt.Printf("[%d/%d] %s runtime=%t contract=%t calls=%d duration_ms=%.0f\n",
			index+1, len(selected), item.JourneyID, result.RuntimePassed,
			result.ContractPassed, result.ModelCalls, result.DurationMS,
		)
	}
	evaluation.CompletedAt = time.Now().UTC()
	writeJSON(filepath.Join(*outputDirectory, "evaluation.json"), evaluation)
	fmt.Printf("peer evaluation: %d/%d contracts passed; %d runtime failures\n",
		evaluation.ContractsPassed, evaluation.CasesCompleted, evaluation.RuntimeFailures,
	)
}

func specialistHTTPClient(config modelapi.Config) *http.Client {
	if !config.Enabled {
		return nil
	}
	return &http.Client{Timeout: config.Timeout}
}

func selectCases(values []productscope.PeerJourneyCase, start, maximum int, exactID string) []productscope.PeerJourneyCase {
	if exactID != "" {
		for _, item := range values {
			if item.JourneyID == exactID {
				return []productscope.PeerJourneyCase{item}
			}
		}
		return nil
	}
	if start < 0 || start >= len(values) {
		return nil
	}
	end := len(values)
	if maximum > 0 && start+maximum < end {
		end = start + maximum
	}
	return append([]productscope.PeerJourneyCase(nil), values[start:end]...)
}

func appendResult(evaluation *producteval.PeerEvaluation, result producteval.PeerCaseResult) {
	evaluation.Results = append(evaluation.Results, result)
	evaluation.CasesCompleted++
	evaluation.TotalModelCalls += result.ModelCalls
	evaluation.TotalPromptTokens += result.PromptTokens
	evaluation.TotalOutputTokens += result.CompletionTokens
	if result.ContractPassed {
		evaluation.ContractsPassed++
	}
	if !result.RuntimePassed {
		evaluation.RuntimeFailures++
	}
}

func failedCase(item productscope.PeerJourneyCase, code string) producteval.PeerCaseResult {
	return producteval.PeerCaseResult{
		JourneyID: item.JourneyID, LaneID: item.LaneID,
		CompanyIDs: append([]string(nil), item.CompanyIDs...), QuestionID: item.QuestionID,
		ExpectedMetricDispositions: copyMap(item.ExpectedMetrics),
		FailureCode:                code,
		ClaimBoundary:              "Execution failed before a semantic peer contract could be measured.",
		EvaluatedAt:                time.Now().UTC(),
	}
}

func copyMap(input map[string]string) map[string]string {
	result := make(map[string]string, len(input))
	for key, value := range input {
		result[key] = value
	}
	return result
}

func writeCheckpoint(directory string, evaluation producteval.PeerEvaluation) {
	evaluation.CompletedAt = time.Now().UTC()
	writeJSON(filepath.Join(directory, "evaluation.partial.json"), evaluation)
}

func loadCatalog(path string) productscope.PublicCatalog {
	var value productscope.PublicCatalog
	readJSON(path, &value)
	return value
}

func loadPeers(path string) productscope.PeerEvaluationSuite {
	var value productscope.PeerEvaluationSuite
	readJSON(path, &value)
	return value
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

func readOptionalJSON(path string, target any) error {
	payload, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(payload, target)
}

func writeJSON(path string, value any) {
	payload, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		fatal(err)
	}
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, append(payload, '\n'), 0o640); err != nil {
		fatal(err)
	}
	if err := os.Rename(temporary, path); err != nil {
		fatal(err)
	}
}

func fileSHA256(path string) (string, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:]), nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
