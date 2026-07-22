package contracts

import (
	"errors"
	"fmt"
	"strings"
)

var validResearchIntents = map[string]bool{
	"company_understanding": true, "financial_quality": true, "economic_transmission": true,
	"valuation": true, "company_comparison": true, "concept_education": true,
	"market_behavior": true, "thesis_review": true,
}

func ValidateResearchRequest(request ResearchRequest) error {
	if err := validateEnvelope(request.SchemaVersion, request.RequestID, request.RunID); err != nil {
		return err
	}
	if strings.TrimSpace(request.UserText) == "" || request.PrimaryIntent == "" || request.AsOf.IsZero() {
		return errors.New("user_text, primary_intent, and as_of are required")
	}
	if !validResearchIntents[request.PrimaryIntent] {
		return fmt.Errorf("unsupported primary_intent %q", request.PrimaryIntent)
	}
	if request.ParentRequestID == "" && (len(request.LineageEvidenceRefs) > 0 || len(request.LineageReceiptRefs) > 0) {
		return errors.New("lineage references require parent_request_id")
	}
	for label, values := range map[string][]string{
		"lineage_evidence_refs": request.LineageEvidenceRefs,
		"lineage_receipt_refs":  request.LineageReceiptRefs,
	} {
		seen := map[string]bool{}
		for index, value := range values {
			if strings.TrimSpace(value) == "" || seen[value] {
				return fmt.Errorf("%s[%d] is empty or duplicated", label, index)
			}
			seen[value] = true
		}
	}
	for _, intent := range request.SecondaryIntents {
		if !validResearchIntents[intent] || intent == request.PrimaryIntent {
			return fmt.Errorf("unsupported or duplicate secondary_intent %q", intent)
		}
	}
	if request.Period.Kind == "" || request.Period.LookbackYears < 0 || request.Period.LookbackYears > 20 {
		return errors.New("period kind and a bounded lookback are required")
	}
	switch request.Comparison.Mode {
	case "none", "peer", "benchmark":
	default:
		return fmt.Errorf("unsupported comparison mode %q", request.Comparison.Mode)
	}
	entityIDs := make(map[string]bool)
	for index, entity := range request.Entities {
		if entity.EntityType == "" || entity.Mention == "" || (entity.Resolved && entity.EntityID == "") {
			return fmt.Errorf("entities[%d] is incomplete", index)
		}
		if entity.EntityID != "" && entityIDs[entity.EntityID] {
			return fmt.Errorf("entities[%d] duplicates entity_id %q", index, entity.EntityID)
		}
		entityIDs[entity.EntityID] = entity.EntityID != ""
	}
	switch request.AnswerDepth {
	case "brief", "standard", "deep":
	default:
		return fmt.Errorf("unsupported answer_depth %q", request.AnswerDepth)
	}
	if len(request.RequestedOutputs) == 0 {
		return errors.New("requested_outputs cannot be empty")
	}
	return nil
}

func ValidateResearchPlan(plan ResearchPlan) error {
	if err := validateEnvelope(plan.SchemaVersion, plan.PlanID, plan.RunID); err != nil {
		return err
	}
	if plan.RequestID == "" || len(plan.Steps) == 0 || plan.DeadlineMS <= 0 {
		return errors.New("request_id, steps, and positive deadline_ms are required")
	}
	if plan.MaxParallelSpecialists < 1 || plan.MaxParallelSpecialists > 4 {
		return errors.New("max_parallel_specialists must be between one and four")
	}
	if plan.MaxRepairPasses < 0 || plan.MaxRepairPasses > 1 {
		return errors.New("max_repair_passes must be zero or one")
	}
	steps := make(map[string]PlanStep, len(plan.Steps))
	contextPerWave := map[int]int{}
	contextSteps, synthesisSteps := 0, 0
	for _, step := range plan.Steps {
		if step.StepID == "" || step.Objective == "" || step.RoleID == "" || step.ContextBudget <= 0 || step.TimeoutMS <= 0 || step.TimeoutMS > plan.DeadlineMS {
			return fmt.Errorf("invalid step %q", step.StepID)
		}
		switch step.Kind {
		case "context":
			contextSteps++
			wave := step.Wave
			if wave == 0 {
				wave = 1
			}
			if wave < 1 || wave > 4 {
				return fmt.Errorf("context step %q has invalid wave %d", step.StepID, step.Wave)
			}
			contextPerWave[wave]++
			if contextPerWave[wave] > plan.MaxParallelSpecialists {
				return fmt.Errorf("context wave %d exceeds max_parallel_specialists", wave)
			}
		case "review":
		case "synthesis":
			synthesisSteps++
			if len(step.CapabilityIDs) > 0 {
				return errors.New("synthesis steps cannot execute capabilities")
			}
		default:
			return fmt.Errorf("step %q has unsupported kind %q", step.StepID, step.Kind)
		}
		capabilities := make(map[string]bool)
		for _, capabilityID := range step.CapabilityIDs {
			if strings.TrimSpace(capabilityID) == "" || capabilities[capabilityID] {
				return fmt.Errorf("step %q has an empty or duplicate capability", step.StepID)
			}
			capabilities[capabilityID] = true
		}
		if _, exists := steps[step.StepID]; exists {
			return fmt.Errorf("duplicate step %q", step.StepID)
		}
		steps[step.StepID] = step
	}
	if contextSteps > 8 || synthesisSteps != 1 {
		return errors.New("plan requires at most eight context steps and exactly one synthesis step")
	}
	for _, step := range plan.Steps {
		for _, dependency := range step.DependsOn {
			dependencyStep, exists := steps[dependency]
			if !exists {
				return fmt.Errorf("step %q has unknown dependency %q", step.StepID, dependency)
			}
			if step.Kind == "context" && dependencyStep.Kind == "context" && effectiveWave(dependencyStep.Wave) >= effectiveWave(step.Wave) {
				return fmt.Errorf("context step %q must depend only on an earlier context wave", step.StepID)
			}
		}
	}
	if hasPlanCycle(steps) {
		return errors.New("research plan must be acyclic")
	}
	return nil
}

