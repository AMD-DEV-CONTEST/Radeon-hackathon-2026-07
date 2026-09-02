package workspace

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/executionplan"
	"github.com/rvbernucci/signalforge/internal/intelligenceaudit"
	"github.com/rvbernucci/signalforge/internal/productscope"
	"github.com/rvbernucci/signalforge/internal/telemetry"
)

type fakeCaseStore struct {
	mu       sync.Mutex
	items    map[string]Projection
	failSave bool
	saves    int
}

func newFakeCaseStore() *fakeCaseStore {
	return &fakeCaseStore{items: map[string]Projection{}}
}

func (store *fakeCaseStore) Save(_ context.Context, projection Projection, _ string) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.saves++
	if store.failSave {
		return errors.New("private storage failure")
	}
	store.items[projection.CaseID] = cloneProjection(projection)
	return nil
}

func (store *fakeCaseStore) Get(_ context.Context, caseID string) (Projection, CaseSummary, error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	projection, ok := store.items[caseID]
	if !ok {
		return Projection{}, CaseSummary{}, ErrCaseNotFound
	}
	return cloneProjection(projection), fakeSummary(projection), nil
}

func (store *fakeCaseStore) List(_ context.Context, _ int) ([]CaseSummary, error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	items := make([]CaseSummary, 0, len(store.items))
	for _, projection := range store.items {
		items = append(items, fakeSummary(projection))
	}
	return items, nil
}

func (store *fakeCaseStore) Export(ctx context.Context, caseID string) (CaseExport, error) {
	projection, summary, err := store.Get(ctx, caseID)
	if err != nil {
		return CaseExport{}, err
	}
	return CaseExport{SchemaVersion: CaseExportSchemaV1, ExportedAt: time.Now().UTC(), Summary: summary, Case: projection}, nil
}

func (store *fakeCaseStore) Delete(_ context.Context, caseID string) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if _, ok := store.items[caseID]; !ok {
		return ErrCaseNotFound
	}
	delete(store.items, caseID)
	return nil
}

func fakeSummary(projection Projection) CaseSummary {
	return CaseSummary{
		CaseID: projection.CaseID, RunID: projection.RunID, Title: projection.Title,
		AsOf: projection.AsOf, Intent: projection.Intent, SavedAt: time.Now().UTC(),
		EvidenceItems: len(projection.Evidence), CalculationReceipts: len(projection.Calculations),
		ProjectionSHA: strings.Repeat("a", 64),
	}
}

func (store *fakeCaseStore) saveCount() int {
	store.mu.Lock()
	defer store.mu.Unlock()
	return store.saves
}

func TestFixtureServerExposesSafeConfigurationAndCase(t *testing.T) {
	server := newFixtureTestServer(t)
	handler := server.Handler()

	for _, testCase := range []struct {
		path string
		read func(*testing.T, []byte)
	}{
		{path: "/api/v1/health", read: func(t *testing.T, body []byte) {
			assertJSONField(t, body, "local_only", true)
		}},
		{path: "/api/v1/config", read: func(t *testing.T, body []byte) {
			assertJSONField(t, body, "follow_ups_live", false)
		}},
		{path: "/api/v1/catalog", read: func(t *testing.T, body []byte) {
			var catalog map[string]any
			if err := json.Unmarshal(body, &catalog); err != nil {
				t.Fatal(err)
			}
			if companies, ok := catalog["companies"].([]any); !ok || len(companies) != 20 {
				t.Fatalf("catalog companies = %#v", catalog["companies"])
			}
			if lanes, ok := catalog["peer_lanes"].([]any); !ok || len(lanes) != 5 {
				t.Fatalf("catalog peer lanes = %#v", catalog["peer_lanes"])
			}
		}},
		{path: "/api/v1/financials", read: func(t *testing.T, body []byte) {
			var financials productscope.PublicFinancialSummary
			if err := json.Unmarshal(body, &financials); err != nil {
				t.Fatal(err)
			}
			if len(financials.Companies) != 20 {
				t.Fatalf("financial companies = %d", len(financials.Companies))
			}
		}},
		{path: "/api/v1/peer-evaluations", read: func(t *testing.T, body []byte) {
			var peers productscope.PeerEvaluationSuite
			if err := json.Unmarshal(body, &peers); err != nil {
				t.Fatal(err)
			}
			if len(peers.Lanes) != 5 {
				t.Fatalf("peer lanes = %d", len(peers.Lanes))
			}
		}},
		{path: "/api/v1/cases/golden", read: func(t *testing.T, body []byte) {
			assertJSONField(t, body, "schema_version", SchemaVersionV1)
		}},
	} {
		t.Run(testCase.path, func(t *testing.T) {
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, testCase.path, nil))
			if response.Code != http.StatusOK {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
			if response.Header().Get("Content-Security-Policy") == "" {
				t.Fatal("missing Content-Security-Policy")
			}
			testCase.read(t, response.Body.Bytes())
		})
	}
}

