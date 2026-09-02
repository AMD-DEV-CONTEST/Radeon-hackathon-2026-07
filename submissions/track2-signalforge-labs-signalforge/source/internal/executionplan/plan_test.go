package executionplan

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestProjectionTracksBoundedPlanToCompletion(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	if projection.TotalSteps != 5 || projection.TerminalSteps != 2 || projection.ProgressRatio != 2.0/5.0 {
		t.Fatalf("initial progress = %+v", projection)
	}
	expectedPhases := []string{
		"interpretation", "planning", "context", "tools",
		"review", "synthesis", "memory", "release",
	}
	if len(projection.Phases) != len(expectedPhases) {
		t.Fatalf("phase count = %d", len(projection.Phases))
	}
	for index, phaseID := range expectedPhases {
		if projection.Phases[index].PhaseID != phaseID || projection.Phases[index].Order != index+1 {
			t.Fatalf("phase %d = %+v", index, projection.Phases[index])
		}
	}
	for _, step := range projection.Steps {
		if step.ParentPhaseID == "" || step.ParentPhaseID != step.Phase {
			t.Fatalf("step %s has no stable parent phase: %+v", step.StepID, step)
		}
	}
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second), Attributes: map[string]string{"role_id": "accounting-reporting/v1", "route_reason_code": "intent_requires_specialist"}},
		{Sequence: 3, StepID: "context-01", Type: "context", Status: "completed", At: now.Add(2 * time.Second), Attributes: map[string]string{"packet_id": "packet-1"}},
		{Sequence: 4, StepID: "review-01", Type: "review", Status: "started", At: now.Add(3 * time.Second)},
		{
			Sequence: 5, StepID: "review-01", Type: "review", Status: "approve", At: now.Add(4 * time.Second),
			Attributes: map[string]string{
				"report_id": "report-1", "approved_claim_count": "3",
				"rejected_claim_count": "0", "issue_count": "1", "repair_pass": "0",
				"claim_body": "never-retain",
			},
		},
		{Sequence: 6, StepID: "synthesis-01", Type: "synthesis", Status: "started", At: now.Add(5 * time.Second)},
		{
			Sequence: 7, StepID: "synthesis-01", Type: "synthesis", Status: "passed", At: now.Add(6 * time.Second),
			Attributes: map[string]string{
				"answer_id": "answer-1", "mandatory_review_count": "1", "claim_count": "3",
				"supported_claim_coverage": "3_of_3", "evidence_ref_count": "4",
				"receipt_ref_count": "2", "limitation_count": "1", "section_count": "2",
				"answer_body": "never-retain",
			},
		},
		{Sequence: 8, Type: "workspace", Status: "completed", At: now.Add(7 * time.Second)},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatalf("apply event %+v: %v", event, err)
		}
	}
	if projection.Status != StatusPassed || projection.ProgressRatio != 1 || projection.TerminalSteps != projection.TotalSteps {
		t.Fatalf("completed projection = %+v", projection)
	}
	for _, phaseID := range []string{"interpretation", "planning", "context", "review", "synthesis", "release"} {
		phase := findPhase(projection.Phases, phaseID)
		if phase == nil || phase.Status != StatusPassed {
			t.Fatalf("phase %s = %+v", phaseID, phase)
		}
	}
	for _, phaseID := range []string{"tools", "memory"} {
		phase := findPhase(projection.Phases, phaseID)
		if phase == nil || phase.Status != StatusSkipped {
			t.Fatalf("optional phase %s = %+v", phaseID, phase)
		}
	}
	if step := findStep(&projection, "context-01"); step == nil || step.Status != StatusPassed ||
		len(step.ReferenceIDs) != 1 || step.ReferenceIDs[0] != "packet-1" {
		t.Fatalf("context step = %+v", step)
	}
	review := findStep(&projection, "review-01")
	if review == nil || !strings.Contains(review.SafeSummary, "3 approved claim IDs") ||
		!strings.Contains(review.SafeSummary, "1 review issues") {
		t.Fatalf("review governance summary = %+v", review)
	}
	synthesis := findStep(&projection, "synthesis-01")
	if synthesis == nil || !strings.Contains(synthesis.SafeSummary, "3 of 3 claims referenced") ||
		!strings.Contains(synthesis.SafeSummary, "2 deterministic receipts") {
		t.Fatalf("release governance summary = %+v", synthesis)
	}
	payload, _ := json.Marshal(projection)
	if strings.Contains(string(payload), "never-retain") {
		t.Fatalf("projection retained private review or answer body: %s", payload)
	}
}

