package orchestrator

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/planner"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type Event struct {
	Sequence   int               `json:"sequence"`
	RunID      string            `json:"run_id"`
	StepID     string            `json:"step_id,omitempty"`
	Type       string            `json:"type"`
	Status     string            `json:"status"`
	At         time.Time         `json:"at"`
	Attributes map[string]string `json:"attributes,omitempty"`
}

type Trace struct {
	SchemaVersion        string    `json:"schema_version"`
	RunID                string    `json:"run_id"`
	RequestID            string    `json:"request_id"`
	PlanID               string    `json:"plan_id,omitempty"`
	Events               []Event   `json:"events"`
	PacketIDs            []string  `json:"packet_ids,omitempty"`
	CritiqueIDs          []string  `json:"critique_ids,omitempty"`
	AnswerID             string    `json:"answer_id,omitempty"`
	Failures             []string  `json:"failure_ids,omitempty"`
	MaxConcurrentContext int       `json:"max_concurrent_context"`
	StartedAt            time.Time `json:"started_at"`
	CompletedAt          time.Time `json:"completed_at"`
}

type ReviewInput struct {
	Request    contracts.ResearchRequest
	Plan       contracts.ResearchPlan
	Step       contracts.PlanStep
	Packets    []contracts.ContextPacket
	Prior      []contracts.CritiqueReport
	RepairPass int
}

type SynthesisInput struct {
	Request   contracts.ResearchRequest
	Plan      contracts.ResearchPlan
	Packets   []contracts.ContextPacket
	Critiques []contracts.CritiqueReport
}

type Specialist interface {
	Run(context.Context, contracts.ContextRequest) (contracts.ContextPacket, error)
}

type Reviewer interface {
	Review(context.Context, ReviewInput) (contracts.CritiqueReport, error)
}

type Synthesizer interface {
	Synthesize(context.Context, SynthesisInput) (contracts.FinalAnswer, error)
}

type EventSink interface {
	Emit(Event)
}

type Dependencies struct {
	Specialist  Specialist
	Reviewer    Reviewer
	Synthesizer Synthesizer
	Sink        EventSink
	TraceStore  TraceStore
}

type Runtime struct {
	Planner            planner.Builder
	Roles              roles.Registry
	Tools              ToolGate
	Deps               Dependencies
	Now                func() time.Time
	ContextConcurrency int
}

type Result struct {
	Answer          *contracts.FinalAnswer     `json:"answer,omitempty"`
	Failure         *contracts.FailureReceipt  `json:"failure,omitempty"`
	ContextFailures []contracts.FailureReceipt `json:"context_failures,omitempty"`
	Packets         []contracts.ContextPacket  `json:"packets,omitempty"`
	Critiques       []contracts.CritiqueReport `json:"critiques,omitempty"`
	Trace           Trace                      `json:"trace"`
}

func New(dependencies Dependencies) (*Runtime, error) {
	if dependencies.Specialist == nil || dependencies.Reviewer == nil || dependencies.Synthesizer == nil || dependencies.TraceStore == nil {
		return nil, errors.New("specialist, reviewer, synthesizer, and trace store adapters are required")
	}
	roleRegistry := roles.DefaultRegistry()
	return &Runtime{
		Planner: planner.Default(), Roles: roleRegistry,
		Tools: ToolGate{Capabilities: capability.Tier0Registry(), Roles: roleRegistry},
		Deps:  dependencies, Now: func() time.Time { return time.Now().UTC() }, ContextConcurrency: 4,
	}, nil
}

