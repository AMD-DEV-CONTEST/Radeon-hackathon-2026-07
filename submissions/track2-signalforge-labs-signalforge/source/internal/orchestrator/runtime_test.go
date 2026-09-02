package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/executionplan"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type fakeSpecialist struct {
	mu        sync.Mutex
	active    int
	maximum   int
	attempts  map[string]int
	starts    []string
	temporary bool
	block     bool
	conflicts []string
}

type receiptSpecialist struct{ delegate *fakeSpecialist }

func (specialist receiptSpecialist) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	packet, err := specialist.delegate.Run(ctx, request)
	if err != nil {
		return contracts.ContextPacket{}, err
	}
	receipt := validRuntimeTestReceipt("receipt-"+request.StepID, request.Scope.AsOf)
	receipt.RequestID = request.ContextRequestID
	receipt.OperationID = "financial.free_cash_flow"
	packet.CalculationReceipts = []contracts.CalculationReceipt{receipt}
	return packet, nil
}

type observedRuntimeSpecialist struct{ delegate *fakeSpecialist }

func (specialist observedRuntimeSpecialist) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	return specialist.delegate.Run(ctx, request)
}

type failingObservedSpecialist struct{ stage string }

func (specialist failingObservedSpecialist) Run(context.Context, contracts.ContextRequest) (contracts.ContextPacket, error) {
	return contracts.ContextPacket{}, errors.New("observed specialist failure")
}

func (specialist failingObservedSpecialist) RunObserved(_ context.Context, request contracts.ContextRequest, observer SpecialistLifecycleObserver) (contracts.ContextPacket, error) {
	retrieval := RetrievalLifecycle{
		RetrievalID: "retrieval-" + request.ContextRequestID,
		Method:      "bm25/v1",
		AsOf:        request.Scope.AsOf,
	}
	observer.RetrievalStarted(retrieval)
	if specialist.stage == "retrieval" {
		retrieval.FailureCode = "material_load_failed"
		observer.RetrievalFailed(retrieval)
		return contracts.ContextPacket{}, errors.New("retrieval failed")
	}
	retrieval.BundleID = "bundle-" + request.ContextRequestID
	retrieval.EvidenceCount = 1
	retrieval.SourceClasses = []string{"sec_filing"}
	observer.RetrievalPassed(retrieval)
	tool := ToolLifecycle{
		ToolExecutionID: "calc-" + request.StepID,
		EngineID:        "test-engine", OperationID: "financial.margin", FormulaVersion: "ratio/v1",
	}
	observer.ToolStarted(tool)
	tool.FailureCode = "engine_execution_failed"
	observer.ToolFailed(tool)
	return contracts.ContextPacket{}, errors.New("tool failed")
}

func (specialist observedRuntimeSpecialist) RunObserved(ctx context.Context, request contracts.ContextRequest, observer SpecialistLifecycleObserver) (contracts.ContextPacket, error) {
	retrieval := RetrievalLifecycle{
		RetrievalID: "retrieval-" + request.ContextRequestID,
		BundleID:    "bundle-" + request.ContextRequestID,
		Method:      "bm25/v1", EvidenceCount: 1, SourceClasses: []string{"sec_filing"},
		AsOf: request.Scope.AsOf, CandidateCount: 3, SelectedCandidateCount: 1,
		RejectedCandidateCount: 2, CandidateCountsKnown: true,
	}
	observer.RetrievalStarted(retrieval)
	observer.RetrievalPassed(retrieval)
	tool := ToolLifecycle{
		ToolExecutionID: "calc-" + request.StepID,
		ReceiptID:       "receipt-" + request.StepID,
		ReceiptSHA:      strings.Repeat("a", 64),
		EngineID:        "test-engine", OperationID: "financial.margin",
		FormulaVersion: "ratio/v1", InputRefIDs: []string{"revenue"},
		OutputRefIDs: []string{"margin"}, InputCount: 1, OutputCount: 1,
		InvariantCount: 1, InvariantsPassed: true,
	}
	observer.ToolStarted(tool)
	observer.ToolPassed(tool)
	return specialist.delegate.Run(ctx, request)
}

type memoryTraceStore struct {
	mu     sync.Mutex
	traces []Trace
}

func (store *memoryTraceStore) Save(trace Trace) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.traces = append(store.traces, trace)
	return nil
}

func (specialist *fakeSpecialist) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	specialist.mu.Lock()
	if specialist.attempts == nil {
		specialist.attempts = map[string]int{}
	}
	specialist.attempts[request.StepID]++
	attempt := specialist.attempts[request.StepID]
	specialist.starts = append(specialist.starts, request.SpecialistRole)
	specialist.active++
	if specialist.active > specialist.maximum {
		specialist.maximum = specialist.active
	}
	specialist.mu.Unlock()
	defer func() { specialist.mu.Lock(); specialist.active--; specialist.mu.Unlock() }()
	if specialist.block {
		<-ctx.Done()
		return contracts.ContextPacket{}, ctx.Err()
	}
	if specialist.temporary && attempt == 1 {
		return contracts.ContextPacket{}, temporaryError{message: "transient adapter failure"}
	}
	time.Sleep(5 * time.Millisecond)
	return contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-" + request.StepID,
		RunID: request.RunID, StepID: request.StepID, SpecialistRole: request.SpecialistRole,
		Objective: request.Objective, Scope: request.Scope,
		Findings: []contracts.Finding{{
			ClaimID: "claim-" + request.StepID, ClaimType: contracts.ClaimFact,
			Statement: "Supported finding.", EvidenceRefs: []string{"evidence-1"},
			Confidence: 0.9, ValidAsOf: request.Scope.AsOf,
		}},
		Evidence:  []contracts.EvidenceRef{{EvidenceID: "evidence-1", SourceType: "sec_filing", Locator: "item-1", ContentSHA: "abc", AsOf: request.Scope.AsOf}},
		Conflicts: append([]string(nil), specialist.conflicts...),
	}, nil
}

type assumptionCapturingSpecialist struct {
	delegate    *fakeSpecialist
	mu          sync.Mutex
	assumptions [][]string
}

type lineageCapturingSpecialist struct {
	delegate *fakeSpecialist
	mu       sync.Mutex
	requests []contracts.ContextRequest
}

func (specialist *lineageCapturingSpecialist) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	specialist.mu.Lock()
	specialist.requests = append(specialist.requests, request)
	specialist.mu.Unlock()
	return specialist.delegate.Run(ctx, request)
}

func (specialist *assumptionCapturingSpecialist) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	specialist.mu.Lock()
	specialist.assumptions = append(specialist.assumptions, append([]string(nil), request.Assumptions...))
	specialist.mu.Unlock()
	return specialist.delegate.Run(ctx, request)
}

type fakeReviewer struct{}

func (fakeReviewer) Review(_ context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	claims := []string{"no-context-claim"}
	if len(input.Packets) > 0 {
		claims = nil
		for _, packet := range input.Packets {
			for _, finding := range packet.Findings {
				claims = append(claims, finding.ClaimID)
			}
		}
	}
	return contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-" + input.Step.StepID,
		RunID: input.Request.RunID, ReviewerRole: input.Step.RoleID, Decision: contracts.CritiqueApprove,
		ApprovedClaims: claims, RepairPass: input.RepairPass, CreatedAt: input.Request.AsOf,
	}, nil
}

type countingReviewer struct {
	mu    sync.Mutex
	calls int
}

func (reviewer *countingReviewer) Review(ctx context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	reviewer.mu.Lock()
	reviewer.calls++
	reviewer.mu.Unlock()
	return (fakeReviewer{}).Review(ctx, input)
}

type fakeSynthesizer struct {
	mu    sync.Mutex
	calls int
}

func (synthesizer *fakeSynthesizer) Synthesize(_ context.Context, input SynthesisInput) (contracts.FinalAnswer, error) {
	synthesizer.mu.Lock()
	synthesizer.calls++
	synthesizer.mu.Unlock()
	sections := []contracts.AnswerSection{}
	for _, sectionType := range contracts.RequiredFinalSections(input.Request.PrimaryIntent) {
		section := contracts.AnswerSection{SectionType: sectionType, Title: sectionType, Content: "Evidence-aware content."}
		if sectionType != "evidence" && sectionType != "limitations" {
			section.ClaimRefs = []string{"claim-context-01"}
			section.EvidenceRefs = []string{"evidence-1"}
		}
		sections = append(sections, section)
	}
	critiqueRefs := []string{}
	for _, critique := range input.Critiques {
		critiqueRefs = append(critiqueRefs, critique.ReportID)
	}
	return contracts.FinalAnswer{
		SchemaVersion: contracts.SchemaVersionV1, AnswerID: "answer-1", RunID: input.Request.RunID,
		RequestID: input.Request.RequestID, PrimaryIntent: input.Request.PrimaryIntent, AsOf: input.Request.AsOf,
		Sections: sections, CritiqueRefs: critiqueRefs, ReleasedBy: roles.FinalResearchAnalyst, ReleasedAt: input.Request.AsOf,
	}, nil
}