func TestProjectionKeepsRepairAndApprovedSubsetVisible(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "review-01", Type: "review", Status: "started", At: now.Add(time.Second)},
		{Sequence: 3, StepID: "review-01", Type: "review", Status: "repair_requested", At: now.Add(2 * time.Second), Attributes: map[string]string{"report_id": "report-p0"}},
		{Sequence: 4, StepID: "review-01", Type: "review", Status: "approved_subset", At: now.Add(3 * time.Second), Attributes: map[string]string{"report_id": "report-p1"}},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	step := findStep(&projection, "review-01")
	if step == nil || step.Status != StatusDegraded || step.DegradationCode != "approved_subset" ||
		len(step.ReferenceIDs) != 2 {
		t.Fatalf("review step = %+v", step)
	}
	if projection.TerminalSteps != 3 || projection.ProgressRatio != 3.0/5.0 {
		t.Fatalf("repair history inflated progress: %+v", projection)
	}
}

func TestProjectionShowsSafeInterpretationAndPlanningBoundaries(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{
			Sequence: 1, StepID: "interpret-request", Type: "interpretation",
			Status: "completed", At: now, Attributes: map[string]string{
				"primary_intent": "company_comparison", "entity_count": "2",
				"entity_ids": "company-msft+company-nvda", "as_of": "2026-07-25",
				"answer_depth": "deep", "ambiguity_count": "0", "requested_output_count": "8",
				"raw_prompt": "never-retain",
			},
		},
		{
			Sequence: 2, StepID: "build-plan", Type: "planning",
			Status: "completed", At: now, Attributes: map[string]string{
				"role_count": "5", "wave_count": "1", "max_parallel_specialists": "4",
				"max_repair_passes": "1", "deadline_ms": "90000", "completion_condition_count": "3",
				"abstention_condition_count": "3",
				"completion_conditions":      "review_approved+single_final_answer",
				"abstention_conditions":      "missing_primary_evidence+deadline_exceeded",
			},
		},
		{Sequence: 3, Type: "plan", Status: "accepted", At: now},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	interpretation := findStep(&projection, "interpret-request")
	planning := findStep(&projection, "build-plan")
	if interpretation == nil || len(interpretation.ReferenceIDs) != 2 ||
		!strings.Contains(interpretation.SafeSummary, "Company Comparison") ||
		!hasCheck(interpretation.Checklist, "scope-boundary") {
		t.Fatalf("interpretation boundary = %+v", interpretation)
	}
	if planning == nil || !strings.Contains(planning.SafeSummary, "5 authorized roles") ||
		!strings.Contains(planning.SafeSummary, "Review Approved") ||
		!strings.Contains(planning.SafeSummary, "Missing Primary Evidence") ||
		!strings.Contains(planning.SafeSummary, "90000 ms") ||
		!hasCheck(planning.Checklist, "release-boundary") {
		t.Fatalf("planning boundary = %+v", planning)
	}
	payload, _ := json.Marshal(projection)
	if strings.Contains(string(payload), "never-retain") {
		t.Fatalf("interpretation projection retained private input: %s", payload)
	}
}

func TestProjectionWithholdsAmbiguousRequestBeforePlanning(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := Pending("run-clarify", "request-clarify", now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{
			Sequence: 1, StepID: "interpret-request", Type: "interpretation",
			Status: "clarification_required", At: now.Add(time.Second),
			Attributes: map[string]string{
				"ambiguity_count": "1", "primary_intent": "market_behavior",
				"raw_prompt": "never-retain",
			},
		},
		{
			Sequence: 2, StepID: "interpret-request", Type: "run",
			Status: "failed", At: now.Add(2 * time.Second),
			Attributes: map[string]string{"code": "clarification_required"},
		},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	interpretation := findStep(&projection, "interpret-request")
	planning := findStep(&projection, "build-plan")
	if projection.Status != StatusFailed || interpretation == nil ||
		interpretation.Status != StatusWithheld || planning == nil ||
		planning.Status != StatusUnavailable {
		t.Fatalf("clarification projection = %+v", projection)
	}
	payload, _ := json.Marshal(projection)
	if strings.Contains(string(payload), "never-retain") {
		t.Fatalf("clarification projection retained private input: %s", payload)
	}
}

func TestProjectionReplayIsByteDeterministic(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second)},
		{
			Sequence: 3, StepID: "context-01", Type: "retrieval", Status: "completed",
			At: now.Add(2 * time.Second), Attributes: map[string]string{
				"packet_id": "packet-1", "evidence_count": "2",
				"source_classes": "sec_filing", "as_of": "2026-07-25",
			},
		},
		{Sequence: 4, StepID: "context-01", Type: "context", Status: "completed", At: now.Add(3 * time.Second), Attributes: map[string]string{"packet_id": "packet-1"}},
	}
	replay := func() []byte {
		t.Helper()
		projection, err := FromPlan(testPlan(now), now)
		if err != nil {
			t.Fatal(err)
		}
		for _, event := range events {
			if err := Apply(&projection, event); err != nil {
				t.Fatal(err)
			}
		}
		payload, err := json.Marshal(projection)
		if err != nil {
			t.Fatal(err)
		}
		return payload
	}
	first := replay()
	second := replay()
	if string(first) != string(second) {
		t.Fatalf("identical event replay produced different canonical bytes:\n%s\n%s", first, second)
	}
}

