package workspace

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/executionplan"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/intelligenceaudit"
	"github.com/rvbernucci/signalforge/internal/missioncontrol"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/permissions"
	"github.com/rvbernucci/signalforge/internal/productscope"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/resilience"
	"github.com/rvbernucci/signalforge/internal/runid"
	"github.com/rvbernucci/signalforge/internal/telemetry"
)

const (
	ModeFixture = "fixture"
	ModeLive    = "live"

	maximumStoredRunEvents = 256
	maximumStoredRuns      = 64
)

type ServerConfig struct {
	Mode               string
	FixturePath        string
	CatalogPath        string
	FinancialsPath     string
	PeerEvaluationPath string
	StaticDir          string
	Golden             golden.RunConfig
	EventDelay         time.Duration
	Now                func() time.Time
	RunTimeout         time.Duration
	MaxBodyBytes       int64
	CaseStore          CaseStore
	RuntimeBreaker     *resilience.Breaker
	AuditStore         *intelligenceaudit.Store
	BuildVersion       string
}

type Server struct {
	config     ServerConfig
	fixture    Projection
	catalog    productscope.PublicCatalog
	financials productscope.PublicFinancialSummary
	peers      productscope.PeerEvaluationSuite
	mu         sync.RWMutex
	runs       map[string]*runRecord
	runOrder   []string
	breaker    *resilience.Breaker
}

type runRecord struct {
	view         RunView
	events       []StreamEvent
	nextSequence int
	execution    *executionplan.Projection
	report       *golden.Report
	subscribers  map[chan StreamEvent]struct{}
	terminalOnce sync.Once
	cancel       context.CancelFunc
	retain       bool
	parentRunID  string
	retentionSet bool
	modelCalls   map[string]modelAttemptState
}

type modelAttemptState struct {
	Attempts      int
	LastRoute     string
	LastFailed    bool
	LastMaxTokens int
	LastSystemSHA string
}

type RunView struct {
	RunID       string                    `json:"run_id"`
	TraceID     string                    `json:"trace_id"`
	ParentRunID string                    `json:"parent_run_id,omitempty"`
	Status      string                    `json:"status"`
	StartedAt   time.Time                 `json:"started_at"`
	CompletedAt *time.Time                `json:"completed_at,omitempty"`
	Result      *Projection               `json:"result,omitempty"`
	Execution   *executionplan.Projection `json:"execution_plan,omitempty"`
	Failure     *PublicFailure            `json:"failure,omitempty"`
	Retention   RetentionView             `json:"retention"`
}

type PublicFailure struct {
	Code      string `json:"code"`
	Retryable bool   `json:"retryable"`
}

type StreamEvent struct {
	Sequence   int               `json:"sequence"`
	RunID      string            `json:"run_id"`
	StepID     string            `json:"step_id,omitempty"`
	Type       string            `json:"type"`
	Status     string            `json:"status"`
	Label      string            `json:"label"`
	At         time.Time         `json:"at"`
	Attributes map[string]string `json:"attributes,omitempty"`
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
	IntelligenceAudit  bool            `json:"intelligence_audit"`
	ProtectedCapture   bool            `json:"protected_capture"`
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
	if strings.TrimSpace(config.CatalogPath) == "" {
		return nil, errors.New("workspace product catalog path is required")
	}
	if strings.TrimSpace(config.FinancialsPath) == "" {
		config.FinancialsPath = filepath.Join(filepath.Dir(config.CatalogPath), "technology20-financial-summary.json")
	}
	if strings.TrimSpace(config.PeerEvaluationPath) == "" {
		config.PeerEvaluationPath = filepath.Join(filepath.Dir(config.CatalogPath), "technology20-peer-evaluation.json")
	}
	server.config = config
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
	if err := hydrateFixtureExecution(&server.fixture); err != nil {
		return nil, fmt.Errorf("project workspace fixture execution: %w", err)
	}
	catalogPayload, err := os.ReadFile(config.CatalogPath)
	if err != nil {
		return nil, fmt.Errorf("read workspace product catalog: %w", err)
	}
	if err := json.Unmarshal(catalogPayload, &server.catalog); err != nil {
		return nil, fmt.Errorf("decode workspace product catalog: %w", err)
	}
	if err := productscope.ValidatePublicCatalog(server.catalog); err != nil {
		return nil, fmt.Errorf("validate workspace product catalog: %w", err)
	}
	financialPayload, err := os.ReadFile(config.FinancialsPath)
	if err != nil {
		return nil, fmt.Errorf("read workspace financial summary: %w", err)
	}
	if err := json.Unmarshal(financialPayload, &server.financials); err != nil {
		return nil, fmt.Errorf("decode workspace financial summary: %w", err)
	}
	if err := productscope.ValidatePublicFinancialSummary(server.financials); err != nil {
		return nil, fmt.Errorf("validate workspace financial summary: %w", err)
	}
	peerPayload, err := os.ReadFile(config.PeerEvaluationPath)
	if err != nil {
		return nil, fmt.Errorf("read workspace peer evaluation: %w", err)
	}
	if err := json.Unmarshal(peerPayload, &server.peers); err != nil {
		return nil, fmt.Errorf("decode workspace peer evaluation: %w", err)
	}
	if err := productscope.ValidatePeerEvaluationSuite(server.peers); err != nil {
		return nil, fmt.Errorf("validate workspace peer evaluation: %w", err)
	}
	if config.AuditStore != nil {
		recorder, auditErr := config.AuditStore.Begin(context.Background(), server.fixture.RunID,
			server.fixture.RequestID, server.fixture.Question)
		if auditErr == nil {
			now := config.Now()
			if err := observeFixtureLifecycle(context.Background(), recorder, server.fixture, now); err != nil {
				return nil, fmt.Errorf("initialize fixture audit timeline: %w", err)
			}
			_ = recorder.Complete(auditFixtureProjection(now, now, server.fixture))
		}
	}
	return server, nil
}