func effectiveWave(wave int) int {
	if wave == 0 {
		return 1
	}
	return wave
}

func ValidateContextRequest(request ContextRequest) error {
	if err := validateEnvelope(request.SchemaVersion, request.ContextRequestID, request.RunID); err != nil {
		return err
	}
	if request.StepID == "" || request.SpecialistRole == "" || request.Objective == "" ||
		strings.TrimSpace(request.ResearchQuestion) == "" || request.Scope.AsOf.IsZero() || request.TokenBudget <= 0 {
		return errors.New("context request is incomplete")
	}
	capabilities := map[string]bool{}
	for index, capabilityID := range request.CapabilityIDs {
		if strings.TrimSpace(capabilityID) == "" || capabilities[capabilityID] {
			return fmt.Errorf("capability_ids[%d] is empty or duplicated", index)
		}
		capabilities[capabilityID] = true
	}
	assumptions := map[string]bool{}
	for index, assumption := range request.Assumptions {
		if strings.TrimSpace(assumption) == "" || assumptions[assumption] {
			return fmt.Errorf("assumptions[%d] is empty or duplicated", index)
		}
		assumptions[assumption] = true
	}
	return nil
}

func ValidateEvidenceBundle(bundle EvidenceBundle) error {
	if err := validateEnvelope(bundle.SchemaVersion, bundle.BundleID, bundle.RunID); err != nil {
		return err
	}
	if bundle.StepID == "" || bundle.AsOf.IsZero() {
		return errors.New("step_id and as_of are required")
	}
	for i, item := range bundle.Items {
		switch item.State {
		case EvidenceAvailable, EvidenceStale, EvidenceConflicting, EvidenceMissing, EvidenceIncomparable:
		default:
			return fmt.Errorf("items[%d] has invalid evidence state %q", i, item.State)
		}
		if item.State == EvidenceConflicting && len(item.ConflictRefs) == 0 {
			return fmt.Errorf("items[%d] conflicting evidence requires conflict_refs", i)
		}
	}
	return nil
}

func ValidateToolReceipt(receipt ToolReceipt) error {
	if err := validateEnvelope(receipt.SchemaVersion, receipt.ReceiptID, receipt.RunID); err != nil {
		return err
	}
	if receipt.StepID == "" || receipt.ToolID == "" || receipt.InputSHA == "" || receipt.StartedAt.IsZero() || receipt.CompletedAt.IsZero() {
		return errors.New("tool receipt is incomplete")
	}
	if receipt.CompletedAt.Before(receipt.StartedAt) {
		return errors.New("completed_at cannot precede started_at")
	}
	if receipt.Status == ReceiptSuccess && receipt.OutputSHA == "" {
		return errors.New("successful tool receipt requires output_sha256")
	}
	return nil
}

