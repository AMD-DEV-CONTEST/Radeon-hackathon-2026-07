package workspace

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/permissions"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/resilience"
	"github.com/rvbernucci/signalforge/internal/runid"
)

const (
	ModeFixture = "fixture"
	ModeLive    = "live"
)

type ServerConfig struct {
	Mode           string
	FixturePath    string
	StaticDir      string
	Golden         golden.RunConfig
	EventDelay     time.Duration
	Now            func() time.Time
	RunTimeout     time.Duration
	MaxBodyBytes   int64
	CaseStore      CaseStore
	RuntimeBreaker *resilience.Breaker
}

type Server struct {
	config  ServerConfig
	fixture Projection
	mu      sync.RWMutex
	runs    map[string]*runRecord
	breaker *resilience.Breaker
}

type runRecord struct {
	view         RunView
	events       []StreamEvent
	report       *golden.Report
	subscribers  map[chan StreamEvent]struct{}
	terminalOnce sync.Once
	cancel       context.CancelFunc
	retain       bool
	parentRunID  string
}

type RunView struct {
	RunID       string         `json:"run_id"`
	ParentRunID string         `json:"parent_run_id,omitempty"`
	Status      string         `json:"status"`
	StartedAt   time.Time      `json:"started_at"`
	CompletedAt *time.Time     `json:"completed_at,omitempty"`
	Result      *Projection    `json:"result,omitempty"`
	Failure     *PublicFailure `json:"failure,omitempty"`
	Retention   RetentionView  `json:"retention"`
}

type PublicFailure struct {
	Code      string `json:"code"`
	Retryable bool   `json:"retryable"`
}

type StreamEvent struct {
	Sequence int       `json:"sequence"`
	RunID    string    `json:"run_id"`
	StepID   string    `json:"step_id,omitempty"`
	Type     string    `json:"type"`
	Status   string    `json:"status"`
	Label    string    `json:"label"`
	At       time.Time `json:"at"`
}

type RunRequest struct {
	Question string          `json:"question"`
	Scenario ScenarioControl `json:"scenario"`
	Retain   bool            `json:"retain"`
}

type FollowUpRequest struct {
	Question string `json:"question"`
	Retain   bool   `json:"retain"`
}

type ScenarioControl struct {
	Rates      string `json:"rates"`
	AISpending string `json:"ai_spending"`
}

type ConfigView struct {
	Mode               string          `json:"mode"`
	LocalOnly          bool            `json:"local_only"`
	EndpointScope      string          `json:"endpoint_scope"`
	Model              string          `json:"model"`
	ScenarioDefaults   ScenarioControl `json:"scenario_defaults"`
	FollowUpsLive      bool            `json:"follow_ups_live"`
	RetentionAvailable bool            `json:"retention_available"`
	RetentionDefault   bool            `json:"retention_default"`
}

func NewServer(config ServerConfig) (*Server, error) {
	if config.Mode == "" {
		config.Mode = ModeFixture
	}
	if config.Mode != ModeFixture && config.Mode != ModeLive {
		return nil, fmt.Errorf("unsupported workspace mode %q", config.Mode)
	}
	if config.Now == nil {
		config.Now = func() time.Time { return time.Now().UTC() }
	}
	if config.RunTimeout <= 0 {
		config.RunTimeout = 6 * time.Minute
	}
	if config.MaxBodyBytes <= 0 {
		config.MaxBodyBytes = 16 << 10
	}
	breaker := config.RuntimeBreaker
	if breaker == nil {
		breaker = resilience.NewBreaker(3, 30*time.Second)
	}
	server := &Server{config: config, runs: map[string]*runRecord{}, breaker: breaker}
	if strings.TrimSpace(config.FixturePath) == "" {
		return nil, errors.New("workspace fixture path is required")
	}
	payload, err := os.ReadFile(config.FixturePath)
	if err != nil {
		return nil, fmt.Errorf("read workspace fixture: %w", err)
	}
	if err := json.Unmarshal(payload, &server.fixture); err != nil {
		return nil, fmt.Errorf("decode workspace fixture: %w", err)
	}
	if err := Validate(server.fixture); err != nil {
		return nil, fmt.Errorf("validate workspace fixture: %w", err)
	}
	return server, nil
}