func hasCheck(items []ChecklistItem, checkID string) bool {
	for _, item := range items {
		if item.CheckID == checkID {
			return true
		}
	}
	return false
}

func findPhase(phases []Phase, phaseID string) *Phase {
	for index := range phases {
		if phases[index].PhaseID == phaseID {
			return &phases[index]
		}
	}
	return nil
}

func TestProjectionAddsOnlyValidatedRetrievalAndToolReceipts(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second)},
		{
			Sequence: 3, StepID: "context-01", Type: "retrieval", Status: "completed", At: now.Add(2 * time.Second),
			Attributes: map[string]string{
				"packet_id": "packet-1", "evidence_count": "4",
				"source_classes": "sec_filing+investor_relations", "as_of": "2026-07-25",
				"finding_count": "3", "counterevidence_count": "1",
				"missing_evidence_count": "2", "conflict_count": "1",
				"uncertainty_count": "1", "evidence_coverage": "3_of_4",
				"raw_prompt": "never-retain",
			},
		},
		{
			Sequence: 4, StepID: "context-01", Type: "tool", Status: "completed", At: now.Add(3 * time.Second),
			Attributes: map[string]string{
				"receipt_id": "receipt-1", "operation_id": "financial.free_cash_flow",
				"engine_id": "financial-engine/v1", "formula_version": "fcf/v2",
				"input_count": "3", "input_ref_ids": "operating-cash-flow+capex",
				"output_count": "1", "output_ref_ids": "free-cash-flow", "invariant_count": "2",
				"invariants_passed": "true", "warning_count": "0",
				"receipt_sha256":       "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				"receipt_verification": "metadata_only",
				"inputs":               "never-retain",
			},
		},
		{
			Sequence: 5, StepID: "context-01", Type: "context", Status: "completed", At: now.Add(4 * time.Second),
			Attributes: map[string]string{
				"packet_id": "packet-1", "finding_count": "3", "counterevidence_count": "1",
				"missing_evidence_count": "2", "evidence_coverage": "3_of_4",
				"fact_count": "2", "calculation_count": "1", "inference_count": "1",
				"hypothesis_count": "0", "assumption_count": "2",
				"as_of": "2026-07-25", "freshness_state": "bounded_by_as_of",
				"authority_state": "accepted",
			},
		},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatalf("apply event %+v: %v", event, err)
		}
	}
	step := findStep(&projection, "context-01")
	if step == nil || step.Status != StatusPassed {
		t.Fatalf("context step = %+v", step)
	}
	if !strings.Contains(step.SafeSummary, "2 facts, 1 calculations, 1 inferences, 0 hypotheses, and 2 assumptions") ||
		!strings.Contains(step.SafeSummary, "management assertions and scenarios are not inferred") ||
		!strings.Contains(step.SafeSummary, "as-of date 2026-07-25") ||
		!strings.Contains(step.SafeSummary, "Evidence authority state: Accepted") {
		t.Fatalf("context epistemic boundary = %q", step.SafeSummary)
	}
	var retrieval, tool *ChecklistItem
	for index := range step.Checklist {
		item := &step.Checklist[index]
		if strings.HasPrefix(item.CheckID, "retrieval-") {
			retrieval = item
		}
		if strings.HasPrefix(item.CheckID, "tool-") {
			tool = item
		}
	}
	if retrieval == nil || retrieval.Status != StatusPassed || len(retrieval.ReferenceIDs) != 1 ||
		retrieval.ReferenceIDs[0] != "packet-1" ||
		!strings.Contains(retrieval.SafeDetail, "2 missing-evidence") ||
		!strings.Contains(retrieval.SafeDetail, "3 of 4 claims referenced") {
		t.Fatalf("retrieval checklist = %+v", retrieval)
	}
	if tool == nil || tool.Status != StatusPassed || len(tool.ReferenceIDs) != 1 ||
		tool.ReferenceIDs[0] != "receipt-1" ||
		!strings.Contains(tool.SafeDetail, "3 inputs") || !strings.Contains(tool.SafeDetail, "2 invariants") ||
		!strings.Contains(tool.SafeDetail, "Operating Cash Flow") ||
		!strings.Contains(tool.SafeDetail, "Free Cash Flow") {
		t.Fatalf("tool checklist = %+v", tool)
	}
	toolsPhase := findPhase(projection.Phases, "tools")
	if toolsPhase == nil || toolsPhase.Status != StatusPassed || len(toolsPhase.StepIDs) != 0 {
		t.Fatalf("embedded tools phase = %+v", toolsPhase)
	}
	payload, _ := json.Marshal(projection)
	if strings.Contains(string(payload), "never-retain") {
		t.Fatalf("unsafe event attributes entered projection: %s", payload)
	}
}

