package roleeval

import (
	"context"
	"fmt"
	"slices"
	"sync"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type Metrics struct {
	ContractValid         float64 `json:"contract_valid"`
	RoutingCorrect        float64 `json:"routing_correct"`
	PacketComplete        float64 `json:"packet_complete"`
	CitationSupport       float64 `json:"citation_support"`
	NumericalConsistency  float64 `json:"numerical_consistency"`
	ContradictionHandling float64 `json:"contradiction_handling"`
	BoundaryCompliance    float64 `json:"boundary_compliance"`
}

type Observation struct {
	CaseID           string  `json:"case_id"`
	RoleID           string  `json:"role_id"`
	Kind             string  `json:"kind"`
	Success          bool    `json:"success"`
	Metrics          Metrics `json:"metrics"`
	DurationMS       float64 `json:"duration_ms"`
	PromptTokens     int     `json:"prompt_tokens,omitempty"`
	CompletionTokens int     `json:"completion_tokens,omitempty"`
	FinishReason     string  `json:"finish_reason,omitempty"`
	ModelOutput      string  `json:"model_output,omitempty"`
	FailureClass     string  `json:"failure_class,omitempty"`
	Error            string  `json:"error,omitempty"`
}

type RoleSummary struct {
	RoleID   string  `json:"role_id"`
	Cases    int     `json:"cases"`
	Passed   int     `json:"passed"`
	PassRate float64 `json:"pass_rate"`
	Metrics  Metrics `json:"metrics"`
}

type Report struct {
	SchemaVersion         string        `json:"schema_version"`
	SuiteID               string        `json:"suite_id"`
	SuiteSHA256           string        `json:"suite_sha256,omitempty"`
	PromptSetVersion      string        `json:"prompt_set_version"`
	ModelID               string        `json:"model_id"`
	StartedAt             time.Time     `json:"started_at"`
	CompletedAt           time.Time     `json:"completed_at"`
	Cases                 int           `json:"cases"`
	Passed                int           `json:"passed"`
	PassRate              float64       `json:"pass_rate"`
	TotalPromptTokens     int           `json:"total_prompt_tokens"`
	TotalCompletionTokens int           `json:"total_completion_tokens"`
	Roles                 []RoleSummary `json:"roles"`
	Observations          []Observation `json:"observations"`
}

type Evaluator struct {
	Client  localagent.Completer
	Model   string
	Workers int
	Now     func() time.Time
}

func (evaluator Evaluator) Evaluate(ctx context.Context, suite Suite) (Report, error) {
	if err := suite.Validate(); err != nil {
		return Report{}, err
	}
	if evaluator.Client == nil || evaluator.Model == "" {
		return Report{}, fmt.Errorf("role evaluator requires a model client and model ID")
	}
	if evaluator.Workers < 1 || evaluator.Workers > 8 {
		return Report{}, fmt.Errorf("workers must be between one and eight")
	}
	if evaluator.Now == nil {
		evaluator.Now = func() time.Time { return time.Now().UTC() }
	}
	report := Report{
		SchemaVersion: "signalforge/role-evaluation-report/v1", SuiteID: suite.SuiteID,
		PromptSetVersion: suite.PromptSetVersion, ModelID: evaluator.Model,
		StartedAt: evaluator.Now(), Cases: len(suite.Cases), Observations: make([]Observation, len(suite.Cases)),
	}
	semaphore := make(chan struct{}, evaluator.Workers)
	var wait sync.WaitGroup
	for index, item := range suite.Cases {
		wait.Add(1)
		go func(index int, item Case) {
			defer wait.Done()
			select {
			case semaphore <- struct{}{}:
				defer func() { <-semaphore }()
			case <-ctx.Done():
				report.Observations[index] = Observation{CaseID: item.CaseID, RoleID: item.RoleID, Kind: item.Kind, Error: ctx.Err().Error()}
				return
			}
			report.Observations[index] = evaluator.runCase(ctx, item)
		}(index, item)
	}
	wait.Wait()
	report.CompletedAt = evaluator.Now()
	report.summarize()
	return report, nil
}

func (evaluator Evaluator) runCase(ctx context.Context, item Case) Observation {
	started := time.Now()
	recorder := &recordingCompleter{next: evaluator.Client}
	result := Observation{CaseID: item.CaseID, RoleID: item.RoleID, Kind: item.Kind}
	var metrics Metrics
	var err error
	switch item.Kind {
	case "interpreter":
		metrics, err = evaluateInterpreter(ctx, recorder, evaluator.Model, item)
	case "planner":
		metrics, err = evaluatePlanner(item)
	case "context":
		metrics, err = evaluateContext(ctx, recorder, evaluator.Model, item)
	case "review":
		metrics, err = evaluateReview(ctx, recorder, evaluator.Model, item)
	case "synthesis":
		metrics, err = evaluateSynthesis(ctx, recorder, evaluator.Model, item)
	default:
		err = fmt.Errorf("unsupported role evaluation kind %q", item.Kind)
	}
	result.DurationMS = float64(time.Since(started).Microseconds()) / 1000
	result.Metrics = metrics
	result.Success = err == nil && allMetricsPass(metrics)
	if err != nil {
		result.Error = err.Error()
	}
	if recorder.called {
		result.PromptTokens = recorder.completion.Usage.PromptTokens
		result.CompletionTokens = recorder.completion.Usage.CompletionTokens
		result.FinishReason = recorder.completion.FinishReason
		result.ModelOutput = recorder.completion.Answer
	}
	if !result.Success {
		result.FailureClass = classifyFailure(result)
	}
	return result
}

type recordingCompleter struct {
	next       localagent.Completer
	completion benchmark.Completion
	called     bool
}

func (recorder *recordingCompleter) Complete(ctx context.Context, request benchmark.Request) (benchmark.Completion, error) {
	completion, err := recorder.next.Complete(ctx, request)
	recorder.called = true
	recorder.completion = completion
	return completion, err
}

type staticProvider struct{ material localagent.Material }

func (provider staticProvider) Load(_ context.Context, _ contracts.ContextRequest) (localagent.Material, error) {
	return provider.material, nil
}

func evaluateInterpreter(ctx context.Context, client localagent.Completer, model string, item Case) (Metrics, error) {
	now := frozenTime()
	adapter, _ := localagent.NewInterpreter(client, model)
	request, err := adapter.Interpret(ctx, requestparser.Input{
		Text: item.Question, AsOf: now, RunID: "eval-run", RequestID: "request-" + item.CaseID,
	})
	if err != nil {
		return Metrics{}, err
	}
	metrics := passMetrics()
	metrics.RoutingCorrect = boolMetric(request.PrimaryIntent == item.Expected.PrimaryIntent)
	if len(item.Expected.RequiredTerms) > 0 {
		metrics.BoundaryCompliance = boolMetric(len(request.RiskFlags) > 0)
	}
	return metrics, nil
}

func evaluatePlanner(item Case) (Metrics, error) {
	now := frozenTime()
	var request contracts.ResearchRequest
	var err error
	if item.Expected.PrimaryIntent != "" {
		request = baseRequest(item.Question, item.Expected.PrimaryIntent, now)
		request.RequestID = "request-" + item.CaseID
	} else {
		request, err = requestparser.ParseDeterministic(requestparser.Input{
			Text: item.Question, AsOf: now, RunID: "eval-run", RequestID: "request-" + item.CaseID,
		})
		if err != nil {
			return Metrics{}, err
		}
	}
	plan, err := localagent.DefaultPlannerAdapter().Plan(request)
	if err != nil {
		return Metrics{}, err
	}
	activeRoles, capabilities := []string{}, []string{}
	for _, step := range plan.Steps {
		activeRoles = append(activeRoles, step.RoleID)
		capabilities = append(capabilities, step.CapabilityIDs...)
	}
	routing := containsAll(activeRoles, item.Expected.MandatoryRoles) && containsAll(capabilities, item.Expected.MandatoryCapabilities)
	metrics := passMetrics()
	metrics.RoutingCorrect = boolMetric(routing)
	metrics.ContractValid = boolMetric(contracts.ValidateResearchPlan(plan) == nil)
	return metrics, nil
}

func evaluateContext(ctx context.Context, client localagent.Completer, model string, item Case) (Metrics, error) {
	now := frozenTime()
	request := contracts.ContextRequest{
		SchemaVersion: contracts.SchemaVersionV1, ContextRequestID: "context-" + item.CaseID,
		RunID: "eval-run", StepID: "step-" + item.CaseID, SpecialistRole: item.RoleID,
		Objective: roleMission(item.RoleID), ResearchQuestion: item.Question,
		Scope: contracts.Scope{AsOf: now}, TokenBudget: 5000,
	}
	material := materialFor(item, now, request.StepID)
	adapter, err := localagent.New(client, model, staticProvider{material: material})
	if err != nil {
		return Metrics{}, err
	}
	packet, err := adapter.Run(ctx, request)
	if err != nil {
		return Metrics{}, err
	}
	text := packetText(packet)
	metrics := passMetrics()
	metrics.ContractValid = boolMetric(contracts.ValidateContextPacket(packet) == nil)
	metrics.PacketComplete = boolMetric(len(packet.Findings) >= item.Expected.MinimumFindings &&
		(!item.Expected.RequireMissing || len(packet.MissingEvidence)+len(packet.Uncertainties) > 0) &&
		(!item.Expected.RequireConflict || len(packet.Conflicts) > 0) &&
		(item.Expected.RequiredHandoff == "" || textContains(text, item.Expected.RequiredHandoff)))
	metrics.CitationSupport = boolMetric(!item.Expected.RequireEvidence || packetCitationsSupported(packet))
	metrics.NumericalConsistency = boolMetric(!item.Expected.RequireCalculationRef ||
		packetCalculationSupported(packet, item.Calculations))
	metrics.ContradictionHandling = boolMetric(!item.Expected.RequireConflict || len(packet.Conflicts) > 0)
	metrics.BoundaryCompliance = boolMetric(containsTerms(text, item.Expected.RequiredTerms) &&
		forbiddenTermsClear(text, item.Expected.ForbiddenTerms))
	return metrics, nil
}

func evaluateReview(ctx context.Context, client localagent.Completer, model string, item Case) (Metrics, error) {
	now := frozenTime()
	packet := reviewPacket(item, now)
	request := baseRequest(item.Question, "thesis_review", now)
	adapter, _ := localagent.New(client, model, staticProvider{material: localagent.Material{}})
	report, err := adapter.Review(ctx, orchestrator.ReviewInput{
		Request: request,
		Step:    contracts.PlanStep{StepID: "review-" + item.CaseID, RoleID: item.RoleID},
		Packets: []contracts.ContextPacket{packet},
	})
	if err != nil {
		return Metrics{}, err
	}
	text := critiqueText(report)
	metrics := passMetrics()
	metrics.ContractValid = boolMetric(contracts.ValidateCritiqueReport(report) == nil)
	metrics.CitationSupport = boolMetric(reviewDecisionSupported(report, packet, item.Scenario))
	metrics.ContradictionHandling = boolMetric(!slices.Contains([]string{"conflict", "material_counterevidence"}, item.Scenario) || report.Decision != contracts.CritiqueApprove)
	metrics.BoundaryCompliance = boolMetric(slices.Contains(item.Expected.AllowedDecisions, string(report.Decision)) &&
		containsTerms(text, item.Expected.RequiredTerms))
	return metrics, nil
}

func evaluateSynthesis(ctx context.Context, client localagent.Completer, model string, item Case) (Metrics, error) {
	now := frozenTime()
	packet := synthesisPacket(item, now)
	request := baseRequest(item.Question, item.Scenario, now)
	claims := []string{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		claims = append(claims, finding.ClaimID)
	}
	critique := contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-1", RunID: request.RunID,
		ReviewerRole: roles.EvidenceCritic, Decision: contracts.CritiqueApprove,
		ApprovedClaims: claims, CreatedAt: now,
	}
	adapter, _ := localagent.New(client, model, staticProvider{material: localagent.Material{}})
	answer, err := adapter.Synthesize(ctx, orchestrator.SynthesisInput{
		Request: request, Packets: []contracts.ContextPacket{packet}, Critiques: []contracts.CritiqueReport{critique},
	})
	if err != nil {
		return Metrics{}, err
	}
	present := []string{}
	for _, section := range answer.Sections {
		present = append(present, section.SectionType)
	}
	metrics := passMetrics()
	metrics.ContractValid = boolMetric(contracts.ValidateFinalAnswer(answer) == nil)
	metrics.PacketComplete = boolMetric(containsAll(present, item.Expected.RequiredSections))
	metrics.CitationSupport = boolMetric(!item.Expected.RequireEvidence || answerCitationsSupported(answer, packet))
	return metrics, nil
}