func TestFixtureRunCompletesAndStreamsOnlySafeEvents(t *testing.T) {
	server := newFixtureTestServer(t)
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)

	run := postRun(t, httpServer.URL, `{"question":"Compare Microsoft and NVIDIA.","scenario":{"rates":"easing","ai_spending":"resilient"}}`)
	deadline := time.Now().Add(2 * time.Second)
	for run.Status == "running" && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
		run = getRun(t, httpServer.URL, run.RunID)
	}
	if run.Status != "completed" || run.Result == nil {
		t.Fatalf("run = %+v", run)
	}
	if run.Execution == nil || run.Execution.Status != "passed" || run.Execution.ProgressRatio != 1 ||
		run.Result.ExecutionPlan == nil || run.Result.ExecutionPlan.ProjectionSHA != run.Execution.ProjectionSHA {
		t.Fatalf("execution projection was not completed consistently: %+v", run.Execution)
	}
	if !strings.Contains(run.Result.Question, "easing interest rates") || !strings.Contains(run.Result.Question, "resilient AI infrastructure spending") {
		t.Fatalf("scenario was not applied to fixture question: %q", run.Result.Question)
	}
	if len(run.Result.Assumptions) != 2 || !strings.Contains(run.Result.Assumptions[0], "Easing") || !strings.Contains(run.Result.Assumptions[1], "Resilient") {
		t.Fatalf("scenario was not applied to fixture assumptions: %#v", run.Result.Assumptions)
	}

	response, err := http.Get(httpServer.URL + "/api/v1/runs/" + run.RunID + "/events")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("event status = %d", response.StatusCode)
	}
	scanner := bufio.NewScanner(response.Body)
	eventCount := 0
	toolEventCount := 0
	terminalSeen := false
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data: ") {
			eventCount++
			if strings.Contains(line, `"type":"tool"`) {
				toolEventCount++
			}
			if strings.Contains(line, `"type":"workspace"`) && strings.Contains(line, `"status":"completed"`) {
				terminalSeen = true
			}
			if strings.Contains(line, "prompt") || strings.Contains(line, "response_body") || strings.Contains(line, "token") {
				t.Fatalf("unsafe event field leaked: %s", line)
			}
		}
	}
	if err := scanner.Err(); err != nil {
		t.Fatal(err)
	}
	expectedEvents := len(run.Result.Events) + len(run.Result.Calculations) + 2
	if eventCount != expectedEvents || toolEventCount != len(run.Result.Calculations) {
		t.Fatalf("streamed events = %d (%d tools), expected %d (%d tools)",
			eventCount, toolEventCount, expectedEvents, len(run.Result.Calculations))
	}
	if !terminalSeen {
		t.Fatal("expected workspace completion event")
	}

	resumeRequest, err := http.NewRequest(http.MethodGet,
		httpServer.URL+"/api/v1/runs/"+run.RunID+"/events", nil)
	if err != nil {
		t.Fatal(err)
	}
	resumeRequest.Header.Set("Last-Event-ID", "5")
	resumed, err := http.DefaultClient.Do(resumeRequest)
	if err != nil {
		t.Fatal(err)
	}
	defer resumed.Body.Close()
	resumeScanner := bufio.NewScanner(resumed.Body)
	resumedEvents := 0
	for resumeScanner.Scan() {
		line := resumeScanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		var event StreamEvent
		if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &event); err != nil {
			t.Fatal(err)
		}
		if event.Sequence <= 5 {
			t.Fatalf("resumed stream replayed acknowledged event %d", event.Sequence)
		}
		resumedEvents++
	}
	if err := resumeScanner.Err(); err != nil {
		t.Fatal(err)
	}
	if resumedEvents != eventCount-5 {
		t.Fatalf("resumed events = %d, expected %d", resumedEvents, eventCount-5)
	}

	executionResponse := getRaw(t, httpServer.URL+"/api/v1/runs/"+run.RunID+"/execution")
	defer executionResponse.Body.Close()
	if executionResponse.StatusCode != http.StatusOK {
		t.Fatalf("execution status = %d, body = %s", executionResponse.StatusCode, readBody(t, executionResponse))
	}
	var execution map[string]any
	if err := json.NewDecoder(executionResponse.Body).Decode(&execution); err != nil {
		t.Fatal(err)
	}
	if execution["projection_sha256"] != run.Execution.ProjectionSHA || execution["progress_ratio"] != float64(1) {
		t.Fatalf("execution endpoint = %#v", execution)
	}
	payload, _ := json.Marshal(execution)
	for _, forbidden := range []string{"api_key", "password", "raw_prompt", "chain_of_thought", "response_body"} {
		if strings.Contains(strings.ToLower(string(payload)), forbidden) {
			t.Fatalf("execution projection leaked %q", forbidden)
		}
	}
}

func TestFixtureHydrationProjectsDeterministicReceipts(t *testing.T) {
	server := newFixtureTestServer(t)
	execution := server.fixture.ExecutionPlan
	if execution == nil {
		t.Fatal("fixture execution plan is missing")
	}
	var toolStep *executionplan.Step
	for index := range execution.Steps {
		if execution.Steps[index].StepID == "fixture-calculation" {
			toolStep = &execution.Steps[index]
			break
		}
	}
	if toolStep == nil || toolStep.ParentPhaseID != "tools" ||
		toolStep.Status != executionplan.StatusPassed ||
		len(toolStep.Checklist) != len(server.fixture.Calculations) {
		t.Fatalf("fixture deterministic step = %+v", toolStep)
	}
	toolsPhase := executionPhase(execution, "tools")
	if toolsPhase == nil || toolsPhase.Status != executionplan.StatusPassed ||
		len(toolsPhase.StepIDs) != 1 || toolsPhase.StepIDs[0] != toolStep.StepID ||
		!strings.Contains(toolsPhase.SafeSummary, "18 deterministic calculation records") {
		t.Fatalf("fixture tools phase = %+v", toolsPhase)
	}
	for _, check := range toolStep.Checklist {
		if check.Authority != "engine" || check.Status != executionplan.StatusPassed ||
			len(check.ReferenceIDs) == 0 {
			t.Fatalf("fixture tool check = %+v", check)
		}
	}
}