type temporaryError struct{ message string }

func (err temporaryError) Error() string   { return err.message }
func (err temporaryError) Temporary() bool { return true }

type attemptAwareTemporarySpecialist struct {
	delegate *fakeSpecialist
	attempts map[string][]int
}

func (specialist *attemptAwareTemporarySpecialist) Run(context.Context, contracts.ContextRequest) (contracts.ContextPacket, error) {
	return contracts.ContextPacket{}, errors.New("legacy specialist entrypoint must not run")
}

func (specialist *attemptAwareTemporarySpecialist) RunAttempt(ctx context.Context, request contracts.ContextRequest, attempt int) (contracts.ContextPacket, error) {
	if specialist.attempts == nil {
		specialist.attempts = map[string][]int{}
	}
	specialist.attempts[request.StepID] = append(specialist.attempts[request.StepID], attempt)
	if attempt == 0 {
		return contracts.ContextPacket{}, temporaryError{message: "truncated specialist attempt"}
	}
	return specialist.delegate.Run(ctx, request)
}

type retryingReviewer struct {
	mu       sync.Mutex
	attempts map[string]int
}

func (reviewer *retryingReviewer) Review(ctx context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	reviewer.mu.Lock()
	if reviewer.attempts == nil {
		reviewer.attempts = map[string]int{}
	}
	reviewer.attempts[input.Step.RoleID]++
	attempt := reviewer.attempts[input.Step.RoleID]
	reviewer.mu.Unlock()
	if attempt == 1 {
		return contracts.CritiqueReport{}, temporaryError{message: "transient reviewer failure"}
	}
	return (fakeReviewer{}).Review(ctx, input)
}

type retryingSynthesizer struct {
	mu       sync.Mutex
	attempts int
}

type repairThenApproveReviewer struct {
	calls                 int
	sawSourceOnRepairPass bool
}

func (reviewer *repairThenApproveReviewer) Review(_ context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	reviewer.calls++
	claimID := ""
	for _, packet := range input.Packets {
		for _, finding := range packet.Counterevidence {
			if finding.Origin == contracts.FindingOriginSourceExtraction {
				claimID = finding.ClaimID
			}
		}
	}
	if input.RepairPass == 0 {
		return contracts.CritiqueReport{
			SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-risk-p0", RunID: input.Request.RunID,
			ReviewerRole: input.Step.RoleID, Decision: contracts.CritiqueRepair,
			RejectedClaims: []string{claimID}, Issues: []contracts.CritiqueIssue{{
				IssueID: "evaluate-impact", Severity: "medium", ClaimRefs: []string{claimID},
				Description: "Evaluate whether the disclosed risk challenges the thesis.",
			}},
			RepairPass: 0, CreatedAt: input.Request.AsOf,
		}, nil
	}
	reviewer.sawSourceOnRepairPass = claimID != ""
	return contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-risk-p1", RunID: input.Request.RunID,
		ReviewerRole: input.Step.RoleID, Decision: contracts.CritiqueApprove,
		ApprovedClaims: []string{claimID}, RepairPass: 1, CreatedAt: input.Request.AsOf,
	}, nil
}

func (synthesizer *retryingSynthesizer) Synthesize(ctx context.Context, input SynthesisInput) (contracts.FinalAnswer, error) {
	synthesizer.mu.Lock()
	synthesizer.attempts++
	attempt := synthesizer.attempts
	synthesizer.mu.Unlock()
	if attempt == 1 {
		return contracts.FinalAnswer{}, temporaryError{message: "transient synthesis failure"}
	}
	return (&fakeSynthesizer{}).Synthesize(ctx, input)
}

type conflictObserver struct {
	mu                 sync.Mutex
	reviewerConflicts  []string
	synthesisConflicts []string
}

type dashboardProjectionSink struct {
	mu         sync.Mutex
	projection *executionplan.Projection
	err        error
}

type adapterTranscriptEntry struct {
	Boundary string          `json:"boundary"`
	Key      string          `json:"key"`
	Request  json.RawMessage `json:"request"`
	Response json.RawMessage `json:"response"`
}

type adapterTranscript struct {
	mu      sync.Mutex
	entries []adapterTranscriptEntry
}

func (transcript *adapterTranscript) record(boundary, key string, request, response any) error {
	requestPayload, err := json.Marshal(request)
	if err != nil {
		return err
	}
	responsePayload, err := json.Marshal(response)
	if err != nil {
		return err
	}
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	transcript.entries = append(transcript.entries, adapterTranscriptEntry{
		Boundary: boundary, Key: key, Request: requestPayload, Response: responsePayload,
	})
	return nil
}

func (transcript *adapterTranscript) canonical() ([]byte, error) {
	transcript.mu.Lock()
	entries := append([]adapterTranscriptEntry(nil), transcript.entries...)
	transcript.mu.Unlock()
	sort.Slice(entries, func(left, right int) bool {
		if entries[left].Boundary != entries[right].Boundary {
			return entries[left].Boundary < entries[right].Boundary
		}
		return entries[left].Key < entries[right].Key
	})
	return json.Marshal(entries)
}

type transcriptSpecialist struct {
	delegate   Specialist
	transcript *adapterTranscript
}

func (specialist transcriptSpecialist) Run(ctx context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	packet, err := specialist.delegate.Run(ctx, request)
	if err != nil {
		return contracts.ContextPacket{}, err
	}
	if recordErr := specialist.transcript.record("specialist", request.StepID, request, packet); recordErr != nil {
		return contracts.ContextPacket{}, recordErr
	}
	return packet, nil
}

type transcriptReviewer struct {
	delegate   Reviewer
	transcript *adapterTranscript
}

func (reviewer transcriptReviewer) Review(ctx context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	report, err := reviewer.delegate.Review(ctx, input)
	if err != nil {
		return contracts.CritiqueReport{}, err
	}
	key := input.Step.StepID + ":" + report.ReportID
	if recordErr := reviewer.transcript.record("reviewer", key, input, report); recordErr != nil {
		return contracts.CritiqueReport{}, recordErr
	}
	return report, nil
}

type transcriptSynthesizer struct {
	delegate   Synthesizer
	transcript *adapterTranscript
}

func (synthesizer transcriptSynthesizer) Synthesize(ctx context.Context, input SynthesisInput) (contracts.FinalAnswer, error) {
	answer, err := synthesizer.delegate.Synthesize(ctx, input)
	if err != nil {
		return contracts.FinalAnswer{}, err
	}
	if recordErr := synthesizer.transcript.record("synthesizer", input.Request.RunID, input, answer); recordErr != nil {
		return contracts.FinalAnswer{}, recordErr
	}
	return answer, nil
}

type panickingObservabilitySink struct{}

func (panickingObservabilitySink) AcceptPlan(contracts.ResearchPlan, time.Time) {
	panic("observability plan sink unavailable")
}

func (panickingObservabilitySink) Emit(Event) {
	panic("observability event sink unavailable")
}

func (sink *dashboardProjectionSink) AcceptPlan(plan contracts.ResearchPlan, at time.Time) {
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

func (sink *dashboardProjectionSink) Emit(event Event) {
	sink.mu.Lock()
	defer sink.mu.Unlock()
	if sink.err != nil {
		return
	}
	if sink.projection == nil {
		sink.err = errors.New("dashboard received an event before the accepted plan")
		return
	}
	sink.err = executionplan.Apply(sink.projection, executionplan.Event{
		Sequence: event.Sequence, StepID: event.StepID, Type: event.Type,
		Status: event.Status, At: event.At, Attributes: event.Attributes,
	})
}

func (sink *dashboardProjectionSink) snapshot() (executionplan.Projection, error) {
	sink.mu.Lock()
	defer sink.mu.Unlock()
	if sink.projection == nil {
		return executionplan.Projection{}, errors.New("dashboard projection was not created")
	}
	payload, err := json.Marshal(sink.projection)
	if err != nil {
		return executionplan.Projection{}, err
	}
	var projection executionplan.Projection
	if err := json.Unmarshal(payload, &projection); err != nil {
		return executionplan.Projection{}, err
	}
	return projection, sink.err
}

func (observer *conflictObserver) Review(ctx context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	observer.mu.Lock()
	for _, packet := range input.Packets {
		observer.reviewerConflicts = append(observer.reviewerConflicts, packet.Conflicts...)
	}
	observer.mu.Unlock()
	return (fakeReviewer{}).Review(ctx, input)
}

func (observer *conflictObserver) Synthesize(ctx context.Context, input SynthesisInput) (contracts.FinalAnswer, error) {
	observer.mu.Lock()
	for _, packet := range input.Packets {
		observer.synthesisConflicts = append(observer.synthesisConflicts, packet.Conflicts...)
	}
	observer.mu.Unlock()
	return (&fakeSynthesizer{}).Synthesize(ctx, input)
}

func TestObservabilityFailureCannotBlockResearch(t *testing.T) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	specialist := &fakeSpecialist{}
	synthesizer := &fakeSynthesizer{}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: synthesizer,
		Sink: panickingObservabilitySink{}, TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion.", AsOf: now,
		RunID: "run-observability-failure", RequestID: "request-observability-failure",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil || result.Answer == nil || result.Answer.AnswerID != "answer-1" {
		t.Fatalf("observability failure affected governed research: %+v", result)
	}
	if synthesizer.calls != 1 || len(result.Trace.Events) == 0 {
		t.Fatalf("research did not preserve its authoritative execution: calls=%d trace=%+v", synthesizer.calls, result.Trace)
	}
}