func (report *Report) summarize() {
	byRole := map[string][]Observation{}
	for _, observation := range report.Observations {
		byRole[observation.RoleID] = append(byRole[observation.RoleID], observation)
		if observation.Success {
			report.Passed++
		}
		report.TotalPromptTokens += observation.PromptTokens
		report.TotalCompletionTokens += observation.CompletionTokens
	}
	report.PassRate = ratio(report.Passed, report.Cases)
	for _, role := range roles.DefaultRegistry().List() {
		observations := byRole[role.ID]
		summary := RoleSummary{RoleID: role.ID, Cases: len(observations)}
		for _, observation := range observations {
			if observation.Success {
				summary.Passed++
			}
			summary.Metrics = addMetrics(summary.Metrics, observation.Metrics)
		}
		summary.PassRate = ratio(summary.Passed, summary.Cases)
		summary.Metrics = divideMetrics(summary.Metrics, summary.Cases)
		report.Roles = append(report.Roles, summary)
	}
}

func passMetrics() Metrics {
	return Metrics{ContractValid: 1, RoutingCorrect: 1, PacketComplete: 1, CitationSupport: 1, NumericalConsistency: 1, ContradictionHandling: 1, BoundaryCompliance: 1}
}

func allMetricsPass(metrics Metrics) bool {
	return metrics.ContractValid == 1 && metrics.RoutingCorrect == 1 && metrics.PacketComplete == 1 &&
		metrics.CitationSupport == 1 && metrics.NumericalConsistency == 1 &&
		metrics.ContradictionHandling == 1 && metrics.BoundaryCompliance == 1
}

func addMetrics(left, right Metrics) Metrics {
	return Metrics{left.ContractValid + right.ContractValid, left.RoutingCorrect + right.RoutingCorrect,
		left.PacketComplete + right.PacketComplete, left.CitationSupport + right.CitationSupport,
		left.NumericalConsistency + right.NumericalConsistency, left.ContradictionHandling + right.ContradictionHandling,
		left.BoundaryCompliance + right.BoundaryCompliance}
}

func divideMetrics(value Metrics, count int) Metrics {
	if count == 0 {
		return Metrics{}
	}
	denominator := float64(count)
	return Metrics{value.ContractValid / denominator, value.RoutingCorrect / denominator,
		value.PacketComplete / denominator, value.CitationSupport / denominator,
		value.NumericalConsistency / denominator, value.ContradictionHandling / denominator,
		value.BoundaryCompliance / denominator}
}
