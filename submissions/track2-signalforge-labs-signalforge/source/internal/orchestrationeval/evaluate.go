package orchestrationeval

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/planner"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
	"github.com/rvbernucci/signalforge/internal/taxonomy"
)

type Report struct {
	SchemaVersion             string   `json:"schema_version"`
	Cases                     int      `json:"cases"`
	IntentAccuracy            float64  `json:"intent_accuracy"`
	ClarificationAccuracy     float64  `json:"clarification_accuracy"`
	MandatoryRoleRecall       float64  `json:"mandatory_role_recall"`
	MandatoryCapabilityRecall float64  `json:"mandatory_capability_recall"`
	AdviceBoundaryRecall      float64  `json:"advice_boundary_recall"`
	ValidPlanRate             float64  `json:"valid_plan_rate"`
	UnauthorizedCapabilities  int      `json:"unauthorized_capabilities"`
	MaxContextFanOut          int      `json:"max_context_fan_out"`
	MultipleSynthesisPlans    int      `json:"multiple_synthesis_plans"`
	RecursivePlans            int      `json:"recursive_plans"`
	MissingCapabilities       []string `json:"missing_capabilities,omitempty"`
	RuntimeCases              int      `json:"runtime_cases"`
	RuntimeSuccessRate        float64  `json:"runtime_success_rate"`
	ReviewGateCoverage        float64  `json:"review_gate_coverage"`
	ConflictPreservationRate  float64  `json:"conflict_preservation_rate"`
	TracePrivacyViolations    int      `json:"trace_privacy_violations"`
	RuntimeFailures           []string `json:"runtime_failures,omitempty"`
	Accepted                  bool     `json:"accepted"`
}

