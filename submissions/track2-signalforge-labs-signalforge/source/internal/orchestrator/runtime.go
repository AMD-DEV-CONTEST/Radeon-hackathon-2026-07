package orchestrator

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/engine"
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

// AttemptAwareSpecialist is optional. It lets an adapter preserve bounded generation state across
// the orchestrator's one permitted retry without changing legacy specialist implementations.
type AttemptAwareSpecialist interface {
	RunAttempt(context.Context, contracts.ContextRequest, int) (contracts.ContextPacket, error)
}

type RetrievalLifecycle struct {
	RetrievalID            string
	BundleID               string
	Method                 string
	EvidenceCount          int
	SourceClasses          []string
	AsOf                   time.Time
	MissingEvidenceCount   int
	CandidateCount         int
	SelectedCandidateCount int
	RejectedCandidateCount int
	CandidateCountsKnown   bool
	FailureCode            string
}

type ToolLifecycle struct {
	ToolExecutionID     string
	ReceiptID           string
	ReceiptSHA          string
	ReceiptVerification string
	EngineID            string
	OperationID         string
	FormulaVersion      string
	InputRefIDs         []string
	OutputRefIDs        []string
	InputCount          int
	OutputCount         int
	InvariantCount      int
	InvariantsPassed    bool
	WarningCount        int
	FailureCode         string
}

// SpecialistLifecycleObserver receives only bounded operational metadata. It cannot receive
// prompts, model responses, evidence bodies, numerical values, or authorization material.
type SpecialistLifecycleObserver interface {
	RetrievalStarted(RetrievalLifecycle)
	RetrievalPassed(RetrievalLifecycle)
	RetrievalDegraded(RetrievalLifecycle)
	RetrievalFailed(RetrievalLifecycle)
	ToolStarted(ToolLifecycle)
	ToolPassed(ToolLifecycle)
	ToolFailed(ToolLifecycle)
}

// ObservedSpecialist is optional so existing specialist implementations remain compatible.
type ObservedSpecialist interface {
	RunObserved(context.Context, contracts.ContextRequest, SpecialistLifecycleObserver) (contracts.ContextPacket, error)
}