func (runtime *Runtime) Run(parent context.Context, request contracts.ResearchRequest) Result {
	started := runtime.Now()
	trace := Trace{SchemaVersion: "signalforge/orchestration-trace/v1", RunID: request.RunID, RequestID: request.RequestID, StartedAt: started}
	emitter := newEmitter(request.RunID, runtime.Deps.Sink, runtime.Now, &trace)
	if err := contracts.ValidateResearchRequest(request); err != nil {
		return runtime.fail(&trace, emitter, request.RunID, "request", "invalid_request", err, false)
	}
	plan, err := runtime.Planner.Build(request)
	if err != nil {
		return runtime.fail(&trace, emitter, request.RunID, "planning", classify(err), err, false)
	}
	trace.PlanID = plan.PlanID
	emitter.emit("", "plan", "accepted", map[string]string{"plan_id": plan.PlanID})
	ctx, cancel := context.WithTimeout(parent, time.Duration(plan.DeadlineMS)*time.Millisecond)
	defer cancel()

	contextSteps, reviewSteps, synthesisStep := splitSteps(plan.Steps)
	concurrency := plan.MaxParallelSpecialists
	if runtime.ContextConcurrency > 0 && runtime.ContextConcurrency < concurrency {
		concurrency = runtime.ContextConcurrency
	}
	packets, failures, maxConcurrent := runtime.runContextWaves(ctx, request, contextSteps, concurrency, emitter)
	trace.MaxConcurrentContext = maxConcurrent
	for _, packet := range packets {
		trace.PacketIDs = append(trace.PacketIDs, packet.PacketID)
	}
	for _, failure := range failures {
		trace.Failures = append(trace.Failures, failure.FailureID)
	}
	if len(contextSteps) > 0 && len(packets) == 0 {
		return attachPartial(runtime.fail(&trace, emitter, request.RunID, "context-wave", "context_unavailable", errors.New("all context specialists failed"), false), packets, nil, failures)
	}

	critiques := make([]contracts.CritiqueReport, 0, len(reviewSteps)*(plan.MaxRepairPasses+1))
	approvedCritiques := make([]contracts.CritiqueReport, 0, len(reviewSteps))
	for _, step := range reviewSteps {
		reports, reviewedPackets, reviewErr := runtime.runReview(ctx, request, plan, step, packets, critiques, emitter)
		if reviewErr != nil {
			return attachPartial(runtime.fail(&trace, emitter, request.RunID, step.StepID, classify(reviewErr), reviewErr, retryable(reviewErr)), packets, critiques, failures)
		}
		packets = reviewedPackets
		critiques = append(critiques, reports...)
		for _, report := range reports {
			trace.CritiqueIDs = append(trace.CritiqueIDs, report.ReportID)
		}
		finalReport := reports[len(reports)-1]
		if finalReport.Decision != contracts.CritiqueApprove {
			return attachPartial(runtime.fail(&trace, emitter, request.RunID, step.StepID, "evidence_rejected", errors.New("review did not approve evidence"), false), packets, critiques, failures)
		}
		approvedCritiques = append(approvedCritiques, finalReport)
	}
	if synthesisStep == nil {
		return attachPartial(runtime.fail(&trace, emitter, request.RunID, "synthesis", "invalid_plan", errors.New("plan has no synthesis step"), false), packets, critiques, failures)
	}
	answer, err := runtime.runSynthesis(ctx, request, plan, *synthesisStep, packets, approvedCritiques, emitter)
	if err != nil {
		return attachPartial(runtime.fail(&trace, emitter, request.RunID, synthesisStep.StepID, classify(err), err, retryable(err)), packets, critiques, failures)
	}
	trace.AnswerID = answer.AnswerID
	emitter.emit(synthesisStep.StepID, "run", "completed", map[string]string{"answer_id": answer.AnswerID})
	trace.CompletedAt = runtime.Now()
	if err := runtime.Deps.TraceStore.Save(trace); err != nil {
		return attachPartial(runtime.fail(&trace, emitter, request.RunID, "trace", "trace_persistence_failed", err, false), packets, critiques, failures)
	}
	return Result{Answer: &answer, ContextFailures: failures, Packets: packets, Critiques: critiques, Trace: trace}
}