func TestProjectionDistinguishesEvidenceAbsenceFailureAndRightsExclusion(t *testing.T) {
	now := time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC)
	tests := []struct {
		name       string
		status     string
		attributes map[string]string
		want       string
	}{
		{
			name: "evidence absence", status: "completed",
			attributes: map[string]string{
				"retrieval_id": "retrieval-absence", "evidence_count": "0",
				"missing_evidence_count": "2", "candidate_count_state": "available",
				"candidate_count": "4", "selected_candidate_count": "0",
				"rejected_candidate_count": "4",
			},
			want: "explicit evidence absence, not a retrieval failure",
		},
		{
			name: "provider failure", status: "failed",
			attributes: map[string]string{
				"retrieval_id": "retrieval-failure", "code": "provider_timeout",
			},
			want: "retrieval operation failed",
		},
		{
			name: "rights exclusion", status: "failed",
			attributes: map[string]string{
				"retrieval_id": "retrieval-rights", "code": "source_rights_excluded",
			},
			want: "excluded by the source-rights policy",
		},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			projection, err := FromPlan(testPlan(now), now)
			if err != nil {
				t.Fatal(err)
			}
			if err := Apply(&projection, Event{
				Sequence: 1, StepID: "context-01", Type: "retrieval",
				Status: testCase.status, At: now.Add(time.Second), Attributes: testCase.attributes,
			}); err != nil {
				t.Fatal(err)
			}
			step := findStep(&projection, "context-01")
			var retrieval *ChecklistItem
			for index := range step.Checklist {
				if strings.HasPrefix(step.Checklist[index].CheckID, "retrieval-") {
					retrieval = &step.Checklist[index]
				}
			}
			if retrieval == nil || !strings.Contains(strings.ToLower(retrieval.SafeDetail), strings.ToLower(testCase.want)) {
				t.Fatalf("retrieval outcome = %+v, want %q", retrieval, testCase.want)
			}
		})
	}
}

func TestProjectionPreservesBoundedFallbackRoute(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second)},
		{
			Sequence: 3, StepID: "context-01", Type: "model", Status: "failed",
			At: now.Add(2 * time.Second), Attributes: map[string]string{"route": "radeon_api"},
		},
		{
			Sequence: 4, StepID: "context-01", Type: "model", Status: "completed",
			At: now.Add(3 * time.Second), Attributes: map[string]string{"route": "local_rocm"},
		},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	step := findStep(&projection, "context-01")
	if step == nil || step.Route != "radeon_api_to_local_rocm" {
		t.Fatalf("fallback route was not preserved: %+v", step)
	}
	var routeCheck *ChecklistItem
	for index := range step.Checklist {
		if step.Checklist[index].CheckID == "model-route" {
			routeCheck = &step.Checklist[index]
		}
	}
	if routeCheck == nil || routeCheck.Status != StatusPassed ||
		!strings.Contains(routeCheck.SafeDetail, "fallback route") {
		t.Fatalf("fallback route checklist was not closed safely: %+v", routeCheck)
	}
}