// AttemptAwareObservedSpecialist combines bounded retry state with lifecycle observation.
type AttemptAwareObservedSpecialist interface {
	RunObservedAttempt(context.Context, contracts.ContextRequest, SpecialistLifecycleObserver, int) (contracts.ContextPacket, error)
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

// PlanSink lets an observability adapter project the validated plan without
// making the execution dashboard part of the orchestration authority.
type PlanSink interface {
	AcceptPlan(contracts.ResearchPlan, time.Time)
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
		if errors.Is(err, planner.ErrClarificationRequired) {
			emitter.emit("interpret-request", "interpretation", "clarification_required", interpretationAttributes(request))
			return runtime.fail(&trace, emitter, request.RunID, "interpret-request", "clarification_required", err, false)
		}
		return runtime.fail(&trace, emitter, request.RunID, "planning", classify(err), err, false)
	}
	trace.PlanID = plan.PlanID
	if sink, ok := runtime.Deps.Sink.(PlanSink); ok {
		acceptPlanSafely(sink, plan, runtime.Now())
	}
	emitter.emit("interpret-request", "interpretation", "completed", interpretationAttributes(request))
	emitter.emit("build-plan", "planning", "completed", planningAttributes(plan))
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
	releaseAttributes := releaseOperationalAttributes(answer, approvedCritiques)
	emitter.emit(synthesisStep.StepID, "synthesis", "passed", releaseAttributes)
	emitter.emit(synthesisStep.StepID, "run", "completed", releaseAttributes)
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
		waveStepID := "context-wave-" + strconv.Itoa(wave)
		waveAttributes := map[string]string{
			"wave":              strconv.Itoa(wave),
			"specialist_count":  strconv.Itoa(len(waveSteps)),
			"concurrency_limit": strconv.Itoa(limit),
		}
		emitter.emit(waveStepID, "wave", "started", waveAttributes)
		wavePackets, waveFailures, concurrent := runtime.runContextWave(ctx, request, waveSteps, limit, emitter)
		packets = append(packets, wavePackets...)
		failures = append(failures, waveFailures...)
		waveStatus := "completed"
		if len(wavePackets) == 0 {
			waveStatus = "failed"
		} else if len(waveFailures) > 0 {
			waveStatus = "degraded"
		}
		waveAttributes["succeeded_count"] = strconv.Itoa(len(wavePackets))
		waveAttributes["failed_count"] = strconv.Itoa(len(waveFailures))
		waveAttributes["observed_concurrency"] = strconv.Itoa(concurrent)
		emitter.emit(waveStepID, "wave", waveStatus, waveAttributes)
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
				lifecycle := specialistLifecycleEventAdapter{emitter: emitter, stepID: step.StepID}
				_, observedLegacy := runtime.Deps.Specialist.(ObservedSpecialist)
				_, observedAttempt := runtime.Deps.Specialist.(AttemptAwareObservedSpecialist)
				observed := observedLegacy || observedAttempt
				packet, err := runtime.callSpecialist(ctx, contextRequest, step, lifecycle)
				if err != nil {
					outcomes <- outcome{index: index, failure: failure(contextRequest.RunID, step.StepID, classify(err), err, retryable(err), runtime.Now())}
					emitter.emit(step.StepID, "context", "failed", map[string]string{"code": classify(err)})
					return
				}
				packetAttributes := packetOperationalAttributes(packet)
				if !observed {
					// A legacy specialist exposes only its validated packet boundary. Do not
					// manufacture starts or failures that its adapter did not observe.
					emitter.emit(step.StepID, "retrieval", "completed", packetAttributes)
					for _, receipt := range packet.CalculationReceipts {
						emitter.emit(step.StepID, "tool", "completed", calculationReceiptAttributes(receipt))
					}
				}
				outcomes <- outcome{index: index, packet: packet}
				emitter.emit(step.StepID, "context", "completed", packetAttributes)
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

func sourceClasses(evidence []contracts.EvidenceRef) string {
	seen := map[string]bool{}
	for _, item := range evidence {
		value := strings.TrimSpace(item.SourceType)
		if value != "" {
			seen[value] = true
		}
	}
	result := make([]string, 0, len(seen))
	for value := range seen {
		result = append(result, value)
	}
	sort.Strings(result)
	return strings.Join(result, "+")
}

func packetOperationalAttributes(packet contracts.ContextPacket) map[string]string {
	totalClaims := len(packet.Findings) + len(packet.Counterevidence)
	supportedClaims := 0
	findings := append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...)
	claimCounts := map[contracts.ClaimType]int{}
	for _, finding := range findings {
		if len(finding.EvidenceRefs) > 0 {
			supportedClaims++
		}
		claimCounts[finding.ClaimType]++
	}
	return map[string]string{
		"packet_id":              packet.PacketID,
		"evidence_count":         fmt.Sprintf("%d", len(packet.Evidence)),
		"source_classes":         sourceClasses(packet.Evidence),
		"as_of":                  packet.Scope.AsOf.UTC().Format(time.DateOnly),
		"freshness_state":        "bounded_by_as_of",
		"finding_count":          fmt.Sprintf("%d", len(packet.Findings)),
		"counterevidence_count":  fmt.Sprintf("%d", len(packet.Counterevidence)),
		"fact_count":             fmt.Sprintf("%d", claimCounts[contracts.ClaimFact]),
		"calculation_count":      fmt.Sprintf("%d", claimCounts[contracts.ClaimCalculation]),
		"inference_count":        fmt.Sprintf("%d", claimCounts[contracts.ClaimInference]),
		"hypothesis_count":       fmt.Sprintf("%d", claimCounts[contracts.ClaimHypothesis]),
		"assumption_count":       fmt.Sprintf("%d", len(packet.Assumptions)),
		"missing_evidence_count": fmt.Sprintf("%d", len(packet.MissingEvidence)),
		"conflict_count":         fmt.Sprintf("%d", len(packet.Conflicts)),
		"uncertainty_count":      fmt.Sprintf("%d", len(packet.Uncertainties)),
		"evidence_coverage":      fmt.Sprintf("%d_of_%d", supportedClaims, totalClaims),
		"authority_state":        packet.AuthorityState,
	}
}

