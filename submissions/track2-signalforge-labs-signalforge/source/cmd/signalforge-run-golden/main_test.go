package main

import (
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/executionplan"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
)

func TestRuntimeProfileRequiresCompleteAttestation(t *testing.T) {
	t.Parallel()
	if _, err := runtimeProfile(runtimeProfileInput{ProfileID: "partial"}, "local-model"); err == nil {
		t.Fatal("partial runtime attestation must fail closed")
	}
	profile, err := runtimeProfile(runtimeProfileInput{
		ProfileID: "radeon", GPUArchitecture: "gfx1100", ROCmVersion: "7.2.1",
		Runtime: "llama.cpp", RuntimeRevision: "runtime-revision", Quantization: "QAT-Q4_0",
		ModelRevision: "model-revision", RuntimeEvidenceSHA: strings.Repeat("a", 64),
	}, "local-model")
	if err != nil {
		t.Fatal(err)
	}
	if !profile.Attested || profile.ModelID != "local-model" {
		t.Fatalf("unexpected complete runtime profile: %+v", profile)
	}
}

func TestRuntimeProfileAllowsExplicitlyUnattestedLocalReplay(t *testing.T) {
	t.Parallel()
	profile, err := runtimeProfile(runtimeProfileInput{}, "local-model")
	if err != nil {
		t.Fatal(err)
	}
	if profile.Attested || profile.ModelID != "local-model" {
		t.Fatalf("unexpected unattested profile: %+v", profile)
	}
}

func TestExecutionPlanSinkProducesAValidatedPassedProjection(t *testing.T) {
	now := time.Date(2026, 7, 25, 20, 0, 0, 0, time.UTC)
	plan := contracts.ResearchPlan{
		SchemaVersion: contracts.SchemaVersionV1,
		PlanID:        "plan-dashboard", RunID: "run-dashboard", RequestID: "request-dashboard",
		MaxParallelSpecialists: 1, MaxRepairPasses: 1, DeadlineMS: 90000,
		CompletionConditions: []string{"review_approved", "single_final_answer"},
		AbstentionConditions: []string{"missing_primary_evidence"},
		Steps: []contracts.PlanStep{
			{
				StepID: "context-01", Kind: "context", Wave: 1,
				Objective: "Compile governed evidence.", RoleID: "accounting-reporting/v1",
				EvidenceRequirements: []string{"primary_filing"}, Mandatory: true,
				ContextBudget: 1000, TimeoutMS: 10000,
			},
			{
				StepID: "review-01", Kind: "review", Objective: "Review supported claims.",
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
	sink := &executionPlanSink{}
	sink.AcceptPlan(plan, now)
	events := []orchestrator.Event{
		{Sequence: 1, RunID: plan.RunID, Type: "plan", Status: "accepted", At: now},
		{Sequence: 2, RunID: plan.RunID, StepID: "context-01", Type: "context", Status: "started", At: now},
		{Sequence: 3, RunID: plan.RunID, StepID: "context-01", Type: "context", Status: "completed", At: now},
		{Sequence: 4, RunID: plan.RunID, StepID: "review-01", Type: "review", Status: "started", At: now},
		{Sequence: 5, RunID: plan.RunID, StepID: "review-01", Type: "review", Status: "approve", At: now},
		{Sequence: 6, RunID: plan.RunID, StepID: "synthesis-01", Type: "synthesis", Status: "started", At: now},
		{Sequence: 7, RunID: plan.RunID, StepID: "synthesis-01", Type: "synthesis", Status: "passed", At: now},
	}
	for _, event := range events {
		sink.Emit(event)
	}
	projection, err := sink.complete(now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if projection.Status != executionplan.StatusPassed ||
		projection.ProgressRatio != 1 ||
		projection.LastSequence != 8 {
		t.Fatalf("projection = %+v", projection)
	}
}