func attachPartial(result Result, packets []contracts.ContextPacket, critiques []contracts.CritiqueReport, failures []contracts.FailureReceipt) Result {
	result.Packets = append([]contracts.ContextPacket(nil), packets...)
	result.Critiques = append([]contracts.CritiqueReport(nil), critiques...)
	result.ContextFailures = append([]contracts.FailureReceipt(nil), failures...)
	return result
}

func (runtime *Runtime) runContextWaves(ctx context.Context, request contracts.ResearchRequest, steps []contracts.PlanStep, limit int, emitter *eventEmitter) ([]contracts.ContextPacket, []contracts.FailureReceipt, int) {
	waves := make(map[int][]contracts.PlanStep)
	maximumWave := 0
	for _, step := range steps {
		wave := step.Wave
		if wave == 0 {
			wave = 1
		}
		waves[wave] = append(waves[wave], step)
		if wave > maximumWave {
			maximumWave = wave
		}
	}
	packets := []contracts.ContextPacket{}
	failures := []contracts.FailureReceipt{}
	maximumConcurrent := 0
	for wave := 1; wave <= maximumWave; wave++ {
		waveSteps := waves[wave]
		if len(waveSteps) == 0 {
			continue
		}
		wavePackets, waveFailures, concurrent := runtime.runContextWave(ctx, request, waveSteps, limit, emitter)
		packets = append(packets, wavePackets...)
		failures = append(failures, waveFailures...)
		if concurrent > maximumConcurrent {
			maximumConcurrent = concurrent
		}
		if ctx.Err() != nil {
			break
		}
	}
	return packets, failures, maximumConcurrent
}

func (runtime *Runtime) runContextWave(ctx context.Context, request contracts.ResearchRequest, steps []contracts.PlanStep, limit int, emitter *eventEmitter) ([]contracts.ContextPacket, []contracts.FailureReceipt, int) {
	if len(steps) == 0 {
		return nil, nil, 0
	}
	type outcome struct {
		index   int
		packet  contracts.ContextPacket
		failure *contracts.FailureReceipt
	}
	orderedPackets := make([]*contracts.ContextPacket, len(steps))
	orderedFailures := make([]*contracts.FailureReceipt, len(steps))
	maximum := 0
	for start := 0; start < len(steps); start += limit {
		end := start + limit
		if end > len(steps) {
			end = len(steps)
		}
		outcomes := make(chan outcome, end-start)
		var wait sync.WaitGroup
		for index := start; index < end; index++ {
			step := steps[index]
			wait.Add(1)
			go func(index int, step contracts.PlanStep) {
				defer wait.Done()
				if ctx.Err() != nil {
					outcomes <- outcome{index: index, failure: failure(request.RunID, step.StepID, "cancelled", ctx.Err(), false, runtime.Now())}
					return
				}
				emitter.emit(step.StepID, "context", "started", routeAttributes(step))
				contextRequest := contextRequest(request, step)
				packet, err := runtime.callSpecialist(ctx, contextRequest, step)
				if err != nil {
					outcomes <- outcome{index: index, failure: failure(contextRequest.RunID, step.StepID, classify(err), err, retryable(err), runtime.Now())}
					emitter.emit(step.StepID, "context", "failed", map[string]string{"code": classify(err)})
					return
				}
				outcomes <- outcome{index: index, packet: packet}
				emitter.emit(step.StepID, "context", "completed", map[string]string{"packet_id": packet.PacketID})
			}(index, step)
		}
		if end-start > maximum {
			maximum = end - start
		}
		wait.Wait()
		close(outcomes)
		for outcome := range outcomes {
			if outcome.failure != nil {
				orderedFailures[outcome.index] = outcome.failure
			} else {
				packet := outcome.packet
				orderedPackets[outcome.index] = &packet
			}
		}
	}
	packets := []contracts.ContextPacket{}
	failures := []contracts.FailureReceipt{}
	for index := range steps {
		if orderedPackets[index] != nil {
			packets = append(packets, *orderedPackets[index])
		}
		if orderedFailures[index] != nil {
			failures = append(failures, *orderedFailures[index])
		}
	}
	return packets, failures, maximum
}