func TestProjectionCreatesBoundedSyntheticToolStepFromReceiptEvents(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{
			Sequence: 1, StepID: "fixture-calculation", Type: "tool", Status: "completed",
			At: now.Add(time.Second), Attributes: map[string]string{
				"tool_execution_id":    "engine-fixture-receipt-1",
				"receipt_id":           "receipt-1",
				"operation_id":         "financial.free_cash_flow",
				"engine_id":            "financial",
				"formula_version":      "fcf/v2",
				"output_count":         "1",
				"output_ref_ids":       "free-cash-flow",
				"invariant_count":      "1",
				"invariants_passed":    "true",
				"warning_count":        "0",
				"receipt_sha256":       strings.Repeat("a", 64),
				"receipt_verification": "metadata_only",
			},
		},
		{
			Sequence: 2, StepID: "fixture-calculation", Type: "tool", Status: "completed",
			At: now.Add(2 * time.Second), Attributes: map[string]string{
				"tool_execution_id":    "engine-fixture-receipt-2",
				"receipt_id":           "receipt-2",
				"operation_id":         "valuation.peer_multiple",
				"engine_id":            "valuation",
				"formula_version":      "peer/v1",
				"output_count":         "1",
				"output_ref_ids":       "peer-multiple",
				"invariant_count":      "1",
				"invariants_passed":    "true",
				"warning_count":        "0",
				"receipt_sha256":       strings.Repeat("b", 64),
				"receipt_verification": "metadata_only",
			},
		},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatalf("apply event %+v: %v", event, err)
		}
	}
	step := findStep(&projection, "fixture-calculation")
	if step == nil || step.ParentPhaseID != "tools" || step.Status != StatusPassed ||
		step.Route != "local_deterministic" || len(step.Checklist) != 2 ||
		!strings.Contains(step.SafeSummary, "2 of 2") {
		t.Fatalf("synthetic tool step = %+v", step)
	}
	phase := findPhase(projection.Phases, "tools")
	if phase == nil || phase.Status != StatusPassed ||
		len(phase.StepIDs) != 1 || phase.StepIDs[0] != step.StepID ||
		phase.SafeSummary != "2 deterministic calculation records passed contract checks." {
		t.Fatalf("tools phase = %+v", phase)
	}
	if err := Validate(projection); err != nil {
		t.Fatalf("validate synthetic tool projection: %v", err)
	}
}

