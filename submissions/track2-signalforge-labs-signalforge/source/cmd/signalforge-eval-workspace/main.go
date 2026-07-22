package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/workspace"
)

const evaluationSchemaV1 = "signalforge/workspace-evaluation/v1"

type evaluation struct {
	SchemaVersion string    `json:"schema_version"`
	MeasuredAt    time.Time `json:"measured_at"`
	Mode          string    `json:"mode"`
	LocalOnly     bool      `json:"local_only"`
	Frontend      struct {
		IndexStatus          int     `json:"index_status"`
		IndexBytes           int     `json:"index_bytes"`
		ContentSecurityReady bool    `json:"content_security_ready"`
		InitialCaseMS        float64 `json:"initial_case_ms"`
	} `json:"frontend"`
	Journey struct {
		StartStatus           int     `json:"start_status"`
		TimeToFirstProgress   float64 `json:"time_to_first_progress_ms"`
		TimeToCompletedCase   float64 `json:"time_to_completed_case_ms"`
		StreamedEvents        int     `json:"streamed_events"`
		Sections              int     `json:"sections"`
		EvidenceItems         int     `json:"evidence_items"`
		CalculationReceipts   int     `json:"calculation_receipts"`
		PrivateFieldsExcluded bool    `json:"private_fields_excluded"`
	} `json:"journey"`
}

func main() {
	fixturePath := flag.String("fixture", "fixtures/workspace/golden-case.json", "safe public workspace fixture")
	staticDir := flag.String("static-dir", "web/dist", "built frontend directory")
	output := flag.String("output", "", "optional JSON output path")
	eventDelay := flag.Duration("event-delay", 5*time.Millisecond, "fixture replay delay")
	flag.Parse()

	result, err := evaluate(*fixturePath, *staticDir, *eventDelay)
	if err != nil {
		fatal(err)
	}
	payload, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fatal(err)
	}
	payload = append(payload, '\n')
	if *output == "" {
		fmt.Print(string(payload))
		return
	}
	if err := os.WriteFile(*output, payload, 0o640); err != nil {
		fatal(err)
	}
}

func evaluate(fixturePath, staticDir string, eventDelay time.Duration) (evaluation, error) {
	workspaceServer, err := workspace.NewServer(workspace.ServerConfig{
		Mode: workspace.ModeFixture, FixturePath: fixturePath, StaticDir: staticDir, EventDelay: eventDelay,
	})
	if err != nil {
		return evaluation{}, err
	}
	server := httptest.NewServer(workspaceServer.Handler())
	defer server.Close()
	result := evaluation{SchemaVersion: evaluationSchemaV1, MeasuredAt: time.Now().UTC(), Mode: workspace.ModeFixture, LocalOnly: true}

	indexResponse, err := http.Get(server.URL + "/")
	if err != nil {
		return result, err
	}
	indexPayload, err := io.ReadAll(indexResponse.Body)
	indexResponse.Body.Close()
	if err != nil {
		return result, err
	}
	result.Frontend.IndexStatus = indexResponse.StatusCode
	result.Frontend.IndexBytes = len(indexPayload)
	result.Frontend.ContentSecurityReady = strings.Contains(indexResponse.Header.Get("Content-Security-Policy"), "default-src 'self'")

	initialStarted := time.Now()
	caseResponse, err := http.Get(server.URL + "/api/v1/cases/golden")
	if err != nil {
		return result, err
	}
	var projection workspace.Projection
	if err := json.NewDecoder(caseResponse.Body).Decode(&projection); err != nil {
		caseResponse.Body.Close()
		return result, err
	}
	caseResponse.Body.Close()
	result.Frontend.InitialCaseMS = elapsedMS(initialStarted)

	runStarted := time.Now()
	runResponse, err := http.Post(server.URL+"/api/v1/runs", "application/json", bytes.NewBufferString(`{"question":"Compare Microsoft and NVIDIA.","scenario":{"rates":"higher_for_longer","ai_spending":"slower"}}`))
	if err != nil {
		return result, err
	}
	result.Journey.StartStatus = runResponse.StatusCode
	var run workspace.RunView
	if err := json.NewDecoder(runResponse.Body).Decode(&run); err != nil {
		runResponse.Body.Close()
		return result, err
	}
	runResponse.Body.Close()

	eventsResponse, err := http.Get(server.URL + "/api/v1/runs/" + run.RunID + "/events")
	if err != nil {
		return result, err
	}
	scanner := bufio.NewScanner(eventsResponse.Body)
	firstSeen := false
	privateFieldsExcluded := true
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		if !firstSeen {
			result.Journey.TimeToFirstProgress = elapsedMS(runStarted)
			firstSeen = true
		}
		result.Journey.StreamedEvents++
		lower := strings.ToLower(line)
		if strings.Contains(lower, "prompt_body") || strings.Contains(lower, "response_body") || strings.Contains(lower, "chain_of_thought") || strings.Contains(lower, "token") {
			privateFieldsExcluded = false
		}
	}
	eventsResponse.Body.Close()
	if err := scanner.Err(); err != nil {
		return result, err
	}
	result.Journey.TimeToCompletedCase = elapsedMS(runStarted)
	completedResponse, err := http.Get(server.URL + "/api/v1/runs/" + run.RunID)
	if err != nil {
		return result, err
	}
	if err := json.NewDecoder(completedResponse.Body).Decode(&run); err != nil {
		completedResponse.Body.Close()
		return result, err
	}
	completedResponse.Body.Close()
	if run.Status != "completed" || run.Result == nil {
		return result, fmt.Errorf("fixture run ended in %s", run.Status)
	}
	result.Journey.Sections = len(run.Result.Sections)
	result.Journey.EvidenceItems = len(run.Result.Evidence)
	result.Journey.CalculationReceipts = len(run.Result.Calculations)
	result.Journey.PrivateFieldsExcluded = privateFieldsExcluded
	return result, nil
}

func elapsedMS(start time.Time) float64 {
	return float64(time.Since(start).Microseconds()) / 1000
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