func (runtime *Runtime) callSpecialist(parent context.Context, request contracts.ContextRequest, step contracts.PlanStep) (contracts.ContextPacket, error) {
	role, _ := runtime.Roles.Get(step.RoleID)
	var last error
	for attempt := 0; attempt <= role.MaxRetries; attempt++ {
		ctx, cancel := context.WithTimeout(parent, time.Duration(step.TimeoutMS)*time.Millisecond)
		packet, err := runtime.Deps.Specialist.Run(ctx, request)
		cancel()
		if err == nil {
			if validationErr := validatePacket(packet, request); validationErr != nil {
				return contracts.ContextPacket{}, validationErr
			}
			return packet, nil
		}
		last = err
		if !retryable(err) {
			break
		}
	}
	return contracts.ContextPacket{}, last
}

func (runtime *Runtime) runReview(parent context.Context, request contracts.ResearchRequest, plan contracts.ResearchPlan, step contracts.PlanStep, packets []contracts.ContextPacket, prior []contracts.CritiqueReport, emitter *eventEmitter) ([]contracts.CritiqueReport, []contracts.ContextPacket, error) {
	emitter.emit(step.StepID, "review", "started", routeAttributes(step))
	working := clonePackets(packets)
	history := []contracts.CritiqueReport{}
	reviewContext := append([]contracts.CritiqueReport(nil), prior...)
	for pass := 0; pass <= plan.MaxRepairPasses; pass++ {
		report, err := runtime.callReviewer(parent, ReviewInput{Request: request, Plan: plan, Step: step, Packets: working, Prior: reviewContext, RepairPass: pass})
		if err != nil {
			return nil, working, err
		}
		if report.RunID != request.RunID || report.ReviewerRole != step.RoleID || report.RepairPass != pass {
			return nil, working, errors.New("review contract does not match orchestration step")
		}
		if err := contracts.ValidateCritiqueReport(report); err != nil {
			return nil, working, err
		}
		history = append(history, report)
		if pass == plan.MaxRepairPasses && report.Decision != contracts.CritiqueApprove && report.Decision != contracts.CritiqueReject {
			approvedPackets, approval, ok := closeExplicitlyApprovedSubset(working, report)
			if ok {
				history = append(history, approval)
				emitter.emit(step.StepID, "review", "approved_subset", map[string]string{"report_id": approval.ReportID})
				return history, approvedPackets, nil
			}
		}
		if report.Decision == contracts.CritiqueApprove || report.Decision == contracts.CritiqueReject || pass == plan.MaxRepairPasses {
			emitter.emit(step.StepID, "review", string(report.Decision), map[string]string{"report_id": report.ReportID})
			return history, working, nil
		}
		// A repair asks the same reviewer to reconsider the unchanged claims with its prior issue
		// visible. Removing those claims here would make repair impossible because review roles are
		// deliberately forbidden from authoring replacement research. Narrow is the only intermediate
		// decision that prunes claims; a repeated repair on the final pass closes to the explicitly
		// approved subset above or remains non-approved.
		if report.Decision == contracts.CritiqueRepair {
			reviewContext = append(reviewContext, report)
			emitter.emit(step.StepID, "review", "repair_requested", map[string]string{"report_id": report.ReportID})
			continue
		}
		narrowed, changed := narrowContextPackets(working, report)
		if !changed {
			emitter.emit(step.StepID, "review", "repair_unresolved", map[string]string{"report_id": report.ReportID})
			return history, working, nil
		}
		working = narrowed
		reviewContext = append(reviewContext, report)
		emitter.emit(step.StepID, "review", "narrowed", map[string]string{"report_id": report.ReportID})
	}
	return history, working, errors.New("review exhausted repair budget")
}