func TestExecutionDashboardIsObservationallyEquivalent(t *testing.T) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	journeys := []struct {
		name string
		text string
	}{
		{name: "cash-conversion", text: "Compare Microsoft and NVIDIA on cash conversion."},
		{
			name: "full-research",
			text: "Compare Microsoft and NVIDIA as long-term businesses under higher-for-longer interest rates and slower AI infrastructure spending. Include accounting, market behavior, DCF valuation, and assumptions implied by market prices.",
		},
		{name: "market-behavior", text: "How sensitive have Microsoft and NVIDIA been to the Nasdaq?"},
	}
	for _, journey := range journeys {
		t.Run(journey.name, func(t *testing.T) {
			request, err := requestparser.ParseDeterministic(requestparser.Input{
				Text: journey.text, AsOf: now,
				RunID: "run-dashboard-" + journey.name, RequestID: "request-dashboard-" + journey.name,
			})
			if err != nil {
				t.Fatal(err)
			}
			run := func(sink EventSink) ([]byte, int, []byte, Trace) {
				t.Helper()
				specialist := &fakeSpecialist{}
				reviewer := &countingReviewer{}
				synthesizer := &fakeSynthesizer{}
				transcript := &adapterTranscript{}
				runtime, newErr := New(Dependencies{
					Specialist: transcriptSpecialist{
						delegate: receiptSpecialist{delegate: specialist}, transcript: transcript,
					},
					Reviewer: transcriptReviewer{delegate: reviewer, transcript: transcript},
					Synthesizer: transcriptSynthesizer{
						delegate: synthesizer, transcript: transcript,
					},
					Sink: sink, TraceStore: &memoryTraceStore{},
				})
				if newErr != nil {
					t.Fatal(newErr)
				}
				runtime.Now = func() time.Time { return now }
				result := runtime.Run(context.Background(), request)
				if result.Failure != nil || result.Answer == nil {
					t.Fatalf("unexpected ablation result: %+v", result)
				}
				answer, marshalErr := json.Marshal(result.Answer)
				if marshalErr != nil {
					t.Fatal(marshalErr)
				}
				specialist.mu.Lock()
				specialistCalls := 0
				for _, attempts := range specialist.attempts {
					specialistCalls += attempts
				}
				specialist.mu.Unlock()
				reviewer.mu.Lock()
				reviewerCalls := reviewer.calls
				reviewer.mu.Unlock()
				synthesizer.mu.Lock()
				synthesisCalls := synthesizer.calls
				synthesizer.mu.Unlock()
				canonicalTranscript, transcriptErr := transcript.canonical()
				if transcriptErr != nil {
					t.Fatal(transcriptErr)
				}
				return answer, specialistCalls + reviewerCalls + synthesisCalls, canonicalTranscript, result.Trace
			}

			baselineAnswer, baselineCalls, baselineTranscript, baselineTrace := run(nil)
			dashboard := &dashboardProjectionSink{}
			dashboardAnswer, dashboardCalls, dashboardTranscript, dashboardTrace := run(dashboard)
			if string(dashboardAnswer) != string(baselineAnswer) {
				t.Fatalf("dashboard changed final answer bytes:\nbaseline=%s\ndashboard=%s", baselineAnswer, dashboardAnswer)
			}
			if dashboardCalls != baselineCalls {
				t.Fatalf("dashboard changed governed adapter calls: baseline=%d dashboard=%d", baselineCalls, dashboardCalls)
			}
			if string(dashboardTranscript) != string(baselineTranscript) {
				t.Fatalf(
					"dashboard changed canonical model-boundary requests or responses:\nbaseline=%s\ndashboard=%s",
					baselineTranscript, dashboardTranscript,
				)
			}
			if len(dashboardTrace.Events) != len(baselineTrace.Events) {
				t.Fatalf("dashboard changed runtime event count: baseline=%d dashboard=%d", len(baselineTrace.Events), len(dashboardTrace.Events))
			}
			projection, err := dashboard.snapshot()
			if err != nil {
				t.Fatal(err)
			}
			if projection.Status != executionplan.StatusRunning ||
				projection.LastSequence != len(dashboardTrace.Events) ||
				projection.ProgressRatio != 1 {
				t.Fatalf("dashboard did not reconcile the complete orchestrator runtime: %+v", projection)
			}
			dashboard.Emit(Event{
				Sequence: len(dashboardTrace.Events) + 1, RunID: request.RunID,
				Type: "workspace", Status: "completed", At: now,
			})
			projection, err = dashboard.snapshot()
			if err != nil {
				t.Fatal(err)
			}
			if projection.Status != executionplan.StatusPassed ||
				projection.LastSequence != len(dashboardTrace.Events)+1 ||
				projection.ProgressRatio != 1 {
				t.Fatalf("dashboard did not reconcile the host completion boundary: %+v", projection)
			}
		})
	}
}

func BenchmarkExecutionDashboardCPUOverhead(b *testing.B) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA as long-term businesses under higher-for-longer interest rates and slower AI infrastructure spending. Include accounting, market behavior, DCF valuation, and assumptions implied by market prices.",
		AsOf: now, RunID: "run-dashboard-cpu", RequestID: "request-dashboard-cpu",
	})
	if err != nil {
		b.Fatal(err)
	}
	run := func(b *testing.B, dashboard bool) {
		b.Helper()
		b.ReportAllocs()
		for iteration := 0; iteration < b.N; iteration++ {
			var sink EventSink
			if dashboard {
				sink = &dashboardProjectionSink{}
			}
			runtime, newErr := New(Dependencies{
				Specialist:  receiptSpecialist{delegate: &fakeSpecialist{}},
				Reviewer:    &countingReviewer{},
				Synthesizer: &fakeSynthesizer{},
				Sink:        sink,
				TraceStore:  &memoryTraceStore{},
			})
			if newErr != nil {
				b.Fatal(newErr)
			}
			runtime.Now = func() time.Time { return now }
			result := runtime.Run(context.Background(), request)
			if result.Failure != nil || result.Answer == nil {
				b.Fatalf("unexpected benchmark result: %+v", result)
			}
		}
	}
	b.Run("baseline", func(b *testing.B) { run(b, false) })
	b.Run("dashboard", func(b *testing.B) { run(b, true) })
}