func TestFixtureCalculationEventsRejectUnverifiedSuccess(t *testing.T) {
	valid := CalculationCard{
		ReceiptID: "receipt-1", OperationID: "financial.free_cash_flow",
		EngineID: "financial-engine/v1", FormulaVersion: "fcf/v2",
		Status:           contracts.ReceiptSuccess,
		Outputs:          []contracts.ReceiptOutput{{OutputID: "free-cash-flow", Status: "available"}},
		InvariantResults: []contracts.InvariantResult{{InvariantID: "finite-output", Passed: true}},
		ReceiptSHA:       strings.Repeat("a", 64),
	}
	if events, err := fixtureCalculationEvents([]CalculationCard{valid}, time.Now()); err != nil || len(events) != 1 {
		t.Fatalf("valid fixture receipt = events %d, error %v", len(events), err)
	}

	failedInvariant := valid
	failedInvariant.InvariantResults = []contracts.InvariantResult{{InvariantID: "finite-output", Passed: false}}
	if _, err := fixtureCalculationEvents([]CalculationCard{failedInvariant}, time.Now()); err == nil {
		t.Fatal("expected failed invariant to reject a successful fixture receipt")
	}

	malformedHash := valid
	malformedHash.ReceiptSHA = "not-a-hash"
	if _, err := fixtureCalculationEvents([]CalculationCard{malformedHash}, time.Now()); err == nil {
		t.Fatal("expected malformed fixture receipt hash to be rejected")
	}
}

func executionPhase(plan *executionplan.Projection, phaseID string) *executionplan.Phase {
	for index := range plan.Phases {
		if plan.Phases[index].PhaseID == phaseID {
			return &plan.Phases[index]
		}
	}
	return nil
}

func TestFixtureServerRejectsInvalidInputsAndExplainsFollowUpDegradation(t *testing.T) {
	server := newFixtureTestServer(t)
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)

	unknown := postRaw(t, httpServer.URL+"/api/v1/runs", `{"question":"test","unexpected":true}`)
	if unknown.StatusCode != http.StatusBadRequest {
		t.Fatalf("unknown field status = %d", unknown.StatusCode)
	}
	unknown.Body.Close()

	invalidScenario := postRaw(t, httpServer.URL+"/api/v1/runs", `{"question":"test","scenario":{"rates":"magic","ai_spending":"slower"}}`)
	if invalidScenario.StatusCode != http.StatusBadRequest {
		t.Fatalf("invalid scenario status = %d", invalidScenario.StatusCode)
	}
	invalidScenario.Body.Close()

	oversized := postRaw(t, httpServer.URL+"/api/v1/runs", `{"question":"`+strings.Repeat("x", 17<<10)+`"}`)
	if oversized.StatusCode != http.StatusBadRequest {
		t.Fatalf("oversized body status = %d", oversized.StatusCode)
	}
	oversized.Body.Close()

	invalidUnicodeRequest, err := http.NewRequest(http.MethodPost, httpServer.URL+"/api/v1/runs", bytes.NewReader([]byte{'{', '"', 'q', 'u', 'e', 's', 't', 'i', 'o', 'n', '"', ':', '"', 0xff, '"', '}'}))
	if err != nil {
		t.Fatal(err)
	}
	invalidUnicodeRequest.Header.Set("Content-Type", "application/json")
	invalidUnicode, err := http.DefaultClient.Do(invalidUnicodeRequest)
	if err != nil {
		t.Fatal(err)
	}
	if invalidUnicode.StatusCode != http.StatusBadRequest {
		t.Fatalf("invalid UTF-8 status = %d", invalidUnicode.StatusCode)
	}
	invalidUnicode.Body.Close()

	run := postRun(t, httpServer.URL, `{"question":"test","scenario":{}}`)
	deadline := time.Now().Add(2 * time.Second)
	for run.Status == "running" && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
		run = getRun(t, httpServer.URL, run.RunID)
	}
	followUp := postRaw(t, httpServer.URL+"/api/v1/runs/"+run.RunID+"/follow-ups", `{"question":"What changes the thesis?"}`)
	defer followUp.Body.Close()
	if followUp.StatusCode != http.StatusConflict {
		body, _ := io.ReadAll(followUp.Body)
		t.Fatalf("follow-up status = %d, body = %s", followUp.StatusCode, body)
	}
	var problem map[string]map[string]any
	if err := json.NewDecoder(followUp.Body).Decode(&problem); err != nil {
		t.Fatal(err)
	}
	if problem["error"]["code"] != "follow_up_requires_completed_live_case" {
		t.Fatalf("problem = %#v", problem)
	}
}