func (server *Server) Handler() http.Handler {
	api := http.NewServeMux()
	api.HandleFunc("GET /api/v1/health", server.handleHealth)
	api.HandleFunc("GET /api/v1/config", server.handleConfig)
	api.HandleFunc("GET /api/v1/cases/golden", server.handleGoldenCase)
	api.HandleFunc("GET /api/v1/cases", server.handleListCases)
	api.HandleFunc("GET /api/v1/cases/{caseID}", server.handleGetCase)
	api.HandleFunc("GET /api/v1/cases/{caseID}/export", server.handleExportCase)
	api.HandleFunc("DELETE /api/v1/cases/{caseID}", server.handleDeleteCase)
	api.HandleFunc("POST /api/v1/runs", server.handleCreateRun)
	api.HandleFunc("GET /api/v1/runs/{runID}", server.handleGetRun)
	api.HandleFunc("GET /api/v1/runs/{runID}/events", server.handleEvents)
	api.HandleFunc("POST /api/v1/runs/{runID}/follow-ups", server.handleFollowUp)
	api.HandleFunc("DELETE /api/v1/runs/{runID}", server.handleCancelRun)

	var root http.Handler = api
	if strings.TrimSpace(server.config.StaticDir) != "" {
		root = spaHandler(api, server.config.StaticDir)
	}
	return securityHeaders(root)
}

func (server *Server) handleHealth(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, map[string]any{"status": "ok", "local_only": true, "mode": server.config.Mode})
}

func (server *Server) handleConfig(writer http.ResponseWriter, _ *http.Request) {
	model := server.config.Golden.Model
	if model == "" {
		model = server.fixture.Execution.Model
	}
	writeJSON(writer, http.StatusOK, ConfigView{
		Mode: server.config.Mode, LocalOnly: true, EndpointScope: "loopback_only", Model: model,
		ScenarioDefaults:   ScenarioControl{Rates: "higher_for_longer", AISpending: "slower"},
		FollowUpsLive:      server.config.Mode == ModeLive,
		RetentionAvailable: server.config.CaseStore != nil,
		RetentionDefault:   false,
	})
}

func (server *Server) handleGoldenCase(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, server.fixture)
}

func (server *Server) handleListCases(writer http.ResponseWriter, request *http.Request) {
	if permissions.Authorize(permissions.AuthorityUser, permissions.CaseRead) != nil {
		writeProblem(writer, http.StatusForbidden, "case_read_denied")
		return
	}
	if server.config.CaseStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "case_store_unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 2*time.Second)
	defer cancel()
	items, err := server.config.CaseStore.List(ctx, 50)
	if err != nil {
		writeProblem(writer, http.StatusServiceUnavailable, "case_store_read_failed")
		return
	}
	if items == nil {
		items = []CaseSummary{}
	}
	writeJSON(writer, http.StatusOK, map[string]any{"cases": items})
}

func (server *Server) handleGetCase(writer http.ResponseWriter, request *http.Request) {
	if permissions.Authorize(permissions.AuthorityUser, permissions.CaseRead) != nil {
		writeProblem(writer, http.StatusForbidden, "case_read_denied")
		return
	}
	caseID, ok := validCaseID(request.PathValue("caseID"))
	if !ok {
		writeProblem(writer, http.StatusBadRequest, "invalid_case_id")
		return
	}
	if server.config.CaseStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "case_store_unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 2*time.Second)
	defer cancel()
	projection, summary, err := server.config.CaseStore.Get(ctx, caseID)
	if err != nil {
		server.writeCaseStoreProblem(writer, err, "case_store_read_failed")
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"summary": summary, "case": projection})
}