func TestRuntimeExecutesBoundedInspectableWorkflow(t *testing.T) {
	specialist := &fakeSpecialist{}
	synthesizer := &fakeSynthesizer{}
	store := &memoryTraceStore{}
	runtime, err := New(Dependencies{Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: synthesizer, TraceStore: store})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion.", AsOf: now, RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil || result.Answer == nil {
		t.Fatalf("unexpected result %+v", result)
	}
	if result.Trace.MaxConcurrentContext != 3 || specialist.maximum != 3 || synthesizer.calls != 1 {
		t.Fatalf("workflow was not bounded or singly synthesized: trace=%+v max=%d calls=%d", result.Trace, specialist.maximum, synthesizer.calls)
	}
	if len(result.Trace.PacketIDs) != 3 || len(result.Trace.CritiqueIDs) < 1 || len(result.Trace.Events) == 0 {
		t.Fatalf("trace is incomplete %+v", result.Trace)
	}
	routeStarts := 0
	retrievals := 0
	interpretations := 0
	plannings := 0
	reviews := 0
	releases := 0
	for _, event := range result.Trace.Events {
		if event.At.After(result.Trace.CompletedAt) {
			t.Fatalf("trace completed before event %d: %+v", event.Sequence, result.Trace)
		}
		if event.Status == "started" && (event.Type == "context" || event.Type == "review" || event.Type == "synthesis") {
			routeStarts++
			if event.Attributes["role_id"] == "" || event.Attributes["route_reason_code"] == "" {
				t.Fatalf("route event omitted safe decision attributes: %+v", event)
			}
		}
		if event.Type == "retrieval" && event.Status == "completed" {
			retrievals++
			if event.Attributes["packet_id"] == "" || event.Attributes["evidence_count"] != "1" ||
				event.Attributes["source_classes"] != "sec_filing" || event.Attributes["as_of"] != "2026-07-21" ||
				event.Attributes["finding_count"] != "1" || event.Attributes["evidence_coverage"] != "1_of_1" ||
				event.Attributes["freshness_state"] != "bounded_by_as_of" ||
				event.Attributes["fact_count"] != "1" || event.Attributes["calculation_count"] != "0" ||
				event.Attributes["inference_count"] != "0" || event.Attributes["hypothesis_count"] != "0" ||
				event.Attributes["assumption_count"] != "0" {
				t.Fatalf("retrieval event omitted its safe packet metadata: %+v", event)
			}
		}
		if event.Type == "interpretation" && event.Status == "completed" {
			interpretations++
			if event.Attributes["primary_intent"] == "" || event.Attributes["entity_count"] != "2" ||
				event.Attributes["as_of"] != "2026-07-21" {
				t.Fatalf("interpretation event omitted its safe boundary: %+v", event)
			}
		}
		if event.Type == "planning" && event.Status == "completed" {
			plannings++
			if event.Attributes["role_count"] == "" || event.Attributes["max_parallel_specialists"] != "4" ||
				event.Attributes["deadline_ms"] == "" ||
				event.Attributes["completion_condition_count"] == "" ||
				event.Attributes["completion_conditions"] == "" ||
				event.Attributes["abstention_conditions"] == "" {
				t.Fatalf("planning event omitted its safe boundary: %+v", event)
			}
		}
		if event.Type == "review" && event.Status == "approve" {
			reviews++
			if event.Attributes["report_id"] == "" || event.Attributes["approved_claim_count"] == "" ||
				event.Attributes["rejected_claim_count"] == "" || event.Attributes["issue_count"] == "" {
				t.Fatalf("review event omitted its safe governance counts: %+v", event)
			}
		}
		if (event.Type == "synthesis" && event.Status == "passed") ||
			(event.Type == "run" && event.Status == "completed") {
			releases++
			if event.Attributes["answer_id"] == "" || event.Attributes["mandatory_review_count"] == "" ||
				event.Attributes["claim_count"] == "" || event.Attributes["supported_claim_coverage"] == "" ||
				event.Attributes["evidence_ref_count"] == "" || event.Attributes["receipt_ref_count"] == "" ||
				event.Attributes["limitation_count"] == "" || event.Attributes["section_count"] == "" {
				t.Fatalf("release event omitted its safe governance metadata: %+v", event)
			}
		}
	}
	if routeStarts < 4 {
		t.Fatalf("expected context, review, and synthesis route starts, got %d", routeStarts)
	}
	if retrievals != 3 {
		t.Fatalf("expected one validated retrieval event per packet, got %d", retrievals)
	}
	if interpretations != 1 || plannings != 1 {
		t.Fatalf("expected one safe interpretation and planning event, got %d and %d", interpretations, plannings)
	}
	if reviews != 2 || releases != 2 {
		t.Fatalf("expected two review approvals and two release events, got %d and %d", reviews, releases)
	}
	if len(store.traces) != 1 || store.traces[0].AnswerID != "answer-1" {
		t.Fatalf("completed trace was not persisted: %+v", store.traces)
	}
}