func TestPublicModelRouteKeepsOnlyBoundedExecutionClass(t *testing.T) {
	cases := map[string]string{
		"local-rocm":           "local_rocm",
		"loopback-llama":       "local_rocm",
		"radeon-specialists":   "radeon_api",
		"third-party-provider": "authorized_model_api",
	}
	for providerID, expected := range cases {
		if actual := publicModelRoute(providerID); actual != expected {
			t.Fatalf("provider %q route = %q, expected %q", providerID, actual, expected)
		}
	}
}

func TestModelObserverClassifiesObservedAttemptsWithoutRetainingPrompts(t *testing.T) {
	server := newFixtureTestServer(t)
	record, err := server.newRun("", false)
	if err != nil {
		t.Fatal(err)
	}
	observer := runModelObserver{server: server, record: record}
	request := benchmark.Request{
		Messages:  []benchmark.Message{{Role: "system", Content: "private primary prompt"}},
		MaxTokens: 100,
	}
	observer.ObserveModelCall(context.Background(), "request-interpreter/v1", "local-rocm",
		request, benchmark.Completion{}, nil)
	request.MaxTokens = 200
	observer.ObserveModelCall(context.Background(), "request-interpreter/v1", "local-rocm",
		request, benchmark.Completion{}, nil)
	fallbackErr := errors.New("fallback temporarily unavailable")
	observer.ObserveModelCall(context.Background(), "request-interpreter/v1", "radeon-specialists",
		request, benchmark.Completion{}, fallbackErr)
	observer.ObserveModelCall(context.Background(), "request-interpreter/v1", "radeon-specialists",
		request, benchmark.Completion{}, nil)

	server.mu.RLock()
	events := append([]StreamEvent(nil), record.events...)
	projection := cloneExecutionPlan(*record.execution)
	server.mu.RUnlock()
	if len(events) != 4 {
		t.Fatalf("model events = %d, expected 4", len(events))
	}
	expectedKinds := []string{"primary", "bounded_repair", "fallback", "retry"}
	expectedStatuses := []string{"completed", "completed", "failed", "completed"}
	for index, event := range events {
		if event.Type != "model" || event.Status != expectedStatuses[index] ||
			event.Attributes["call_kind"] != expectedKinds[index] ||
			event.Attributes["attempt"] != strconv.Itoa(index+1) {
			t.Fatalf("event %d = %+v", index, event)
		}
		payload, _ := json.Marshal(event)
		if strings.Contains(string(payload), "private primary prompt") {
			t.Fatalf("model event retained prompt: %s", payload)
		}
	}
	step := projection.Steps[0]
	if step.Attempt != 1 || step.MaxAttempts != 1 || step.Route != "local_rocm_to_radeon_api" {
		t.Fatalf("observed attempt projection = %+v", step)
	}
}

func TestWorkspaceExecutionRouteMatrix(t *testing.T) {
	cases := []struct {
		name  string
		calls []struct {
			provider string
			err      error
		}
		expectedRoute   string
		expectedAttempt int
	}{
		{
			name: "local-only",
			calls: []struct {
				provider string
				err      error
			}{{provider: "local-rocm"}},
			expectedRoute: "local_rocm", expectedAttempt: 1,
		},
		{
			name: "hybrid-specialist",
			calls: []struct {
				provider string
				err      error
			}{{provider: "radeon-specialists"}},
			expectedRoute: "radeon_api", expectedAttempt: 1,
		},
		{
			name: "hybrid-fallback-to-local",
			calls: []struct {
				provider string
				err      error
			}{
				{provider: "radeon-specialists", err: errors.New("specialist endpoint unavailable")},
				{provider: "local-rocm"},
			},
			expectedRoute: "radeon_api_to_local_rocm", expectedAttempt: 2,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			server := newFixtureTestServer(t)
			record, err := server.newRun("", false)
			if err != nil {
				t.Fatal(err)
			}
			plan, err := fixtureResearchPlan(server.fixture)
			if err != nil {
				t.Fatal(err)
			}
			runSink{server: server, record: record}.AcceptPlan(plan, server.config.Now())
			observer := runModelObserver{server: server, record: record}
			request := benchmark.Request{
				Messages:  []benchmark.Message{{Role: "system", Content: "private route-matrix prompt"}},
				MaxTokens: 800,
			}
			for _, call := range testCase.calls {
				observer.ObserveModelCall(
					context.Background(), "business-strategy/v1", call.provider,
					request, benchmark.Completion{}, call.err,
				)
			}

			server.mu.RLock()
			projection := cloneExecutionPlan(*record.execution)
			events := append([]StreamEvent(nil), record.events...)
			server.mu.RUnlock()
			var step *executionplan.Step
			for index := range projection.Steps {
				if projection.Steps[index].StepID == "context-01" {
					step = &projection.Steps[index]
					break
				}
			}
			if step == nil || step.Route != testCase.expectedRoute ||
				step.Attempt != testCase.expectedAttempt {
				t.Fatalf("route matrix projection = %+v", step)
			}
			payload, err := json.Marshal(struct {
				Projection executionplan.Projection `json:"projection"`
				Events     []StreamEvent            `json:"events"`
			}{Projection: projection, Events: events})
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(payload), "private route-matrix prompt") {
				t.Fatalf("route matrix retained a model prompt: %s", payload)
			}
		})
	}
}

