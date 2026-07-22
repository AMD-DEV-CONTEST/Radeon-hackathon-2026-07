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
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
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
	terminalSeen := false
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data: ") {
			eventCount++
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
	if eventCount != len(run.Result.Events)+1 {
		t.Fatalf("streamed events = %d, expected %d", eventCount, len(run.Result.Events)+1)
	}
	if !terminalSeen {
		t.Fatal("expected workspace completion event")
	}
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

	saved := postRun(t, httpServer.URL, `{"question":"Saved case","scenario":{},"retain":true}`)
	saved = waitForRun(t, httpServer.URL, saved)
	if saved.Status != "completed" || saved.Retention.Status != "saved" || saved.Retention.CaseID == "" || store.saveCount() != 1 {
		t.Fatalf("saved run = %+v, saves = %d", saved, store.saveCount())
	}

	list := getRaw(t, httpServer.URL+"/api/v1/cases")
	if list.StatusCode != http.StatusOK || !strings.Contains(readBody(t, list), saved.Retention.CaseID) {
		t.Fatal("saved case was not listed")
	}
	inspect := getRaw(t, httpServer.URL+"/api/v1/cases/"+saved.Retention.CaseID)
	if inspect.StatusCode != http.StatusOK || !strings.Contains(readBody(t, inspect), `"case"`) {
		t.Fatal("saved case was not inspectable")
	}
	exported := getRaw(t, httpServer.URL+"/api/v1/cases/"+saved.Retention.CaseID+"/export")
	if exported.StatusCode != http.StatusOK || !strings.Contains(exported.Header.Get("Content-Disposition"), saved.Retention.CaseID) {
		t.Fatalf("export status = %d, disposition = %q", exported.StatusCode, exported.Header.Get("Content-Disposition"))
	}
	exported.Body.Close()

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

func newFixtureTestServer(t *testing.T) *Server {
	t.Helper()
	return newFixtureTestServerWithConfig(t, ServerConfig{})
}

func newFixtureTestServerWithConfig(t *testing.T, overrides ServerConfig) *Server {
	t.Helper()
	config := overrides
	config.Mode = ModeFixture
	config.FixturePath = filepath.Join("..", "..", "fixtures", "workspace", "golden-case.json")
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
	deadline := time.Now().Add(2 * time.Second)
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