func TestRuntimeEmitsClarificationBoundaryBeforePlanning(t *testing.T) {
	runtime, err := New(Dependencies{
		Specialist: &fakeSpecialist{}, Reviewer: fakeReviewer{},
		Synthesizer: &fakeSynthesizer{}, TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "How sensitive has this stock been to the Nasdaq?", AsOf: now,
		RunID: "run-clarify", RequestID: "request-clarify",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure == nil || result.Failure.FailureCode != "clarification_required" ||
		result.Answer != nil {
		t.Fatalf("ambiguous request did not fail closed: %+v", result)
	}
	clarifications := 0
	for _, event := range result.Trace.Events {
		if event.Type == "interpretation" && event.Status == "clarification_required" {
			clarifications++
			if event.Attributes["ambiguity_count"] != "1" ||
				event.Attributes["primary_intent"] == "" {
				t.Fatalf("clarification event omitted its safe boundary: %+v", event)
			}
		}
		if event.Type == "planning" || event.Type == "plan" {
			t.Fatalf("ambiguous request must not pretend planning began: %+v", event)
		}
	}
	if clarifications != 1 {
		t.Fatalf("expected one clarification event, got %d", clarifications)
	}
}

func TestRuntimeEmitsDeterministicReceiptEvents(t *testing.T) {
	specialist := receiptSpecialist{delegate: &fakeSpecialist{}}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{},
		Synthesizer: &fakeSynthesizer{}, TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion.", AsOf: now,
		RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil {
		t.Fatalf("unexpected runtime failure: %+v", result.Failure)
	}
	tools := 0
	for _, event := range result.Trace.Events {
		if event.Type != "tool" || event.Status != "completed" {
			continue
		}
		tools++
		if event.Attributes["receipt_id"] == "" ||
			event.Attributes["operation_id"] != "financial.free_cash_flow" ||
			event.Attributes["engine_id"] != "test-engine" ||
			event.Attributes["input_ref_ids"] != "input-1" ||
			event.Attributes["output_count"] != "1" ||
			event.Attributes["output_ref_ids"] != "output-1" ||
			event.Attributes["warning_count"] != "0" {
			t.Fatalf("tool event omitted safe deterministic receipt metadata: %+v", event)
		}
	}
	if tools != 3 {
		t.Fatalf("expected one deterministic receipt event per specialist packet, got %d", tools)
	}
}

func TestRuntimeProjectsObservedSpecialistLifecycleWithoutLegacyDuplicates(t *testing.T) {
	runtime, err := New(Dependencies{
		Specialist: observedRuntimeSpecialist{delegate: &fakeSpecialist{}},
		Reviewer:   fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion.", AsOf: now,
		RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil {
		t.Fatalf("unexpected runtime failure: %+v", result.Failure)
	}
	retrievalStarted, retrievalPassed, toolsStarted, toolsPassed := 0, 0, 0, 0
	for _, event := range result.Trace.Events {
		switch {
		case event.Type == "retrieval" && event.Status == "started":
			retrievalStarted++
		case event.Type == "retrieval" && event.Status == "passed":
			retrievalPassed++
			if event.Attributes["retrieval_method"] != "bm25/v1" ||
				event.Attributes["candidate_count"] != "3" ||
				event.Attributes["rejected_candidate_count"] != "2" {
				t.Fatalf("retrieval event omitted bounded lifecycle metadata: %+v", event)
			}
		case event.Type == "retrieval" && event.Status == "completed":
			t.Fatalf("observed specialist received a duplicate legacy retrieval event: %+v", event)
		case event.Type == "tool" && event.Status == "started":
			toolsStarted++
		case event.Type == "tool" && event.Status == "passed":
			toolsPassed++
			if event.Attributes["tool_execution_id"] == "" ||
				event.Attributes["receipt_id"] == "" ||
				event.Attributes["operation_id"] != "financial.margin" {
				t.Fatalf("tool event omitted bounded lifecycle metadata: %+v", event)
			}
		case event.Type == "tool" && event.Status == "completed":
			t.Fatalf("observed specialist received a duplicate legacy tool event: %+v", event)
		}
	}
	want := len(result.Packets)
	if retrievalStarted != want || retrievalPassed != want || toolsStarted != want || toolsPassed != want {
		t.Fatalf("lifecycle counts retrieval=%d/%d tools=%d/%d packets=%d",
			retrievalStarted, retrievalPassed, toolsStarted, toolsPassed, want)
	}
}

func TestRuntimeFailureMatrixProjectsRetrievalAndToolFailures(t *testing.T) {
	for _, stage := range []string{"retrieval", "tool"} {
		t.Run(stage, func(t *testing.T) {
			sink := &dashboardProjectionSink{}
			runtime, err := New(Dependencies{
				Specialist: failingObservedSpecialist{stage: stage},
				Reviewer:   fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
				Sink: sink, TraceStore: &memoryTraceStore{},
			})
			if err != nil {
				t.Fatal(err)
			}
			now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
			runtime.Now = func() time.Time { return now }
			request, err := requestparser.ParseDeterministic(requestparser.Input{
				Text: "Compare Microsoft and NVIDIA on cash conversion.", AsOf: now,
				RunID: "run-" + stage, RequestID: "request-" + stage,
			})
			if err != nil {
				t.Fatal(err)
			}
			result := runtime.Run(context.Background(), request)
			expectedType := stage
			expectedAuthority := stage
			expectedCode := "material_load_failed"
			if stage == "tool" {
				expectedAuthority = "engine"
				expectedCode = "engine_execution_failed"
			}
			foundFailure := false
			for _, event := range result.Trace.Events {
				if event.Type == expectedType && event.Status == "failed" &&
					event.Attributes["code"] == expectedCode {
					foundFailure = true
				}
			}
			if !foundFailure {
				t.Fatalf("%s failure was absent from trace: %+v", stage, result.Trace.Events)
			}
			projection, err := sink.snapshot()
			if err != nil {
				t.Fatal(err)
			}
			foundChecklistFailure := false
			for _, step := range projection.Steps {
				for _, check := range step.Checklist {
					if check.Authority == expectedAuthority && check.Status == executionplan.StatusFailed {
						foundChecklistFailure = true
					}
				}
			}
			if !foundChecklistFailure {
				t.Fatalf("%s failure was absent from dashboard projection: %+v", stage, projection)
			}
		})
	}
}

func TestReviewRepairPreservesClaimsForBoundedReevaluation(t *testing.T) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	reviewer := &repairThenApproveReviewer{}
	runtime := &Runtime{
		Roles: roles.DefaultRegistry(), Deps: Dependencies{Reviewer: reviewer}, Now: func() time.Time { return now },
	}
	request := contracts.ResearchRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: "request-1", RunID: "run-1",
		UserText: "Pressure-test the thesis.", PrimaryIntent: "thesis_review", AsOf: now,
		RequestedOutputs: contracts.RequiredFinalSections("thesis_review"),
	}
	plan := contracts.ResearchPlan{MaxRepairPasses: 1}
	step := contracts.PlanStep{
		StepID: "review-02", Kind: "review", RoleID: roles.RiskContrarian,
		Objective: "Challenge the thesis.", TimeoutMS: 1000,
	}
	packets := []contracts.ContextPacket{{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-1", SpecialistRole: roles.BusinessStrategy, Objective: "Understand risks.",
		Scope: contracts.Scope{AsOf: now},
		Counterevidence: []contracts.Finding{{
			ClaimID: "risk-1", ClaimType: contracts.ClaimFact,
			Origin: contracts.FindingOriginSourceExtraction, Statement: "Export controls can restrict demand.",
			EvidenceRefs: []string{"evidence-1"}, Confidence: 1, ValidAsOf: now,
		}},
		Evidence: []contracts.EvidenceRef{{
			EvidenceID: "evidence-1", SourceType: "sec_filing", DocumentSection: "Item 1A. Risk Factors",
			Locator: "filing#risk", ContentSHA: "sha", AsOf: now,
		}},
	}}
	trace := Trace{RunID: "run-1", StartedAt: now}
	emitter := newEmitter("run-1", nil, runtime.Now, &trace)
	history, reviewed, err := runtime.runReview(context.Background(), request, plan, step, packets, nil, emitter)
	if err != nil {
		t.Fatal(err)
	}
	if reviewer.calls != 2 || !reviewer.sawSourceOnRepairPass {
		t.Fatalf("repair did not preserve the claim for reevaluation: reviewer=%+v", reviewer)
	}
	if len(history) != 2 || history[1].Decision != contracts.CritiqueApprove ||
		len(reviewed) != 1 || len(reviewed[0].Counterevidence) != 1 {
		t.Fatalf("bounded repair did not close with the approved claim: history=%+v packets=%+v", history, reviewed)
	}
}

func TestRuntimeExecutesGoldenSpecialistsInTwoBoundedWaves(t *testing.T) {
	specialist := &fakeSpecialist{}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA as long-term businesses under higher-for-longer interest rates and slower AI infrastructure spending. Include accounting, market behavior, DCF valuation, and assumptions implied by market prices.",
		AsOf: now, RunID: "run-golden", RequestID: "request-golden",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil || result.Answer == nil {
		t.Fatalf("unexpected golden workflow result: %+v", result)
	}
	if len(result.Trace.PacketIDs) != 6 || specialist.maximum != 4 || result.Trace.MaxConcurrentContext != 4 {
		t.Fatalf("expected six packets with maximum fan-out four: trace=%+v max=%d", result.Trace, specialist.maximum)
	}
	waveEvents := make([]Event, 0, 4)
	for _, event := range result.Trace.Events {
		if event.Type == "wave" {
			waveEvents = append(waveEvents, event)
		}
	}
	if len(waveEvents) != 4 {
		t.Fatalf("wave lifecycle events=%+v, want two started and two terminal events", waveEvents)
	}
	want := []struct {
		stepID      string
		status      string
		wave        string
		specialists string
		succeeded   string
		concurrency string
	}{
		{"context-wave-1", "started", "1", "4", "", ""},
		{"context-wave-1", "completed", "1", "4", "4", "4"},
		{"context-wave-2", "started", "2", "2", "", ""},
		{"context-wave-2", "completed", "2", "2", "2", "2"},
	}
	for index, expected := range want {
		event := waveEvents[index]
		if event.StepID != expected.stepID || event.Status != expected.status ||
			event.Attributes["wave"] != expected.wave ||
			event.Attributes["specialist_count"] != expected.specialists ||
			event.Attributes["succeeded_count"] != expected.succeeded ||
			event.Attributes["observed_concurrency"] != expected.concurrency {
			t.Fatalf("wave event %d=%+v, want %+v", index, event, expected)
		}
	}
}

func TestRuntimeUsesDeterministicOrderedBatchesWhenConcurrencyIsReduced(t *testing.T) {
	specialist := &fakeSpecialist{}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	runtime.ContextConcurrency = 2
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	runtime.Now = func() time.Time { return now }
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA as long-term businesses under higher-for-longer interest rates and slower AI infrastructure spending. Include accounting, market behavior, DCF valuation, and assumptions implied by market prices.",
		AsOf: now, RunID: "run-ordered", RequestID: "request-ordered",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil {
		t.Fatalf("unexpected failure: %+v", result.Failure)
	}
	if result.Trace.MaxConcurrentContext != 2 || specialist.maximum != 2 {
		t.Fatalf("expected physical concurrency two: trace=%d observed=%d", result.Trace.MaxConcurrentContext, specialist.maximum)
	}
	specialist.mu.Lock()
	starts := append([]string(nil), specialist.starts...)
	specialist.mu.Unlock()
	if len(starts) != 6 {
		t.Fatalf("started roles=%v, want six", starts)
	}
	assertRoleBatch(t, starts[0:2], roles.BusinessStrategy, roles.FinancialQuality)
	assertRoleBatch(t, starts[2:4], roles.EconomicsTransmission, roles.Valuation)
	assertRoleBatch(t, starts[4:6], roles.AccountingReporting, roles.MarketBehavior)
}

func TestRuntimeExecutesThreeGovernedFollowUpsWithScopeAndEvidenceLineage(t *testing.T) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	specialist := &lineageCapturingSpecialist{delegate: &fakeSpecialist{}}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	runtime.Now = func() time.Time { return now }
	parent, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA as long-term businesses.",
		AsOf: now, RunID: "followup-run-parent", RequestID: "followup-request-parent",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), parent)
	if result.Failure != nil || result.Answer == nil {
		t.Fatalf("parent run failed: %+v", result)
	}
	cases := []struct {
		text, runID, requestID, intent string
	}{
		{"And is that margin improvement supported by cash?", "followup-run-cash", "followup-request-cash", "financial_quality"},
		{"How sensitive have these two companies been to the Nasdaq?", "followup-run-market", "followup-request-market", "market_behavior"},
		{"What evidence would invalidate that thesis?", "followup-run-risk", "followup-request-risk", "thesis_review"},
	}
	for _, item := range cases {
		followUp, err := requestparser.NewFollowUpContext(parent, *result.Answer)
		if err != nil {
			t.Fatal(err)
		}
		child, err := requestparser.ParseDeterministic(requestparser.Input{
			Text: item.text, AsOf: now.Add(time.Hour), RunID: item.runID, RequestID: item.requestID,
			FollowUp: &followUp,
		})
		if err != nil {
			t.Fatal(err)
		}
		if child.PrimaryIntent != item.intent || child.ParentRequestID != parent.RequestID ||
			!child.AsOf.Equal(now) || len(child.Entities) != 2 || len(child.LineageEvidenceRefs) == 0 {
			t.Fatalf("follow-up request lost governed state: %+v", child)
		}
		before := len(specialist.requests)
		result = runtime.Run(context.Background(), child)
		if result.Failure != nil || result.Answer == nil {
			t.Fatalf("follow-up %q failed: %+v", item.text, result)
		}
		for _, contextRequest := range specialist.requests[before:] {
			if len(contextRequest.EvidenceRefs) == 0 || contextRequest.EvidenceRefs[0] != "evidence-1" {
				t.Fatalf("follow-up evidence lineage did not reach specialist %q: %+v", contextRequest.SpecialistRole, contextRequest)
			}
		}
		parent = child
	}
}