func TestRecoveredFallbackOverlayProducesValidPassedProjection(t *testing.T) {
	var overlay struct {
		SchemaVersion       string      `json:"schema_version"`
		BaseFixture         string      `json:"base_fixture"`
		InsertAfterSequence int         `json:"insert_after_sequence"`
		Events              []SafeEvent `json:"events"`
	}
	overlayPayload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "workspace", "recovered-fallback-events.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(overlayPayload, &overlay); err != nil {
		t.Fatal(err)
	}
	if overlay.SchemaVersion != "signalforge/workspace-lifecycle-overlay/v1" ||
		overlay.BaseFixture != "fixtures/workspace/golden-case.json" ||
		overlay.InsertAfterSequence < 1 || len(overlay.Events) != 2 {
		t.Fatalf("invalid recovered-fallback overlay: %+v", overlay)
	}
	basePayload, err := os.ReadFile(filepath.Join("..", "..", overlay.BaseFixture))
	if err != nil {
		t.Fatal(err)
	}
	var projection Projection
	if err := json.Unmarshal(basePayload, &projection); err != nil {
		t.Fatal(err)
	}
	events := make([]SafeEvent, 0, len(projection.Events)+len(overlay.Events))
	for _, event := range projection.Events {
		if event.Sequence <= overlay.InsertAfterSequence {
			events = append(events, event)
		}
	}
	events = append(events, overlay.Events...)
	for _, event := range projection.Events {
		if event.Sequence <= overlay.InsertAfterSequence {
			continue
		}
		event.Sequence += len(overlay.Events)
		events = append(events, event)
	}
	projection.Events = events
	if err := hydrateFixtureExecution(&projection); err != nil {
		t.Fatal(err)
	}
	if projection.ExecutionPlan == nil || projection.ExecutionPlan.Status != executionplan.StatusPassed {
		t.Fatalf("recovered fallback did not preserve a passed projection: %+v", projection.ExecutionPlan)
	}
	var recovered *executionplan.Step
	for index := range projection.ExecutionPlan.Steps {
		if projection.ExecutionPlan.Steps[index].StepID == "context-01" {
			recovered = &projection.ExecutionPlan.Steps[index]
			break
		}
	}
	if recovered == nil || recovered.Route != "radeon_api_to_local_rocm" ||
		recovered.Attempt != 2 || recovered.Status != executionplan.StatusPassed {
		t.Fatalf("fallback route was not recovered safely: %+v", recovered)
	}
	payload, err := json.Marshal(projection.ExecutionPlan)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"private prompt", "response body", "authorization"} {
		if strings.Contains(strings.ToLower(string(payload)), forbidden) {
			t.Fatalf("recovered projection retained forbidden content: %s", payload)
		}
	}
}

func TestRetentionIsOptInAndSupportsInspectExportDelete(t *testing.T) {
	store := newFakeCaseStore()
	server := newFixtureTestServerWithConfig(t, ServerConfig{CaseStore: store})
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)

	configResponse, err := http.Get(httpServer.URL + "/api/v1/config")
	if err != nil {
		t.Fatal(err)
	}
	defer configResponse.Body.Close()
	var config ConfigView
	if err := json.NewDecoder(configResponse.Body).Decode(&config); err != nil {
		t.Fatal(err)
	}
	if !config.RetentionAvailable || config.RetentionDefault {
		t.Fatalf("retention config = %+v", config)
	}

	unsaved := postRun(t, httpServer.URL, `{"question":"Ephemeral case","scenario":{}}`)
	unsaved = waitForRun(t, httpServer.URL, unsaved)
	if unsaved.Retention.Status != "not_requested" || store.saveCount() != 0 {
		t.Fatalf("unsaved retention = %+v, saves = %d", unsaved.Retention, store.saveCount())
	}
	assertRetentionEvents(t, server, unsaved.RunID, []string{"not_requested"})

	saved := postRun(t, httpServer.URL, `{"question":"Saved case","scenario":{},"retain":true}`)
	saved = waitForRun(t, httpServer.URL, saved)
	if saved.Status != "completed" || saved.Retention.Status != "saved" || saved.Retention.CaseID == "" ||
		saved.Execution == nil || store.saveCount() != 1 {
		t.Fatalf("saved run = %+v, saves = %d", saved, store.saveCount())
	}
	assertRetentionEvents(t, server, saved.RunID, []string{"requested", "approved", "saved"})

	list := getRaw(t, httpServer.URL+"/api/v1/cases")
	if list.StatusCode != http.StatusOK || !strings.Contains(readBody(t, list), saved.Retention.CaseID) {
		t.Fatal("saved case was not listed")
	}
	inspect := getRaw(t, httpServer.URL+"/api/v1/cases/"+saved.Retention.CaseID)
	if inspect.StatusCode != http.StatusOK {
		t.Fatalf("inspect status = %d", inspect.StatusCode)
	}
	var inspected struct {
		Case Projection `json:"case"`
	}
	if err := json.NewDecoder(inspect.Body).Decode(&inspected); err != nil {
		inspect.Body.Close()
		t.Fatal(err)
	}
	inspect.Body.Close()
	if inspected.Case.ExecutionPlan == nil ||
		executionplan.Validate(*inspected.Case.ExecutionPlan) != nil {
		t.Fatal("saved case did not preserve a valid signed execution plan")
	}
	exported := getRaw(t, httpServer.URL+"/api/v1/cases/"+saved.Retention.CaseID+"/export")
	if exported.StatusCode != http.StatusOK || !strings.Contains(exported.Header.Get("Content-Disposition"), saved.Retention.CaseID) {
		t.Fatalf("export status = %d, disposition = %q", exported.StatusCode, exported.Header.Get("Content-Disposition"))
	}
	var export CaseExport
	if err := json.NewDecoder(exported.Body).Decode(&export); err != nil {
		exported.Body.Close()
		t.Fatal(err)
	}
	exported.Body.Close()
	if export.Case.ExecutionPlan == nil ||
		executionplan.Validate(*export.Case.ExecutionPlan) != nil ||
		export.Case.ExecutionPlan.ProjectionSHA != inspected.Case.ExecutionPlan.ProjectionSHA {
		t.Fatal("export did not preserve the saved signed execution plan")
	}

	request, err := http.NewRequest(http.MethodDelete, httpServer.URL+"/api/v1/cases/"+saved.Retention.CaseID, nil)
	if err != nil {
		t.Fatal(err)
	}
	deleted, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	deleted.Body.Close()
	if deleted.StatusCode != http.StatusOK {
		t.Fatalf("delete status = %d", deleted.StatusCode)
	}
	deletedRun := getRun(t, httpServer.URL, saved.RunID)
	if deletedRun.Retention.Status != "deleted" || deletedRun.Execution == nil {
		t.Fatalf("deleted retention state = %+v", deletedRun)
	}
	assertRetentionEvents(t, server, saved.RunID, []string{"requested", "approved", "saved", "deleted"})
	missing := getRaw(t, httpServer.URL+"/api/v1/cases/"+saved.Retention.CaseID)
	if missing.StatusCode != http.StatusNotFound {
		t.Fatalf("missing status = %d", missing.StatusCode)
	}
	missing.Body.Close()
}