func (server *Server) handleExportCase(writer http.ResponseWriter, request *http.Request) {
	if permissions.Authorize(permissions.AuthorityUser, permissions.CaseExport) != nil {
		writeProblem(writer, http.StatusForbidden, "case_export_denied")
		return
	}
	caseID, ok := validCaseID(request.PathValue("caseID"))
	if !ok {
		writeProblem(writer, http.StatusBadRequest, "invalid_case_id")
		return
	}
	if server.config.CaseStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "case_store_unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 2*time.Second)
	defer cancel()
	exported, err := server.config.CaseStore.Export(ctx, caseID)
	if err != nil {
		server.writeCaseStoreProblem(writer, err, "case_export_failed")
		return
	}
	writer.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s.json"`, caseID))
	writeJSON(writer, http.StatusOK, exported)
}

func (server *Server) handleDeleteCase(writer http.ResponseWriter, request *http.Request) {
	if permissions.Authorize(permissions.AuthorityUser, permissions.CaseDelete) != nil {
		writeProblem(writer, http.StatusForbidden, "case_delete_denied")
		return
	}
	caseID, ok := validCaseID(request.PathValue("caseID"))
	if !ok {
		writeProblem(writer, http.StatusBadRequest, "invalid_case_id")
		return
	}
	if server.config.CaseStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "case_store_unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 2*time.Second)
	defer cancel()
	if err := server.config.CaseStore.Delete(ctx, caseID); err != nil {
		server.writeCaseStoreProblem(writer, err, "case_delete_failed")
		return
	}
	writeJSON(writer, http.StatusOK, map[string]string{"status": "deleted", "case_id": caseID})
}

func (server *Server) handleCreateRun(writer http.ResponseWriter, request *http.Request) {
	var input RunRequest
	if err := server.decodeJSON(writer, request, &input); err != nil {
		return
	}
	input.Question = strings.TrimSpace(input.Question)
	if input.Question == "" {
		input.Question = golden.DefaultQuestion
	}
	if len(input.Question) > 1600 {
		writeProblem(writer, http.StatusBadRequest, "question_too_long")
		return
	}
	question, assumptions, scenarioErr := normalizedScenario(input.Question, input.Scenario)
	if scenarioErr != nil {
		writeProblem(writer, http.StatusBadRequest, "invalid_scenario")
		return
	}
	record, err := server.newRun("", input.Retain)
	if err != nil {
		writeProblem(writer, http.StatusInternalServerError, "run_identity_failed")
		return
	}
	if server.config.Mode == ModeFixture {
		go server.replayFixture(record, question, assumptions)
	} else {
		go server.executeLive(record, question, assumptions, nil)
	}
	writeJSON(writer, http.StatusAccepted, record.view)
}

func (server *Server) handleFollowUp(writer http.ResponseWriter, request *http.Request) {
	parentID := request.PathValue("runID")
	parent, ok := server.record(parentID)
	if !ok {
		writeProblem(writer, http.StatusNotFound, "run_not_found")
		return
	}
	var input FollowUpRequest
	if err := server.decodeJSON(writer, request, &input); err != nil {
		return
	}
	input.Question = strings.TrimSpace(input.Question)
	if input.Question == "" || len(input.Question) > 1200 {
		writeProblem(writer, http.StatusBadRequest, "invalid_follow_up")
		return
	}
	server.mu.RLock()
	parentReport := parent.report
	parentStatus := parent.view.Status
	server.mu.RUnlock()
	if server.config.Mode != ModeLive || parentReport == nil || parentReport.Result.Answer == nil || parentStatus != "completed" {
		writeProblem(writer, http.StatusConflict, "follow_up_requires_completed_live_case")
		return
	}
	followUp, err := requestparser.NewFollowUpContext(parentReport.Request, *parentReport.Result.Answer)
	if err != nil {
		writeProblem(writer, http.StatusConflict, "follow_up_context_invalid")
		return
	}
	record, err := server.newRun(parentID, input.Retain)
	if err != nil {
		writeProblem(writer, http.StatusInternalServerError, "run_identity_failed")
		return
	}
	child, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: input.Question, AsOf: server.config.Now(), RunID: record.view.RunID,
		RequestID: "request-" + strings.TrimPrefix(record.view.RunID, "run-"), FollowUp: &followUp,
	})
	if err != nil {
		server.fail(record, "follow_up_parse_failed", false)
		writeProblem(writer, http.StatusUnprocessableEntity, "follow_up_parse_failed")
		return
	}
	child.Assumptions = append([]string(nil), parentReport.Request.Assumptions...)
	go server.executeLive(record, input.Question, nil, &child)
	writeJSON(writer, http.StatusAccepted, record.view)
}