func assertRoleBatch(t *testing.T, got []string, first string, second string) {
	t.Helper()
	want := map[string]bool{first: true, second: true}
	if len(got) != 2 || !want[got[0]] || !want[got[1]] || got[0] == got[1] {
		t.Fatalf("role batch=%v, want {%s, %s}", got, first, second)
	}
}

func TestRuntimePropagatesResearchAssumptionsToSpecialists(t *testing.T) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA under higher-for-longer interest rates.",
		AsOf: now, RunID: "run-assumptions", RequestID: "request-assumptions",
	})
	if err != nil {
		t.Fatal(err)
	}
	request.Assumptions = []string{"Higher rates are a scenario, not a forecast."}
	specialist := &assumptionCapturingSpecialist{delegate: &fakeSpecialist{}}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	runtime.Now = func() time.Time { return now }
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil {
		t.Fatalf("unexpected failure: %+v", result.Failure)
	}
	specialist.mu.Lock()
	seen := append([][]string(nil), specialist.assumptions...)
	specialist.mu.Unlock()
	if len(seen) == 0 {
		t.Fatal("specialist was not called")
	}
	for index, assumptions := range seen {
		if len(assumptions) != 1 || assumptions[0] != request.Assumptions[0] {
			t.Fatalf("specialist call %d assumptions=%v, want %v", index, assumptions, request.Assumptions)
		}
	}
}

func TestNarrowContextPacketsRemovesCriticizedClaimsAndUnusedAuthority(t *testing.T) {
	now := time.Now().UTC()
	packets := []contracts.ContextPacket{{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-1", SpecialistRole: roles.FinancialQuality, Objective: "Compare quality.",
		Scope: contracts.Scope{AsOf: now},
		Findings: []contracts.Finding{
			{ClaimID: "keep", ClaimType: contracts.ClaimFact, Statement: "Keep.", EvidenceRefs: []string{"evidence-keep"}, Confidence: 1, ValidAsOf: now},
			{ClaimID: "remove", ClaimType: contracts.ClaimCalculation, Statement: "Remove.", CalculationRefs: []string{"receipt-remove"}, Confidence: 1, ValidAsOf: now},
		},
		Evidence: []contracts.EvidenceRef{
			{EvidenceID: "evidence-keep", SourceType: "sec_filing", Locator: "keep", ContentSHA: "a", AsOf: now},
			{EvidenceID: "evidence-unused", SourceType: "sec_filing", Locator: "unused", ContentSHA: "b", AsOf: now},
		},
		CalculationReceipts: []contracts.CalculationReceipt{{ReceiptID: "receipt-remove"}},
	}}
	report := contracts.CritiqueReport{Issues: []contracts.CritiqueIssue{{ClaimRefs: []string{"remove"}}}}
	narrowed, changed := narrowContextPackets(packets, report)
	if !changed || len(narrowed[0].Findings) != 1 || narrowed[0].Findings[0].ClaimID != "keep" {
		t.Fatalf("claims were not narrowed: %+v", narrowed)
	}
	if len(narrowed[0].Evidence) != 1 || narrowed[0].Evidence[0].EvidenceID != "evidence-keep" || len(narrowed[0].CalculationReceipts) != 0 {
		t.Fatalf("unused authority survived narrowing: %+v", narrowed[0])
	}
	if len(packets[0].Findings) != 2 || len(packets[0].Evidence) != 2 {
		t.Fatal("narrowing mutated the original packets")
	}
}

func TestNarrowContextPacketsClosesNumericalAuthorityWithRetainedClaims(t *testing.T) {
	now := time.Now().UTC()
	actual := contracts.NumericalVariable{
		VariableID: "actual-keep", EntityID: "adbe", MetricID: "free_cash_flow", Period: "FY2025",
		PeriodBasis: contracts.PeriodBasisNominalLabel, ComparisonKey: "adbe:free_cash_flow:FY2025",
		ValueKind: contracts.NumericalActual, Value: contracts.Quantity{Value: "10", Unit: "USD", Currency: "USD"},
		Method: contracts.NormalizationNone, EvidenceRefs: []string{"evidence-keep"}, AsOf: now,
	}
	derived := contracts.NumericalVariable{
		VariableID: "derived-remove", EntityID: "adbe", MetricID: "cash_conversion", Period: "FY2025",
		PeriodBasis: contracts.PeriodBasisNominalLabel, ComparisonKey: "adbe:cash_conversion:FY2025",
		ValueKind: contracts.NumericalDerivedView, Value: contracts.Quantity{Value: "0.9", Unit: "ratio"},
		Method: contracts.NormalizationAbsoluteDerived, FormulaVersion: "quality/v1",
		ReceiptRefs: []string{"receipt-remove"}, AsOf: now,
	}
	packets := []contracts.ContextPacket{{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-1", SpecialistRole: roles.FinancialQuality, Objective: "Assess quality.",
		Scope: contracts.Scope{AsOf: now},
		Findings: []contracts.Finding{
			{ClaimID: "keep", ClaimType: contracts.ClaimFact, Statement: "Keep.", EvidenceRefs: []string{"evidence-keep"}, NumericalRefs: []string{"actual-keep"}, Confidence: 1, ValidAsOf: now},
			{ClaimID: "remove", ClaimType: contracts.ClaimCalculation, Statement: "Remove.", CalculationRefs: []string{"receipt-remove"}, NumericalRefs: []string{"derived-remove"}, Confidence: 1, ValidAsOf: now},
		},
		Evidence: []contracts.EvidenceRef{
			{EvidenceID: "evidence-keep", SourceType: "sec_filing", Locator: "keep", ContentSHA: "a", AsOf: now},
			{EvidenceID: "evidence-remove", SourceType: "sec_filing", Locator: "remove", ContentSHA: "b", AsOf: now},
		},
		CalculationReceipts: []contracts.CalculationReceipt{{ReceiptID: "receipt-remove"}},
		NumericalContext: &contracts.NumericalContext{
			SchemaVersion: contracts.SchemaVersionV1, ContextID: "numerical-1", RunID: "run-1",
			Version: contracts.NumericalContextVersionV1, AsOf: now,
			Variables: []contracts.NumericalVariable{actual, derived},
		},
	}}

	narrowed, changed := narrowContextPackets(packets, contracts.CritiqueReport{
		Issues: []contracts.CritiqueIssue{{ClaimRefs: []string{"remove"}}},
	})
	if !changed {
		t.Fatal("expected numerical authority to be narrowed")
	}
	if err := contracts.ValidateContextPacket(narrowed[0]); err != nil {
		t.Fatalf("narrowed packet is invalid: %v", err)
	}
	if narrowed[0].NumericalContext == nil || len(narrowed[0].NumericalContext.Variables) != 1 ||
		narrowed[0].NumericalContext.Variables[0].VariableID != "actual-keep" {
		t.Fatalf("unexpected retained numerical context: %+v", narrowed[0].NumericalContext)
	}
	if len(narrowed[0].CalculationReceipts) != 0 || len(narrowed[0].Evidence) != 1 ||
		narrowed[0].Evidence[0].EvidenceID != "evidence-keep" {
		t.Fatalf("removed numerical authority survived: %+v", narrowed[0])
	}
	if len(packets[0].NumericalContext.Variables) != 2 {
		t.Fatal("narrowing mutated the original numerical context")
	}
}