func (server *Server) Handler() http.Handler {
	api := http.NewServeMux()
	api.HandleFunc("GET /health/live", server.handleLiveness)
	api.HandleFunc("GET /health/ready", server.handleReadiness)
	api.HandleFunc("GET /api/v1/health", server.handleHealth)
	api.Handle("GET /metrics", missioncontrol.MetricsHandler{Store: server.config.AuditStore, Version: server.config.BuildVersion})
	api.HandleFunc("GET /api/v1/config", server.handleConfig)
	api.HandleFunc("GET /api/v1/catalog", server.handleCatalog)
	api.HandleFunc("GET /api/v1/financials", server.handleFinancials)
	api.HandleFunc("GET /api/v1/peer-evaluations", server.handlePeerEvaluations)
	api.HandleFunc("GET /api/v1/cases/golden", server.handleGoldenCase)
	api.HandleFunc("GET /api/v1/cases", server.handleListCases)
	api.HandleFunc("GET /api/v1/cases/{caseID}", server.handleGetCase)
	api.HandleFunc("GET /api/v1/cases/{caseID}/export", server.handleExportCase)
	api.HandleFunc("DELETE /api/v1/cases/{caseID}", server.handleDeleteCase)
	api.HandleFunc("POST /api/v1/runs", server.handleCreateRun)
	api.HandleFunc("GET /api/v1/runs/{runID}", server.handleGetRun)
	api.HandleFunc("GET /api/v1/runs/{runID}/events", server.handleEvents)
	api.HandleFunc("GET /api/v1/runs/{runID}/execution", server.handleExecutionPlan)
	api.HandleFunc("GET /api/v1/runs/{runID}/intelligence", server.handleIntelligence)
	api.HandleFunc("GET /api/v1/runs/{runID}/intelligence/protected", server.handleProtectedIntelligence)
	api.HandleFunc("DELETE /api/v1/runs/{runID}/intelligence/protected", server.handlePurgeProtectedIntelligence)
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

func (server *Server) handleLiveness(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, map[string]string{"status": "alive"})
}

func (server *Server) handleReadiness(writer http.ResponseWriter, _ *http.Request) {
	modelDependency := "not_required"
	if server.config.Mode == ModeLive {
		modelDependency = "configured"
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"status": "ready",
		"mode":   server.config.Mode,
		"dependencies": map[string]string{
			"model_runtime":      modelDependency,
			"case_retention":     availability(server.config.CaseStore != nil),
			"intelligence_audit": availability(server.config.AuditStore != nil),
		},
	})
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
		IntelligenceAudit:  server.config.AuditStore != nil,
		ProtectedCapture:   server.config.AuditStore != nil && server.config.AuditStore.Enabled(),
	})
}

func (server *Server) handleCatalog(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, server.catalog)
}

func (server *Server) handleFinancials(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, server.financials)
}

func (server *Server) handlePeerEvaluations(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, server.peers)
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
	server.markCaseDeleted(caseID)
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

func (server *Server) handleExecutionPlan(writer http.ResponseWriter, request *http.Request) {
	record, ok := server.record(request.PathValue("runID"))
	if !ok {
		writeProblem(writer, http.StatusNotFound, "run_not_found")
		return
	}
	server.mu.RLock()
	if record.execution == nil {
		server.mu.RUnlock()
		writeProblem(writer, http.StatusNotFound, "execution_plan_not_found")
		return
	}
	projection := cloneExecutionPlan(*record.execution)
	server.mu.RUnlock()
	writeJSON(writer, http.StatusOK, projection)
}

func (server *Server) handleIntelligence(writer http.ResponseWriter, request *http.Request) {
	runID := request.PathValue("runID")
	if server.config.AuditStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "intelligence_audit_unavailable")
		return
	}
	record, err := server.config.AuditStore.Public(runID)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			writeProblem(writer, http.StatusNotFound, "intelligence_audit_not_found")
			return
		}
		writeProblem(writer, http.StatusServiceUnavailable, "intelligence_audit_read_failed")
		return
	}
	writeJSON(writer, http.StatusOK, record)
}

func (server *Server) handleProtectedIntelligence(writer http.ResponseWriter, request *http.Request) {
	runID := request.PathValue("runID")
	if server.config.AuditStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "protected_audit_unavailable")
		return
	}
	record, err := server.config.AuditStore.Protected(runID, request.Header.Get("X-SignalForge-Audit-Token"))
	if err != nil {
		writeProblem(writer, http.StatusForbidden, "protected_audit_denied")
		return
	}
	writer.Header().Set("Cache-Control", "no-store")
	writeJSON(writer, http.StatusOK, record)
}