func ValidateCritiqueReport(report CritiqueReport) error {
	if err := validateEnvelope(report.SchemaVersion, report.ReportID, report.RunID); err != nil {
		return err
	}
	if report.ReviewerRole == "" || report.CreatedAt.IsZero() || report.RepairPass < 0 || report.RepairPass > 1 {
		return errors.New("critique report is incomplete")
	}
	switch report.Decision {
	case CritiqueApprove:
		if len(report.ApprovedClaims) == 0 {
			return errors.New("approval requires approved_claims")
		}
	case CritiqueRepair, CritiqueNarrow, CritiqueReject:
		if len(report.Issues) == 0 {
			return errors.New("non-approval decision requires issues")
		}
	default:
		return fmt.Errorf("invalid critique decision %q", report.Decision)
	}
	return nil
}

func ValidateFinalAnswer(answer FinalAnswer) error {
	if err := validateEnvelope(answer.SchemaVersion, answer.AnswerID, answer.RunID); err != nil {
		return err
	}
	if answer.RequestID == "" || answer.PrimaryIntent == "" || answer.AsOf.IsZero() || answer.ReleasedAt.IsZero() || answer.ReleasedBy == "" {
		return errors.New("final answer is incomplete")
	}
	if len(answer.Sections) == 0 || len(answer.CritiqueRefs) == 0 {
		return errors.New("final answer requires sections and critique_refs")
	}
	for i, section := range answer.Sections {
		if section.SectionType == "" || section.Title == "" || strings.TrimSpace(section.Content) == "" {
			return fmt.Errorf("sections[%d] is incomplete", i)
		}
		if len(section.ClaimRefs) > 0 && len(section.EvidenceRefs)+len(section.ReceiptRefs)+len(section.NumericalRefs) == 0 {
			return fmt.Errorf("sections[%d] has claims without evidence, receipts, or numerical authority", i)
		}
	}
	present := make(map[string]bool, len(answer.Sections))
	for _, section := range answer.Sections {
		present[section.SectionType] = true
	}
	for _, required := range RequiredFinalSections(answer.PrimaryIntent) {
		if !present[required] {
			return fmt.Errorf("primary intent %q requires section %q", answer.PrimaryIntent, required)
		}
	}
	return nil
}

func ValidateMemoryCandidate(candidate MemoryCandidate) error {
	if err := validateEnvelope(candidate.SchemaVersion, candidate.CandidateID, candidate.RunID); err != nil {
		return err
	}
	if strings.TrimSpace(candidate.Content) == "" || len(candidate.SourceArtifactIDs) == 0 || candidate.Sensitivity == "" || candidate.CreatedAt.IsZero() {
		return errors.New("memory candidate is incomplete")
	}
	if !candidate.RequiresApproval {
		return errors.New("memory candidate must require approval")
	}
	return nil
}

func ValidateFailureReceipt(receipt FailureReceipt) error {
	if err := validateEnvelope(receipt.SchemaVersion, receipt.FailureID, receipt.RunID); err != nil {
		return err
	}
	if receipt.StepID == "" || receipt.ComponentID == "" || receipt.FailureCode == "" ||
		strings.TrimSpace(receipt.Message) == "" || receipt.CreatedAt.IsZero() {
		return errors.New("failure receipt is incomplete")
	}
	return nil
}

func RequiredFinalSections(primaryIntent string) []string {
	switch primaryIntent {
	case "company_understanding":
		return []string{"business_overview", "evidence", "limitations"}
	case "financial_quality":
		return []string{"financial_quality", "evidence", "limitations"}
	case "economic_transmission":
		return []string{"transmission_mechanisms", "scenarios", "evidence", "limitations"}
	case "valuation":
		return []string{"assumptions", "valuation_range", "sensitivity", "evidence", "limitations"}
	case "company_comparison":
		return []string{"comparison", "evidence", "limitations"}
	case "concept_education":
		return []string{"concept", "company_example", "evidence", "limitations"}
	case "market_behavior":
		return []string{"market_measurement", "evidence", "limitations"}
	case "thesis_review":
		return []string{"thesis", "counterevidence", "invalidation_conditions", "evidence", "limitations"}
	default:
		return nil
	}
}

func hasPlanCycle(steps map[string]PlanStep) bool {
	const (
		unseen = iota
		visiting
		done
	)
	state := make(map[string]int, len(steps))
	var visit func(string) bool
	visit = func(id string) bool {
		if state[id] == visiting {
			return true
		}
		if state[id] == done {
			return false
		}
		state[id] = visiting
		for _, dependency := range steps[id].DependsOn {
			if visit(dependency) {
				return true
			}
		}
		state[id] = done
		return false
	}
	for id := range steps {
		if state[id] == unseen && visit(id) {
			return true
		}
	}
	return false
}