// On the final repair pass, only claims explicitly approved by the reviewer may survive. Omitted
// and rejected claims remain unapproved. The derived report records this deterministic closure for
// synthesis while the original non-approval report remains in the audit history.
func closeExplicitlyApprovedSubset(packets []contracts.ContextPacket, report contracts.CritiqueReport) ([]contracts.ContextPacket, contracts.CritiqueReport, bool) {
	if len(report.ApprovedClaims) == 0 {
		return packets, contracts.CritiqueReport{}, false
	}
	approved := make(map[string]bool, len(report.ApprovedClaims))
	for _, claimID := range report.ApprovedClaims {
		approved[claimID] = true
	}
	result := clonePackets(packets)
	retained := map[string]bool{}
	filter := func(findings []contracts.Finding) []contracts.Finding {
		kept := make([]contracts.Finding, 0, len(findings))
		for _, finding := range findings {
			if approved[finding.ClaimID] {
				kept = append(kept, finding)
				retained[finding.ClaimID] = true
			}
		}
		return kept
	}
	for index := range result {
		result[index].Findings = filter(result[index].Findings)
		result[index].Counterevidence = filter(result[index].Counterevidence)
		prunePacketReferences(&result[index])
	}
	if len(retained) != len(approved) {
		return packets, contracts.CritiqueReport{}, false
	}
	approval := report
	approval.ReportID = report.ReportID + "-approved-subset"
	approval.Decision = contracts.CritiqueApprove
	approval.ApprovedClaims = append([]string(nil), report.ApprovedClaims...)
	approval.RejectedClaims = nil
	approval.Issues = nil
	if err := contracts.ValidateCritiqueReport(approval); err != nil {
		return packets, contracts.CritiqueReport{}, false
	}
	return result, approval, true
}

func clonePackets(packets []contracts.ContextPacket) []contracts.ContextPacket {
	result := append([]contracts.ContextPacket(nil), packets...)
	for index := range result {
		result[index].Findings = append([]contracts.Finding(nil), packets[index].Findings...)
		result[index].Counterevidence = append([]contracts.Finding(nil), packets[index].Counterevidence...)
		result[index].Evidence = append([]contracts.EvidenceRef(nil), packets[index].Evidence...)
		result[index].CalculationReceipts = append([]contracts.CalculationReceipt(nil), packets[index].CalculationReceipts...)
	}
	return result
}

func narrowContextPackets(packets []contracts.ContextPacket, report contracts.CritiqueReport) ([]contracts.ContextPacket, bool) {
	rejected := make(map[string]bool, len(report.RejectedClaims))
	for _, claimID := range report.RejectedClaims {
		rejected[claimID] = true
	}
	for _, issue := range report.Issues {
		for _, claimID := range issue.ClaimRefs {
			rejected[claimID] = true
		}
	}
	if len(rejected) == 0 {
		return packets, false
	}
	result := clonePackets(packets)
	changed := false
	for index := range result {
		result[index].Findings, changed = filterClaims(result[index].Findings, rejected, changed)
		result[index].Counterevidence, changed = filterClaims(result[index].Counterevidence, rejected, changed)
		prunePacketReferences(&result[index])
	}
	return result, changed
}

func filterClaims(findings []contracts.Finding, rejected map[string]bool, changed bool) ([]contracts.Finding, bool) {
	kept := make([]contracts.Finding, 0, len(findings))
	for _, finding := range findings {
		if rejected[finding.ClaimID] {
			changed = true
			continue
		}
		kept = append(kept, finding)
	}
	return kept, changed
}

