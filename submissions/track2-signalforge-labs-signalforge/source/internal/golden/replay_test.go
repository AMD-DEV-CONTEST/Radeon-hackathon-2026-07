package golden

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestSafeDecisionReplayExcludesPrivateBodiesAndDetectsTampering(t *testing.T) {
	t.Parallel()
	privateQuestion := "PRIVATE_QUESTION_SENTINEL"
	privateFinding := "PRIVATE_FINDING_SENTINEL"
	privateAnswer := "PRIVATE_ANSWER_SENTINEL"
	privateFailure := "PRIVATE_FAILURE_SENTINEL"
	privateProviderError := "PRIVATE_PROVIDER_ERROR_SENTINEL"
	start := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	sha := strings.Repeat("a", 64)

	packet := contracts.ContextPacket{
		SchemaVersion:  contracts.SchemaVersionV1,
		PacketID:       "packet-business",
		RunID:          "run-safe-replay",
		StepID:         "context-business",
		SpecialistRole: roles.BusinessStrategy,
		Findings: []contracts.Finding{
			{ClaimID: "claim-released", ClaimType: contracts.ClaimFact, Statement: privateFinding, EvidenceRefs: []string{"evidence-primary"}, Confidence: 1, ValidAsOf: start},
			{ClaimID: "claim-rejected", ClaimType: contracts.ClaimInference, Statement: privateFinding, EvidenceRefs: []string{"evidence-primary"}, AssumptionRefs: []string{"Rates remain above the base case."}, Confidence: 0.5, ValidAsOf: start},
		},
		Evidence: []contracts.EvidenceRef{{EvidenceID: "evidence-primary", SourceType: "fixture", Locator: "private-locator", ContentSHA: sha, AsOf: start}},
	}
	critique := contracts.CritiqueReport{
		SchemaVersion: contracts.SchemaVersionV1, ReportID: "critique-evidence", RunID: "run-safe-replay",
		ReviewerRole: roles.EvidenceCritic, Decision: contracts.CritiqueApprove,
		ApprovedClaims: []string{"claim-released"}, RejectedClaims: []string{"claim-rejected"}, CreatedAt: start.Add(4 * time.Second),
	}
	answer := contracts.FinalAnswer{
		SchemaVersion: contracts.SchemaVersionV1, AnswerID: "answer-safe", RunID: "run-safe-replay",
		RequestID: "request-safe-replay", PrimaryIntent: "company_comparison", AsOf: start,
		Sections:     []contracts.AnswerSection{{SectionType: "comparison", Title: "Private", Content: privateAnswer, ClaimRefs: []string{"claim-released"}, EvidenceRefs: []string{"evidence-primary"}}},
		CritiqueRefs: []string{"critique-evidence"}, ReleasedBy: roles.FinalResearchAnalyst, ReleasedAt: start,
	}
	trace := orchestrator.Trace{
		SchemaVersion: "signalforge/orchestration-trace/v1", RunID: "run-safe-replay",
		RequestID: "request-safe-replay", PlanID: "plan-safe-replay", StartedAt: start,
		CompletedAt: start.Add(7 * time.Second), MaxConcurrentContext: 1,
		Events: []orchestrator.Event{
			{Sequence: 1, RunID: "run-safe-replay", StepID: "context-business", Type: "context", Status: "started", At: start.Add(time.Second), Attributes: map[string]string{"role_id": roles.BusinessStrategy, "route_reason_code": "intent_requires_specialist", "capability_ids": "strategy.business_model"}},
			{Sequence: 2, RunID: "run-safe-replay", StepID: "context-business", Type: "context", Status: "completed", At: start.Add(2 * time.Second)},
			{Sequence: 3, RunID: "run-safe-replay", StepID: "review-evidence", Type: "review", Status: "started", At: start.Add(3 * time.Second), Attributes: map[string]string{"role_id": roles.EvidenceCritic, "route_reason_code": "evidence_release_gate"}},
			{Sequence: 4, RunID: "run-safe-replay", StepID: "review-evidence", Type: "review", Status: "approve", At: start.Add(4 * time.Second)},
			{Sequence: 5, RunID: "run-safe-replay", StepID: "synthesis-final", Type: "synthesis", Status: "started", At: start.Add(5 * time.Second), Attributes: map[string]string{"role_id": roles.FinalResearchAnalyst, "route_reason_code": "single_release_authority"}},
			{Sequence: 6, RunID: "run-safe-replay", StepID: "synthesis-final", Type: "run", Status: "completed", At: start.Add(6 * time.Second)},
		},
	}
	report := Report{
		SchemaVersion: ReportSchemaV1, GeneratedAt: start.Add(8 * time.Second), Question: privateQuestion,
		Model: "local-model", LocalBaseURL: "http://127.0.0.1:8000/v1",
		Request: contracts.ResearchRequest{SchemaVersion: contracts.SchemaVersionV1, RequestID: "request-safe-replay", RunID: "run-safe-replay", UserText: privateQuestion, AsOf: start},
		Result: orchestrator.Result{
			Answer: &answer, Packets: []contracts.ContextPacket{packet}, Critiques: []contracts.CritiqueReport{critique}, Trace: trace,
			ContextFailures: []contracts.FailureReceipt{{SchemaVersion: contracts.SchemaVersionV1, FailureID: "failure-partial", RunID: "run-safe-replay", StepID: "context-optional", ComponentID: "specialist", FailureCode: "timeout", Message: privateFailure, Retryable: true, CreatedAt: start}},
		},
		Calls: []CallMetric{
			{RoleID: roles.BusinessStrategy, Duration: 2 * time.Second, TTFT: 100 * time.Millisecond, PromptTokens: 100, CompletionTokens: 20, FinishReason: "stop"},
			{RoleID: roles.EvidenceCritic, Duration: time.Second, TTFT: 80 * time.Millisecond, Failed: true, Error: privateProviderError, FinishReason: privateProviderError},
		},
		Metrics: Metrics{DurationMS: 7000, ModelCalls: 2, PromptTokens: 100, CompletionTokens: 20, ContextPackets: 1, Critiques: 1, Claims: 2, SupportedClaims: 2, EvidenceCoverage: 1, MaxConcurrentContext: 1},
	}
	profile := RuntimeProfile{
		Attested: true, ProfileID: "gemma-rocm", GPUArchitecture: "gfx1100", ROCmVersion: "7.2.1",
		Runtime: "llama.cpp", RuntimeRevision: "runtime-revision", Quantization: "QAT-Q4_0",
		ModelID: "signalforge-gemma4-26b-q4", ModelRevision: "model-revision", RuntimeEvidenceSHA: sha,
	}

	replay, err := BuildSafeDecisionReplay(report, profile)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := json.Marshal(replay)
	if err != nil {
		t.Fatal(err)
	}
	serialized := string(payload)
	for _, forbidden := range []string{privateQuestion, privateFinding, privateAnswer, privateFailure, privateProviderError, "private-locator"} {
		if strings.Contains(serialized, forbidden) {
			t.Fatalf("safe replay leaked %q: %s", forbidden, serialized)
		}
	}
	if len(replay.Routes) != 3 || len(replay.Artifacts) == 0 || len(replay.Claims) != 2 || replay.Metrics.ReleasedClaims != 1 {
		t.Fatalf("safe replay omitted decision evidence: %+v", replay)
	}
	if got := replay.Claims[0].AssumptionRefs; len(got) != 1 || got[0] != "Rates remain above the base case." {
		t.Fatalf("safe replay omitted assumption authority: %+v", replay.Claims)
	}
	if replay.Calls[1].FinishReason != "other" || len(replay.Failures) != 1 {
		t.Fatalf("provider or failure data was not safely projected: %+v %+v", replay.Calls, replay.Failures)
	}

	tampered := replay
	tampered.Metrics.PromptTokens++
	if err := ValidateSafeDecisionReplay(tampered); err == nil {
		t.Fatal("tampered safe replay must fail hash validation")
	}
}

func TestRecordingCompleterPreservesRoleForBoundedRepairPrompt(t *testing.T) {
	t.Parallel()
	recorder := newRecordingCompleter(benchmarkClientForRoleTest())
	prompt, ok := localPromptForRole(roles.FinalResearchAnalyst)
	if !ok {
		t.Fatal("final analyst prompt is missing")
	}
	if got := recorder.roleForSystemPrompt(prompt + " bounded repair instruction"); got != roles.FinalResearchAnalyst {
		t.Fatalf("repair prompt role=%q", got)
	}
	if got := recorder.roleForSystemPrompt("unregistered prompt"); got != "unknown" {
		t.Fatalf("unregistered prompt role=%q", got)
	}
}

func benchmarkClientForRoleTest() benchmark.Client { return benchmark.Client{} }

func localPromptForRole(roleID string) (string, bool) {
	prompt, ok := localagent.DefaultPromptRegistry().Get(roleID)
	return prompt.System, ok
}