func Evaluate() (Report, error) {
	cases := taxonomy.FrozenCases()
	builder := planner.Default()
	gate := orchestrator.ToolGate{Capabilities: builder.Capabilities, Roles: builder.Roles}
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)
	intentCorrect, clarificationCorrect, adviceCases, adviceFound := 0, 0, 0, 0
	roleTotal, roleFound, capabilityTotal, capabilityFound := 0, 0, 0, 0
	validPlans, unauthorized, maxFanOut, multipleSynthesis, recursive := 0, 0, 0, 0, 0
	runtimeCases, runtimeSuccesses, requiredGates, observedGates, conflictPreserved := 0, 0, 0, 0, 0
	tracePrivacyViolations := 0
	runtimeFailures := []string{}
	missingCapabilities := []string{}
	for _, item := range cases {
		input := requestparser.Input{Text: item.Question, AsOf: now, RunID: "eval-run", RequestID: "eval-" + item.CaseID}
		input.InheritedEntities = mentioned(item.EntityMentions)
		if item.FollowUp {
			input.ParentRequestID = "eval-parent"
			if len(input.InheritedEntities) == 0 {
				input.InheritedEntities = inherited(item.CaseID)
			}
		}
		request, err := requestparser.ParseDeterministic(input)
		if err != nil {
			return Report{}, err
		}
		if request.PrimaryIntent == string(item.PrimaryIntent) {
			intentCorrect++
		}
		if item.AdversarialAdvice {
			adviceCases++
			if len(request.RiskFlags) > 0 {
				adviceFound++
			}
		}
		plan, planErr := builder.Build(request)
		if item.ClarificationRequired {
			if errors.Is(planErr, planner.ErrClarificationRequired) {
				clarificationCorrect++
			}
			continue
		}
		if planErr != nil {
			return Report{}, fmt.Errorf("case %s: %w", item.CaseID, planErr)
		}
		clarificationCorrect++
		if contracts.ValidateResearchPlan(plan) == nil {
			validPlans++
		} else {
			recursive++
		}
		rolesInPlan := []string{}
		capabilitiesInPlan := []string{}
		contextCount, synthesisCount := 0, 0
		for _, step := range plan.Steps {
			rolesInPlan = append(rolesInPlan, step.RoleID)
			capabilitiesInPlan = append(capabilitiesInPlan, step.CapabilityIDs...)
			if step.Kind == "context" {
				contextCount++
			}
			if step.Kind == "synthesis" {
				synthesisCount++
			}
			for _, operationID := range step.CapabilityIDs {
				if _, err := gate.Authorize(step.RoleID, operationID); err != nil {
					unauthorized++
				}
			}
		}
		if contextCount > maxFanOut {
			maxFanOut = contextCount
		}
		if synthesisCount != 1 {
			multipleSynthesis++
		}
		for _, required := range item.MandatoryRoles {
			roleTotal++
			if slices.Contains(rolesInPlan, required) {
				roleFound++
			}
		}
		for _, required := range item.MandatoryCapabilities {
			capabilityTotal++
			if slices.Contains(capabilitiesInPlan, required) {
				capabilityFound++
			} else {
				missingCapabilities = append(missingCapabilities, item.CaseID+":"+required)
			}
		}
		probe := &runtimeProbe{}
		runtime, runtimeErr := orchestrator.New(orchestrator.Dependencies{
			Specialist: probe, Reviewer: probe, Synthesizer: probe, TraceStore: probe,
		})
		if runtimeErr != nil {
			return Report{}, runtimeErr
		}
		runtime.Now = func() time.Time { return now }
		runtimeCases++
		result := runtime.Run(context.Background(), request)
		if result.Failure == nil && result.Answer != nil && probe.synthesisCalls == 1 {
			runtimeSuccesses++
		} else {
			failureCode := "missing_answer"
			if result.Failure != nil {
				failureCode = result.Failure.FailureCode + ":" + result.Failure.Message
			}
			runtimeFailures = append(runtimeFailures, item.CaseID+":"+failureCode)
		}
		for _, step := range plan.Steps {
			if step.Kind == "review" {
				requiredGates++
				if slices.Contains(probe.reviewRoles, step.RoleID) {
					observedGates++
				}
			}
		}
		if probe.conflictSeenByReview && probe.conflictSeenBySynthesis {
			conflictPreserved++
		}
		encoded, _ := json.Marshal(result.Trace)
		if strings.Contains(string(encoded), item.Question) || strings.Contains(strings.ToLower(string(encoded)), "api_key") {
			tracePrivacyViolations++
		}
	}
	report := Report{
		SchemaVersion: "signalforge/orchestration-evaluation/v1", Cases: len(cases),
		IntentAccuracy: ratio(intentCorrect, len(cases)), ClarificationAccuracy: ratio(clarificationCorrect, len(cases)),
		MandatoryRoleRecall: ratio(roleFound, roleTotal), MandatoryCapabilityRecall: ratio(capabilityFound, capabilityTotal),
		AdviceBoundaryRecall: ratio(adviceFound, adviceCases), ValidPlanRate: ratio(validPlans, len(cases)-clarificationCount(cases)),
		UnauthorizedCapabilities: unauthorized, MaxContextFanOut: maxFanOut,
		MultipleSynthesisPlans: multipleSynthesis, RecursivePlans: recursive,
		MissingCapabilities: missingCapabilities,
		RuntimeCases:        runtimeCases, RuntimeSuccessRate: ratio(runtimeSuccesses, runtimeCases),
		ReviewGateCoverage:       ratio(observedGates, requiredGates),
		ConflictPreservationRate: ratio(conflictPreserved, runtimeCases), TracePrivacyViolations: tracePrivacyViolations,
		RuntimeFailures: runtimeFailures,
	}
	report.Accepted = report.IntentAccuracy == 1 && report.ClarificationAccuracy == 1 &&
		report.MandatoryRoleRecall == 1 && report.MandatoryCapabilityRecall == 1 &&
		report.AdviceBoundaryRecall == 1 && report.ValidPlanRate == 1 &&
		report.UnauthorizedCapabilities == 0 && report.MaxContextFanOut <= 4 &&
		report.MultipleSynthesisPlans == 0 && report.RecursivePlans == 0 &&
		report.RuntimeSuccessRate == 1 && report.ReviewGateCoverage == 1 &&
		report.ConflictPreservationRate == 1 && report.TracePrivacyViolations == 0
	return report, nil
}

type runtimeProbe struct {
	reviewRoles             []string
	synthesisCalls          int
	conflictSeenByReview    bool
	conflictSeenBySynthesis bool
	traces                  []orchestrator.Trace
}