func interpretationAttributes(request contracts.ResearchRequest) map[string]string {
	entityIDs := make([]string, 0, len(request.Entities))
	for _, entity := range request.Entities {
		if entity.Resolved && strings.TrimSpace(entity.EntityID) != "" {
			entityIDs = append(entityIDs, entity.EntityID)
		}
	}
	sort.Strings(entityIDs)
	return map[string]string{
		"primary_intent":         request.PrimaryIntent,
		"entity_count":           fmt.Sprintf("%d", len(entityIDs)),
		"entity_ids":             strings.Join(entityIDs, "+"),
		"as_of":                  request.AsOf.UTC().Format("2006-01-02"),
		"answer_depth":           request.AnswerDepth,
		"ambiguity_count":        fmt.Sprintf("%d", len(request.Ambiguities)),
		"requested_output_count": fmt.Sprintf("%d", len(request.RequestedOutputs)),
	}
}

func planningAttributes(plan contracts.ResearchPlan) map[string]string {
	rolesSeen := map[string]bool{}
	maximumWave := 0
	for _, step := range plan.Steps {
		if step.RoleID != "" {
			rolesSeen[step.RoleID] = true
		}
		if step.Wave > maximumWave {
			maximumWave = step.Wave
		}
	}
	return map[string]string{
		"role_count":                 fmt.Sprintf("%d", len(rolesSeen)),
		"wave_count":                 fmt.Sprintf("%d", maximumWave),
		"max_parallel_specialists":   fmt.Sprintf("%d", plan.MaxParallelSpecialists),
		"max_repair_passes":          fmt.Sprintf("%d", plan.MaxRepairPasses),
		"deadline_ms":                fmt.Sprintf("%d", plan.DeadlineMS),
		"completion_condition_count": fmt.Sprintf("%d", len(plan.CompletionConditions)),
		"abstention_condition_count": fmt.Sprintf("%d", len(plan.AbstentionConditions)),
		"completion_conditions":      strings.Join(plan.CompletionConditions, "+"),
		"abstention_conditions":      strings.Join(plan.AbstentionConditions, "+"),
	}
}

func invariantsPassed(results []contracts.InvariantResult) bool {
	if len(results) == 0 {
		return false
	}
	for _, result := range results {
		if !result.Passed {
			return false
		}
	}
	return true
}

func receiptInputIDs(receipt contracts.CalculationReceipt) string {
	values := make([]string, 0, len(receipt.NormalizedInputs))
	for _, input := range receipt.NormalizedInputs {
		values = append(values, input.InputID)
	}
	return boundedSafeIDs(values)
}

func receiptOutputIDs(receipt contracts.CalculationReceipt) string {
	values := make([]string, 0, len(receipt.Outputs))
	for _, output := range receipt.Outputs {
		values = append(values, output.OutputID)
	}
	return boundedSafeIDs(values)
}

func calculationReceiptAttributes(receipt contracts.CalculationReceipt) map[string]string {
	verification := "metadata_only"
	if engine.VerifyReceipt(receipt) == nil {
		verification = "canonical_verified"
	}
	return map[string]string{
		"tool_execution_id":    receipt.RequestID,
		"engine_id":            receipt.EngineID,
		"formula_version":      receipt.FormulaVersion,
		"input_count":          fmt.Sprintf("%d", len(receipt.NormalizedInputs)),
		"input_ref_ids":        receiptInputIDs(receipt),
		"invariant_count":      fmt.Sprintf("%d", len(receipt.InvariantResults)),
		"invariants_passed":    fmt.Sprintf("%t", invariantsPassed(receipt.InvariantResults)),
		"operation_id":         receipt.OperationID,
		"output_count":         fmt.Sprintf("%d", len(receipt.Outputs)),
		"output_ref_ids":       receiptOutputIDs(receipt),
		"receipt_id":           receipt.ReceiptID,
		"receipt_sha256":       receipt.ReceiptSHA,
		"receipt_verification": verification,
		"warning_count":        fmt.Sprintf("%d", len(receipt.Warnings)),
	}
}