func TestProjectionPreservesExplicitRetentionLifecycleThroughDeletion(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := Pending("run-retention", "request-retention", now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{Sequence: 1, Type: "retention", Status: "requested", At: now},
		{Sequence: 2, Type: "retention", Status: "approved", At: now.Add(time.Second)},
		{
			Sequence: 3, Type: "retention", Status: "saved", At: now.Add(2 * time.Second),
			Attributes: map[string]string{"case_id": "case-retention"},
		},
		{
			Sequence: 4, Type: "retention", Status: "deleted", At: now.Add(3 * time.Second),
			Attributes: map[string]string{"case_id": "case-retention"},
		},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	step := findStep(&projection, "memory-retention")
	if step == nil || step.Status != StatusPassed ||
		!strings.Contains(step.SafeSummary, "deleted") ||
		len(step.ReferenceIDs) != 1 || step.ReferenceIDs[0] != "case-retention" {
		t.Fatalf("retention projection = %+v", step)
	}
}

func TestProjectionRejectsSequenceGapsAndIgnoresDuplicates(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	first := Event{Sequence: 1, Type: "plan", Status: "accepted", At: now}
	if err := Apply(&projection, first); err != nil {
		t.Fatal(err)
	}
	hash := projection.ProjectionSHA
	if err := Apply(&projection, first); err != nil || projection.ProjectionSHA != hash {
		t.Fatal("duplicate event changed the projection")
	}
	if err := Apply(&projection, Event{Sequence: 3, Type: "workspace", Status: "completed", At: now}); err == nil {
		t.Fatal("sequence gap should fail")
	}
}

func TestExecutionEventVocabularyIsClosed(t *testing.T) {
	allowed := map[string][]string{
		"interpretation": {"completed", "clarification_required"},
		"planning":       {"completed"},
		"plan":           {"accepted"},
		"context":        {"started", "completed", "failed"},
		"model":          {"completed", "failed"},
		"retrieval":      {"started", "passed", "completed", "degraded", "failed", "unavailable"},
		"tool":           {"started", "passed", "completed", "failed", "unavailable"},
		"review": {
			"started", "approve", "reject", "repair_requested", "narrowed",
			"approved_subset", "repair_unresolved",
		},
		"synthesis": {"started", "passed", "completed"},
		"run":       {"completed", "failed"},
		"retention": {
			"not_requested", "requested", "approved", "saved",
			"unavailable", "failed", "deleted",
		},
		"workspace": {"completed", "cancelled", "failed"},
	}
	for eventType, statuses := range allowed {
		for _, status := range statuses {
			if !validEventPair(eventType, status) {
				t.Fatalf("documented event %s:%s was rejected", eventType, status)
			}
		}
	}
	for _, pair := range [][2]string{
		{"unknown", "completed"},
		{"context", "approve"},
		{"review", "completed"},
		{"tool", "degraded"},
		{"workspace", "passed"},
		{"", ""},
	} {
		if validEventPair(pair[0], pair[1]) {
			t.Fatalf("forbidden event %s:%s was accepted", pair[0], pair[1])
		}
	}

	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	hash := projection.ProjectionSHA
	err = Apply(&projection, Event{
		Sequence: 1, StepID: "context-01", Type: "tool", Status: "degraded", At: now,
	})
	if err == nil || projection.ProjectionSHA != hash || projection.LastSequence != 0 {
		t.Fatalf("forbidden transition mutated projection: err=%v projection=%+v", err, projection)
	}
}

func TestProjectionTracksRetrievalAndToolLifecycleByStableExecutionIdentity(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second)},
		{
			Sequence: 3, StepID: "context-01", Type: "retrieval", Status: "started",
			At: now.Add(2 * time.Second), Attributes: map[string]string{
				"retrieval_id": "retrieval-context-01",
			},
		},
		{
			Sequence: 4, StepID: "context-01", Type: "retrieval", Status: "degraded",
			At: now.Add(3 * time.Second), Attributes: map[string]string{
				"retrieval_id": "retrieval-context-01", "bundle_id": "bundle-context-01",
				"retrieval_method": "bm25/v1", "evidence_count": "4",
				"source_classes": "sec_filing+investor_relations", "as_of": "2026-07-25",
				"missing_evidence_count": "1", "candidate_count": "8",
				"selected_candidate_count": "4", "rejected_candidate_count": "4",
				"candidate_count_state": "available",
			},
		},
		{
			Sequence: 5, StepID: "context-01", Type: "tool", Status: "started",
			At: now.Add(4 * time.Second), Attributes: map[string]string{
				"tool_execution_id": "calc-context-01", "engine_id": "financial-engine/v1",
				"operation_id": "financial.margin", "formula_version": "ratio/v1",
			},
		},
		{
			Sequence: 6, StepID: "context-01", Type: "tool", Status: "failed",
			At: now.Add(5 * time.Second), Attributes: map[string]string{
				"tool_execution_id": "calc-context-01", "engine_id": "financial-engine/v1",
				"operation_id": "financial.margin", "formula_version": "ratio/v1",
				"code": "engine_execution_failed",
			},
		},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	step := findStep(&projection, "context-01")
	if step == nil {
		t.Fatal("context step missing")
	}
	retrievalChecks, toolChecks := 0, 0
	for _, check := range step.Checklist {
		switch check.Authority {
		case "retrieval":
			if strings.HasPrefix(check.CheckID, "retrieval-") {
				retrievalChecks++
				if check.Status != StatusDegraded || !strings.Contains(check.SafeDetail, "4 of 8") ||
					!strings.Contains(check.SafeDetail, "4 rejected") {
					t.Fatalf("retrieval lifecycle was not reconciled: %+v", check)
				}
			}
		case "engine":
			if strings.HasPrefix(check.CheckID, "tool-") {
				toolChecks++
				if check.Status != StatusFailed || !strings.Contains(strings.ToLower(check.SafeDetail), "engine execution failed") {
					t.Fatalf("tool lifecycle was not reconciled: %+v", check)
				}
			}
		}
	}
	if retrievalChecks != 1 || toolChecks != 1 {
		t.Fatalf("lifecycle events created duplicate checks: retrieval=%d tool=%d", retrievalChecks, toolChecks)
	}
}

func TestProjectionDoesNotRetainUnsafeEventAttributes(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	if err := Apply(&projection, Event{Sequence: 1, Type: "plan", Status: "accepted", At: now, Attributes: map[string]string{
		"prompt": "private", "api_key": "secret", "user_text": "do not retain",
	}}); err != nil {
		t.Fatal(err)
	}
	payload, _ := json.Marshal(projection)
	for _, forbidden := range []string{"private", "secret", "do not retain", "api_key", "user_text"} {
		if strings.Contains(string(payload), forbidden) {
			t.Fatalf("projection leaked %q: %s", forbidden, payload)
		}
	}
}

func TestFailureMarksPendingWorkUnavailable(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	if err := MarkFailed(&projection, "model_unavailable", now.Add(time.Second), false); err != nil {
		t.Fatal(err)
	}
	if projection.Status != StatusFailed {
		t.Fatalf("status = %s", projection.Status)
	}
	for _, step := range projection.Steps[2:] {
		if step.Status != StatusUnavailable {
			t.Fatalf("step %s = %s", step.StepID, step.Status)
		}
	}
}