func (server *Server) handleGetRun(writer http.ResponseWriter, request *http.Request) {
	record, ok := server.record(request.PathValue("runID"))
	if !ok {
		writeProblem(writer, http.StatusNotFound, "run_not_found")
		return
	}
	server.mu.RLock()
	view := cloneRunView(record.view)
	server.mu.RUnlock()
	writeJSON(writer, http.StatusOK, view)
}

func (server *Server) handleCancelRun(writer http.ResponseWriter, request *http.Request) {
	record, ok := server.record(request.PathValue("runID"))
	if !ok {
		writeProblem(writer, http.StatusNotFound, "run_not_found")
		return
	}
	server.mu.Lock()
	if record.view.Status != "running" || record.cancel == nil {
		server.mu.Unlock()
		writeProblem(writer, http.StatusConflict, "run_not_active")
		return
	}
	record.cancel()
	server.mu.Unlock()
	writeJSON(writer, http.StatusAccepted, map[string]string{"status": "cancelling"})
}

func (server *Server) handleEvents(writer http.ResponseWriter, request *http.Request) {
	record, ok := server.record(request.PathValue("runID"))
	if !ok {
		writeProblem(writer, http.StatusNotFound, "run_not_found")
		return
	}
	flusher, ok := writer.(http.Flusher)
	if !ok {
		writeProblem(writer, http.StatusInternalServerError, "streaming_unsupported")
		return
	}
	writer.Header().Set("Content-Type", "text/event-stream")
	writer.Header().Set("Cache-Control", "no-cache, no-transform")
	writer.Header().Set("Connection", "keep-alive")
	channel := make(chan StreamEvent, 32)
	server.mu.Lock()
	existing := append([]StreamEvent(nil), record.events...)
	terminal := record.view.Status != "running"
	if !terminal {
		record.subscribers[channel] = struct{}{}
	}
	server.mu.Unlock()
	defer func() {
		server.mu.Lock()
		delete(record.subscribers, channel)
		server.mu.Unlock()
	}()
	for _, event := range existing {
		if err := writeSSE(writer, event); err != nil {
			return
		}
	}
	flusher.Flush()
	if terminal {
		return
	}
	for {
		select {
		case event := <-channel:
			if err := writeSSE(writer, event); err != nil {
				return
			}
			flusher.Flush()
			if event.Type == "workspace" && (event.Status == "completed" || event.Status == "failed" || event.Status == "cancelled") {
				return
			}
		case <-request.Context().Done():
			return
		}
	}
}

func (server *Server) newRun(parentRunID string, retain bool) (*runRecord, error) {
	value, err := runid.New(server.config.Now())
	if err != nil {
		return nil, err
	}
	record := &runRecord{
		view: RunView{
			RunID: "run-" + value, ParentRunID: parentRunID, Status: "running", StartedAt: server.config.Now(),
			Retention: retentionInitialStatus(retain, server.config.CaseStore != nil),
		},
		subscribers: map[chan StreamEvent]struct{}{},
		retain:      retain,
		parentRunID: parentRunID,
	}
	server.mu.Lock()
	server.runs[record.view.RunID] = record
	server.mu.Unlock()
	return record, nil
}