func TestRetentionFailureDoesNotInvalidateCompletedResearch(t *testing.T) {
	store := newFakeCaseStore()
	store.failSave = true
	server := newFixtureTestServerWithConfig(t, ServerConfig{CaseStore: store})
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)

	run := postRun(t, httpServer.URL, `{"question":"Keep the analysis","scenario":{},"retain":true}`)
	run = waitForRun(t, httpServer.URL, run)
	if run.Status != "completed" || run.Result == nil {
		t.Fatalf("analysis was invalidated by retention failure: %+v", run)
	}
	if run.Retention.Status != "failed" || run.Retention.ErrorCode != "case_save_failed" {
		t.Fatalf("retention = %+v", run.Retention)
	}
	assertRetentionEvents(t, server, run.RunID, []string{"requested", "approved", "failed"})
}

func TestRequestedRetentionIsExplicitlyUnavailableWithoutCaseStore(t *testing.T) {
	server := newFixtureTestServer(t)
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)

	run := postRun(t, httpServer.URL, `{"question":"Keep if available","scenario":{},"retain":true}`)
	run = waitForRun(t, httpServer.URL, run)
	if run.Status != "completed" || run.Result == nil || run.Retention.Status != "unavailable" ||
		run.Retention.ErrorCode != "case_store_unavailable" {
		t.Fatalf("unavailable retention invalidated or obscured the run: %+v", run)
	}
	assertRetentionEvents(t, server, run.RunID, []string{"requested", "unavailable"})
}

func assertRetentionEvents(t *testing.T, server *Server, runID string, expected []string) {
	t.Helper()
	record, ok := server.record(runID)
	if !ok {
		t.Fatalf("run %q not found", runID)
	}
	server.mu.RLock()
	var actual []string
	for _, event := range record.events {
		if event.Type == "retention" {
			actual = append(actual, event.Status)
		}
	}
	server.mu.RUnlock()
	if strings.Join(actual, ",") != strings.Join(expected, ",") {
		t.Fatalf("retention events = %v, expected %v", actual, expected)
	}
}

func TestCaseEndpointsFailClosedWhenUnavailableOrInvalid(t *testing.T) {
	server := newFixtureTestServer(t)
	handler := server.Handler()
	for _, path := range []string{"/api/v1/cases", "/api/v1/cases/case-missing", "/api/v1/cases/case-missing/export"} {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		if response.Code != http.StatusServiceUnavailable {
			t.Fatalf("%s status = %d", path, response.Code)
		}
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/v1/cases/:invalid", nil))
	if response.Code != http.StatusBadRequest {
		t.Fatalf("invalid case status = %d", response.Code)
	}
}

func TestStaticServerRejectsEscapingPaths(t *testing.T) {
	staticDir := t.TempDir()
	server := newFixtureTestServerWithConfig(t, ServerConfig{StaticDir: staticDir})
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/../secret", nil)
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
}

func TestSPAHandlerPreservesOperationalEndpoints(t *testing.T) {
	staticDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(staticDir, "index.html"), []byte("<html>workspace</html>"), 0o600); err != nil {
		t.Fatal(err)
	}
	api := http.NewServeMux()
	api.HandleFunc("GET /health/ready", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]string{"status": "ready"})
	})
	api.HandleFunc("GET /metrics", func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte("signalforge_test_metric 1\n"))
	})
	handler := spaHandler(api, staticDir)

	for path, expected := range map[string]string{
		"/health/ready": `"status":"ready"`,
		"/metrics":      "signalforge_test_metric 1",
	} {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), expected) {
			t.Fatalf("%s was intercepted by SPA fallback: status=%d body=%q", path, response.Code, response.Body.String())
		}
	}
}