func TestTerminalStepIgnoresLateReopeningEvent(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second)},
		{Sequence: 3, StepID: "context-01", Type: "context", Status: "completed", At: now.Add(2 * time.Second), Attributes: map[string]string{"packet_id": "packet-1"}},
		{Sequence: 4, StepID: "context-01", Type: "context", Status: "started", At: now.Add(3 * time.Second)},
		{Sequence: 5, StepID: "context-01", Type: "context", Status: "failed", At: now.Add(4 * time.Second), Attributes: map[string]string{"code": "late_failure"}},
	}
	for _, event := range events {
		if err := Apply(&projection, event); err != nil {
			t.Fatal(err)
		}
	}
	step := findStep(&projection, "context-01")
	if step == nil || step.Status != StatusPassed || step.FailureCode != "" ||
		step.DegradationCode != "" || projection.LastSequence != 5 {
		t.Fatalf("late events mutated terminal step: %+v", step)
	}
}

func TestCompletionRejectsBlockingMandatoryStep(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	hash := projection.ProjectionSHA
	if err := MarkCompleted(&projection, now.Add(time.Second)); err == nil {
		t.Fatal("completion should reject pending mandatory work")
	}
	if projection.Status == StatusPassed || projection.ProjectionSHA != hash {
		t.Fatalf("rejected completion mutated projection: %+v", projection)
	}
}

func TestWorkspaceCompletionFailsClosedWhenMandatoryWorkIsPending(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	projection, err := FromPlan(testPlan(now), now)
	if err != nil {
		t.Fatal(err)
	}
	if err := Apply(&projection, Event{
		Sequence: 1, Type: "workspace", Status: "completed", At: now.Add(time.Second),
	}); err != nil {
		t.Fatal(err)
	}
	if projection.Status != StatusFailed || projection.ProgressRatio != 1 {
		t.Fatalf("workspace completion did not close safely: %+v", projection)
	}
}

func BenchmarkProjectionReplay(b *testing.B) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	events := []Event{
		{Sequence: 1, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, StepID: "context-01", Type: "context", Status: "started", At: now.Add(time.Second)},
		{
			Sequence: 3, StepID: "context-01", Type: "retrieval", Status: "completed",
			At: now.Add(2 * time.Second), Attributes: map[string]string{
				"packet_id": "packet-1", "evidence_count": "2",
				"source_classes": "sec_filing", "as_of": "2026-07-25",
			},
		},
		{
			Sequence: 4, StepID: "context-01", Type: "tool", Status: "completed",
			At: now.Add(3 * time.Second), Attributes: map[string]string{
				"receipt_id": "receipt-1", "operation_id": "financial.free_cash_flow",
				"engine_id": "financial-engine/v1", "formula_version": "fcf/v2",
				"input_count": "3", "output_count": "1", "invariant_count": "2",
				"invariants_passed": "true", "warning_count": "0",
				"receipt_sha256":       strings.Repeat("a", 64),
				"receipt_verification": "metadata_only",
			},
		},
		{Sequence: 5, StepID: "context-01", Type: "context", Status: "completed", At: now.Add(4 * time.Second), Attributes: map[string]string{"packet_id": "packet-1"}},
		{Sequence: 6, StepID: "review-01", Type: "review", Status: "approve", At: now.Add(5 * time.Second), Attributes: map[string]string{"report_id": "report-1"}},
		{Sequence: 7, StepID: "synthesis-01", Type: "synthesis", Status: "passed", At: now.Add(6 * time.Second), Attributes: map[string]string{"answer_id": "answer-1"}},
		{Sequence: 8, Type: "workspace", Status: "completed", At: now.Add(7 * time.Second)},
	}
	b.ReportAllocs()
	for range b.N {
		projection, err := FromPlan(testPlan(now), now)
		if err != nil {
			b.Fatal(err)
		}
		for _, event := range events {
			if err := Apply(&projection, event); err != nil {
				b.Fatal(err)
			}
		}
	}
}