func boundedSafeIDs(values []string) string {
	const maximumIDs = 12
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		result = append(result, value)
		if len(result) == maximumIDs {
			break
		}
	}
	sort.Strings(result)
	return strings.Join(result, "+")
}

func reviewOperationalAttributes(report contracts.CritiqueReport) map[string]string {
	return map[string]string{
		"report_id":            report.ReportID,
		"approved_claim_count": fmt.Sprintf("%d", len(report.ApprovedClaims)),
		"rejected_claim_count": fmt.Sprintf("%d", len(report.RejectedClaims)),
		"issue_count":          fmt.Sprintf("%d", len(report.Issues)),
		"repair_pass":          fmt.Sprintf("%d", report.RepairPass),
	}
}

func releaseOperationalAttributes(answer contracts.FinalAnswer, critiques []contracts.CritiqueReport) map[string]string {
	answerClaims := map[string]bool{}
	evidenceRefs := map[string]bool{}
	receiptRefs := map[string]bool{}
	for _, section := range answer.Sections {
		for _, claimID := range section.ClaimRefs {
			answerClaims[claimID] = true
		}
		for _, evidenceID := range section.EvidenceRefs {
			evidenceRefs[evidenceID] = true
		}
		for _, receiptID := range section.ReceiptRefs {
			receiptRefs[receiptID] = true
		}
	}
	approved := map[string]bool{}
	for _, critique := range critiques {
		for _, claimID := range critique.ApprovedClaims {
			approved[claimID] = true
		}
	}
	supported := 0
	for claimID := range answerClaims {
		if approved[claimID] {
			supported++
		}
	}
	return map[string]string{
		"answer_id":                answer.AnswerID,
		"mandatory_review_count":   fmt.Sprintf("%d", len(critiques)),
		"claim_count":              fmt.Sprintf("%d", len(answerClaims)),
		"supported_claim_coverage": fmt.Sprintf("%d_of_%d", supported, len(answerClaims)),
		"evidence_ref_count":       fmt.Sprintf("%d", len(evidenceRefs)),
		"receipt_ref_count":        fmt.Sprintf("%d", len(receiptRefs)),
		"limitation_count":         fmt.Sprintf("%d", len(answer.Limitations)),
		"section_count":            fmt.Sprintf("%d", len(answer.Sections)),
	}
}