func (server *Server) handlePurgeProtectedIntelligence(writer http.ResponseWriter, request *http.Request) {
	runID := request.PathValue("runID")
	if server.config.AuditStore == nil {
		writeProblem(writer, http.StatusServiceUnavailable, "protected_audit_unavailable")
		return
	}
	if err := server.config.AuditStore.Purge(runID, request.Header.Get("X-SignalForge-Audit-Token")); err != nil {
		writeProblem(writer, http.StatusForbidden, "protected_audit_denied")
		return
	}
	writeJSON(writer, http.StatusOK, map[string]string{"status": "purged", "run_id": runID})
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
	channel := make(chan StreamEvent, 128)
	lastSequence, _ := strconv.Atoi(strings.TrimSpace(request.Header.Get("Last-Event-ID")))
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
		if event.Sequence <= lastSequence {
			continue
		}
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
	now := server.config.Now()
	value, err := runid.New(now)
	if err != nil {
		return nil, err
	}
	runID := "run-" + value
	requestID := "request-" + value
	execution, err := executionplan.Pending(runID, requestID, now)
	if err != nil {
		return nil, err
	}
	record := &runRecord{
		view: RunView{
			RunID: runID, TraceID: telemetry.TraceIDForRun(runID),
			ParentRunID: parentRunID, Status: "running", StartedAt: now,
			Execution: cloneExecutionPlanPointer(&execution),
			Retention: retentionInitialStatus(retain, server.config.CaseStore != nil),
		},
		execution:   &execution,
		subscribers: map[chan StreamEvent]struct{}{},
		retain:      retain,
		parentRunID: parentRunID,
		modelCalls:  map[string]modelAttemptState{},
	}
	server.mu.Lock()
	server.runs[record.view.RunID] = record
	server.runOrder = append(server.runOrder, record.view.RunID)
	server.evictCompletedRunsLocked()
	server.mu.Unlock()
	return record, nil
}

func (server *Server) replayFixture(record *runRecord, question string, assumptions []string) {
	journeyContext, journeySpan := telemetry.StartJourney(context.Background(), record.view.RunID,
		"request-"+strings.TrimPrefix(record.view.RunID, "run-"), ModeFixture)
	defer journeySpan.End()
	projection := cloneProjection(server.fixture)
	projection.RunID = record.view.RunID
	projection.RequestID = "request-" + strings.TrimPrefix(record.view.RunID, "run-")
	projection.CaseID = "case-" + projection.RequestID
	projection.Question = question
	projection.Assumptions = append([]string(nil), assumptions...)
	projection.Status = "completed"
	audit := server.beginAudit(journeyContext, record.view.RunID, projection.RequestID, question)
	if plan, err := fixtureResearchPlan(projection); err == nil {
		runSink{server: server, record: record}.AcceptPlan(plan, server.config.Now())
	}
	toolEvents, err := fixtureCalculationEvents(projection.Calculations, server.config.Now())
	if err != nil {
		server.fail(record, "fixture_receipt_validation_failed", false)
		return
	}
	timelineSequence := 0
	for _, fixtureEvent := range projection.Events {
		if server.config.EventDelay > 0 {
			time.Sleep(server.config.EventDelay)
		}
		accepted := server.publish(record, StreamEvent{
			StepID: fixtureEvent.StepID, Type: fixtureEvent.Type, Status: fixtureEvent.Status,
			Label: eventLabel(fixtureEvent.Type, fixtureEvent.Status), At: server.config.Now(),
			Attributes: safeStreamAttributes(fixtureEvent.Attributes),
		})
		if accepted && audit != nil {
			timelineSequence++
			audit.ObserveLifecycle(journeyContext, orchestrator.Event{
				Sequence: timelineSequence, RunID: record.view.RunID,
				StepID: fixtureEvent.StepID, Type: fixtureEvent.Type, Status: fixtureEvent.Status,
				At: server.config.Now(), Attributes: safeStreamAttributes(fixtureEvent.Attributes),
			})
		}
	}
	for _, toolEvent := range toolEvents {
		if server.config.EventDelay > 0 {
			time.Sleep(server.config.EventDelay)
		}
		accepted := server.publish(record, toolEvent)
		if accepted && audit != nil {
			timelineSequence++
			audit.ObserveLifecycle(journeyContext, orchestrator.Event{
				Sequence: timelineSequence, RunID: record.view.RunID,
				StepID: toolEvent.StepID, Type: toolEvent.Type, Status: toolEvent.Status,
				At: server.config.Now(), Attributes: safeStreamAttributes(toolEvent.Attributes),
			})
		}
	}
	if audit != nil {
		_ = audit.Complete(auditFixtureProjection(record.view.StartedAt, server.config.Now(), projection))
	}
	server.complete(record, projection, nil)
}