func (server *Server) replayFixture(record *runRecord, question string, assumptions []string) {
	projection := cloneProjection(server.fixture)
	projection.RunID = record.view.RunID
	projection.RequestID = "request-" + strings.TrimPrefix(record.view.RunID, "run-")
	projection.CaseID = "case-" + projection.RequestID
	projection.Question = question
	projection.Assumptions = append([]string(nil), assumptions...)
	projection.Status = "completed"
	for _, fixtureEvent := range projection.Events {
		if server.config.EventDelay > 0 {
			time.Sleep(server.config.EventDelay)
		}
		server.publish(record, StreamEvent{
			StepID: fixtureEvent.StepID, Type: fixtureEvent.Type, Status: fixtureEvent.Status,
			Label: eventLabel(fixtureEvent.Type, fixtureEvent.Status), At: server.config.Now(),
		})
	}
	server.complete(record, projection, nil)
}

func (server *Server) executeLive(record *runRecord, question string, assumptions []string, requestOverride *contracts.ResearchRequest) {
	if !server.breaker.Allow(server.config.Now()) {
		server.fail(record, "local_runtime_temporarily_unavailable", true)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), server.config.RunTimeout)
	server.mu.Lock()
	record.cancel = cancel
	server.mu.Unlock()
	defer cancel()
	config := server.config.Golden
	config.Question = question
	config.RunID = record.view.RunID
	config.RequestID = "request-" + strings.TrimPrefix(record.view.RunID, "run-")
	config.Timeout = server.config.RunTimeout
	config.EventSink = runSink{server: server, record: record}
	config.RequestOverride = requestOverride
	if requestOverride == nil {
		config.UseAssumptions = true
		config.Assumptions = append([]string(nil), assumptions...)
	}
	report, err := golden.Run(ctx, config)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			server.fail(record, "context_cancelled", false)
			return
		}
		server.breaker.Failure(server.config.Now())
		server.fail(record, "local_run_failed", errors.Is(err, context.DeadlineExceeded))
		return
	}
	server.breaker.Success()
	if report.Result.Failure != nil {
		server.mu.Lock()
		record.report = &report
		server.mu.Unlock()
		server.fail(record, report.Result.Failure.FailureCode, report.Result.Failure.Retryable)
		return
	}
	projection, err := Project(report)
	if err != nil {
		server.fail(record, "workspace_projection_failed", false)
		return
	}
	server.complete(record, projection, &report)
}

func (server *Server) complete(record *runRecord, projection Projection, report *golden.Report) {
	record.terminalOnce.Do(func() {
		now := server.config.Now()
		retention := retentionInitialStatus(record.retain, server.config.CaseStore != nil)
		if record.retain && server.config.CaseStore != nil {
			var err error
			if permissions.Authorize(permissions.AuthorityUser, permissions.CaseSave) != nil {
				err = permissions.ErrDenied
			} else {
				ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
				err = server.config.CaseStore.Save(ctx, projection, record.parentRunID)
				cancel()
			}
			if err != nil {
				retention.Status = "failed"
				retention.ErrorCode = "case_save_failed"
			} else {
				retention.Status = "saved"
				retention.CaseID = projection.CaseID
			}
		}
		server.mu.Lock()
		record.view.Status = "completed"
		record.view.CompletedAt = &now
		record.view.Result = &projection
		record.view.Retention = retention
		record.report = report
		server.mu.Unlock()
		if record.retain {
			status := "completed"
			label := "Research case saved locally"
			if retention.Status != "saved" {
				status = "failed"
				label = "Research completed; local save unavailable"
			}
			server.publish(record, StreamEvent{Type: "retention", Status: status, Label: label, At: now})
		}
		server.publish(record, StreamEvent{Type: "workspace", Status: "completed", Label: "Research case ready", At: now})
	})
}