func (runtime *Runtime) callSpecialist(parent context.Context, request contracts.ContextRequest, step contracts.PlanStep, lifecycle SpecialistLifecycleObserver) (contracts.ContextPacket, error) {
	role, _ := runtime.Roles.Get(step.RoleID)
	var last error
	for attempt := 0; attempt <= role.MaxRetries; attempt++ {
		ctx, cancel := context.WithTimeout(parent, time.Duration(step.TimeoutMS)*time.Millisecond)
		var packet contracts.ContextPacket
		var err error
		if observed, ok := runtime.Deps.Specialist.(AttemptAwareObservedSpecialist); ok {
			packet, err = observed.RunObservedAttempt(ctx, request, lifecycle, attempt)
		} else if observed, ok := runtime.Deps.Specialist.(ObservedSpecialist); ok {
			packet, err = observed.RunObserved(ctx, request, lifecycle)
		} else if aware, ok := runtime.Deps.Specialist.(AttemptAwareSpecialist); ok {
			packet, err = aware.RunAttempt(ctx, request, attempt)
		} else {
			packet, err = runtime.Deps.Specialist.Run(ctx, request)
		}
		cancel()
		if err == nil {
			if authorityErr := bindPacketAuthority(&packet, request); authorityErr != nil {
				return contracts.ContextPacket{}, authorityErr
			}
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
				emitter.emit(step.StepID, "review", "approved_subset", reviewOperationalAttributes(approval))
				return history, approvedPackets, nil
			}
		}
		if report.Decision == contracts.CritiqueApprove || report.Decision == contracts.CritiqueReject || pass == plan.MaxRepairPasses {
			emitter.emit(step.StepID, "review", string(report.Decision), reviewOperationalAttributes(report))
			return history, working, nil
		}
		// A repair asks the same reviewer to reconsider the unchanged claims with its prior issue
		// visible. Removing those claims here would make repair impossible because review roles are
		// deliberately forbidden from authoring replacement research. Narrow is the only intermediate
		// decision that prunes claims; a repeated repair on the final pass closes to the explicitly
		// approved subset above or remains non-approved.
		if report.Decision == contracts.CritiqueRepair {
			reviewContext = append(reviewContext, report)
			emitter.emit(step.StepID, "review", "repair_requested", reviewOperationalAttributes(report))
			continue
		}
		narrowed, changed := narrowContextPackets(working, report)
		if !changed {
			emitter.emit(step.StepID, "review", "repair_unresolved", reviewOperationalAttributes(report))
			return history, working, nil
		}
		working = narrowed
		reviewContext = append(reviewContext, report)
		emitter.emit(step.StepID, "review", "narrowed", reviewOperationalAttributes(report))
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
		if err := contracts.ValidateContextPacket(result[index]); err != nil {
			return packets, contracts.CritiqueReport{}, false
		}
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
		if packets[index].NumericalContext != nil {
			numerical := *packets[index].NumericalContext
			numerical.Variables = append([]contracts.NumericalVariable(nil), numerical.Variables...)
			numerical.Relations = append([]contracts.NumericalRelation(nil), numerical.Relations...)
			result[index].NumericalContext = &numerical
		}
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
		if err := contracts.ValidateContextPacket(result[index]); err != nil {
			return packets, false
		}
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
	evidence, receipts, numerical := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		for _, evidenceID := range finding.EvidenceRefs {
			evidence[evidenceID] = true
		}
		for _, receiptID := range finding.CalculationRefs {
			receipts[receiptID] = true
		}
		for _, numericalID := range finding.NumericalRefs {
			numerical[numericalID] = true
		}
	}

	if packet.NumericalContext != nil {
		variables := make(map[string]contracts.NumericalVariable, len(packet.NumericalContext.Variables))
		relations := make(map[string]contracts.NumericalRelation, len(packet.NumericalContext.Relations))
		for _, variable := range packet.NumericalContext.Variables {
			variables[variable.VariableID] = variable
		}
		for _, relation := range packet.NumericalContext.Relations {
			relations[relation.RelationID] = relation
		}

		retainedVariables, retainedRelations := map[string]bool{}, map[string]bool{}
		var retainVariable func(string)
		retainVariable = func(variableID string) {
			if retainedVariables[variableID] {
				return
			}
			variable, exists := variables[variableID]
			if !exists {
				return
			}
			retainedVariables[variableID] = true
			for _, baselineID := range variable.BaselineRefs {
				retainVariable(baselineID)
			}
		}
		for numericalID := range numerical {
			if relation, exists := relations[numericalID]; exists {
				retainedRelations[numericalID] = true
				retainVariable(relation.LeftVariableID)
				retainVariable(relation.RightVariableID)
				continue
			}
			retainVariable(numericalID)
		}

		keptVariables := make([]contracts.NumericalVariable, 0, len(retainedVariables))
		for _, variable := range packet.NumericalContext.Variables {
			if !retainedVariables[variable.VariableID] {
				continue
			}
			keptVariables = append(keptVariables, variable)
			for _, evidenceID := range variable.EvidenceRefs {
				evidence[evidenceID] = true
			}
			for _, receiptID := range variable.ReceiptRefs {
				receipts[receiptID] = true
			}
		}
		keptRelations := make([]contracts.NumericalRelation, 0, len(retainedRelations))
		for _, relation := range packet.NumericalContext.Relations {
			if !retainedRelations[relation.RelationID] {
				continue
			}
			keptRelations = append(keptRelations, relation)
			for _, evidenceID := range relation.EvidenceRefs {
				evidence[evidenceID] = true
			}
			for _, receiptID := range relation.ReceiptRefs {
				receipts[receiptID] = true
			}
		}
		if len(keptVariables) == 0 {
			packet.NumericalContext = nil
		} else {
			packet.NumericalContext.Variables = keptVariables
			packet.NumericalContext.Relations = keptRelations
		}
	}

	keptReceipts := make([]contracts.CalculationReceipt, 0, len(packet.CalculationReceipts))
	for _, receipt := range packet.CalculationReceipts {
		if receipts[receipt.ReceiptID] {
			keptReceipts = append(keptReceipts, receipt)
			for _, evidenceID := range receipt.EvidenceRefs {
				evidence[evidenceID] = true
			}
		}
	}
	packet.CalculationReceipts = keptReceipts
	keptEvidence := make([]contracts.EvidenceRef, 0, len(packet.Evidence))
	for _, item := range packet.Evidence {
		if evidence[item.EvidenceID] {
			keptEvidence = append(keptEvidence, item)
		}
	}
	packet.Evidence = keptEvidence
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
		EvidenceRefs:         append([]string(nil), request.LineageEvidenceRefs...),
		ReceiptRefs:          append([]string(nil), request.LineageReceiptRefs...),
		Assumptions:          append([]string(nil), request.Assumptions...),
		AuthorityState:       request.AuthorityState,
		AuthorityRefs:        append([]string(nil), request.AuthorityRefs...),
		AuthorityReasonCodes: append([]string(nil), request.AuthorityReasonCodes...),
	}
}