func (probe *runtimeProbe) Run(_ context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	evidenceID := "evidence-" + request.StepID
	return contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-" + request.StepID,
		RunID: request.RunID, StepID: request.StepID, SpecialistRole: request.SpecialistRole,
		Objective: request.Objective, Scope: request.Scope,
		Findings: []contracts.Finding{{
			ClaimID: "claim-" + request.StepID, ClaimType: contracts.ClaimFact,
			Statement: "Synthetic orchestration-contract finding.", EvidenceRefs: []string{evidenceID},
			Confidence: 1, ValidAsOf: request.Scope.AsOf,
		}},
		Evidence: []contracts.EvidenceRef{{
			EvidenceID: evidenceID, SourceType: "evaluation_fixture", Locator: request.StepID,
			ContentSHA: "synthetic-contract-only", AsOf: request.Scope.AsOf,
		}},
		Conflicts: []string{"synthetic conflict preserved for orchestration validation"},
	}, nil
}

func (probe *runtimeProbe) Review(_ context.Context, input orchestrator.ReviewInput) (contracts.CritiqueReport, error) {
	probe.reviewRoles = append(probe.reviewRoles, input.Step.RoleID)
	claims := []string{}
	for _, packet := range input.Packets {
		probe.conflictSeenByReview = probe.conflictSeenByReview || len(packet.Conflicts) > 0
		for _, finding := range packet.Findings {
			claims = append(claims, finding.ClaimID)
		}
	}
	return contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-" + input.Step.StepID,
		RunID: input.Request.RunID, ReviewerRole: input.Step.RoleID, Decision: contracts.CritiqueApprove,
		ApprovedClaims: claims, RepairPass: input.RepairPass, CreatedAt: input.Request.AsOf,
	}, nil
}

func (probe *runtimeProbe) Synthesize(_ context.Context, input orchestrator.SynthesisInput) (contracts.FinalAnswer, error) {
	probe.synthesisCalls++
	claimID, evidenceID := "", ""
	for _, packet := range input.Packets {
		probe.conflictSeenBySynthesis = probe.conflictSeenBySynthesis || len(packet.Conflicts) > 0
		if claimID == "" && len(packet.Findings) > 0 && len(packet.Evidence) > 0 {
			claimID = packet.Findings[0].ClaimID
			evidenceID = packet.Evidence[0].EvidenceID
		}
	}
	sections := []contracts.AnswerSection{}
	for _, sectionType := range contracts.RequiredFinalSections(input.Request.PrimaryIntent) {
		section := contracts.AnswerSection{
			SectionType: sectionType, Title: sectionType,
			Content: "Synthetic orchestration-contract answer.",
		}
		if sectionType != "evidence" && sectionType != "limitations" {
			section.ClaimRefs = []string{claimID}
			section.EvidenceRefs = []string{evidenceID}
		}
		sections = append(sections, section)
	}
	critiqueRefs := make([]string, 0, len(input.Critiques))
	for _, critique := range input.Critiques {
		critiqueRefs = append(critiqueRefs, critique.ReportID)
	}
	return contracts.FinalAnswer{
		SchemaVersion: contracts.SchemaVersionV1, AnswerID: "answer-" + input.Request.RequestID,
		RunID: input.Request.RunID, RequestID: input.Request.RequestID,
		PrimaryIntent: input.Request.PrimaryIntent, AsOf: input.Request.AsOf, Sections: sections,
		CritiqueRefs: critiqueRefs, ReleasedBy: roles.FinalResearchAnalyst, ReleasedAt: input.Request.AsOf,
	}, nil
}

func (probe *runtimeProbe) Save(trace orchestrator.Trace) error {
	probe.traces = append(probe.traces, trace)
	return nil
}

func inherited(caseID string) []contracts.EntityRef {
	entities := []contracts.EntityRef{{EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true}}
	if caseID == "comparison-03" {
		entities = append(entities, contracts.EntityRef{EntityType: "company", EntityID: "sec-cik:0001045810", Mention: "NVIDIA", Resolved: true})
	}
	return entities
}

func mentioned(values []string) []contracts.EntityRef {
	result := []contracts.EntityRef{}
	for _, value := range values {
		switch value {
		case "Microsoft":
			result = append(result, contracts.EntityRef{EntityType: "company", EntityID: "sec-cik:0000789019", Mention: value, Resolved: true})
		case "NVIDIA":
			result = append(result, contracts.EntityRef{EntityType: "company", EntityID: "sec-cik:0001045810", Mention: value, Resolved: true})
		}
	}
	return result
}

func clarificationCount(cases []taxonomy.QuestionCase) int {
	count := 0
	for _, item := range cases {
		if item.ClarificationRequired {
			count++
		}
	}
	return count
}

func ratio(numerator, denominator int) float64 {
	if denominator == 0 {
		return 1
	}
	return float64(numerator) / float64(denominator)
}