func TestCloseExplicitlyApprovedSubsetClosesNumericalAuthority(t *testing.T) {
	now := time.Now().UTC()
	packet := contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-1", SpecialistRole: roles.FinancialQuality, Objective: "Assess quality.",
		Scope: contracts.Scope{AsOf: now},
		Findings: []contracts.Finding{
			{ClaimID: "keep", ClaimType: contracts.ClaimFact, Statement: "Keep.", EvidenceRefs: []string{"evidence-keep"}, NumericalRefs: []string{"actual-keep"}, Confidence: 1, ValidAsOf: now},
			{ClaimID: "drop", ClaimType: contracts.ClaimCalculation, Statement: "Drop.", CalculationRefs: []string{"receipt-drop"}, NumericalRefs: []string{"derived-drop"}, Confidence: 1, ValidAsOf: now},
		},
		Evidence: []contracts.EvidenceRef{
			{EvidenceID: "evidence-keep", SourceType: "sec_filing", Locator: "keep", ContentSHA: "a", AsOf: now},
		},
		CalculationReceipts: []contracts.CalculationReceipt{{ReceiptID: "receipt-drop"}},
		NumericalContext: &contracts.NumericalContext{
			SchemaVersion: contracts.SchemaVersionV1, ContextID: "numerical-1", RunID: "run-1",
			Version: contracts.NumericalContextVersionV1, AsOf: now,
			Variables: []contracts.NumericalVariable{
				{
					VariableID: "actual-keep", EntityID: "adbe", MetricID: "cash", Period: "FY2025",
					PeriodBasis: contracts.PeriodBasisNominalLabel, ComparisonKey: "adbe:cash:FY2025",
					ValueKind: contracts.NumericalActual, Value: contracts.Quantity{Value: "10", Unit: "USD", Currency: "USD"},
					Method: contracts.NormalizationNone, EvidenceRefs: []string{"evidence-keep"}, AsOf: now,
				},
				{
					VariableID: "derived-drop", EntityID: "adbe", MetricID: "quality", Period: "FY2025",
					PeriodBasis: contracts.PeriodBasisNominalLabel, ComparisonKey: "adbe:quality:FY2025",
					ValueKind: contracts.NumericalDerivedView, Value: contracts.Quantity{Value: "0.9", Unit: "ratio"},
					Method: contracts.NormalizationAbsoluteDerived, FormulaVersion: "quality/v1",
					ReceiptRefs: []string{"receipt-drop"}, AsOf: now,
				},
			},
		},
	}
	report := contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-1", RunID: "run-1",
		ReviewerRole: roles.EvidenceCritic, Decision: contracts.CritiqueRepair,
		ApprovedClaims: []string{"keep"}, RejectedClaims: []string{"drop"},
		Issues: []contracts.CritiqueIssue{{
			IssueID: "drop", Severity: "high", ClaimRefs: []string{"drop"}, Description: "Drop it.",
		}},
		RepairPass: 1, CreatedAt: now,
	}

	closed, _, ok := closeExplicitlyApprovedSubset([]contracts.ContextPacket{packet}, report)
	if !ok {
		t.Fatal("expected approved numerical subset to close")
	}
	if err := contracts.ValidateContextPacket(closed[0]); err != nil {
		t.Fatalf("closed numerical subset is invalid: %v", err)
	}
	if closed[0].NumericalContext == nil || len(closed[0].NumericalContext.Variables) != 1 ||
		closed[0].NumericalContext.Variables[0].VariableID != "actual-keep" ||
		len(closed[0].CalculationReceipts) != 0 {
		t.Fatalf("closed subset retained rejected numerical authority: %+v", closed[0])
	}
}

func TestNarrowContextPacketsRetainsRelationDependencies(t *testing.T) {
	now := time.Now().UTC()
	variable := func(id, entity, value string) contracts.NumericalVariable {
		return contracts.NumericalVariable{
			VariableID: id, EntityID: entity, MetricID: "margin", Period: "FY2025",
			PeriodBasis: contracts.PeriodBasisNominalLabel, ComparisonKey: "margin:FY2025",
			ValueKind: contracts.NumericalActual, Value: contracts.Quantity{Value: value, Unit: "ratio"},
			Method: contracts.NormalizationNone, EvidenceRefs: []string{"evidence-" + entity}, AsOf: now,
		}
	}
	left, right := variable("left", "msft", "0.4"), variable("right", "googl", "0.3")
	difference := contracts.Quantity{Value: "0.1", Unit: "ratio"}
	packet := contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-1", SpecialistRole: roles.FinancialQuality, Objective: "Compare margins.",
		Scope: contracts.Scope{AsOf: now},
		Findings: []contracts.Finding{
			{ClaimID: "keep", ClaimType: contracts.ClaimCalculation, Statement: "Keep relation.", CalculationRefs: []string{"receipt-relation"}, NumericalRefs: []string{"relation-keep"}, Confidence: 1, ValidAsOf: now},
			{ClaimID: "remove", ClaimType: contracts.ClaimFact, Statement: "Remove.", EvidenceRefs: []string{"evidence-remove"}, Confidence: 1, ValidAsOf: now},
		},
		Evidence: []contracts.EvidenceRef{
			{EvidenceID: "evidence-msft", SourceType: "sec_filing", Locator: "msft", ContentSHA: "a", AsOf: now},
			{EvidenceID: "evidence-googl", SourceType: "sec_filing", Locator: "googl", ContentSHA: "b", AsOf: now},
			{EvidenceID: "evidence-remove", SourceType: "sec_filing", Locator: "remove", ContentSHA: "c", AsOf: now},
		},
		NumericalContext: &contracts.NumericalContext{
			SchemaVersion: contracts.SchemaVersionV1, ContextID: "numerical-1", RunID: "run-1",
			Version: contracts.NumericalContextVersionV1, AsOf: now,
			Variables: []contracts.NumericalVariable{left, right},
			Relations: []contracts.NumericalRelation{{
				RelationID: "relation-keep", MetricID: "margin", LeftVariableID: "left",
				Operator: contracts.RelationGreaterThan, RightVariableID: "right", Difference: &difference,
				Tolerance: "0", Comparable: true, FormulaVersion: "relation/v1",
				ReceiptRefs: []string{"receipt-relation"},
			}},
		},
		CalculationReceipts: []contracts.CalculationReceipt{validRuntimeTestReceipt("receipt-relation", now)},
	}
	packet.CalculationReceipts[0].EvidenceRefs = []string{"evidence-msft", "evidence-googl"}
	if err := contracts.ValidateContextPacket(packet); err != nil {
		t.Fatalf("relation fixture is invalid: %v", err)
	}

	narrowed, changed := narrowContextPackets([]contracts.ContextPacket{packet}, contracts.CritiqueReport{
		Issues: []contracts.CritiqueIssue{{ClaimRefs: []string{"remove"}}},
	})
	if !changed {
		t.Fatal("expected packet to be narrowed")
	}
	if err := contracts.ValidateContextPacket(narrowed[0]); err != nil {
		t.Fatalf("narrowed relation packet is invalid: %v", err)
	}
	if len(narrowed[0].NumericalContext.Variables) != 2 || len(narrowed[0].NumericalContext.Relations) != 1 ||
		len(narrowed[0].CalculationReceipts) != 1 || len(narrowed[0].Evidence) != 2 {
		t.Fatalf("relation dependencies were not retained: %+v", narrowed[0])
	}
}

func validRuntimeTestReceipt(receiptID string, now time.Time) contracts.CalculationReceipt {
	return contracts.CalculationReceipt{
		SchemaVersion: contracts.SchemaVersionV1, ReceiptID: receiptID, RequestID: "request-1",
		EngineID: "test-engine", OperationID: "test-operation", FormulaVersion: "test/v1",
		Status: contracts.ReceiptSuccess,
		NormalizedInputs: []contracts.EngineInput{{
			InputID: "input-1", Status: "assumed",
			Quantity: contracts.Quantity{Value: "0.2", Unit: "ratio"},
		}},
		Outputs: []contracts.ReceiptOutput{{
			OutputID: "output-1", Status: "available",
			Quantity: contracts.Quantity{Value: "0.1", Unit: "ratio"},
		}},
		InvariantResults: []contracts.InvariantResult{{
			InvariantID: "finite-output", Passed: true,
		}},
		SourceAsOf: now, GeneratedAt: now, CodeCommit: "test", InputSHA: "input",
		ReceiptSHA: strings.Repeat("a", 64),
	}
}

