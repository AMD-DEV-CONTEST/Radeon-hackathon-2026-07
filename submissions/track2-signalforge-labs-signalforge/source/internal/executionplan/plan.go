package executionplan

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const (
	SchemaVersionV1           = "signalforge/execution-plan/v1"
	maximumChecklistItems     = 64
	maximumReferenceIDs       = 64
	maximumExecutionPlanSteps = 24
)

type Status string

const (
	StatusPending     Status = "pending"
	StatusReady       Status = "ready"
	StatusRunning     Status = "running"
	StatusPassed      Status = "passed"
	StatusFailed      Status = "failed"
	StatusDegraded    Status = "degraded"
	StatusRepairing   Status = "repairing"
	StatusSkipped     Status = "skipped"
	StatusCancelled   Status = "cancelled"
	StatusWithheld    Status = "withheld"
	StatusUnavailable Status = "unavailable"
)

type ChecklistItem struct {
	CheckID      string    `json:"check_id"`
	Label        string    `json:"label"`
	Status       Status    `json:"status"`
	Authority    string    `json:"authority"`
	Required     bool      `json:"required"`
	ReferenceIDs []string  `json:"reference_ids,omitempty"`
	CompletedAt  time.Time `json:"completed_at,omitempty"`
	SafeDetail   string    `json:"safe_detail,omitempty"`
}

type Phase struct {
	PhaseID       string   `json:"phase_id"`
	Order         int      `json:"order"`
	SafeLabel     string   `json:"safe_label"`
	SafeObjective string   `json:"safe_objective"`
	Mandatory     bool     `json:"mandatory"`
	Status        Status   `json:"status"`
	StepIDs       []string `json:"step_ids"`
	SafeSummary   string   `json:"safe_summary"`
}

type Step struct {
	StepID                   string          `json:"step_id"`
	ParentStepID             string          `json:"parent_step_id,omitempty"`
	ParentPhaseID            string          `json:"parent_phase_id"`
	Phase                    string          `json:"phase"`
	Kind                     string          `json:"kind"`
	SafeLabel                string          `json:"safe_label"`
	SafeObjective            string          `json:"safe_objective"`
	RoleID                   string          `json:"role_id,omitempty"`
	Wave                     int             `json:"wave,omitempty"`
	DependsOn                []string        `json:"depends_on,omitempty"`
	Mandatory                bool            `json:"mandatory"`
	Status                   Status          `json:"status"`
	Route                    string          `json:"route,omitempty"`
	RouteReasonCode          string          `json:"route_reason_code,omitempty"`
	AuthorizedCapabilityIDs  []string        `json:"authorized_capability_ids,omitempty"`
	EvidenceRequirementClass []string        `json:"evidence_requirement_classes,omitempty"`
	Checklist                []ChecklistItem `json:"checklist"`
	StartedAt                time.Time       `json:"started_at,omitempty"`
	CompletedAt              time.Time       `json:"completed_at,omitempty"`
	DurationMS               int64           `json:"duration_ms,omitempty"`
	Attempt                  int             `json:"attempt"`
	MaxAttempts              int             `json:"max_attempts"`
	ReferenceIDs             []string        `json:"reference_ids,omitempty"`
	FailureCode              string          `json:"failure_code,omitempty"`
	DegradationCode          string          `json:"degradation_code,omitempty"`
	SafeSummary              string          `json:"safe_summary"`
}

type Projection struct {
	SchemaVersion          string    `json:"schema_version"`
	RunID                  string    `json:"run_id"`
	RequestID              string    `json:"request_id"`
	PlanID                 string    `json:"plan_id,omitempty"`
	Status                 Status    `json:"status"`
	CreatedAt              time.Time `json:"created_at"`
	StartedAt              time.Time `json:"started_at,omitempty"`
	CompletedAt            time.Time `json:"completed_at,omitempty"`
	TotalSteps             int       `json:"total_steps"`
	TerminalSteps          int       `json:"terminal_steps"`
	ProgressRatio          float64   `json:"progress_ratio"`
	MaxParallelSpecialists int       `json:"max_parallel_specialists"`
	CurrentWave            int       `json:"current_wave,omitempty"`
	RouteSummary           []string  `json:"route_summary,omitempty"`
	Phases                 []Phase   `json:"phases"`
	Steps                  []Step    `json:"steps"`
	DegradationSummary     []string  `json:"degradation_summary,omitempty"`
	LastSequence           int       `json:"last_sequence"`
	ProjectionSHA          string    `json:"projection_sha256"`
}

type Event struct {
	Sequence   int
	StepID     string
	Type       string
	Status     string
	At         time.Time
	Attributes map[string]string
}