func prunePacketReferences(packet *contracts.ContextPacket) {
	evidence, receipts := map[string]bool{}, map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		for _, evidenceID := range finding.EvidenceRefs {
			evidence[evidenceID] = true
		}
		for _, receiptID := range finding.CalculationRefs {
			receipts[receiptID] = true
		}
	}
	keptEvidence := make([]contracts.EvidenceRef, 0, len(packet.Evidence))
	for _, item := range packet.Evidence {
		if evidence[item.EvidenceID] {
			keptEvidence = append(keptEvidence, item)
		}
	}
	packet.Evidence = keptEvidence
	keptReceipts := make([]contracts.CalculationReceipt, 0, len(packet.CalculationReceipts))
	for _, receipt := range packet.CalculationReceipts {
		if receipts[receipt.ReceiptID] {
			keptReceipts = append(keptReceipts, receipt)
		}
	}
	packet.CalculationReceipts = keptReceipts
}

func (runtime *Runtime) callReviewer(parent context.Context, input ReviewInput) (contracts.CritiqueReport, error) {
	role, _ := runtime.Roles.Get(input.Step.RoleID)
	var last error
	for attempt := 0; attempt <= role.MaxRetries; attempt++ {
		ctx, cancel := context.WithTimeout(parent, time.Duration(input.Step.TimeoutMS)*time.Millisecond)
		report, err := runtime.Deps.Reviewer.Review(ctx, input)
		cancel()
		if err == nil {
			return report, nil
		}
		last = err
		if !retryable(err) {
			break
		}
	}
	return contracts.CritiqueReport{}, last
}

func (runtime *Runtime) runSynthesis(parent context.Context, request contracts.ResearchRequest, plan contracts.ResearchPlan, step contracts.PlanStep, packets []contracts.ContextPacket, critiques []contracts.CritiqueReport, emitter *eventEmitter) (contracts.FinalAnswer, error) {
	emitter.emit(step.StepID, "synthesis", "started", routeAttributes(step))
	role, _ := runtime.Roles.Get(step.RoleID)
	input := SynthesisInput{Request: request, Plan: plan, Packets: packets, Critiques: critiques}
	var answer contracts.FinalAnswer
	var err error
	for attempt := 0; attempt <= role.MaxRetries; attempt++ {
		ctx, cancel := context.WithTimeout(parent, time.Duration(step.TimeoutMS)*time.Millisecond)
		answer, err = runtime.Deps.Synthesizer.Synthesize(ctx, input)
		cancel()
		if err == nil || !retryable(err) {
			break
		}
	}
	if err != nil {
		return contracts.FinalAnswer{}, err
	}
	if answer.RunID != request.RunID || answer.RequestID != request.RequestID || answer.ReleasedBy != roles.FinalResearchAnalyst {
		return contracts.FinalAnswer{}, errors.New("final answer violates sole-synthesis boundary")
	}
	if err := contracts.ValidateFinalAnswer(answer); err != nil {
		return contracts.FinalAnswer{}, err
	}
	return answer, nil
}

func (runtime *Runtime) fail(trace *Trace, emitter *eventEmitter, runID, stepID, code string, err error, canRetry bool) Result {
	at := runtime.Now()
	receipt := failure(runID, stepID, code, err, canRetry, at)
	trace.Failures = append(trace.Failures, receipt.FailureID)
	emitter.emit(stepID, "run", "failed", map[string]string{"code": code})
	trace.CompletedAt = runtime.Now()
	if saveErr := runtime.Deps.TraceStore.Save(*trace); saveErr != nil {
		receipt.FailureCode = "trace_persistence_failed"
		receipt.Message = receipt.Message + "; persist trace: " + saveErr.Error()
	}
	return Result{Failure: receipt, Trace: *trace}
}

func splitSteps(steps []contracts.PlanStep) (contexts, reviews []contracts.PlanStep, synthesis *contracts.PlanStep) {
	for index := range steps {
		switch steps[index].Kind {
		case "context":
			contexts = append(contexts, steps[index])
		case "review":
			reviews = append(reviews, steps[index])
		case "synthesis":
			if synthesis == nil {
				copy := steps[index]
				synthesis = &copy
			}
		}
	}
	return contexts, reviews, synthesis
}