func (server *Server) fail(record *runRecord, code string, retryable bool) {
	record.terminalOnce.Do(func() {
		now := server.config.Now()
		status := "failed"
		if code == "context_cancelled" {
			status = "cancelled"
		}
		server.mu.Lock()
		record.view.Status = status
		record.view.CompletedAt = &now
		record.view.Failure = &PublicFailure{Code: code, Retryable: retryable}
		server.mu.Unlock()
		server.publish(record, StreamEvent{Type: "workspace", Status: status, Label: failureLabel(code), At: now})
	})
}

func (server *Server) publish(record *runRecord, event StreamEvent) {
	server.mu.Lock()
	event.Sequence = len(record.events) + 1
	event.RunID = record.view.RunID
	if event.At.IsZero() {
		event.At = server.config.Now()
	}
	record.events = append(record.events, event)
	for subscriber := range record.subscribers {
		select {
		case subscriber <- event:
		default:
		}
	}
	server.mu.Unlock()
}

func (server *Server) record(runID string) (*runRecord, bool) {
	server.mu.RLock()
	record, ok := server.runs[runID]
	server.mu.RUnlock()
	return record, ok
}

func (server *Server) writeCaseStoreProblem(writer http.ResponseWriter, err error, fallback string) {
	if errors.Is(err, ErrCaseNotFound) {
		writeProblem(writer, http.StatusNotFound, "case_not_found")
		return
	}
	writeProblem(writer, http.StatusServiceUnavailable, fallback)
}

func retentionInitialStatus(requested, available bool) RetentionView {
	view := RetentionView{Requested: requested, Status: "not_requested"}
	if requested && available {
		view.Status = "pending"
	} else if requested {
		view.Status = "unavailable"
		view.ErrorCode = "case_store_unavailable"
	}
	return view
}

func validCaseID(value string) (string, bool) {
	value = strings.TrimSpace(value)
	if len(value) == 0 || len(value) > 160 {
		return "", false
	}
	for index, character := range value {
		allowed := character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' ||
			character >= '0' && character <= '9' || character == '-' || character == '_' || character == '.' || character == ':'
		if !allowed || index == 0 && (character == '.' || character == ':') {
			return "", false
		}
	}
	return value, true
}

func (server *Server) decodeJSON(writer http.ResponseWriter, request *http.Request, target any) error {
	request.Body = http.MaxBytesReader(writer, request.Body, server.config.MaxBodyBytes)
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		writeProblem(writer, http.StatusBadRequest, "invalid_json")
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		writeProblem(writer, http.StatusBadRequest, "invalid_json")
		return errors.New("request body must contain one JSON object")
	}
	return nil
}

type runSink struct {
	server *Server
	record *runRecord
}

func (sink runSink) Emit(event orchestrator.Event) {
	sink.server.publish(sink.record, StreamEvent{
		StepID: event.StepID, Type: event.Type, Status: event.Status,
		Label: eventLabel(event.Type, event.Status), At: event.At,
	})
}

func normalizedScenario(question string, scenario ScenarioControl) (string, []string, error) {
	if scenario.Rates == "" {
		scenario.Rates = "higher_for_longer"
	}
	if scenario.AISpending == "" {
		scenario.AISpending = "slower"
	}
	ratesLabel := map[string]string{
		"higher_for_longer": "higher-for-longer interest rates",
		"easing":            "easing interest rates",
	}[scenario.Rates]
	aiLabel := map[string]string{
		"slower":    "slower AI infrastructure spending",
		"resilient": "resilient AI infrastructure spending",
	}[scenario.AISpending]
	if ratesLabel == "" || aiLabel == "" {
		return "", nil, errors.New("unknown scenario value")
	}
	base := strings.TrimSpace(question)
	if base == golden.DefaultQuestion {
		base = "Compare Microsoft and NVIDIA as long-term businesses. Include business quality, accounting comparability, financial quality, market behavior, DCF valuation ranges, multiples, explicit assumptions, counterevidence, and thesis invalidation conditions."
	}
	base += " Evaluate the explicit scenario of " + ratesLabel + " and " + aiLabel + "."
	assumptions := []string{
		strings.ToUpper(ratesLabel[:1]) + ratesLabel[1:] + " are an explicit scenario, not a claim that the future path of rates is known.",
		strings.ToUpper(aiLabel[:1]) + aiLabel[1:] + " is an explicit scenario, not an observed causal forecast.",
	}
	return base, assumptions, nil
}