var safeID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$`)
var sha256Hex = regexp.MustCompile(`^[a-f0-9]{64}$`)
var unsafeText = regexp.MustCompile(`(?i)(bearer\s+|api[_-]?key|password|private[_ -]?token|chain[_ -]?of[_ -]?thought|raw[_ -]?prompt|response[_ -]?body)`)

var canonicalPhases = []Phase{
	{
		PhaseID: "interpretation", Order: 1, SafeLabel: "Interpretation",
		SafeObjective: "Resolve the governed intent, entities, scope, and ambiguity boundary.",
		Mandatory:     true,
	},
	{
		PhaseID: "planning", Order: 2, SafeLabel: "Planning",
		SafeObjective: "Freeze authorized roles, dependencies, budgets, and release conditions.",
		Mandatory:     true,
	},
	{
		PhaseID: "context", Order: 3, SafeLabel: "Context",
		SafeObjective: "Build evidence-grounded specialist context under source and authority controls.",
		Mandatory:     true,
	},
	{
		PhaseID: "tools", Order: 4, SafeLabel: "Tools",
		SafeObjective: "Execute deterministic capabilities and release only validated receipts.",
		Mandatory:     false,
	},
	{
		PhaseID: "review", Order: 5, SafeLabel: "Review",
		SafeObjective: "Independently challenge evidence, assumptions, calculations, and release boundaries.",
		Mandatory:     true,
	},
	{
		PhaseID: "synthesis", Order: 6, SafeLabel: "Synthesis",
		SafeObjective: "Compose one bounded answer from approved claims and deterministic references.",
		Mandatory:     true,
	},
	{
		PhaseID: "memory", Order: 7, SafeLabel: "Memory",
		SafeObjective: "Apply the user's explicit local retention preference without implicit storage.",
		Mandatory:     false,
	},
	{
		PhaseID: "release", Order: 8, SafeLabel: "Release",
		SafeObjective: "Release only after mandatory contracts pass or stop safely with a typed outcome.",
		Mandatory:     true,
	},
}

func Pending(runID, requestID string, at time.Time) (Projection, error) {
	projection := Projection{
		SchemaVersion: SchemaVersionV1,
		RunID:         runID,
		RequestID:     requestID,
		Status:        StatusPending,
		CreatedAt:     at.UTC(),
		Phases:        initialPhases(),
		Steps: []Step{
			{
				StepID: "interpret-request", ParentPhaseID: "interpretation",
				Phase: "interpretation", Kind: "control",
				SafeLabel: "Interpret request", SafeObjective: "Identify the governed research intent and scope.",
				RoleID: "request-interpreter/v1", Mandatory: true, Status: StatusRunning,
				Attempt: 1, MaxAttempts: 1, StartedAt: at.UTC(),
				Checklist: []ChecklistItem{{
					CheckID: "request-contract", Label: "Validate request contract", Status: StatusPending,
					Authority: "contract", Required: true,
				}},
				SafeSummary: "Validating the request boundary.",
			},
			{
				StepID: "build-plan", ParentPhaseID: "planning", Phase: "planning", Kind: "control",
				SafeLabel: "Build bounded plan", SafeObjective: "Select authorized roles, dependencies, and release gates.",
				RoleID: "research-orchestrator/v1", DependsOn: []string{"interpret-request"},
				Mandatory: true, Status: StatusPending, Attempt: 0, MaxAttempts: 1,
				Checklist: []ChecklistItem{{
					CheckID: "plan-contract", Label: "Validate bounded plan", Status: StatusPending,
					Authority: "contract", Required: true,
				}},
				SafeSummary: "Waiting for request interpretation.",
			},
		},
	}
	recalculate(&projection)
	if err := signAndValidate(&projection); err != nil {
		return Projection{}, err
	}
	return projection, nil
}

func FromPlan(plan contracts.ResearchPlan, at time.Time) (Projection, error) {
	if err := contracts.ValidateResearchPlan(plan); err != nil {
		return Projection{}, fmt.Errorf("validate research plan: %w", err)
	}
	projection, err := Pending(plan.RunID, plan.RequestID, at)
	if err != nil {
		return Projection{}, err
	}
	projection.PlanID = plan.PlanID
	projection.Status = StatusRunning
	projection.StartedAt = at.UTC()
	projection.MaxParallelSpecialists = plan.MaxParallelSpecialists
	markStepPassed(&projection.Steps[0], at, "The governed request contract passed.")
	markChecklist(&projection.Steps[0], "request-contract", StatusPassed, at, nil, "Request envelope accepted.")
	projection.Steps[1].Status = StatusPassed
	projection.Steps[1].StartedAt = at.UTC()
	markStepPassed(&projection.Steps[1], at, "The bounded execution plan passed validation.")
	markChecklist(&projection.Steps[1], "plan-contract", StatusPassed, at, []string{plan.PlanID}, "Plan dependencies and limits accepted.")

	for _, planStep := range plan.Steps {
		step := projectPlanStep(planStep)
		projection.Steps = append(projection.Steps, step)
	}
	recalculate(&projection)
	if err := signAndValidate(&projection); err != nil {
		return Projection{}, err
	}
	return projection, nil
}

func projectPlanStep(planStep contracts.PlanStep) Step {
	phase, label := phaseAndLabel(planStep)
	checklist := []ChecklistItem{{
		CheckID: "role-authority", Label: "Role authority verified", Status: StatusPassed,
		Authority: "contract", Required: true, SafeDetail: "The role is authorized for this plan step.",
	}, {
		CheckID: "model-route", Label: "Complete authorized model route", Status: StatusPending,
		Authority: "runtime", Required: true,
	}}
	switch planStep.Kind {
	case "context":
		checklist = append(checklist,
			ChecklistItem{CheckID: "evidence-authority", Label: "Authorize evidence context", Status: StatusPending, Authority: "retrieval", Required: true},
			ChecklistItem{CheckID: "context-contract", Label: "Validate specialist packet", Status: StatusPending, Authority: "specialist", Required: true},
		)
	case "review":
		checklist = append(checklist, ChecklistItem{
			CheckID: "review-contract", Label: "Complete independent review", Status: StatusPending,
			Authority: "reviewer", Required: true,
		})
	case "synthesis":
		checklist = append(checklist,
			ChecklistItem{CheckID: "review-gates", Label: "Verify mandatory review gates", Status: StatusPending, Authority: "release_gate", Required: true},
			ChecklistItem{CheckID: "answer-contract", Label: "Validate final answer contract", Status: StatusPending, Authority: "release_gate", Required: true},
		)
	}
	for index, capabilityID := range planStep.CapabilityIDs {
		checklist = append(checklist, ChecklistItem{
			CheckID: fmt.Sprintf("capability-%02d", index+1), Label: humanizeID(capabilityID) + " authorized",
			Status: StatusPassed, Authority: "capability", Required: false,
			ReferenceIDs: []string{capabilityID}, SafeDetail: "The capability is allowlisted for this role.",
		})
	}
	return Step{
		StepID: planStep.StepID, ParentPhaseID: phase, Phase: phase, Kind: planStep.Kind, SafeLabel: label,
		SafeObjective: safeText(planStep.Objective, 280), RoleID: planStep.RoleID,
		Wave: planStep.Wave, DependsOn: append([]string(nil), planStep.DependsOn...),
		Mandatory: planStep.Mandatory, Status: StatusPending,
		RouteReasonCode: routeReason(planStep), AuthorizedCapabilityIDs: append([]string(nil), planStep.CapabilityIDs...),
		EvidenceRequirementClass: append([]string(nil), planStep.EvidenceRequirements...),
		Checklist:                checklist, MaxAttempts: 2, SafeSummary: "Waiting for its dependencies.",
	}
}

func Apply(projection *Projection, event Event) error {
	if projection == nil {
		return errors.New("execution projection is required")
	}
	if event.Sequence <= projection.LastSequence {
		return nil
	}
	if event.Sequence != projection.LastSequence+1 {
		return fmt.Errorf("execution event sequence gap: got %d after %d", event.Sequence, projection.LastSequence)
	}
	if event.At.IsZero() {
		return errors.New("execution event timestamp is required")
	}
	if !validEventPair(event.Type, event.Status) {
		return fmt.Errorf("unsupported execution event %q:%q", event.Type, event.Status)
	}
	attributes := safeAttributes(event.Attributes)
	if event.Type == "tool" && (event.Status == "passed" || event.Status == "completed") {
		if err := validateCompletedToolAttributes(attributes); err != nil {
			return err
		}
	}
	if event.Type == "plan" && event.Status == "accepted" {
		projection.Status = StatusRunning
		projection.LastSequence = event.Sequence
		recalculate(projection)
		return signAndValidate(projection)
	}
	step := findStep(projection, event.StepID)
	if step == nil && event.Type == "tool" {
		if reference(attributes, "tool_execution_id") == "" {
			return errors.New("synthetic tool event requires a tool_execution_id")
		}
		step = ensureSyntheticToolStep(projection, event, attributes)
	}
	if step != nil && terminal(step.Status) && !compatibleTerminalEvent(step.Status, event) {
		projection.LastSequence = event.Sequence
		recalculate(projection)
		return signAndValidate(projection)
	}
	switch event.Type {
	case "interpretation":
		applyInterpretation(step, event, attributes)
	case "planning":
		applyPlanning(step, event, attributes)
	case "context":
		applyContext(step, event, attributes)
	case "model":
		applyModel(step, event, attributes)
	case "retrieval":
		applyRetrieval(step, event, attributes)
	case "tool":
		applyTool(step, event, attributes)
	case "review":
		applyReview(step, event, attributes)
	case "synthesis":
		applySynthesis(step, event, attributes)
	case "run":
		applyRun(projection, step, event, attributes)
	case "retention":
		applyRetention(projection, event, attributes)
	case "workspace":
		applyWorkspace(projection, event, attributes)
	default:
		// Unknown events remain visible in the raw safe event stream but cannot mutate the plan.
	}
	projection.LastSequence = event.Sequence
	recalculate(projection)
	return signAndValidate(projection)
}

func validEventPair(eventType, status string) bool {
	allowed := map[string]map[string]bool{
		"interpretation": {"completed": true, "clarification_required": true},
		"planning":       {"completed": true},
		"plan":           {"accepted": true},
		"wave":           {"started": true, "completed": true, "degraded": true, "failed": true},
		"context":        {"started": true, "completed": true, "failed": true},
		"model":          {"completed": true, "failed": true},
		"retrieval": {
			"started": true, "passed": true, "completed": true,
			"degraded": true, "failed": true, "unavailable": true,
		},
		"tool": {
			"started": true, "passed": true, "completed": true,
			"failed": true, "unavailable": true,
		},
		"review": {
			"started": true, "approve": true, "reject": true,
			"repair_requested": true, "narrowed": true,
			"approved_subset": true, "repair_unresolved": true,
		},
		"synthesis": {"started": true, "passed": true, "completed": true},
		"run":       {"completed": true, "failed": true},
		"retention": {
			"not_requested": true, "requested": true, "approved": true,
			"saved": true, "unavailable": true, "failed": true, "deleted": true,
		},
		"workspace": {"completed": true, "cancelled": true, "failed": true},
	}
	return allowed[eventType][status]
}

func MarkCompleted(projection *Projection, at time.Time) error {
	if projection == nil {
		return errors.New("execution projection is required")
	}
	for _, step := range projection.Steps {
		if step.Mandatory && step.Kind != "synthesis" &&
			step.Status != StatusPassed && step.Status != StatusDegraded {
			return fmt.Errorf("mandatory execution step %q cannot complete from status %q", step.StepID, step.Status)
		}
	}
	for index := range projection.Steps {
		step := &projection.Steps[index]
		if step.Kind == "synthesis" && !terminal(step.Status) {
			markStepPassed(step, at, "Final synthesis passed its release contract.")
			markChecklist(step, "model-route", StatusPassed, at, nil, "The authorized model route completed before answer release.")
			markChecklist(step, "review-gates", StatusPassed, at, nil, "Mandatory review gates passed.")
			markChecklist(step, "answer-contract", StatusPassed, at, nil, "Final answer contract passed.")
		}
	}
	if stepID, status := firstBlockingMandatoryStep(projection.Steps); stepID != "" {
		return fmt.Errorf("mandatory execution step %q cannot complete from status %q", stepID, status)
	}
	projection.Status = StatusPassed
	projection.CompletedAt = at.UTC()
	recalculate(projection)
	return signAndValidate(projection)
}

func MarkFailed(projection *Projection, code string, at time.Time, cancelled bool) error {
	if projection == nil {
		return errors.New("execution projection is required")
	}
	projection.Status = StatusFailed
	if cancelled {
		projection.Status = StatusCancelled
	}
	projection.CompletedAt = at.UTC()
	for index := range projection.Steps {
		step := &projection.Steps[index]
		if step.Status == StatusRunning || step.Status == StatusRepairing {
			step.Status = StatusFailed
			if cancelled {
				step.Status = StatusCancelled
			}
			step.FailureCode = safeIDValue(code)
			step.CompletedAt = at.UTC()
			step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
			step.SafeSummary = "The step stopped safely."
		} else if step.Status == StatusPending || step.Status == StatusReady {
			step.Status = StatusUnavailable
			step.CompletedAt = at.UTC()
			step.SafeSummary = "The step was not executed after the run stopped."
		}
	}
	recalculate(projection)
	return signAndValidate(projection)
}

func Validate(projection Projection) error {
	if err := validateStructure(projection); err != nil {
		return err
	}
	if projection.ProjectionSHA == "" {
		return errors.New("execution projection hash is required")
	}
	expected, err := digest(projection)
	if err != nil {
		return err
	}
	if projection.ProjectionSHA != expected {
		return errors.New("execution projection hash mismatch")
	}
	return nil
}

func validateStructure(projection Projection) error {
	if projection.SchemaVersion != SchemaVersionV1 || !safeID.MatchString(projection.RunID) ||
		!safeID.MatchString(projection.RequestID) || projection.CreatedAt.IsZero() {
		return errors.New("execution projection envelope is invalid")
	}
	if projection.PlanID != "" && !safeID.MatchString(projection.PlanID) {
		return errors.New("execution projection plan_id is invalid")
	}
	if !validStatus(projection.Status) || len(projection.Steps) < 2 || len(projection.Steps) > maximumExecutionPlanSteps {
		return errors.New("execution projection status or step count is invalid")
	}
	if len(projection.Phases) != len(canonicalPhases) {
		return errors.New("execution projection phase count is invalid")
	}
	if projection.TotalSteps != len(projection.Steps) || projection.TerminalSteps < 0 ||
		projection.TerminalSteps > projection.TotalSteps || projection.ProgressRatio < 0 || projection.ProgressRatio > 1 {
		return errors.New("execution projection progress is invalid")
	}
	phaseIDs := map[string]bool{}
	for index, phase := range projection.Phases {
		expected := canonicalPhases[index]
		if phase.PhaseID != expected.PhaseID || phase.Order != expected.Order ||
			phase.SafeLabel != expected.SafeLabel || phase.SafeObjective != expected.SafeObjective ||
			phase.Mandatory != expected.Mandatory || !validStatus(phase.Status) ||
			phase.SafeSummary == "" || unsafeText.MatchString(phase.SafeLabel+" "+phase.SafeObjective+" "+phase.SafeSummary) {
			return fmt.Errorf("execution phase %q is invalid", phase.PhaseID)
		}
		if phaseIDs[phase.PhaseID] {
			return fmt.Errorf("execution phase %q is duplicated", phase.PhaseID)
		}
		phaseIDs[phase.PhaseID] = true
	}
	ids := map[string]bool{}
	for _, step := range projection.Steps {
		if !safeID.MatchString(step.StepID) || ids[step.StepID] || !validStatus(step.Status) ||
			step.SafeLabel == "" || step.SafeObjective == "" || step.SafeSummary == "" ||
			step.ParentPhaseID == "" || step.ParentPhaseID != step.Phase || !phaseIDs[step.ParentPhaseID] {
			return fmt.Errorf("execution step %q is invalid", step.StepID)
		}
		if step.MaxAttempts < 1 || step.MaxAttempts > 2 || step.Attempt < 0 || step.Attempt > step.MaxAttempts ||
			step.DurationMS < 0 {
			return fmt.Errorf("execution step %q has invalid attempt or duration metadata", step.StepID)
		}
		if unsafeText.MatchString(step.SafeLabel + " " + step.SafeObjective + " " + step.SafeSummary) {
			return fmt.Errorf("execution step %q contains unsafe text", step.StepID)
		}
		if len(step.ReferenceIDs) > maximumReferenceIDs {
			return fmt.Errorf("execution step %q exceeds the reference limit", step.StepID)
		}
		if len(step.Checklist) > maximumChecklistItems {
			return fmt.Errorf("execution step %q exceeds the checklist limit", step.StepID)
		}
		for _, referenceID := range step.ReferenceIDs {
			if !safeID.MatchString(referenceID) {
				return fmt.Errorf("execution step %q has an invalid reference", step.StepID)
			}
		}
		ids[step.StepID] = true
		checks := map[string]bool{}
		for _, check := range step.Checklist {
			if !safeID.MatchString(check.CheckID) || checks[check.CheckID] || !validStatus(check.Status) ||
				check.Label == "" || check.Authority == "" || unsafeText.MatchString(check.Label+" "+check.SafeDetail) {
				return fmt.Errorf("execution checklist item %q is invalid", check.CheckID)
			}
			for _, referenceID := range check.ReferenceIDs {
				if len(check.ReferenceIDs) > maximumReferenceIDs {
					return fmt.Errorf("execution checklist item %q exceeds the reference limit", check.CheckID)
				}
				if !safeID.MatchString(referenceID) {
					return fmt.Errorf("execution checklist item %q has an invalid reference", check.CheckID)
				}
			}
			checks[check.CheckID] = true
		}
	}
	for _, phase := range projection.Phases {
		expectedStepIDs := []string{}
		for _, step := range projection.Steps {
			if step.ParentPhaseID == phase.PhaseID {
				expectedStepIDs = append(expectedStepIDs, step.StepID)
			}
		}
		if strings.Join(phase.StepIDs, "\x00") != strings.Join(expectedStepIDs, "\x00") {
			return fmt.Errorf("execution phase %q has invalid child steps", phase.PhaseID)
		}
	}
	for _, step := range projection.Steps {
		for _, dependency := range step.DependsOn {
			if !ids[dependency] {
				return fmt.Errorf("execution step %q has unknown dependency %q", step.StepID, dependency)
			}
		}
	}
	if projection.Status == StatusPassed {
		if stepID, status := firstBlockingMandatoryStep(projection.Steps); stepID != "" {
			return fmt.Errorf("passed execution projection has blocking mandatory step %q in status %q", stepID, status)
		}
	}
	return nil
}

func applyInterpretation(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	if event.Status == "clarification_required" {
		step.Status = StatusWithheld
		step.CompletedAt = event.At.UTC()
		step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
		step.FailureCode = "clarification_required"
		step.SafeSummary = "Clarification is required before a bounded research plan can begin."
		markChecklist(step, "request-contract", StatusWithheld, event.At, nil,
			"The request remains ambiguous across "+safeCount(attributes["ambiguity_count"])+" governed boundaries.")
		return
	}
	if event.Status != "completed" {
		return
	}
	intent := attributes["primary_intent"]
	entityIDs := splitSafeReferences(attributes["entity_ids"])
	for _, entityID := range entityIDs {
		appendReference(step, entityID)
	}
	intentDetail := "The governed request intent was classified."
	if intent != "" {
		intentDetail = "Primary intent: " + humanizeID(intent) + "."
	}
	scopeDetail := "The research scope was bounded."
	if count := attributes["entity_count"]; count != "" {
		scopeDetail = count + " resolved entities"
		if asOf := attributes["as_of"]; asOf != "" {
			scopeDetail += " with an as-of boundary of " + asOf
		}
		scopeDetail += "."
	}
	ambiguityDetail := "Declared ambiguities and requested outputs were preserved."
	if ambiguities := attributes["ambiguity_count"]; ambiguities != "" {
		ambiguityDetail = "Answer depth " + humanizeID(attributes["answer_depth"]) + "; " +
			ambiguities + " declared ambiguities and " +
			attributes["requested_output_count"] + " requested outputs were preserved."
	}
	upsertChecklist(step, ChecklistItem{
		CheckID: "intent-boundary", Label: "Classify governed intent", Status: StatusPassed,
		Authority: "contract", Required: true, CompletedAt: event.At.UTC(), SafeDetail: intentDetail,
	})
	upsertChecklist(step, ChecklistItem{
		CheckID: "scope-boundary", Label: "Resolve research scope", Status: StatusPassed,
		Authority: "contract", Required: true, ReferenceIDs: entityIDs,
		CompletedAt: event.At.UTC(), SafeDetail: scopeDetail,
	})
	upsertChecklist(step, ChecklistItem{
		CheckID: "ambiguity-boundary", Label: "Preserve ambiguity boundary", Status: StatusPassed,
		Authority: "contract", Required: false, CompletedAt: event.At.UTC(), SafeDetail: ambiguityDetail,
	})
	step.SafeSummary = intentDetail + " " + scopeDetail
}

func applyPlanning(step *Step, event Event, attributes map[string]string) {
	if step == nil || event.Status != "completed" {
		return
	}
	roleDetail := "The planner selected a bounded role topology."
	if roles := attributes["role_count"]; roles != "" {
		roleDetail = roles + " authorized roles across " + attributes["wave_count"] +
			" specialist waves, with at most " + attributes["max_parallel_specialists"] +
			" parallel specialists."
	}
	releaseDetail := "Completion and abstention conditions were fixed before execution."
	if completion := attributes["completion_condition_count"]; completion != "" {
		releaseDetail = completion + " completion conditions, " +
			attributes["abstention_condition_count"] + " abstention conditions, and at most " +
			attributes["max_repair_passes"] + " repair passes were fixed"
		if conditions := humanizeSafeList(attributes["completion_conditions"]); conditions != "" {
			releaseDetail += "; completion requires " + conditions
		}
		if abstentions := humanizeSafeList(attributes["abstention_conditions"]); abstentions != "" {
			releaseDetail += "; abstention applies to " + abstentions
		}
		if deadline := attributes["deadline_ms"]; deadline != "" {
			releaseDetail += "; total deadline " + deadline + " ms"
		}
		releaseDetail += "."
	}
	upsertChecklist(step, ChecklistItem{
		CheckID: "role-topology", Label: "Select bounded role topology", Status: StatusPassed,
		Authority: "planner", Required: true, CompletedAt: event.At.UTC(), SafeDetail: roleDetail,
	})
	upsertChecklist(step, ChecklistItem{
		CheckID: "release-boundary", Label: "Fix release and abstention gates", Status: StatusPassed,
		Authority: "planner", Required: true, CompletedAt: event.At.UTC(), SafeDetail: releaseDetail,
	})
	step.SafeSummary = roleDetail + " " + releaseDetail
}

func applyContext(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	switch event.Status {
	case "started":
		startStep(step, event.At, attributes)
		step.SafeSummary = "The specialist is compiling governed context."
	case "completed":
		summary := "The specialist returned a validated context packet."
		if findings := attributes["finding_count"]; findings != "" {
			summary = "The validated packet released " + findings + " findings, " +
				attributes["counterevidence_count"] + " counterevidence items, and " +
				attributes["missing_evidence_count"] + " missing-evidence declarations; evidence coverage is " +
				humanizeCoverage(attributes["evidence_coverage"]) + "."
		}
		summary += epistemicCountDetail(attributes)
		if asOf := attributes["as_of"]; asOf != "" {
			summary += " Evidence freshness is bounded by the governed as-of date " + asOf + "."
		}
		if authority := attributes["authority_state"]; authority != "" {
			summary += " Evidence authority state: " + humanizeID(authority) + "."
		}
		markStepPassed(step, event.At, summary)
		reference := reference(attributes, "packet_id")
		appendReference(step, reference)
		markChecklist(step, "model-route", StatusPassed, event.At, nil, "The authorized model route completed before packet release.")
		markChecklist(step, "evidence-authority", StatusPassed, event.At, []string{reference}, "Authorized evidence context compiled.")
		markChecklist(step, "context-contract", StatusPassed, event.At, []string{reference}, "Specialist packet passed validation.")
	case "failed":
		step.Status = StatusDegraded
		step.CompletedAt = event.At.UTC()
		step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
		step.DegradationCode = safeIDValue(attributes["code"])
		step.SafeSummary = "The specialist was unavailable; the run retained its fail-closed boundary."
		markChecklist(step, "model-route", StatusUnavailable, event.At, nil, "No releasable model result was produced.")
		markChecklist(step, "evidence-authority", StatusUnavailable, event.At, nil, "No releasable context was produced.")
		markChecklist(step, "context-contract", StatusUnavailable, event.At, nil, "No specialist packet was released.")
	}
}

func applyModel(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	route := safeIDValue(attributes["route"])
	callKind := safeIDValue(attributes["call_kind"])
	attempt, _ := strconv.Atoi(safeIDValue(attributes["attempt"]))
	if attempt > 0 {
		step.Attempt = attempt
		if step.Attempt > step.MaxAttempts {
			step.Attempt = step.MaxAttempts
		}
	}
	priorRoute := step.Route
	fallback := callKind == "fallback" ||
		callKind == "" && event.Status == "completed" && priorRoute != "" && priorRoute != route
	if route != "" {
		if fallback && priorRoute != "" && priorRoute != route {
			step.Route = priorRoute + "_to_" + route
		} else if priorRoute == "" || !strings.HasSuffix(priorRoute, route) {
			step.Route = route
		}
	}
	switch event.Status {
	case "completed":
		detail := "The authorized model route completed."
		switch {
		case fallback:
			detail = "The authorized fallback route completed after the primary route failed."
		case callKind == "retry":
			detail = "The authorized bounded retry completed."
		case callKind == "bounded_repair":
			detail = "The authorized bounded contract repair completed."
		}
		markChecklist(step, "model-route", StatusPassed, event.At, nil, detail)
	case "failed":
		detail := "The attempted primary route failed; bounded retry or fallback remains available."
		switch callKind {
		case "fallback":
			detail = "The attempted fallback route failed."
		case "retry":
			detail = "The bounded retry failed; the run remains fail-closed."
		case "bounded_repair":
			detail = "The bounded contract repair failed; the run remains fail-closed."
		}
		markChecklist(step, "model-route", StatusDegraded, event.At, nil, detail)
	}
}

func applyRetrieval(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	packetID := reference(attributes, "packet_id")
	bundleID := reference(attributes, "bundle_id")
	retrievalID := reference(attributes, "retrieval_id")
	checkReference := retrievalID
	if checkReference == "" {
		checkReference = bundleID
	}
	if checkReference == "" {
		checkReference = packetID
	}
	checkID := derivedCheckID("retrieval", checkReference)
	detail := "The specialist received an authorized evidence bundle; inspect the packet lineage for its bounded contents."
	if count := attributes["evidence_count"]; count != "" {
		if count == "0" && safeCount(attributes["missing_evidence_count"]) != "0" {
			detail = "No evidence item satisfied the governed request; this is explicit evidence absence, not a retrieval failure"
		} else {
			detail = "The validated packet contains " + count + " authorized evidence references"
		}
		if classes := attributes["source_classes"]; classes != "" {
			detail += " across " + humanizeID(strings.ReplaceAll(classes, "+", "_and_")) + " source classes"
		}
		if asOf := attributes["as_of"]; asOf != "" {
			detail += " as of " + asOf
		}
		if missing := attributes["missing_evidence_count"]; missing != "" {
			detail += "; " + missing + " missing-evidence declarations, " +
				attributes["conflict_count"] + " conflicts, and " +
				attributes["uncertainty_count"] + " uncertainties remain visible"
		}
		if coverage := attributes["evidence_coverage"]; coverage != "" {
			detail += "; finding coverage " + humanizeCoverage(coverage)
		}
		if method := attributes["retrieval_method"]; method != "" {
			detail += "; retrieval method " + humanizeID(method)
		}
		if attributes["candidate_count_state"] == "available" {
			detail += "; " + safeCount(attributes["selected_candidate_count"]) + " of " +
				safeCount(attributes["candidate_count"]) + " matched candidates selected and " +
				safeCount(attributes["rejected_candidate_count"]) + " rejected by the bounded rank"
		} else if attributes["candidate_count_state"] == "unavailable" {
			detail += "; candidate rejection telemetry was unavailable for this provider"
		}
		detail += "."
	}
	switch event.Status {
	case "started":
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: "Retrieve authorized evidence",
			Status: StatusRunning, Authority: "retrieval", Required: false,
			ReferenceIDs: compactRefs([]string{retrievalID}),
			SafeDetail:   "The authorized retrieval provider is resolving bounded evidence.",
		})
	case "passed", "completed":
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: "Authorized evidence retrieval completed",
			Status: StatusPassed, Authority: "retrieval", Required: false,
			ReferenceIDs: compactRefs([]string{retrievalID, bundleID, packetID}), CompletedAt: event.At.UTC(),
			SafeDetail: detail,
		})
		appendReference(step, bundleID)
		appendReference(step, packetID)
	case "degraded":
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: "Authorized evidence retrieval completed with limitations",
			Status: StatusDegraded, Authority: "retrieval", Required: false,
			ReferenceIDs: compactRefs([]string{retrievalID, bundleID}), CompletedAt: event.At.UTC(),
			SafeDetail: detail,
		})
		appendReference(step, bundleID)
	case "failed", "unavailable":
		status := StatusFailed
		if event.Status == "unavailable" {
			status = StatusUnavailable
		}
		failureDetail := retrievalFailureDetail(event.Status, attributes["code"])
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: "Authorized evidence retrieval unavailable",
			Status: status, Authority: "retrieval", Required: false,
			ReferenceIDs: compactRefs([]string{retrievalID}),
			CompletedAt:  event.At.UTC(),
			SafeDetail:   failureDetail,
		})
	}
}

func applyTool(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	receiptID := reference(attributes, "receipt_id")
	operationID := reference(attributes, "operation_id")
	engineID := reference(attributes, "engine_id")
	executionID := reference(attributes, "tool_execution_id")
	checkReference := executionID
	if checkReference == "" {
		checkReference = receiptID
	}
	checkID := derivedCheckID("tool", checkReference)
	refs := compactRefs([]string{executionID, receiptID})
	verification := attributes["receipt_verification"]
	label := "Deterministic calculation metadata accepted"
	if operationID != "" {
		label = humanizeID(operationID) + " metadata accepted"
	}
	detail := "A deterministic engine completed and its bounded calculation metadata passed contract checks."
	if verification == "canonical_verified" {
		label = "Deterministic engine receipt verified"
		if operationID != "" {
			label = humanizeID(operationID) + " receipt verified"
		}
		detail = "A deterministic engine completed and its receipt hash matched canonical content."
	}
	if formula := attributes["formula_version"]; formula != "" {
		engineLabel := "deterministic engine"
		if engineID != "" {
			engineLabel = humanizeID(engineID)
		}
		detail = "The " + engineLabel + " completed " + humanizeID(operationID) +
			" with formula " + humanizeID(formula) + ", " +
			attributes["input_count"] + " inputs, " + attributes["output_count"] + " outputs, " +
			attributes["invariant_count"] + " invariants, and " + attributes["warning_count"] +
			" warnings."
		if attributes["invariants_passed"] == "true" {
			detail += " All recorded invariants passed."
		}
		if inputs := humanizeSafeList(attributes["input_ref_ids"]); inputs != "" {
			detail += " Input references: " + inputs + "."
		}
		if outputs := humanizeSafeList(attributes["output_ref_ids"]); outputs != "" {
			detail += " Output references: " + outputs + "."
		}
		if receiptSHA := attributes["receipt_sha256"]; receiptSHA != "" {
			if len(receiptSHA) > 12 {
				receiptSHA = receiptSHA[:12]
			}
			if verification == "canonical_verified" {
				detail += " Verified receipt hash " + receiptSHA + "."
			} else {
				detail += " Declared receipt identity " + receiptSHA + "."
			}
		}
	}
	switch event.Status {
	case "started":
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: "Run " + humanizeID(operationID),
			Status: StatusRunning, Authority: "engine", Required: false,
			ReferenceIDs: compactRefs([]string{executionID}),
			SafeDetail:   "The deterministic engine accepted the governed operation request.",
		})
	case "passed", "completed":
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: label, Status: StatusPassed, Authority: "engine",
			Required: false, ReferenceIDs: refs, CompletedAt: event.At.UTC(),
			SafeDetail: detail,
		})
		appendReference(step, receiptID)
	case "failed", "unavailable":
		status := StatusFailed
		if event.Status == "unavailable" {
			status = StatusUnavailable
		}
		upsertChecklist(step, ChecklistItem{
			CheckID: checkID, Label: label, Status: status, Authority: "engine",
			Required: false, ReferenceIDs: refs, CompletedAt: event.At.UTC(),
			SafeDetail: "The deterministic engine released no valid receipt; failure code " + humanizeID(attributes["code"]) + ".",
		})
	}
	if step.Kind == "tool" {
		refreshSyntheticToolStep(step, event.At)
	}
}

func validateCompletedToolAttributes(attributes map[string]string) error {
	for _, key := range []string{"receipt_id", "operation_id", "engine_id"} {
		if reference(attributes, key) == "" {
			return fmt.Errorf("completed tool event requires %s", key)
		}
	}
	if !sha256Hex.MatchString(attributes["receipt_sha256"]) {
		return errors.New("completed tool event requires a valid receipt_sha256")
	}
	switch attributes["receipt_verification"] {
	case "canonical_verified", "metadata_only":
	default:
		return errors.New("completed tool event requires an explicit receipt_verification scope")
	}
	outputCount, outputErr := strconv.Atoi(attributes["output_count"])
	invariantCount, invariantErr := strconv.Atoi(attributes["invariant_count"])
	if outputErr != nil || outputCount < 1 {
		return errors.New("completed tool event requires at least one output")
	}
	if invariantErr != nil || invariantCount < 1 || attributes["invariants_passed"] != "true" {
		return errors.New("completed tool event requires passed invariants")
	}
	return nil
}

func applyReview(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	reportID := reference(attributes, "report_id")
	switch event.Status {
	case "started":
		startStep(step, event.At, attributes)
		step.SafeSummary = "An independent reviewer is checking the evidence boundary."
	case "repair_requested", "narrowed":
		step.Status = StatusRepairing
		step.Attempt++
		if step.Attempt > step.MaxAttempts {
			step.Attempt = step.MaxAttempts
		}
		appendReference(step, reportID)
		step.SafeSummary = "The reviewer requested one bounded correction pass. " + reviewCountDetail(attributes)
	case "approve":
		markStepPassed(step, event.At, "The independent review gate approved the evidence. "+reviewCountDetail(attributes))
		appendReference(step, reportID)
		markChecklist(step, "model-route", StatusPassed, event.At, nil, "The authorized model route completed before review release.")
		markChecklist(step, "review-contract", StatusPassed, event.At, []string{reportID}, "Review contract approved. "+reviewCountDetail(attributes))
	case "approved_subset":
		step.Status = StatusDegraded
		step.CompletedAt = event.At.UTC()
		step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
		step.DegradationCode = "approved_subset"
		appendReference(step, reportID)
		step.SafeSummary = "The reviewer released only an explicitly approved subset. " + reviewCountDetail(attributes)
		markChecklist(step, "model-route", StatusPassed, event.At, nil, "The authorized model route completed before bounded release.")
		markChecklist(step, "review-contract", StatusDegraded, event.At, []string{reportID}, "Only the approved subset may continue. "+reviewCountDetail(attributes))
	case "reject", "repair_unresolved":
		step.Status = StatusFailed
		step.CompletedAt = event.At.UTC()
		step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
		step.FailureCode = safeIDValue(event.Status)
		appendReference(step, reportID)
		step.SafeSummary = "The review gate withheld the evidence. " + reviewCountDetail(attributes)
		markChecklist(step, "model-route", StatusPassed, event.At, nil, "The authorized model route completed; the independent gate withheld release.")
		markChecklist(step, "review-contract", StatusFailed, event.At, []string{reportID}, "Review did not authorize release. "+reviewCountDetail(attributes))
	}
}

func applySynthesis(step *Step, event Event, attributes map[string]string) {
	if step == nil {
		return
	}
	switch event.Status {
	case "started":
		startStep(step, event.At, attributes)
		step.SafeSummary = "The final analyst is composing only reviewer-approved material."
	case "passed", "completed":
		releaseDetail := releaseCountDetail(attributes)
		markStepPassed(step, event.At, "Final synthesis passed its answer contract. "+releaseDetail)
		markChecklist(step, "model-route", StatusPassed, event.At, nil, "The authorized model route completed before answer release.")
		markChecklist(step, "review-gates", StatusPassed, event.At, nil, "Mandatory reviews completed: "+safeCount(attributes["mandatory_review_count"])+".")
		markChecklist(step, "answer-contract", StatusPassed, event.At, nil, "Final answer contract passed. "+releaseDetail)
	}
}

func applyRun(projection *Projection, step *Step, event Event, attributes map[string]string) {
	switch event.Status {
	case "completed":
		if step != nil {
			releaseDetail := releaseCountDetail(attributes)
			markStepPassed(step, event.At, "Final synthesis passed its answer contract. "+releaseDetail)
			answerID := reference(attributes, "answer_id")
			appendReference(step, answerID)
			markChecklist(step, "model-route", StatusPassed, event.At, nil, "The authorized model route completed before answer release.")
			markChecklist(step, "review-gates", StatusPassed, event.At, nil, "Mandatory reviews completed: "+safeCount(attributes["mandatory_review_count"])+".")
			markChecklist(step, "answer-contract", StatusPassed, event.At, []string{answerID}, "Final answer contract passed. "+releaseDetail)
		}
	case "failed":
		_ = MarkFailed(projection, attributes["code"], event.At, false)
	}
}

func applyRetention(projection *Projection, event Event, attributes map[string]string) {
	status := StatusRunning
	summary := "The explicit local retention request is awaiting completion."
	completedAt := time.Time{}
	switch event.Status {
	case "not_requested":
		status = StatusSkipped
		summary = "The session is ephemeral; no research case was retained."
		completedAt = event.At.UTC()
	case "requested":
		summary = "The user explicitly requested local research-case retention."
	case "approved":
		summary = "The local retention policy authorized the explicit request."
	case "saved":
		status = StatusPassed
		summary = "The user-approved research case was saved locally."
		completedAt = event.At.UTC()
	case "unavailable":
		status = StatusUnavailable
		summary = "Local retention was requested, but no case store was available."
		completedAt = event.At.UTC()
	case "failed":
		status = StatusDegraded
		summary = "Research completed, but the requested local save failed."
		completedAt = event.At.UTC()
	case "deleted":
		status = StatusPassed
		summary = "The saved local research case was deleted at the user's request."
		completedAt = event.At.UTC()
	}
	startedAt := event.At.UTC()
	references := []string(nil)
	if current := findStep(projection, "memory-retention"); current != nil {
		if !current.StartedAt.IsZero() {
			startedAt = current.StartedAt
		}
		references = append(references, current.ReferenceIDs...)
	}
	if caseID := reference(attributes, "case_id"); caseID != "" {
		references = append(references, caseID)
	}
	checkStatus := status
	checkCompletedAt := completedAt
	upsertSyntheticStep(projection, Step{
		StepID: "memory-retention", ParentPhaseID: "memory", Phase: "memory", Kind: "memory",
		SafeLabel:     "Apply memory preference",
		SafeObjective: "Honor the user's explicit local retention choice.", RoleID: "final-research-analyst/v1",
		Mandatory: false, Status: status, StartedAt: startedAt, CompletedAt: completedAt,
		Attempt: 1, MaxAttempts: 1, SafeSummary: summary, ReferenceIDs: compactRefs(references),
		Checklist: []ChecklistItem{{
			CheckID: "retention-policy", Label: "Apply opt-in retention policy", Status: checkStatus,
			Authority: "runtime", Required: false, CompletedAt: checkCompletedAt, SafeDetail: summary,
		}},
	})
}

func applyWorkspace(projection *Projection, event Event, attributes map[string]string) {
	switch event.Status {
	case "completed":
		if stepID, _ := firstBlockingMandatoryStep(projection.Steps); stepID == "" {
			projection.Status = StatusPassed
			projection.CompletedAt = event.At.UTC()
		} else {
			_ = MarkFailed(projection, "mandatory_step_incomplete", event.At, false)
		}
	case "cancelled":
		_ = MarkFailed(projection, "cancelled", event.At, true)
	case "failed":
		_ = MarkFailed(projection, attributes["code"], event.At, false)
	}
}

func startStep(step *Step, at time.Time, attributes map[string]string) {
	if step.Status == StatusPending || step.Status == StatusReady || step.Status == StatusRepairing {
		step.Status = StatusRunning
	}
	if step.StartedAt.IsZero() {
		step.StartedAt = at.UTC()
	}
	step.Attempt++
	if step.Attempt > step.MaxAttempts {
		step.Attempt = step.MaxAttempts
	}
	if value := safeIDValue(attributes["route_reason_code"]); value != "" {
		step.RouteReasonCode = value
	}
	if value := safeIDValue(attributes["route"]); value != "" {
		step.Route = value
	}
}

func markStepPassed(step *Step, at time.Time, summary string) {
	step.Status = StatusPassed
	if step.StartedAt.IsZero() {
		step.StartedAt = at.UTC()
	}
	step.CompletedAt = at.UTC()
	step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
	step.SafeSummary = summary
	if step.Attempt == 0 {
		step.Attempt = 1
	}
}

func markChecklist(step *Step, checkID string, status Status, at time.Time, refs []string, detail string) {
	for index := range step.Checklist {
		if step.Checklist[index].CheckID != checkID {
			continue
		}
		step.Checklist[index].Status = status
		step.Checklist[index].CompletedAt = at.UTC()
		step.Checklist[index].ReferenceIDs = compactRefs(refs)
		step.Checklist[index].SafeDetail = detail
		return
	}
}

func upsertChecklist(step *Step, item ChecklistItem) {
	for index := range step.Checklist {
		if step.Checklist[index].CheckID == item.CheckID {
			step.Checklist[index] = item
			return
		}
	}
	step.Checklist = append(step.Checklist, item)
}

func derivedCheckID(prefix, referenceID string) string {
	if referenceID == "" {
		return prefix + "-unavailable"
	}
	sum := sha256.Sum256([]byte(referenceID))
	return prefix + "-" + hex.EncodeToString(sum[:6])
}

func upsertSyntheticStep(projection *Projection, step Step) {
	for index := range projection.Steps {
		if projection.Steps[index].StepID == step.StepID {
			projection.Steps[index] = step
			return
		}
	}
	projection.Steps = append(projection.Steps, step)
}

func ensureSyntheticToolStep(projection *Projection, event Event, attributes map[string]string) *Step {
	stepID := safeIDValue(event.StepID)
	if stepID == "" {
		stepID = "deterministic-tools"
	}
	upsertSyntheticStep(projection, Step{
		StepID: stepID, ParentPhaseID: "tools", Phase: "tools", Kind: "tool",
		SafeLabel:     "Run deterministic calculations",
		SafeObjective: "Execute governed formulas and expose only validated receipt metadata.",
		RoleID:        "deterministic-engine/v1", Mandatory: false, Status: StatusPending,
		Route: "local_deterministic", RouteReasonCode: "deterministic_receipt",
		Attempt: 0, MaxAttempts: 1, Checklist: []ChecklistItem{},
		SafeSummary: "Waiting for deterministic receipt validation.",
	})
	return findStep(projection, stepID)
}

func refreshSyntheticToolStep(step *Step, at time.Time) {
	if step == nil {
		return
	}
	statuses := make([]Status, 0, len(step.Checklist))
	passed := 0
	for _, check := range step.Checklist {
		if check.Authority != "engine" || !strings.HasPrefix(check.CheckID, "tool-") {
			continue
		}
		statuses = append(statuses, check.Status)
		if check.Status == StatusPassed {
			passed++
		}
	}
	if len(statuses) == 0 {
		return
	}
	status := aggregateStatuses(statuses)
	if status == StatusFailed || status == StatusUnavailable {
		status = StatusDegraded
	}
	step.Status = status
	if step.StartedAt.IsZero() {
		step.StartedAt = at.UTC()
	}
	step.Attempt = 1
	step.SafeSummary = strconv.Itoa(passed) + " of " + strconv.Itoa(len(statuses)) +
		" deterministic calculation records passed contract checks."
	if terminal(status) {
		step.CompletedAt = at.UTC()
		step.DurationMS = durationMS(step.StartedAt, step.CompletedAt)
	}
}

func initialPhases() []Phase {
	phases := make([]Phase, len(canonicalPhases))
	for index, spec := range canonicalPhases {
		phases[index] = spec
		phases[index].Status = StatusPending
		phases[index].StepIDs = []string{}
		phases[index].SafeSummary = "Waiting for governed phase activity."
	}
	return phases
}

func recalculate(projection *Projection) {
	projection.TotalSteps = len(projection.Steps)
	projection.TerminalSteps = 0
	projection.CurrentWave = 0
	routes := map[string]bool{}
	degradations := map[string]bool{}
	for _, step := range projection.Steps {
		if terminal(step.Status) {
			projection.TerminalSteps++
		}
		if step.Status == StatusRunning && step.Wave > projection.CurrentWave {
			projection.CurrentWave = step.Wave
		}
		if step.Route != "" {
			routes[step.Route] = true
		}
		if step.DegradationCode != "" {
			degradations[step.DegradationCode] = true
		}
	}
	if projection.TotalSteps > 0 {
		projection.ProgressRatio = float64(projection.TerminalSteps) / float64(projection.TotalSteps)
	}
	projection.RouteSummary = sortedKeys(routes)
	projection.DegradationSummary = sortedKeys(degradations)
	recalculatePhases(projection)
}

func recalculatePhases(projection *Projection) {
	phases := initialPhases()
	for index := range phases {
		phase := &phases[index]
		statuses := []Status{}
		toolStatuses := []Status{}
		for _, step := range projection.Steps {
			if step.ParentPhaseID != phase.PhaseID {
				continue
			}
			phase.StepIDs = append(phase.StepIDs, step.StepID)
			statuses = append(statuses, step.Status)
		}
		if phase.PhaseID == "tools" {
			for _, step := range projection.Steps {
				for _, check := range step.Checklist {
					if check.Authority == "engine" && strings.HasPrefix(check.CheckID, "tool-") {
						toolStatuses = append(toolStatuses, check.Status)
					}
				}
			}
			if len(phase.StepIDs) == 0 {
				statuses = append(statuses, toolStatuses...)
			}
		}
		if phase.PhaseID == "release" {
			phase.Status, phase.SafeSummary = releasePhaseState(*projection)
			continue
		}
		if len(statuses) == 0 {
			if terminal(projection.Status) {
				phase.Status = StatusSkipped
				phase.SafeSummary = "No standalone activity was required for this phase."
			}
			continue
		}
		phase.Status = aggregateStatuses(statuses)
		phase.SafeSummary = phaseSummary(phase.Status, len(statuses))
		if phase.PhaseID == "tools" && len(toolStatuses) > 0 {
			phase.SafeSummary = toolPhaseSummary(phase.Status, toolStatuses)
		}
	}
	projection.Phases = phases
}

func toolPhaseSummary(status Status, toolStatuses []Status) string {
	passed := 0
	for _, toolStatus := range toolStatuses {
		if toolStatus == StatusPassed {
			passed++
		}
	}
	total := len(toolStatuses)
	switch status {
	case StatusPassed:
		return strconv.Itoa(total) + " deterministic calculation records passed contract checks."
	case StatusRunning, StatusReady, StatusPending:
		return strconv.Itoa(passed) + " of " + strconv.Itoa(total) +
			" deterministic calculation records have passed contract checks."
	default:
		return strconv.Itoa(passed) + " of " + strconv.Itoa(total) +
			" deterministic calculation records passed contract checks; the remainder is explicitly bounded."
	}
}

func aggregateStatuses(statuses []Status) Status {
	for _, candidate := range []Status{
		StatusFailed, StatusWithheld, StatusCancelled, StatusUnavailable,
		StatusRepairing, StatusRunning, StatusDegraded, StatusReady, StatusPending,
	} {
		for _, status := range statuses {
			if status == candidate {
				return candidate
			}
		}
	}
	allSkipped := true
	for _, status := range statuses {
		if status != StatusSkipped {
			allSkipped = false
			break
		}
	}
	if allSkipped {
		return StatusSkipped
	}
	return StatusPassed
}

func phaseSummary(status Status, activityCount int) string {
	count := strconv.Itoa(activityCount)
	switch status {
	case StatusPassed:
		return count + " governed phase activities passed."
	case StatusFailed:
		return "A governed phase activity stopped safely."
	case StatusDegraded:
		return count + " governed phase activities released a bounded subset."
	case StatusRepairing:
		return "A governed phase activity is undergoing bounded repair."
	case StatusRunning:
		return count + " governed phase activities are in progress."
	case StatusReady:
		return count + " governed phase activities are ready."
	case StatusWithheld:
		return "A governed phase activity withheld release."
	case StatusUnavailable:
		return "A governed phase activity was unavailable."
	case StatusCancelled:
		return "A governed phase activity was cancelled."
	case StatusSkipped:
		return "No standalone activity was required for this phase."
	default:
		return count + " governed phase activities are waiting."
	}
}

func releasePhaseState(projection Projection) (Status, string) {
	switch projection.Status {
	case StatusPassed:
		return StatusPassed, "All mandatory release contracts passed."
	case StatusFailed:
		return StatusFailed, "The run stopped safely before release."
	case StatusCancelled:
		return StatusCancelled, "The run was cancelled before release."
	case StatusWithheld:
		return StatusWithheld, "The final answer was withheld by a governed gate."
	case StatusUnavailable:
		return StatusUnavailable, "The release path was unavailable."
	case StatusDegraded:
		return StatusDegraded, "Only a bounded subset was released."
	}
	for _, step := range projection.Steps {
		if step.Kind == "synthesis" && terminal(step.Status) {
			return StatusRunning, "Final release checks are in progress."
		}
	}
	return StatusPending, "Waiting for mandatory review and synthesis contracts."
}

func signAndValidate(projection *Projection) error {
	projection.ProjectionSHA = ""
	if err := validateStructure(*projection); err != nil {
		return err
	}
	hash, err := digest(*projection)
	if err != nil {
		return err
	}
	projection.ProjectionSHA = hash
	return nil
}

func digest(projection Projection) (string, error) {
	projection.ProjectionSHA = ""
	payload, err := json.Marshal(projection)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:]), nil
}

func phaseAndLabel(step contracts.PlanStep) (string, string) {
	switch step.Kind {
	case "context":
		return "context", humanizeID(step.RoleID)
	case "review":
		return "review", humanizeID(step.RoleID)
	case "synthesis":
		return "synthesis", "Final synthesis"
	default:
		return "execution", humanizeID(step.StepID)
	}
}

func routeReason(step contracts.PlanStep) string {
	switch step.Kind {
	case "review":
		if strings.Contains(step.RoleID, "evidence-critic") {
			return "evidence_release_gate"
		}
		if strings.Contains(step.RoleID, "risk-contrarian") {
			return "risk_contrarian_gate"
		}
		return "independent_review_gate"
	case "synthesis":
		return "single_release_authority"
	default:
		return "intent_requires_specialist"
	}
}

func findStep(projection *Projection, stepID string) *Step {
	for index := range projection.Steps {
		if projection.Steps[index].StepID == stepID {
			return &projection.Steps[index]
		}
	}
	return nil
}

func appendReference(step *Step, referenceID string) {
	if referenceID == "" {
		return
	}
	for _, existing := range step.ReferenceIDs {
		if existing == referenceID {
			return
		}
	}
	step.ReferenceIDs = append(step.ReferenceIDs, referenceID)
	sort.Strings(step.ReferenceIDs)
}

func reference(attributes map[string]string, key string) string {
	return safeIDValue(attributes[key])
}

func safeAttributes(attributes map[string]string) map[string]string {
	allowed := map[string]bool{
		"answer_id": true, "code": true, "packet_id": true, "report_id": true,
		"role_id": true, "route": true, "route_reason_code": true,
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
	result := map[string]string{}
	for key, value := range attributes {
		if allowed[key] {
			result[key] = safeIDValue(value)
		}
	}
	return result
}

func splitSafeReferences(value string) []string {
	if value == "" {
		return nil
	}
	result := []string{}
	for _, item := range strings.Split(value, "+") {
		if referenceID := safeIDValue(item); referenceID != "" {
			result = append(result, referenceID)
		}
	}
	sort.Strings(result)
	return result
}

func humanizeSafeList(value string) string {
	values := splitSafeReferences(value)
	for index := range values {
		values[index] = humanizeID(values[index])
	}
	return strings.Join(values, ", ")
}

func humanizeCoverage(value string) string {
	parts := strings.Split(value, "_of_")
	if len(parts) != 2 {
		return "unavailable"
	}
	return parts[0] + " of " + parts[1] + " claims referenced"
}

func epistemicCountDetail(attributes map[string]string) string {
	keys := []string{"fact_count", "calculation_count", "inference_count", "hypothesis_count", "assumption_count"}
	for _, key := range keys {
		if attributes[key] == "" {
			return ""
		}
	}
	return " The packet explicitly distinguishes " +
		safeCount(attributes["fact_count"]) + " facts, " +
		safeCount(attributes["calculation_count"]) + " calculations, " +
		safeCount(attributes["inference_count"]) + " inferences, " +
		safeCount(attributes["hypothesis_count"]) + " hypotheses, and " +
		safeCount(attributes["assumption_count"]) +
		" assumptions; management assertions and scenarios are not inferred from source class."
}

func retrievalFailureDetail(status, code string) string {
	safeCode := safeIDValue(code)
	lowerCode := strings.ToLower(safeCode)
	switch {
	case strings.Contains(lowerCode, "rights") || strings.Contains(lowerCode, "license"):
		return "Retrieval was excluded by the source-rights policy; no restricted body or evidence bundle was released. Failure code " +
			humanizeID(safeCode) + "."
	case status == "unavailable":
		return "The authorized retrieval provider was unavailable and released no evidence bundle. Failure code " +
			humanizeID(safeCode) + "."
	default:
		return "The authorized retrieval operation failed and released no evidence bundle. Failure code " +
			humanizeID(safeCode) + "."
	}
}

func reviewCountDetail(attributes map[string]string) string {
	approved := safeCount(attributes["approved_claim_count"])
	rejected := safeCount(attributes["rejected_claim_count"])
	issues := safeCount(attributes["issue_count"])
	if approved == "unavailable" && rejected == "unavailable" && issues == "unavailable" {
		return "No claim bodies are exposed."
	}
	return approved + " approved claim IDs, " + rejected + " rejected claim IDs, and " + issues + " review issues recorded; claim bodies remain private."
}

func releaseCountDetail(attributes map[string]string) string {
	coverage := humanizeCoverage(attributes["supported_claim_coverage"])
	if coverage == "unavailable" {
		return "Release metadata is unavailable."
	}
	return "Supported-claim coverage: " + coverage + "; " +
		safeCount(attributes["evidence_ref_count"]) + " evidence references, " +
		safeCount(attributes["receipt_ref_count"]) + " deterministic receipts, " +
		safeCount(attributes["limitation_count"]) + " limitations, and " +
		safeCount(attributes["section_count"]) + " answer sections."
}

func safeCount(value string) string {
	if value = safeIDValue(value); value != "" {
		return value
	}
	return "unavailable"
}

func safeIDValue(value string) string {
	value = strings.TrimSpace(value)
	if safeID.MatchString(value) {
		return value
	}
	return ""
}

func safeText(value string, maximum int) string {
	value = strings.Join(strings.Fields(strings.TrimSpace(value)), " ")
	if value == "" || unsafeText.MatchString(value) {
		return "Execute the governed step without exposing private reasoning."
	}
	if len(value) > maximum {
		value = value[:maximum]
	}
	return value
}

func humanizeID(value string) string {
	value = strings.TrimSuffix(value, "/v1")
	value = strings.NewReplacer(".", " ", "_", " ", "-", " ", "/", " ").Replace(value)
	words := strings.Fields(value)
	for index := range words {
		words[index] = strings.ToUpper(words[index][:1]) + words[index][1:]
	}
	if len(words) == 0 {
		return "Governed step"
	}
	return strings.Join(words, " ")
}

func validStatus(status Status) bool {
	switch status {
	case StatusPending, StatusReady, StatusRunning, StatusPassed, StatusFailed, StatusDegraded,
		StatusRepairing, StatusSkipped, StatusCancelled, StatusWithheld, StatusUnavailable:
		return true
	default:
		return false
	}
}

func terminal(status Status) bool {
	switch status {
	case StatusPassed, StatusFailed, StatusDegraded, StatusSkipped, StatusCancelled, StatusWithheld, StatusUnavailable:
		return true
	default:
		return false
	}
}

func compatibleTerminalEvent(status Status, event Event) bool {
	switch event.Type {
	case "interpretation", "planning":
		return status == StatusPassed && event.Status == "completed"
	case "context":
		return status == StatusPassed && event.Status == "completed" ||
			status == StatusDegraded && event.Status == "failed"
	case "review":
		return status == StatusPassed && event.Status == "approve" ||
			status == StatusDegraded && event.Status == "approved_subset" ||
			status == StatusFailed && (event.Status == "reject" || event.Status == "repair_unresolved")
	case "synthesis":
		return status == StatusPassed && (event.Status == "passed" || event.Status == "completed")
	case "tool":
		return true
	case "run":
		return status == StatusPassed && event.Status == "completed" || event.Status == "failed"
	case "retention":
		return event.Status == "deleted" && status == StatusPassed
	default:
		return false
	}
}

func firstBlockingMandatoryStep(steps []Step) (string, Status) {
	for _, step := range steps {
		if !step.Mandatory {
			continue
		}
		if step.Status != StatusPassed && step.Status != StatusDegraded {
			return step.StepID, step.Status
		}
	}
	return "", ""
}

func durationMS(start, end time.Time) int64 {
	if start.IsZero() || end.IsZero() || end.Before(start) {
		return 0
	}
	return end.Sub(start).Milliseconds()
}

func compactRefs(values []string) []string {
	result := []string{}
	seen := map[string]bool{}
	for _, value := range values {
		if value = safeIDValue(value); value != "" && !seen[value] {
			result = append(result, value)
			seen[value] = true
		}
	}
	sort.Strings(result)
	return result
}

func sortedKeys(values map[string]bool) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}