func TestCloseExplicitlyApprovedSubsetRetainsOnlyReviewerApprovedClaims(t *testing.T) {
	now := time.Now().UTC()
	packets := []contracts.ContextPacket{{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-1", SpecialistRole: roles.BusinessStrategy, Objective: "Compare.",
		Scope: contracts.Scope{AsOf: now},
		Findings: []contracts.Finding{
			{ClaimID: "keep", ClaimType: contracts.ClaimFact, Statement: "Keep.", EvidenceRefs: []string{"evidence-keep"}, Confidence: 1, ValidAsOf: now},
			{ClaimID: "drop", ClaimType: contracts.ClaimFact, Statement: "Drop.", EvidenceRefs: []string{"evidence-drop"}, Confidence: 1, ValidAsOf: now},
		},
		Evidence: []contracts.EvidenceRef{
			{EvidenceID: "evidence-keep", SourceType: "sec_filing", Locator: "keep", ContentSHA: "keep", AsOf: now},
			{EvidenceID: "evidence-drop", SourceType: "sec_filing", Locator: "drop", ContentSHA: "drop", AsOf: now},
		},
	}}
	report := contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-1", RunID: "run-1",
		ReviewerRole: roles.EvidenceCritic, Decision: contracts.CritiqueRepair,
		ApprovedClaims: []string{"keep"}, RejectedClaims: []string{"drop"},
		Issues:     []contracts.CritiqueIssue{{IssueID: "issue-1", Severity: "high", ClaimRefs: []string{"drop"}, Description: "Remove."}},
		RepairPass: 1, CreatedAt: now,
	}

	closed, approval, ok := closeExplicitlyApprovedSubset(packets, report)
	if !ok || approval.Decision != contracts.CritiqueApprove || len(approval.Issues) != 0 || len(approval.RejectedClaims) != 0 {
		t.Fatalf("approved subset did not produce a valid closure: ok=%v approval=%+v", ok, approval)
	}
	if len(closed[0].Findings) != 1 || closed[0].Findings[0].ClaimID != "keep" || len(closed[0].Evidence) != 1 || closed[0].Evidence[0].EvidenceID != "evidence-keep" {
		t.Fatalf("closure retained unauthorized context: %+v", closed[0])
	}
	if len(packets[0].Findings) != 2 {
		t.Fatal("closure mutated original packets")
	}
}

func TestTemporarySpecialistFailureRetriesAtMostOnce(t *testing.T) {
	specialist := &fakeSpecialist{temporary: true}
	runtime, _ := New(Dependencies{Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{}, TraceStore: &memoryTraceStore{}})
	now := time.Now().UTC()
	request, _ := requestparser.ParseDeterministic(requestparser.Input{
		Text: "What does Microsoft sell?", AsOf: now, RunID: "run-1", RequestID: "request-1",
	})
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil || specialist.attempts["context-01"] != 2 {
		t.Fatalf("temporary failure should retry once: result=%+v attempts=%+v", result, specialist.attempts)
	}
}

func TestTemporarySpecialistRetryReceivesBoundedAttemptIndex(t *testing.T) {
	specialist := &attemptAwareTemporarySpecialist{delegate: &fakeSpecialist{}}
	runtime, err := New(Dependencies{
		Specialist: specialist, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "What does Microsoft sell?", AsOf: now, RunID: "run-attempt-aware",
		RequestID: "request-attempt-aware",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil || result.Answer == nil {
		t.Fatalf("attempt-aware retry did not recover: %+v", result)
	}
	if attempts := specialist.attempts["context-01"]; !slices.Equal(attempts, []int{0, 1}) {
		t.Fatalf("specialist attempt sequence=%v, want [0 1]", attempts)
	}
}

func TestTemporaryReviewAndSynthesisFailuresRetryAtMostOnce(t *testing.T) {
	reviewer := &retryingReviewer{}
	synthesizer := &retryingSynthesizer{}
	runtime, err := New(Dependencies{
		Specialist: &fakeSpecialist{}, Reviewer: reviewer, Synthesizer: synthesizer,
		TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	request, err := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Estimate a defensible DCF value range for Microsoft.", AsOf: now,
		RunID: "run-1", RequestID: "request-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil || result.Answer == nil {
		t.Fatalf("bounded transient retries should recover: %+v", result)
	}
	for _, roleID := range []string{roles.RiskContrarian, roles.EvidenceCritic} {
		if reviewer.attempts[roleID] != 2 {
			t.Fatalf("reviewer %s attempts=%d, want 2", roleID, reviewer.attempts[roleID])
		}
	}
	if synthesizer.attempts != 2 {
		t.Fatalf("synthesis attempts=%d, want 2", synthesizer.attempts)
	}
}

func TestRuntimePreservesConflictsThroughReviewAndSynthesis(t *testing.T) {
	observer := &conflictObserver{}
	runtime, err := New(Dependencies{
		Specialist: &fakeSpecialist{conflicts: []string{"reported and normalized margins disagree"}},
		Reviewer:   observer, Synthesizer: observer, TraceStore: &memoryTraceStore{},
	})
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	request, _ := requestparser.ParseDeterministic(requestparser.Input{
		Text: "Compare Microsoft and NVIDIA on cash conversion.", AsOf: now,
		RunID: "run-1", RequestID: "request-1",
	})
	result := runtime.Run(context.Background(), request)
	if result.Failure != nil {
		t.Fatalf("unexpected failure: %+v", result.Failure)
	}
	if len(observer.reviewerConflicts) == 0 || len(observer.synthesisConflicts) == 0 {
		t.Fatalf("conflicts were lost: review=%v synthesis=%v", observer.reviewerConflicts, observer.synthesisConflicts)
	}
}

func TestRuntimeTraceExcludesUserTextAndSecrets(t *testing.T) {
	runtime, _ := New(Dependencies{
		Specialist: &fakeSpecialist{}, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{},
		TraceStore: &memoryTraceStore{},
	})
	now := time.Now().UTC()
	secretText := "What does Microsoft sell? private-token-should-never-enter-trace\nforged_event=completed"
	request, _ := requestparser.ParseDeterministic(requestparser.Input{
		Text: secretText, AsOf: now, RunID: "run-1", RequestID: "request-1",
	})
	result := runtime.Run(context.Background(), request)
	encoded, err := json.Marshal(result.Trace)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), secretText) || strings.Contains(string(encoded), "private-token") || strings.Contains(string(encoded), "forged_event") {
		t.Fatalf("trace leaked request text: %s", encoded)
	}
}

func TestCancellationProducesFailureAndNoAnswer(t *testing.T) {
	runtime, _ := New(Dependencies{Specialist: &fakeSpecialist{block: true}, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{}, TraceStore: &memoryTraceStore{}})
	now := time.Now().UTC()
	request, _ := requestparser.ParseDeterministic(requestparser.Input{
		Text: "What does Microsoft sell?", AsOf: now, RunID: "run-1", RequestID: "request-1",
	})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	result := runtime.Run(ctx, request)
	if result.Answer != nil || result.Failure == nil || len(result.Trace.Failures) == 0 {
		t.Fatalf("cancellation must be explicit %+v", result)
	}
}

func TestToolGateRejectsUnregisteredOrUnauthorizedCalls(t *testing.T) {
	runtime, _ := New(Dependencies{Specialist: &fakeSpecialist{}, Reviewer: fakeReviewer{}, Synthesizer: &fakeSynthesizer{}, TraceStore: &memoryTraceStore{}})
	if _, err := runtime.Tools.Authorize(roles.MarketBehavior, "market.beta"); err != nil {
		t.Fatal(err)
	}
	if _, err := runtime.Tools.Authorize(roles.BusinessStrategy, "market.beta"); err == nil {
		t.Fatal("business strategy must not execute market beta")
	}
	if _, err := runtime.Tools.Authorize(roles.MarketBehavior, "unknown.operation"); err == nil {
		t.Fatal("unregistered operations must fail closed")
	}
}

func TestRuntimeRequiresAllAdapters(t *testing.T) {
	if _, err := New(Dependencies{}); err == nil {
		t.Fatal("missing adapters must fail")
	}
}

func TestFileTraceStoreWritesPrivateAtomicJSON(t *testing.T) {
	directory := t.TempDir()
	trace := Trace{
		SchemaVersion: "signalforge/orchestration-trace/v1", RunID: "run-1", RequestID: "request-1",
		StartedAt: time.Now().UTC(), CompletedAt: time.Now().UTC(),
	}
	if err := (FileTraceStore{Directory: directory}).Save(trace); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "run-1.json")
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("trace permissions are %o", info.Mode().Perm())
	}
	if err := (FileTraceStore{Directory: directory}).Save(Trace{RunID: "../escape", CompletedAt: time.Now().UTC()}); err == nil {
		t.Fatal("unsafe trace IDs must fail closed")
	}
}

func TestContextPacketRejectsEmptyOrDuplicateConflicts(t *testing.T) {
	now := time.Now().UTC()
	base := contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-1", RunID: "run-1",
		StepID: "context-01", SpecialistRole: roles.FinancialQuality, Objective: "Assess quality.",
		Scope: contracts.Scope{AsOf: now},
	}
	base.Conflicts = []string{""}
	if err := contracts.ValidateContextPacket(base); err == nil {
		t.Fatal("empty conflicts must fail closed")
	}
	base.Conflicts = []string{"same conflict", "same conflict"}
	if err := contracts.ValidateContextPacket(base); err == nil {
		t.Fatal("duplicate conflicts must fail closed")
	}
}
