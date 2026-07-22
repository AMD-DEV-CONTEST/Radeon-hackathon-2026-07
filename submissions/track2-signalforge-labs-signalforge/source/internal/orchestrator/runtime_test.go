package orchestrator

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
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
	if result.Trace.MaxConcurrentContext != 2 || specialist.maximum != 2 || synthesizer.calls != 1 {
		t.Fatalf("workflow was not bounded or singly synthesized: trace=%+v max=%d calls=%d", result.Trace, specialist.maximum, synthesizer.calls)
	}
	if len(result.Trace.PacketIDs) != 2 || len(result.Trace.CritiqueIDs) < 1 || len(result.Trace.Events) == 0 {
		t.Fatalf("trace is incomplete %+v", result.Trace)
	}
	routeStarts := 0
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
	}
	if routeStarts < 4 {
		t.Fatalf("expected context, review, and synthesis route starts, got %d", routeStarts)
	}
	if len(store.traces) != 1 || store.traces[0].AnswerID != "answer-1" {
		t.Fatalf("completed trace was not persisted: %+v", store.traces)
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
	secretText := "What does Microsoft sell? private-token-should-never-enter-trace"
	request, _ := requestparser.ParseDeterministic(requestparser.Input{
		Text: secretText, AsOf: now, RunID: "run-1", RequestID: "request-1",
	})
	result := runtime.Run(context.Background(), request)
	encoded, err := json.Marshal(result.Trace)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), secretText) || strings.Contains(string(encoded), "private-token") {
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