func contextRequest(request contracts.ResearchRequest, step contracts.PlanStep) contracts.ContextRequest {
	companyIDs := []string{}
	for _, entity := range request.Entities {
		if entity.EntityType == "company" && entity.Resolved {
			companyIDs = append(companyIDs, entity.EntityID)
		}
	}
	return contracts.ContextRequest{
		SchemaVersion: contracts.SchemaVersionV1, ContextRequestID: "context-request-" + step.StepID,
		RunID: request.RunID, StepID: step.StepID, SpecialistRole: step.RoleID, Objective: step.Objective,
		ResearchQuestion: request.UserText,
		Scope:            contracts.Scope{CompanyIDs: companyIDs, AsOf: request.AsOf},
		CapabilityIDs:    append([]string(nil), step.CapabilityIDs...), TokenBudget: step.ContextBudget,
		EvidenceRefs: append([]string(nil), request.LineageEvidenceRefs...),
		ReceiptRefs:  append([]string(nil), request.LineageReceiptRefs...),
		Assumptions:  append([]string(nil), request.Assumptions...),
	}
}

func routeAttributes(step contracts.PlanStep) map[string]string {
	reason := "intent_requires_specialist"
	switch step.Kind {
	case "review":
		if step.RoleID == roles.EvidenceCritic {
			reason = "evidence_release_gate"
		} else if step.RoleID == roles.RiskContrarian {
			reason = "risk_contrarian_gate"
		} else {
			reason = "independent_review_gate"
		}
	case "synthesis":
		reason = "single_release_authority"
	}
	return map[string]string{
		"role_id":           step.RoleID,
		"route_reason_code": reason,
		"capability_ids":    strings.Join(step.CapabilityIDs, ","),
	}
}

func validatePacket(packet contracts.ContextPacket, request contracts.ContextRequest) error {
	if packet.RunID != request.RunID || packet.StepID != request.StepID || packet.SpecialistRole != request.SpecialistRole {
		return errors.New("context packet does not match orchestration request")
	}
	return contracts.ValidateContextPacket(packet)
}

func failure(runID, stepID, code string, err error, canRetry bool, at time.Time) *contracts.FailureReceipt {
	if stepID == "" {
		stepID = "run"
	}
	return &contracts.FailureReceipt{
		SchemaVersion: contracts.SchemaVersionV1, FailureID: fmt.Sprintf("failure-%d", at.UnixNano()),
		RunID: runID, StepID: stepID, ComponentID: roles.ResearchOrchestrator,
		FailureCode: code, Message: err.Error(), Retryable: canRetry, CreatedAt: at,
	}
}

type temporary interface{ Temporary() bool }

func retryable(err error) bool {
	var candidate temporary
	return errors.As(err, &candidate) && candidate.Temporary()
}

func classify(err error) string {
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return "deadline_exceeded"
	case errors.Is(err, context.Canceled):
		return "cancelled"
	case errors.Is(err, planner.ErrClarificationRequired):
		return "clarification_required"
	default:
		return "component_failure"
	}
}

type eventEmitter struct {
	mu    sync.Mutex
	runID string
	sink  EventSink
	now   func() time.Time
	trace *Trace
}

func newEmitter(runID string, sink EventSink, now func() time.Time, trace *Trace) *eventEmitter {
	return &eventEmitter{runID: runID, sink: sink, now: now, trace: trace}
}

func (emitter *eventEmitter) emit(stepID, eventType, status string, attributes map[string]string) {
	emitter.mu.Lock()
	defer emitter.mu.Unlock()
	event := Event{Sequence: len(emitter.trace.Events) + 1, RunID: emitter.runID, StepID: stepID, Type: eventType, Status: status, At: emitter.now(), Attributes: attributes}
	emitter.trace.Events = append(emitter.trace.Events, event)
	if emitter.sink != nil {
		emitter.sink.Emit(event)
	}
}
