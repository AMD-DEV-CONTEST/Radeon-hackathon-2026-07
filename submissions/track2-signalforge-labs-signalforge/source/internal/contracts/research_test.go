package contracts

import (
	"testing"
	"time"
)

func TestResearchPlanRejectsCyclesAndExcessiveFanout(t *testing.T) {
	plan := validPlan()
	plan.Steps[0].DependsOn = []string{"s2"}
	if err := ValidateResearchPlan(plan); err == nil {
		t.Fatal("cyclic plan must fail")
	}
	plan = validPlan()
	plan.MaxParallelSpecialists = 5
	if err := ValidateResearchPlan(plan); err == nil {
		t.Fatal("more than four specialists must fail")
	}
}

func TestConflictingEvidenceRequiresReferences(t *testing.T) {
	now := time.Now().UTC()
	bundle := EvidenceBundle{
		SchemaVersion: SchemaVersionV1, BundleID: "bundle-1", RunID: "run-1", StepID: "step-1", AsOf: now,
		Items: []EvidenceItem{{EvidenceRef: EvidenceRef{EvidenceID: "e1"}, State: EvidenceConflicting}},
	}
	if err := ValidateEvidenceBundle(bundle); err == nil {
		t.Fatal("unresolved conflict without references must fail")
	}
	bundle.Items[0].ConflictRefs = []string{"e2"}
	if err := ValidateEvidenceBundle(bundle); err != nil {
		t.Fatalf("referenced conflict should pass: %v", err)
	}
}

func TestFindingOriginRequiresMatchingAuthority(t *testing.T) {
	now := time.Now().UTC()
	tests := []struct {
		name    string
		finding Finding
		wantErr bool
	}{
		{
			name: "source extraction fact",
			finding: Finding{ClaimID: "source-1", ClaimType: ClaimFact,
				Origin: FindingOriginSourceExtraction, Statement: "The filing identifies a risk.",
				EvidenceRefs: []string{"evidence-1"}, Confidence: 1, ValidAsOf: now},
		},
		{
			name: "source extraction cannot claim calculation",
			finding: Finding{ClaimID: "source-2", ClaimType: ClaimCalculation,
				Origin: FindingOriginSourceExtraction, Statement: "A value exists.",
				CalculationRefs: []string{"receipt-1"}, Confidence: 1, ValidAsOf: now},
			wantErr: true,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := validateFinding(test.finding)
			if (err != nil) != test.wantErr {
				t.Fatalf("validateFinding() error=%v, wantErr=%v", err, test.wantErr)
			}
		})
	}
}

func TestFinalAnswerRejectsUnsupportedClaims(t *testing.T) {
	now := time.Now().UTC()
	answer := FinalAnswer{
		SchemaVersion: SchemaVersionV1, AnswerID: "answer-1", RunID: "run-1", RequestID: "request-1",
		PrimaryIntent: "company_comparison", AsOf: now, CritiqueRefs: []string{"critique-1"},
		ReleasedBy: "final-research-analyst/v1", ReleasedAt: now,
		Sections: []AnswerSection{
			{SectionType: "comparison", Title: "Comparison", Content: "Claim", ClaimRefs: []string{"claim-1"}},
			{SectionType: "evidence", Title: "Evidence", Content: "Primary evidence."},
			{SectionType: "limitations", Title: "Limitations", Content: "Known limits."},
		},
	}
	if err := ValidateFinalAnswer(answer); err == nil {
		t.Fatal("claim without evidence or receipt must fail")
	}
	answer.Sections[0].EvidenceRefs = []string{"evidence-1"}
	if err := ValidateFinalAnswer(answer); err != nil {
		t.Fatalf("supported answer should pass: %v", err)
	}
}

func TestFinalAnswerSectionsDependOnIntent(t *testing.T) {
	if got := RequiredFinalSections("valuation"); len(got) != 5 || got[0] != "assumptions" {
		t.Fatalf("unexpected valuation sections %v", got)
	}
	if got := RequiredFinalSections("concept_education"); len(got) != 4 || got[0] != "concept" {
		t.Fatalf("unexpected education sections %v", got)
	}
	if got := RequiredFinalSections("thesis_review"); len(got) != 5 || got[1] != "counterevidence" {
		t.Fatalf("unexpected thesis sections %v", got)
	}
}

func TestFailureReceiptMakesCancellationExplicit(t *testing.T) {
	receipt := FailureReceipt{
		SchemaVersion: SchemaVersionV1, FailureID: "failure-1", RunID: "run-1", StepID: "step-1",
		ComponentID: "research-orchestrator/v1", FailureCode: "cancelled", Message: "User cancelled.",
		Retryable: false, CreatedAt: time.Now().UTC(),
	}
	if err := ValidateFailureReceipt(receipt); err != nil {
		t.Fatal(err)
	}
	receipt.Message = ""
	if err := ValidateFailureReceipt(receipt); err == nil {
		t.Fatal("failure without a message must fail")
	}
}

func TestMemoryCandidateAlwaysRequiresApproval(t *testing.T) {
	candidate := MemoryCandidate{
		SchemaVersion: SchemaVersionV1, CandidateID: "memory-1", RunID: "run-1", Content: "User prefers concise answers.",
		SourceArtifactIDs: []string{"request-1"}, Sensitivity: "preference", CreatedAt: time.Now().UTC(),
	}
	if err := ValidateMemoryCandidate(candidate); err == nil {
		t.Fatal("unapproved memory candidate must fail")
	}
	candidate.RequiresApproval = true
	if err := ValidateMemoryCandidate(candidate); err != nil {
		t.Fatalf("approved candidate contract should pass: %v", err)
	}
}

func validPlan() ResearchPlan {
	return ResearchPlan{
		SchemaVersion: SchemaVersionV1, PlanID: "plan-1", RunID: "run-1", RequestID: "request-1",
		MaxParallelSpecialists: 4, MaxRepairPasses: 1, DeadlineMS: 60000,
		CompletionConditions: []string{"evidence_approved"}, AbstentionConditions: []string{"missing_primary_evidence"},
		Steps: []PlanStep{
			{StepID: "s1", Kind: "context", Objective: "Understand business", RoleID: "business-strategy/v1", ContextBudget: 1000, TimeoutMS: 10000},
			{StepID: "s2", Kind: "review", Objective: "Review", RoleID: "evidence-critic/v1", DependsOn: []string{"s1"}, ContextBudget: 1000, TimeoutMS: 10000},
			{StepID: "s3", Kind: "synthesis", Objective: "Synthesize", RoleID: "final-research-analyst/v1", DependsOn: []string{"s2"}, ContextBudget: 1000, TimeoutMS: 10000},
		},
	}
}