func TestIntelligenceInspectorSeparatesMetadataAndProtectedBodies(t *testing.T) {
	audit, err := intelligenceaudit.NewStore(intelligenceaudit.Config{
		Directory: t.TempDir(), Enabled: true, Token: "operator-token", TTL: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}
	server := newFixtureTestServerWithConfig(t, ServerConfig{AuditStore: audit})
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)
	run := waitForRun(t, httpServer.URL, postRun(t, httpServer.URL, `{"question":"Compare Microsoft and NVIDIA.","scenario":{}}`))
	if run.TraceID != telemetry.TraceIDForRun(run.RunID) {
		t.Fatalf("workspace trace ID = %q, want canonical identity", run.TraceID)
	}

	metadata := getRaw(t, httpServer.URL+"/api/v1/runs/"+run.RunID+"/intelligence")
	if metadata.StatusCode != http.StatusOK {
		t.Fatalf("metadata status = %d, body = %s", metadata.StatusCode, readBody(t, metadata))
	}
	metadataBody := readBody(t, metadata)
	if !strings.Contains(metadataBody, `"engine_calls"`) || !strings.Contains(metadataBody, `"retrievals"`) ||
		strings.Contains(metadataBody, `"question"`) {
		t.Fatalf("unexpected metadata body: %s", metadataBody)
	}
	var metadataRecord intelligenceaudit.Record
	if err := json.Unmarshal([]byte(metadataBody), &metadataRecord); err != nil {
		t.Fatal(err)
	}
	if metadataRecord.RunID != run.RunID || metadataRecord.TraceID != run.TraceID {
		t.Fatalf("workspace/mission-control identity mismatch: run=%q/%q trace=%q/%q",
			run.RunID, metadataRecord.RunID, run.TraceID, metadataRecord.TraceID)
	}
	if len(metadataRecord.Timeline) == 0 {
		t.Fatal("Mission Control did not expose the correlated public lifecycle timeline")
	}

	denied := getRaw(t, httpServer.URL+"/api/v1/runs/"+run.RunID+"/intelligence/protected")
	if denied.StatusCode != http.StatusForbidden {
		t.Fatalf("protected status = %d", denied.StatusCode)
	}
	denied.Body.Close()

	request, err := http.NewRequest(http.MethodGet, httpServer.URL+"/api/v1/runs/"+run.RunID+"/intelligence/protected", nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("X-SignalForge-Audit-Token", "operator-token")
	protected, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer protected.Body.Close()
	if protected.StatusCode != http.StatusOK {
		t.Fatalf("protected status = %d, body = %s", protected.StatusCode, readBody(t, protected))
	}
	if !strings.Contains(readBody(t, protected), `Compare Microsoft and NVIDIA.`) {
		t.Fatal("protected fixture question was unavailable")
	}
}

func TestGoldenFixtureHasImmediateIntelligenceLineage(t *testing.T) {
	audit, err := intelligenceaudit.NewStore(intelligenceaudit.Config{Directory: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	server := newFixtureTestServerWithConfig(t, ServerConfig{AuditStore: audit})
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet,
		"/api/v1/runs/"+server.fixture.RunID+"/intelligence", nil)
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	var record intelligenceaudit.Record
	if err := json.Unmarshal(response.Body.Bytes(), &record); err != nil {
		t.Fatal(err)
	}
	if record.Release == nil || len(record.Timeline) == 0 || len(record.Retrievals) != 1 ||
		len(record.Engines) != len(server.fixture.Calculations) {
		t.Fatalf("record = %+v", record)
	}
	if record.RunID != server.fixture.RunID ||
		record.TraceID != telemetry.TraceIDForRun(server.fixture.RunID) {
		t.Fatalf("fixture lineage identity = run %q trace %q", record.RunID, record.TraceID)
	}
}

func newFixtureTestServer(t *testing.T) *Server {
	t.Helper()
	return newFixtureTestServerWithConfig(t, ServerConfig{})
}

func newFixtureTestServerWithConfig(t *testing.T, overrides ServerConfig) *Server {
	t.Helper()
	config := overrides
	config.Mode = ModeFixture
	config.FixturePath = filepath.Join("..", "..", "fixtures", "workspace", "golden-case.json")
	config.CatalogPath = filepath.Join("..", "..", "fixtures", "productscope", "technology20-catalog.json")
	config.EventDelay = time.Millisecond
	server, err := NewServer(config)
	if err != nil {
		t.Fatal(err)
	}
	return server
}

func postRun(t *testing.T, baseURL, payload string) RunView {
	t.Helper()
	response := postRaw(t, baseURL+"/api/v1/runs", payload)
	defer response.Body.Close()
	if response.StatusCode != http.StatusAccepted {
		body, _ := io.ReadAll(response.Body)
		t.Fatalf("create run status = %d, body = %s", response.StatusCode, body)
	}
	var view RunView
	if err := json.NewDecoder(response.Body).Decode(&view); err != nil {
		t.Fatal(err)
	}
	return view
}

func getRun(t *testing.T, baseURL, runID string) RunView {
	t.Helper()
	response, err := http.Get(baseURL + "/api/v1/runs/" + runID)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var view RunView
	if err := json.NewDecoder(response.Body).Decode(&view); err != nil {
		t.Fatal(err)
	}
	return view
}

func waitForRun(t *testing.T, baseURL string, run RunView) RunView {
	t.Helper()
	// Race instrumentation and concurrent package tests can make the fixture replay exceed two
	// seconds on constrained CI runners even though the runtime continues to make progress.
	deadline := time.Now().Add(10 * time.Second)
	for run.Status == "running" && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
		run = getRun(t, baseURL, run.RunID)
	}
	return run
}

func getRaw(t *testing.T, url string) *http.Response {
	t.Helper()
	response, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	return response
}

func readBody(t *testing.T, response *http.Response) string {
	t.Helper()
	defer response.Body.Close()
	payload, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	return string(payload)
}

func postRaw(t *testing.T, url, payload string) *http.Response {
	t.Helper()
	response, err := http.Post(url, "application/json", bytes.NewBufferString(payload))
	if err != nil {
		t.Fatal(err)
	}
	return response
}

func assertJSONField(t *testing.T, body []byte, key string, expected any) {
	t.Helper()
	var value map[string]any
	if err := json.Unmarshal(body, &value); err != nil {
		t.Fatal(err)
	}
	if value[key] != expected {
		t.Fatalf("%s = %#v, expected %#v", key, value[key], expected)
	}
}

func TestSafeStreamAttributesKeepsReceiptMetadataAndDropsBodies(t *testing.T) {
	safe := safeStreamAttributes(map[string]string{
		"packet_id":                "packet-1",
		"evidence_count":           "4",
		"source_classes":           "sec_filing+investor_relations",
		"formula_version":          "fcf/v2",
		"input_ref_ids":            "operating-cash-flow+capex",
		"receipt_id":               "receipt-1",
		"receipt_sha256":           strings.Repeat("a", 64),
		"receipt_verification":     "canonical_verified",
		"output_ref_ids":           "free-cash-flow",
		"retrieval_id":             "retrieval-1",
		"bundle_id":                "bundle-1",
		"retrieval_method":         "bm25/v1",
		"candidate_count":          "8",
		"selected_candidate_count": "4",
		"rejected_candidate_count": "4",
		"candidate_count_state":    "available",
		"tool_execution_id":        "calc-1",
		"primary_intent":           "company_comparison",
		"entity_count":             "2",
		"entity_ids":               "company-msft+company-nvda",
		"role_count":               "9",
		"completion_conditions":    "review_approved+single_final_answer",
		"abstention_conditions":    "missing_primary_evidence+deadline_exceeded",
		"finding_count":            "3",
		"counterevidence_count":    "1",
		"missing_evidence_count":   "2",
		"evidence_coverage":        "3_of_4",
		"approved_claim_count":     "3",
		"rejected_claim_count":     "1",
		"issue_count":              "2",
		"repair_pass":              "1",
		"mandatory_review_count":   "3",
		"claim_count":              "4",
		"supported_claim_coverage": "3_of_4",
		"evidence_ref_count":       "6",
		"receipt_ref_count":        "2",
		"limitation_count":         "1",
		"section_count":            "3",
		"freshness_state":          "bounded_by_as_of",
		"fact_count":               "3",
		"calculation_count":        "2",
		"inference_count":          "1",
		"hypothesis_count":         "1",
		"assumption_count":         "2",
		"raw_prompt":               "private",
		"response_body":            "private",
		"claim_body":               "private",
		"answer_body":              "private",
		"authorization":            "Bearer-secret",
		"financial_values":         "private",
	})
	for _, key := range []string{
		"packet_id", "evidence_count", "source_classes", "formula_version",
		"input_ref_ids", "receipt_id", "receipt_sha256", "receipt_verification", "output_ref_ids",
		"retrieval_id", "bundle_id", "retrieval_method", "candidate_count",
		"selected_candidate_count", "rejected_candidate_count", "candidate_count_state",
		"tool_execution_id",
		"primary_intent", "entity_count", "entity_ids", "role_count",
		"completion_conditions", "abstention_conditions",
		"finding_count", "counterevidence_count", "missing_evidence_count", "evidence_coverage",
		"approved_claim_count", "rejected_claim_count", "issue_count", "repair_pass",
		"mandatory_review_count", "claim_count", "supported_claim_coverage",
		"evidence_ref_count", "receipt_ref_count", "limitation_count", "section_count",
		"freshness_state", "fact_count", "calculation_count", "inference_count",
		"hypothesis_count", "assumption_count",
	} {
		if safe[key] == "" {
			t.Fatalf("safe operational attribute %q was dropped: %#v", key, safe)
		}
	}
	for _, key := range []string{"raw_prompt", "response_body", "claim_body", "answer_body", "authorization", "financial_values"} {
		if _, exists := safe[key]; exists {
			t.Fatalf("private attribute %q crossed the stream boundary: %#v", key, safe)
		}
	}
}