func bindPacketAuthority(packet *contracts.ContextPacket, request contracts.ContextRequest) error {
	if packet.AuthorityState != "" && packet.AuthorityState != request.AuthorityState {
		return errors.New("specialist attempted to mutate deterministic authority state")
	}
	if len(packet.AuthorityRefs) > 0 && !stringSlicesEqual(packet.AuthorityRefs, request.AuthorityRefs) {
		return errors.New("specialist attempted to mutate deterministic authority references")
	}
	packet.AuthorityState = request.AuthorityState
	packet.AuthorityRefs = append([]string(nil), request.AuthorityRefs...)
	return nil
}

func stringSlicesEqual(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
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
	wave := step.Wave
	if wave <= 0 && step.Kind == "context" {
		wave = 1
	}
	attributes := map[string]string{
		"role_id":           step.RoleID,
		"route_reason_code": reason,
		"capability_ids":    strings.Join(step.CapabilityIDs, ","),
	}
	if wave > 0 {
		attributes["wave"] = strconv.Itoa(wave)
	}
	return attributes
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

type specialistLifecycleEventAdapter struct {
	emitter *eventEmitter
	stepID  string
}

func (adapter specialistLifecycleEventAdapter) RetrievalStarted(lifecycle RetrievalLifecycle) {
	adapter.emitRetrieval("started", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) RetrievalPassed(lifecycle RetrievalLifecycle) {
	adapter.emitRetrieval("passed", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) RetrievalDegraded(lifecycle RetrievalLifecycle) {
	adapter.emitRetrieval("degraded", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) RetrievalFailed(lifecycle RetrievalLifecycle) {
	adapter.emitRetrieval("failed", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) ToolStarted(lifecycle ToolLifecycle) {
	adapter.emitTool("started", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) ToolPassed(lifecycle ToolLifecycle) {
	adapter.emitTool("passed", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) ToolFailed(lifecycle ToolLifecycle) {
	adapter.emitTool("failed", lifecycle)
}

func (adapter specialistLifecycleEventAdapter) emitRetrieval(status string, lifecycle RetrievalLifecycle) {
	if adapter.emitter == nil {
		return
	}
	attributes := map[string]string{
		"retrieval_id":           lifecycle.RetrievalID,
		"bundle_id":              lifecycle.BundleID,
		"retrieval_method":       lifecycle.Method,
		"evidence_count":         fmt.Sprintf("%d", lifecycle.EvidenceCount),
		"source_classes":         boundedSafeIDs(lifecycle.SourceClasses),
		"missing_evidence_count": fmt.Sprintf("%d", lifecycle.MissingEvidenceCount),
	}
	if !lifecycle.AsOf.IsZero() {
		attributes["as_of"] = lifecycle.AsOf.UTC().Format(time.DateOnly)
	}
	if lifecycle.CandidateCountsKnown {
		attributes["candidate_count"] = fmt.Sprintf("%d", lifecycle.CandidateCount)
		attributes["selected_candidate_count"] = fmt.Sprintf("%d", lifecycle.SelectedCandidateCount)
		attributes["rejected_candidate_count"] = fmt.Sprintf("%d", lifecycle.RejectedCandidateCount)
		attributes["candidate_count_state"] = "available"
	} else {
		attributes["candidate_count_state"] = "unavailable"
	}
	if lifecycle.FailureCode != "" {
		attributes["code"] = lifecycle.FailureCode
	}
	adapter.emitter.emit(adapter.stepID, "retrieval", status, attributes)
}

func (adapter specialistLifecycleEventAdapter) emitTool(status string, lifecycle ToolLifecycle) {
	if adapter.emitter == nil {
		return
	}
	attributes := map[string]string{
		"tool_execution_id":    lifecycle.ToolExecutionID,
		"receipt_id":           lifecycle.ReceiptID,
		"receipt_sha256":       lifecycle.ReceiptSHA,
		"receipt_verification": lifecycle.ReceiptVerification,
		"engine_id":            lifecycle.EngineID,
		"operation_id":         lifecycle.OperationID,
		"formula_version":      lifecycle.FormulaVersion,
		"input_ref_ids":        boundedSafeIDs(lifecycle.InputRefIDs),
		"output_ref_ids":       boundedSafeIDs(lifecycle.OutputRefIDs),
		"input_count":          fmt.Sprintf("%d", lifecycle.InputCount),
		"output_count":         fmt.Sprintf("%d", lifecycle.OutputCount),
		"invariant_count":      fmt.Sprintf("%d", lifecycle.InvariantCount),
		"invariants_passed":    fmt.Sprintf("%t", lifecycle.InvariantsPassed),
		"warning_count":        fmt.Sprintf("%d", lifecycle.WarningCount),
	}
	if lifecycle.FailureCode != "" {
		attributes["code"] = lifecycle.FailureCode
	}
	adapter.emitter.emit(adapter.stepID, "tool", status, attributes)
}

func newEmitter(runID string, sink EventSink, now func() time.Time, trace *Trace) *eventEmitter {
	return &eventEmitter{runID: runID, sink: sink, now: now, trace: trace}
}

func (emitter *eventEmitter) emit(stepID, eventType, status string, attributes map[string]string) {
	emitter.mu.Lock()
	defer emitter.mu.Unlock()
	snapshot := make(map[string]string, len(attributes))
	for key, value := range attributes {
		snapshot[key] = value
	}
	event := Event{Sequence: len(emitter.trace.Events) + 1, RunID: emitter.runID, StepID: stepID, Type: eventType, Status: status, At: emitter.now(), Attributes: snapshot}
	emitter.trace.Events = append(emitter.trace.Events, event)
	if emitter.sink != nil {
		emitSafely(emitter.sink, event)
	}
}

func acceptPlanSafely(sink PlanSink, plan contracts.ResearchPlan, at time.Time) {
	defer func() {
		_ = recover()
	}()
	sink.AcceptPlan(plan, at)
}

func emitSafely(sink EventSink, event Event) {
	defer func() {
		_ = recover()
	}()
	sink.Emit(event)
}