func eventLabel(eventType, status string) string {
	labels := map[string]string{
		"plan:accepted":       "Research plan accepted",
		"context:started":     "Specialist context started",
		"context:completed":   "Specialist context ready",
		"context:failed":      "Specialist context degraded",
		"review:started":      "Independent review started",
		"review:completed":    "Independent review complete",
		"synthesis:started":   "Final synthesis started",
		"synthesis:completed": "Final synthesis complete",
		"run:completed":       "Research run completed",
	}
	if label := labels[eventType+":"+status]; label != "" {
		return label
	}
	return titleWords(strings.ReplaceAll(eventType+" "+status, "_", " "))
}

func titleWords(value string) string {
	words := strings.Fields(value)
	for index, word := range words {
		if word == "" {
			continue
		}
		words[index] = strings.ToUpper(word[:1]) + word[1:]
	}
	return strings.Join(words, " ")
}

func failureLabel(code string) string {
	switch code {
	case "context_cancelled":
		return "Research run cancelled"
	case "context_deadline_exceeded":
		return "Local model timed out"
	case "evidence_rejected":
		return "Evidence review rejected the draft"
	case "local_runtime_temporarily_unavailable":
		return "Local runtime is cooling down after repeated failures"
	default:
		return "Research run stopped safely"
	}
}

func cloneProjection(projection Projection) Projection {
	payload, _ := json.Marshal(projection)
	var clone Projection
	_ = json.Unmarshal(payload, &clone)
	return clone
}

func cloneRunView(view RunView) RunView {
	payload, _ := json.Marshal(view)
	var clone RunView
	_ = json.Unmarshal(payload, &clone)
	return clone
}

func writeSSE(writer io.Writer, event StreamEvent) error {
	payload, err := json.Marshal(event)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(writer, "id: %d\nevent: progress\ndata: %s\n\n", event.Sequence, payload)
	return err
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json; charset=utf-8")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeProblem(writer http.ResponseWriter, status int, code string) {
	writeJSON(writer, status, map[string]any{"error": map[string]any{"code": code, "status": status}})
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("X-Content-Type-Options", "nosniff")
		writer.Header().Set("X-Frame-Options", "DENY")
		writer.Header().Set("Referrer-Policy", "no-referrer")
		writer.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
		next.ServeHTTP(writer, request)
	})
}

func spaHandler(api http.Handler, staticDir string) http.Handler {
	root, err := filepath.Abs(staticDir)
	if err != nil {
		root = staticDir
	}
	files := http.FileServer(http.Dir(root))
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if strings.HasPrefix(request.URL.Path, "/api/") {
			api.ServeHTTP(writer, request)
			return
		}
		clean := filepath.Clean(strings.TrimPrefix(request.URL.Path, "/"))
		if clean == "." {
			clean = "index.html"
		}
		candidate, candidateErr := filepath.Abs(filepath.Join(root, clean))
		insideRoot := candidateErr == nil && (candidate == root || strings.HasPrefix(candidate, root+string(os.PathSeparator)))
		if !insideRoot {
			writeProblem(writer, http.StatusBadRequest, "invalid_static_path")
			return
		}
		if _, err := os.Stat(candidate); err != nil {
			request.URL.Path = "/"
		}
		files.ServeHTTP(writer, request)
	})
}