func (server *Server) executeLive(record *runRecord, question string, assumptions []string, requestOverride *contracts.ResearchRequest) {
	if !server.breaker.Allow(server.config.Now()) {
		server.fail(record, "local_runtime_temporarily_unavailable", true)
		return
	}
	requestID := "request-" + strings.TrimPrefix(record.view.RunID, "run-")
	journeyContext, journeySpan := telemetry.StartJourney(context.Background(), record.view.RunID, requestID, ModeLive)
	defer journeySpan.End()
	ctx, cancel := context.WithTimeout(journeyContext, server.config.RunTimeout)
	server.mu.Lock()
	record.cancel = cancel
	server.mu.Unlock()
	defer cancel()
	config := server.config.Golden
	config.Question = question
	config.RunID = record.view.RunID
	config.RequestID = requestID
	config.Timeout = server.config.RunTimeout
	audit := server.beginAudit(ctx, record.view.RunID, config.RequestID, question)
	config.EventSink = runSink{server: server, record: record, audit: audit}
	config.ModelObserver = runModelObserver{
		audit: audit, server: server, record: record,
	}
	config.RequestOverride = requestOverride
	if requestOverride == nil {
		config.UseAssumptions = true
		config.Assumptions = append([]string(nil), assumptions...)
	}
	report, err := golden.Run(ctx, config)
	if err != nil {
		if audit != nil {
			_ = audit.Complete(intelligenceaudit.ProjectionInput{
				RunID: record.view.RunID, RequestID: config.RequestID, Question: question,
				StartedAt: record.view.StartedAt, CompletedAt: server.config.Now(), Status: "failed",
			})
		}
		if errors.Is(err, context.Canceled) {
			server.fail(record, "context_cancelled", false)
			return
		}
		server.breaker.Failure(server.config.Now())
		server.fail(record, "local_run_failed", errors.Is(err, context.DeadlineExceeded))
		return
	}
	if audit != nil {
		_ = audit.Complete(intelligenceaudit.FromResult(question, report.Request, report.Result))
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

func (server *Server) beginAudit(ctx context.Context, runID, requestID, question string) *intelligenceaudit.Recorder {
	if server.config.AuditStore == nil {
		return nil
	}
	recorder, err := server.config.AuditStore.Begin(ctx, runID, requestID, question)
	if err != nil {
		return nil
	}
	return recorder
}

func auditFixtureProjection(startedAt, completedAt time.Time, projection Projection) intelligenceaudit.ProjectionInput {
	input := intelligenceaudit.ProjectionInput{
		RunID: projection.RunID, RequestID: projection.RequestID, Question: projection.Question,
		StartedAt: startedAt, CompletedAt: completedAt, Status: projection.Status,
	}
	retrieval := intelligenceaudit.RetrievalRecord{
		RetrievalID: "retrieval-fixture-" + projection.RunID, StepID: "fixture-evidence",
		RoleID: "fixture-replay", Method: "public_fixture", ContextPacketID: "fixture-" + projection.RunID,
		Status: "selected", CompletedAt: completedAt,
	}
	for _, evidence := range projection.Evidence {
		retrieval.EvidenceIDs = append(retrieval.EvidenceIDs, evidence.EvidenceID)
		retrieval.EvidenceSources = append(retrieval.EvidenceSources, intelligenceaudit.EvidenceSourceRecord{
			EvidenceID: evidence.EvidenceID, SourceType: evidence.SourceType,
			Locator: evidence.Locator, DocumentSection: evidence.DocumentSection,
			ContentSHA: evidence.ContentSHA, AsOf: evidence.AsOf,
		})
	}
	if len(retrieval.EvidenceIDs) > 0 {
		input.Retrievals = append(input.Retrievals, retrieval)
	}
	for _, receipt := range projection.Calculations {
		engine := intelligenceaudit.EngineCall{
			EngineCallID: "engine-fixture-" + receipt.ReceiptID,
			StepID:       "fixture-calculation", RequestedBy: "fixture-replay",
			EngineID: receipt.EngineID, EngineVersion: receipt.EngineVersion,
			OperationID: receipt.OperationID, FormulaVersion: receipt.FormulaVersion,
			ReceiptID: receipt.ReceiptID, ReceiptSHA: receipt.ReceiptSHA,
			EvidenceRefs:    append([]string(nil), receipt.EvidenceRefs...),
			InvariantsTotal: len(receipt.InvariantResults), Status: string(receipt.Status),
			GeneratedAt: completedAt,
		}
		for _, output := range receipt.Outputs {
			engine.OutputRefs = append(engine.OutputRefs, output.OutputID)
		}
		for _, invariant := range receipt.InvariantResults {
			if invariant.Passed {
				engine.InvariantsPass++
			}
		}
		input.Engines = append(input.Engines, engine)
		input.Receipts = append(input.Receipts, intelligenceaudit.ProtectedReceipt{
			ReceiptID: receipt.ReceiptID, Payload: receipt,
		})
	}
	release := &intelligenceaudit.ReleaseRecord{
		AnswerID: "fixture-answer-" + projection.RunID, PrimaryIntent: projection.Intent,
		Status: "released",
	}
	for _, section := range projection.Sections {
		release.SectionTypes = append(release.SectionTypes, section.SectionType)
		release.ClaimRefs = append(release.ClaimRefs, section.ClaimRefs...)
		release.EvidenceRefs = append(release.EvidenceRefs, section.EvidenceRefs...)
		release.ReceiptRefs = append(release.ReceiptRefs, section.ReceiptRefs...)
	}
	input.Release = release
	return input
}

func observeFixtureLifecycle(ctx context.Context, recorder *intelligenceaudit.Recorder, projection Projection, at time.Time) error {
	sequence := 0
	for _, event := range projection.Events {
		sequence++
		eventAt := event.At
		if eventAt.IsZero() {
			eventAt = at.Add(time.Duration(sequence) * time.Nanosecond)
		}
		recorder.ObserveLifecycle(ctx, orchestrator.Event{
			Sequence: sequence, RunID: projection.RunID, StepID: event.StepID,
			Type: event.Type, Status: event.Status, At: eventAt,
			Attributes: safeStreamAttributes(event.Attributes),
		})
	}
	toolEvents, err := fixtureCalculationEvents(projection.Calculations, at)
	if err != nil {
		return err
	}
	for _, event := range toolEvents {
		sequence++
		recorder.ObserveLifecycle(ctx, orchestrator.Event{
			Sequence: sequence, RunID: projection.RunID, StepID: event.StepID,
			Type: event.Type, Status: event.Status, At: event.At,
			Attributes: safeStreamAttributes(event.Attributes),
		})
	}
	return nil
}

func (server *Server) complete(record *runRecord, projection Projection, report *golden.Report) {
	server.initializeRetention(record)
	record.terminalOnce.Do(func() {
		now := server.config.Now()
		server.mu.Lock()
		if record.execution != nil {
			completed := cloneExecutionPlan(*record.execution)
			if executionplan.MarkCompleted(&completed, now) == nil {
				record.execution = &completed
				record.view.Execution = cloneExecutionPlanPointer(&completed)
				projection.ExecutionPlan = cloneExecutionPlanPointer(&completed)
			}
		}
		server.mu.Unlock()
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
		if record.retain && server.config.CaseStore != nil {
			status := "saved"
			label := "Research case saved locally"
			attributes := map[string]string{"case_id": retention.CaseID}
			if retention.Status != "saved" {
				status = "failed"
				label = "Research completed; local save failed"
				attributes = map[string]string{"code": retention.ErrorCode}
			}
			server.publish(record, StreamEvent{
				Type: "retention", Status: status, Label: label, At: now, Attributes: attributes,
			})
		}
		server.publish(record, StreamEvent{Type: "workspace", Status: "completed", Label: "Research case ready", At: now})
		server.mu.Lock()
		if record.execution != nil {
			projection.ExecutionPlan = cloneExecutionPlanPointer(record.execution)
		}
		record.view.Status = "completed"
		record.view.CompletedAt = &now
		record.view.Result = &projection
		record.view.Retention = retention
		record.report = report
		server.evictCompletedRunsLocked()
		server.mu.Unlock()
	})
}

func (server *Server) fail(record *runRecord, code string, retryable bool) {
	server.initializeRetention(record)
	record.terminalOnce.Do(func() {
		now := server.config.Now()
		status := "failed"
		if code == "context_cancelled" {
			status = "cancelled"
		}
		server.publish(record, StreamEvent{Type: "workspace", Status: status, Label: failureLabel(code), At: now})
		server.mu.Lock()
		record.view.Status = status
		record.view.CompletedAt = &now
		record.view.Failure = &PublicFailure{Code: code, Retryable: retryable}
		server.evictCompletedRunsLocked()
		server.mu.Unlock()
	})
}

func (server *Server) publish(record *runRecord, event StreamEvent) bool {
	server.mu.Lock()
	event.Sequence = record.nextSequence + 1
	event.RunID = record.view.RunID
	if event.At.IsZero() {
		event.At = server.config.Now()
	}
	event.Attributes = safeStreamAttributes(event.Attributes)
	if record.execution != nil {
		next := cloneExecutionPlan(*record.execution)
		if err := executionplan.Apply(&next, executionplan.Event{
			Sequence: event.Sequence, StepID: event.StepID, Type: event.Type,
			Status: event.Status, At: event.At, Attributes: event.Attributes,
		}); err != nil {
			server.mu.Unlock()
			return false
		}
		record.execution = &next
		record.view.Execution = cloneExecutionPlanPointer(&next)
		if record.view.Result != nil {
			record.view.Result.ExecutionPlan = cloneExecutionPlanPointer(&next)
		}
	}
	record.nextSequence = event.Sequence
	record.events = append(record.events, event)
	if len(record.events) > maximumStoredRunEvents {
		record.events = append([]StreamEvent(nil), record.events[len(record.events)-maximumStoredRunEvents:]...)
	}
	for subscriber := range record.subscribers {
		select {
		case subscriber <- event:
		default:
		}
	}
	server.mu.Unlock()
	return true
}

func (server *Server) record(runID string) (*runRecord, bool) {
	server.mu.RLock()
	record, ok := server.runs[runID]
	server.mu.RUnlock()
	return record, ok
}

func (server *Server) evictCompletedRunsLocked() {
	if len(server.runs) <= maximumStoredRuns {
		return
	}
	kept := make([]string, 0, len(server.runOrder))
	for _, runID := range server.runOrder {
		record, ok := server.runs[runID]
		if !ok {
			continue
		}
		if len(server.runs) > maximumStoredRuns &&
			record.view.Status != "running" &&
			len(record.subscribers) == 0 {
			delete(server.runs, runID)
			continue
		}
		kept = append(kept, runID)
	}
	server.runOrder = kept
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

func (server *Server) initializeRetention(record *runRecord) {
	server.mu.Lock()
	if record.retentionSet {
		server.mu.Unlock()
		return
	}
	record.retentionSet = true
	requested := record.retain
	available := server.config.CaseStore != nil
	server.mu.Unlock()

	now := server.config.Now()
	if !requested {
		server.publish(record, StreamEvent{
			Type: "retention", Status: "not_requested",
			Label: "Research remains ephemeral", At: now,
		})
		return
	}
	server.publish(record, StreamEvent{
		Type: "retention", Status: "requested",
		Label: "Local case retention requested", At: now,
	})
	if !available {
		server.publish(record, StreamEvent{
			Type: "retention", Status: "unavailable",
			Label: "Local case retention unavailable", At: now,
			Attributes: map[string]string{"code": "case_store_unavailable"},
		})
		return
	}
	server.publish(record, StreamEvent{
		Type: "retention", Status: "approved",
		Label: "Local case retention authorized", At: now,
	})
}

func (server *Server) markCaseDeleted(caseID string) {
	var record *runRecord
	server.mu.RLock()
	for _, candidate := range server.runs {
		if candidate.view.Retention.CaseID == caseID {
			record = candidate
			break
		}
	}
	server.mu.RUnlock()
	if record == nil {
		return
	}
	server.publish(record, StreamEvent{
		Type: "retention", Status: "deleted", Label: "Local research case deleted",
		At: server.config.Now(), Attributes: map[string]string{"case_id": caseID},
	})
	server.mu.Lock()
	record.view.Retention.Status = "deleted"
	record.view.Retention.ErrorCode = ""
	server.mu.Unlock()
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
	payload, err := io.ReadAll(request.Body)
	if err != nil {
		writeProblem(writer, http.StatusBadRequest, "invalid_json")
		return err
	}
	if !utf8.Valid(payload) {
		writeProblem(writer, http.StatusBadRequest, "invalid_json")
		return errors.New("request body must be valid UTF-8")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
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
	audit  *intelligenceaudit.Recorder
}

type runModelObserver struct {
	audit  *intelligenceaudit.Recorder
	server *Server
	record *runRecord
}

func (observer runModelObserver) ObserveModelCall(
	ctx context.Context,
	roleID string,
	providerID string,
	request benchmark.Request,
	completion benchmark.Completion,
	callErr error,
) {
	if observer.audit != nil {
		observer.audit.ObserveModelCall(ctx, roleID, providerID, request, completion, callErr)
	}
	stepID := observer.stepID(roleID)
	if stepID == "" {
		return
	}
	route := publicModelRoute(providerID)
	attempt, callKind, previousRoute := observer.classifyAttempt(stepID, route, request, callErr)
	status := "completed"
	if callErr != nil {
		status = "failed"
	}
	label := "Authorized primary model call " + status
	if callKind != "primary" {
		label = "Authorized " + strings.ReplaceAll(callKind, "_", " ") + " model call " + status
	}
	attributes := map[string]string{
		"role_id":   roleID,
		"route":     route,
		"attempt":   strconv.Itoa(attempt),
		"call_kind": callKind,
	}
	if previousRoute != "" {
		attributes["previous_route"] = previousRoute
	}
	observer.server.publish(observer.record, StreamEvent{
		StepID: stepID, Type: "model", Status: status,
		Label: label, At: observer.server.config.Now(), Attributes: attributes,
	})
}

func (observer runModelObserver) classifyAttempt(
	stepID string,
	route string,
	request benchmark.Request,
	callErr error,
) (int, string, string) {
	systemSHA := ""
	if len(request.Messages) > 0 {
		sum := sha256.Sum256([]byte(request.Messages[0].Content))
		systemSHA = fmt.Sprintf("%x", sum[:])
	}
	observer.server.mu.Lock()
	defer observer.server.mu.Unlock()
	if observer.record.modelCalls == nil {
		observer.record.modelCalls = map[string]modelAttemptState{}
	}
	state := observer.record.modelCalls[stepID]
	previousRoute := state.LastRoute
	callKind := "primary"
	if state.Attempts > 0 {
		switch {
		case previousRoute != "" && previousRoute != route:
			callKind = "fallback"
		case state.LastFailed:
			callKind = "retry"
		case request.MaxTokens > state.LastMaxTokens ||
			systemSHA != "" && state.LastSystemSHA != "" && systemSHA != state.LastSystemSHA:
			callKind = "bounded_repair"
		default:
			callKind = "retry"
		}
	}
	state.Attempts++
	state.LastRoute = route
	state.LastFailed = callErr != nil
	state.LastMaxTokens = request.MaxTokens
	state.LastSystemSHA = systemSHA
	observer.record.modelCalls[stepID] = state
	return state.Attempts, callKind, previousRoute
}

func (observer runModelObserver) stepID(roleID string) string {
	observer.server.mu.RLock()
	defer observer.server.mu.RUnlock()
	if observer.record.execution == nil {
		return ""
	}
	for _, step := range observer.record.execution.Steps {
		if step.RoleID == roleID {
			return step.StepID
		}
	}
	return ""
}

func publicModelRoute(providerID string) string {
	value := strings.ToLower(strings.TrimSpace(providerID))
	if strings.Contains(value, "local") || strings.Contains(value, "loopback") ||
		strings.Contains(value, "rocm") {
		return "local_rocm"
	}
	if strings.Contains(value, "radeon") || strings.Contains(value, "specialist") {
		return "radeon_api"
	}
	return "authorized_model_api"
}

func (sink runSink) AcceptPlan(plan contracts.ResearchPlan, at time.Time) {
	projection, err := executionplan.FromPlan(plan, at)
	if err != nil {
		return
	}
	sink.server.mu.Lock()
	sink.record.execution = &projection
	sink.record.view.Execution = cloneExecutionPlanPointer(&projection)
	sink.server.mu.Unlock()
	sink.server.initializeRetention(sink.record)
}

func (sink runSink) Emit(event orchestrator.Event) {
	accepted := sink.server.publish(sink.record, StreamEvent{
		StepID: event.StepID, Type: event.Type, Status: event.Status,
		Label: eventLabel(event.Type, event.Status), At: event.At,
		Attributes: safeStreamAttributes(event.Attributes),
	})
	if accepted && sink.audit != nil {
		sink.audit.ObserveLifecycle(nil, event)
	}
}

func fixtureResearchPlan(projection Projection) (contracts.ResearchPlan, error) {
	plan := contracts.ResearchPlan{
		SchemaVersion: contracts.SchemaVersionV1, RunID: projection.RunID, RequestID: projection.RequestID,
		MaxParallelSpecialists: 4, MaxRepairPasses: 1, DeadlineMS: 180000,
		CompletionConditions: []string{"review_approved", "single_final_answer"},
		AbstentionConditions: []string{"missing_primary_evidence"},
	}
	seen := map[string]bool{}
	contextIDs := []string{}
	reviewIDs := []string{}
	for _, event := range projection.Events {
		if event.Type == "plan" && plan.PlanID == "" {
			plan.PlanID = event.Attributes["plan_id"]
		}
		if event.StepID == "" || seen[event.StepID] ||
			(event.Type != "context" && event.Type != "review" && event.Type != "synthesis") {
			continue
		}
		seen[event.StepID] = true
		roleID := event.Attributes["role_id"]
		if roleID == "" {
			roleID = map[string]string{
				"context": "business-strategy/v1", "review": "evidence-critic/v1",
				"synthesis": "final-research-analyst/v1",
			}[event.Type]
		}
		step := contracts.PlanStep{
			StepID: event.StepID, Kind: event.Type, Objective: fixtureStepObjective(event.Type),
			RoleID: roleID, Mandatory: true, ContextBudget: 1200, TimeoutMS: 30000,
		}
		switch event.Type {
		case "context":
			step.Wave = 1
			if len(contextIDs) >= plan.MaxParallelSpecialists {
				step.Wave = 2
				step.DependsOn = append([]string(nil), contextIDs[:plan.MaxParallelSpecialists]...)
			}
			contextIDs = append(contextIDs, step.StepID)
		case "review":
			if len(reviewIDs) == 0 {
				step.DependsOn = append([]string(nil), contextIDs...)
			} else {
				step.DependsOn = []string{reviewIDs[len(reviewIDs)-1]}
			}
			reviewIDs = append(reviewIDs, step.StepID)
		case "synthesis":
			if len(reviewIDs) > 0 {
				step.DependsOn = []string{reviewIDs[len(reviewIDs)-1]}
			} else {
				step.DependsOn = append([]string(nil), contextIDs...)
			}
		}
		plan.Steps = append(plan.Steps, step)
	}
	if plan.PlanID == "" {
		plan.PlanID = "plan-fixture-" + projection.RunID
	}
	if err := contracts.ValidateResearchPlan(plan); err != nil {
		return contracts.ResearchPlan{}, err
	}
	return plan, nil
}

func hydrateFixtureExecution(projection *Projection) error {
	if projection == nil {
		return errors.New("workspace fixture is required")
	}
	plan, err := fixtureResearchPlan(*projection)
	if err != nil {
		return err
	}
	createdAt := projection.AsOf
	completedAt := projection.AsOf
	if len(projection.Events) > 0 && !projection.Events[0].At.IsZero() {
		createdAt = projection.Events[0].At
		completedAt = projection.Events[len(projection.Events)-1].At
	}
	execution, err := executionplan.FromPlan(plan, createdAt)
	if err != nil {
		return err
	}
	for _, event := range projection.Events {
		if err := executionplan.Apply(&execution, executionplan.Event{
			Sequence: event.Sequence, StepID: event.StepID, Type: event.Type,
			Status: event.Status, At: event.At, Attributes: safeStreamAttributes(event.Attributes),
		}); err != nil {
			return err
		}
	}
	sequence := execution.LastSequence
	toolEvents, err := fixtureCalculationEvents(projection.Calculations, completedAt)
	if err != nil {
		return err
	}
	for _, event := range toolEvents {
		sequence++
		if err := executionplan.Apply(&execution, executionplan.Event{
			Sequence: sequence, StepID: event.StepID, Type: event.Type,
			Status: event.Status, At: event.At, Attributes: safeStreamAttributes(event.Attributes),
		}); err != nil {
			return err
		}
	}
	if err := executionplan.MarkCompleted(&execution, completedAt); err != nil {
		return err
	}
	projection.ExecutionPlan = &execution
	return Validate(*projection)
}

func fixtureStepObjective(kind string) string {
	switch kind {
	case "context":
		return "Compile governed evidence and deterministic receipts for the selected research scope."
	case "review":
		return "Independently review evidence, calculations, assumptions, and release boundaries."
	case "synthesis":
		return "Compose one evidence-grounded answer from material approved by the review gates."
	default:
		return "Execute the governed research step."
	}
}

func fixtureCalculationEvents(calculations []CalculationCard, at time.Time) ([]StreamEvent, error) {
	events := make([]StreamEvent, 0, len(calculations))
	for _, calculation := range calculations {
		status := "completed"
		if calculation.Status != contracts.ReceiptSuccess {
			status = "failed"
		} else if err := validateSuccessfulFixtureCalculation(calculation); err != nil {
			return nil, err
		}
		outputRefs := make([]string, 0, len(calculation.Outputs))
		for _, output := range calculation.Outputs {
			outputRefs = append(outputRefs, output.OutputID)
		}
		invariantsPassed := len(calculation.InvariantResults) > 0
		for _, invariant := range calculation.InvariantResults {
			if !invariant.Passed {
				invariantsPassed = false
				break
			}
		}
		events = append(events, StreamEvent{
			StepID: "fixture-calculation", Type: "tool", Status: status,
			Label: eventLabel("tool", status), At: at,
			Attributes: map[string]string{
				"tool_execution_id":    "engine-fixture-" + calculation.ReceiptID,
				"receipt_id":           calculation.ReceiptID,
				"operation_id":         calculation.OperationID,
				"engine_id":            calculation.EngineID,
				"formula_version":      calculation.FormulaVersion,
				"output_count":         strconv.Itoa(len(calculation.Outputs)),
				"output_ref_ids":       strings.Join(outputRefs, "+"),
				"invariant_count":      strconv.Itoa(len(calculation.InvariantResults)),
				"invariants_passed":    strconv.FormatBool(invariantsPassed),
				"warning_count":        strconv.Itoa(len(calculation.Warnings)),
				"receipt_sha256":       calculation.ReceiptSHA,
				"receipt_verification": "metadata_only",
				"code":                 string(calculation.Status),
			},
		})
	}
	return events, nil
}

func validateSuccessfulFixtureCalculation(calculation CalculationCard) error {
	for label, value := range map[string]string{
		"receipt_id":      calculation.ReceiptID,
		"operation_id":    calculation.OperationID,
		"engine_id":       calculation.EngineID,
		"formula_version": calculation.FormulaVersion,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("successful fixture calculation requires %s", label)
		}
	}
	if len(calculation.ReceiptSHA) != sha256.Size*2 {
		return fmt.Errorf("fixture receipt %q has an invalid sha256 length", calculation.ReceiptID)
	}
	if _, err := hex.DecodeString(calculation.ReceiptSHA); err != nil {
		return fmt.Errorf("fixture receipt %q has an invalid sha256: %w", calculation.ReceiptID, err)
	}
	if len(calculation.Outputs) == 0 {
		return fmt.Errorf("fixture receipt %q has no outputs", calculation.ReceiptID)
	}
	for _, output := range calculation.Outputs {
		if strings.TrimSpace(output.OutputID) == "" {
			return fmt.Errorf("fixture receipt %q has an output without identity", calculation.ReceiptID)
		}
	}
	if len(calculation.InvariantResults) == 0 {
		return fmt.Errorf("fixture receipt %q has no invariant results", calculation.ReceiptID)
	}
	for _, invariant := range calculation.InvariantResults {
		if !invariant.Passed {
			return fmt.Errorf("fixture receipt %q contains a failed invariant", calculation.ReceiptID)
		}
	}
	return nil
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
		"interpretation:completed":              "Governed request interpretation complete",
		"interpretation:clarification_required": "Clarification required before planning",
		"planning:completed":                    "Bounded research plan complete",
		"plan:accepted":                         "Research plan accepted",
		"context:started":                       "Specialist context started",
		"context:completed":                     "Specialist context ready",
		"context:failed":                        "Specialist context degraded",
		"retrieval:completed":                   "Authorized evidence retrieval complete",
		"retrieval:failed":                      "Authorized evidence retrieval unavailable",
		"tool:completed":                        "Deterministic engine receipt ready",
		"tool:failed":                           "Deterministic engine receipt unavailable",
		"review:started":                        "Independent review started",
		"review:completed":                      "Independent review complete",
		"synthesis:started":                     "Final synthesis started",
		"synthesis:completed":                   "Final synthesis complete",
		"run:completed":                         "Research run completed",
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
	case "clarification_required":
		return "Clarification required before planning"
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

func cloneExecutionPlan(projection executionplan.Projection) executionplan.Projection {
	payload, _ := json.Marshal(projection)
	var clone executionplan.Projection
	_ = json.Unmarshal(payload, &clone)
	return clone
}

func cloneExecutionPlanPointer(projection *executionplan.Projection) *executionplan.Projection {
	if projection == nil {
		return nil
	}
	clone := cloneExecutionPlan(*projection)
	return &clone
}

func safeStreamAttributes(attributes map[string]string) map[string]string {
	allowed := map[string]bool{
		"answer_id": true, "code": true, "packet_id": true, "plan_id": true,
		"report_id": true, "role_id": true, "route": true, "route_reason_code": true,
		"attempt": true, "call_kind": true, "previous_route": true, "case_id": true,
		"as_of": true, "engine_id": true, "evidence_count": true, "formula_version": true,
		"input_count": true, "input_ref_ids": true, "invariant_count": true, "invariants_passed": true,
		"operation_id": true, "output_count": true, "output_ref_ids": true, "receipt_id": true,
		"receipt_sha256": true, "receipt_verification": true,
		"source_classes": true, "warning_count": true,
		"retrieval_id": true, "bundle_id": true, "retrieval_method": true,
		"candidate_count": true, "selected_candidate_count": true,
		"rejected_candidate_count": true, "candidate_count_state": true,
		"tool_execution_id": true,
		"primary_intent":    true, "entity_count": true, "entity_ids": true,
		"answer_depth": true, "ambiguity_count": true, "requested_output_count": true,
		"role_count": true, "wave_count": true, "max_parallel_specialists": true,
		"max_repair_passes": true, "deadline_ms": true, "completion_condition_count": true,
		"abstention_condition_count": true,
		"completion_conditions":      true, "abstention_conditions": true,
		"finding_count": true, "counterevidence_count": true,
		"missing_evidence_count": true, "conflict_count": true,
		"uncertainty_count": true, "evidence_coverage": true, "authority_state": true,
		"approved_claim_count": true, "rejected_claim_count": true,
		"issue_count": true, "repair_pass": true,
		"mandatory_review_count": true, "claim_count": true,
		"supported_claim_coverage": true, "evidence_ref_count": true,
		"receipt_ref_count": true, "limitation_count": true, "section_count": true,
		"freshness_state": true, "fact_count": true, "calculation_count": true,
		"inference_count": true, "hypothesis_count": true, "assumption_count": true,
		"wave": true, "specialist_count": true, "concurrency_limit": true,
		"succeeded_count": true, "failed_count": true, "observed_concurrency": true,
	}
	safe := map[string]string{}
	for key, value := range attributes {
		value = strings.TrimSpace(value)
		if !allowed[key] || value == "" || len(value) > 256 {
			continue
		}
		valid := true
		for index, character := range value {
			if !(character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' ||
				character >= '0' && character <= '9' || strings.ContainsRune("._:/@+-", character)) ||
				index == 0 && strings.ContainsRune(".:", character) {
				valid = false
				break
			}
		}
		if valid {
			safe[key] = value
		}
	}
	if len(safe) == 0 {
		return nil
	}
	return safe
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

func availability(available bool) string {
	if available {
		return "available"
	}
	return "disabled"
}

func spaHandler(api http.Handler, staticDir string) http.Handler {
	root, err := filepath.Abs(staticDir)
	if err != nil {
		root = staticDir
	}
	files := http.FileServer(http.Dir(root))
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if strings.HasPrefix(request.URL.Path, "/api/") ||
			strings.HasPrefix(request.URL.Path, "/health/") ||
			request.URL.Path == "/metrics" {
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