func TestProjectionRejectsUnverifiableCompletedToolReceipts(t *testing.T) {
	now := time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC)
	base := map[string]string{
		"receipt_id":           "receipt-1",
		"operation_id":         "financial.free_cash_flow",
		"engine_id":            "financial-engine/v1",
		"output_count":         "1",
		"invariant_count":      "1",
		"invariants_passed":    "true",
		"receipt_sha256":       strings.Repeat("a", 64),
		"receipt_verification": "metadata_only",
	}
	tests := []struct {
		name   string
		mutate func(map[string]string)
	}{
		{name: "missing hash", mutate: func(values map[string]string) { delete(values, "receipt_sha256") }},
		{name: "malformed hash", mutate: func(values map[string]string) { values["receipt_sha256"] = "not-a-hash" }},
		{name: "failed invariant", mutate: func(values map[string]string) { values["invariants_passed"] = "false" }},
		{name: "no output", mutate: func(values map[string]string) { values["output_count"] = "0" }},
		{name: "missing verification scope", mutate: func(values map[string]string) { delete(values, "receipt_verification") }},
		{name: "invalid verification scope", mutate: func(values map[string]string) { values["receipt_verification"] = "verified" }},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			projection, err := FromPlan(testPlan(now), now)
			if err != nil {
				t.Fatal(err)
			}
			attributes := map[string]string{}
			for key, value := range base {
				attributes[key] = value
			}
			testCase.mutate(attributes)
			err = Apply(&projection, Event{
				Sequence: 1, StepID: "context-01", Type: "tool", Status: "completed",
				At: now.Add(time.Second), Attributes: attributes,
			})
			if err == nil {
				t.Fatal("expected unverifiable receipt to be rejected")
			}
			if projection.LastSequence != 0 {
				t.Fatalf("rejected receipt advanced sequence to %d", projection.LastSequence)
			}
		})
	}
}

func TestProjectionEnforcesChecklistAndReferenceBounds(t *testing.T) {
	now := time.Date(2026, 7, 26, 12, 0, 0, 0, time.UTC)
	t.Run("checklist", func(t *testing.T) {
		projection, err := FromPlan(testPlan(now), now)
		if err != nil {
			t.Fatal(err)
		}
		step := findStep(&projection, "context-01")
		step.Checklist = make([]ChecklistItem, maximumChecklistItems+1)
		for index := range step.Checklist {
			step.Checklist[index] = ChecklistItem{
				CheckID: fmt.Sprintf("bounded-check-%02d", index),
				Label:   "Bounded check", Status: StatusPending, Authority: "contract",
			}
		}
		if err := signAndValidate(&projection); err == nil {
			t.Fatal("expected oversized checklist to be rejected")
		}
	})
	t.Run("step references", func(t *testing.T) {
		projection, err := FromPlan(testPlan(now), now)
		if err != nil {
			t.Fatal(err)
		}
		step := findStep(&projection, "context-01")
		for index := 0; index <= maximumReferenceIDs; index++ {
			step.ReferenceIDs = append(step.ReferenceIDs, fmt.Sprintf("reference-%02d", index))
		}
		if err := signAndValidate(&projection); err == nil {
			t.Fatal("expected oversized step references to be rejected")
		}
	})
	t.Run("check references", func(t *testing.T) {
		projection, err := FromPlan(testPlan(now), now)
		if err != nil {
			t.Fatal(err)
		}
		step := findStep(&projection, "context-01")
		step.Checklist[0].ReferenceIDs = make([]string, maximumReferenceIDs+1)
		for index := range step.Checklist[0].ReferenceIDs {
			step.Checklist[0].ReferenceIDs[index] = fmt.Sprintf("reference-%02d", index)
		}
		if err := signAndValidate(&projection); err == nil {
			t.Fatal("expected oversized checklist references to be rejected")
		}
	})
}

func testPlan(now time.Time) contracts.ResearchPlan {
	return contracts.ResearchPlan{
		SchemaVersion: contracts.SchemaVersionV1,
		PlanID:        "plan-1", RunID: "run-1", RequestID: "request-1",
		MaxParallelSpecialists: 4, MaxRepairPasses: 1, DeadlineMS: 90000,
		CompletionConditions: []string{"review_approved", "single_final_answer"},
		AbstentionConditions: []string{"missing_primary_evidence"},
		Steps: []contracts.PlanStep{
			{
				StepID: "context-01", Kind: "context", Wave: 1, Objective: "Check accounting evidence.",
				RoleID: "accounting-reporting/v1", CapabilityIDs: []string{"financial.free_cash_flow"},
				EvidenceRequirements: []string{"primary_filing"}, Mandatory: true, ContextBudget: 1000, TimeoutMS: 10000,
			},
			{
				StepID: "review-01", Kind: "review", Objective: "Review the evidence.",
				RoleID: "evidence-critic/v1", DependsOn: []string{"context-01"},
				Mandatory: true, ContextBudget: 1000, TimeoutMS: 10000,
			},
			{
				StepID: "synthesis-01", Kind: "synthesis", Objective: "Release the final answer.",
				RoleID: "final-research-analyst/v1", DependsOn: []string{"review-01"},
				Mandatory: true, ContextBudget: 1000, TimeoutMS: 10000,
			},
		},
	}
}
