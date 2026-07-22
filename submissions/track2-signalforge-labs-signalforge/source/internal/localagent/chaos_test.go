package localagent

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/benchmark"
	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/requestparser"
	"github.com/rvbernucci/signalforge/internal/roles"
)

const chaosValidPacketBody = `{
  "findings":[{"claim_id":"claim-1","claim_type":"fact","statement":"The filing supports the bounded claim.","evidence_refs":["evidence-1"],"confidence":0.9}],
  "counterevidence":[],"assumptions":[],"missing_evidence":[],"conflicts":[],"uncertainties":[],"handoff_notes":[]
}`

type blockingChaosCompleter struct{}

func (blockingChaosCompleter) Complete(ctx context.Context, _ benchmark.Request) (benchmark.Completion, error) {
	<-ctx.Done()
	return benchmark.Completion{}, ctx.Err()
}

type chaosPartialSpecialist struct{ failRole string }

func (specialist chaosPartialSpecialist) Run(_ context.Context, request contracts.ContextRequest) (contracts.ContextPacket, error) {
	if request.SpecialistRole == specialist.failRole {
		return contracts.ContextPacket{}, errors.New("injected permanent specialist failure")
	}
	evidenceID := "evidence-" + request.StepID
	return contracts.ContextPacket{
		SchemaVersion:  contracts.SchemaVersionV1,
		PacketID:       "packet-" + request.StepID,
		RunID:          request.RunID,
		StepID:         request.StepID,
		SpecialistRole: request.SpecialistRole,
		Objective:      request.Objective,
		Scope:          request.Scope,
		Findings: []contracts.Finding{{
			ClaimID:      "claim-" + request.StepID,
			ClaimType:    contracts.ClaimFact,
			Statement:    "The surviving specialist supplied a supported claim.",
			EvidenceRefs: []string{evidenceID},
			Confidence:   1,
			ValidAsOf:    request.Scope.AsOf,
		}},
		Evidence: []contracts.EvidenceRef{{
			EvidenceID: evidenceID,
			SourceType: "sec_filing",
			Locator:    "fixture#" + request.StepID,
			ContentSHA: "sha-" + request.StepID,
			AsOf:       request.Scope.AsOf,
		}},
	}, nil
}

type chaosApprovingReviewer struct{}

func (chaosApprovingReviewer) Review(_ context.Context, input orchestrator.ReviewInput) (contracts.CritiqueReport, error) {
	claims := []string{}
	for _, packet := range input.Packets {
		for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
			claims = append(claims, finding.ClaimID)
		}
	}
	return contracts.CritiqueReport{
		SchemaVersion:  contracts.SchemaVersionV1,
		ReportID:       fmt.Sprintf("critique-%s-p%d", input.Step.StepID, input.RepairPass),
		RunID:          input.Request.RunID,
		ReviewerRole:   input.Step.RoleID,
		Decision:       contracts.CritiqueApprove,
		ApprovedClaims: claims,
		RepairPass:     input.RepairPass,
		CreatedAt:      input.Request.AsOf,
	}, nil
}

type chaosSynthesizer struct{}

func (chaosSynthesizer) Synthesize(_ context.Context, input orchestrator.SynthesisInput) (contracts.FinalAnswer, error) {
	if len(input.Packets) == 0 || len(input.Packets[0].Findings) == 0 || len(input.Packets[0].Evidence) == 0 {
		return contracts.FinalAnswer{}, errors.New("no approved surviving context")
	}
	claimID := input.Packets[0].Findings[0].ClaimID
	evidenceID := input.Packets[0].Evidence[0].EvidenceID
	sections := make([]contracts.AnswerSection, 0, len(contracts.RequiredFinalSections(input.Request.PrimaryIntent)))
	for _, sectionType := range contracts.RequiredFinalSections(input.Request.PrimaryIntent) {
		section := contracts.AnswerSection{
			SectionType: sectionType,
			Title:       sectionType,
			Content:     "The answer retains only the surviving approved context.",
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
		SchemaVersion: contracts.SchemaVersionV1,
		AnswerID:      "answer-" + input.Request.RequestID,
		RunID:         input.Request.RunID,
		RequestID:     input.Request.RequestID,
		PrimaryIntent: input.Request.PrimaryIntent,
		AsOf:          input.Request.AsOf,
		Sections:      sections,
		CritiqueRefs:  critiqueRefs,
		ReleasedBy:    roles.FinalResearchAnalyst,
		ReleasedAt:    input.Request.AsOf,
	}, nil
}

type chaosTraceStore struct {
	mu     sync.Mutex
	traces []orchestrator.Trace
}

func (store *chaosTraceStore) Save(trace orchestrator.Trace) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.traces = append(store.traces, trace)
	return nil
}

func TestUnifiedFakeProviderChaosSuite(t *testing.T) {
	now := time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC)

	t.Run("malformed JSON fails without broad retry", func(t *testing.T) {
		client := &fakeCompleter{answers: []string{`{"findings":{}}`}}
		adapter, err := New(client, "local-model", staticMaterials{material: validMaterial(now)})
		if err != nil {
			t.Fatal(err)
		}
		_, err = adapter.Run(context.Background(), validContextRequest(now))
		if err == nil || !strings.Contains(err.Error(), "decode context packet body") || len(client.requests) != 1 {
			t.Fatalf("malformed JSON did not fail closed exactly once: calls=%d err=%v", len(client.requests), err)
		}
	})

	t.Run("truncation receives one bounded larger retry", func(t *testing.T) {
		client := &fakeCompleter{answers: []string{`{"findings":[`, chaosValidPacketBody}}
		adapter, err := New(client, "local-model", staticMaterials{material: validMaterial(now)})
		if err != nil {
			t.Fatal(err)
		}
		packet, err := adapter.Run(context.Background(), validContextRequest(now))
		if err != nil || len(packet.Findings) != 1 || len(client.requests) != 2 || client.requests[1].MaxTokens != 3200 {
			t.Fatalf("bounded truncation recovery failed: packet=%+v calls=%d err=%v", packet, len(client.requests), err)
		}
	})

	t.Run("provider timeout propagates and publishes nothing", func(t *testing.T) {
		adapter, err := New(blockingChaosCompleter{}, "local-model", staticMaterials{material: validMaterial(now)})
		if err != nil {
			t.Fatal(err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
		defer cancel()
		packet, err := adapter.Run(ctx, validContextRequest(now))
		if !errors.Is(err, context.DeadlineExceeded) || len(packet.Findings) != 0 {
			t.Fatalf("timeout did not fail closed: packet=%+v err=%v", packet, err)
		}
	})

	t.Run("invented evidence is quarantined claim by claim", func(t *testing.T) {
		client := &fakeCompleter{answers: []string{`{
          "findings":[{"claim_id":"invented","claim_type":"fact","statement":"Invented.","evidence_refs":["not-authorized"],"confidence":1}],
          "counterevidence":[],"assumptions":[],"missing_evidence":[],"conflicts":[],"uncertainties":[],"handoff_notes":[]
        }`}}
		adapter, err := New(client, "local-model", staticMaterials{material: validMaterial(now)})
		if err != nil {
			t.Fatal(err)
		}
		packet, err := adapter.Run(context.Background(), validContextRequest(now))
		if err != nil || len(packet.Findings) != 0 || len(packet.Evidence) != 0 ||
			len(packet.Uncertainties) != 1 || !strings.Contains(packet.Uncertainties[0], "unauthorized evidence reference") {
			t.Fatalf("invented authority escaped quarantine: packet=%+v err=%v", packet, err)
		}
	})

	t.Run("contradictory review fails closed", func(t *testing.T) {
		client := &fakeCompleter{answers: []string{`{"decision":"approve","approved_claims":["claim-1"],"rejected_claims":["claim-1"],"issues":[]}`}}
		adapter, err := New(client, "local-model", staticMaterials{material: validMaterial(now)})
		if err != nil {
			t.Fatal(err)
		}
		_, err = adapter.Review(context.Background(), orchestrator.ReviewInput{
			Request: validResearchRequest(now),
			Step:    contracts.PlanStep{StepID: "review-1", RoleID: roles.EvidenceCritic},
			Packets: []contracts.ContextPacket{validPacket(now)},
		})
		if err == nil {
			t.Fatal("contradictory reviewer disposition was accepted")
		}
	})

	t.Run("partial specialist failure keeps only reviewed surviving context", func(t *testing.T) {
		request, err := requestparser.ParseDeterministic(requestparser.Input{
			Text: "Compare Microsoft and NVIDIA on cash conversion.",
			AsOf: now, RunID: "chaos-run-partial", RequestID: "chaos-request-partial",
		})
		if err != nil {
			t.Fatal(err)
		}
		store := &chaosTraceStore{}
		runtime, err := orchestrator.New(orchestrator.Dependencies{
			Reviewer: chaosApprovingReviewer{}, Synthesizer: chaosSynthesizer{}, TraceStore: store,
			Specialist: chaosPartialSpecialist{},
		})
		if err != nil {
			t.Fatal(err)
		}
		plan, err := runtime.Planner.Build(request)
		if err != nil {
			t.Fatal(err)
		}
		failRole := ""
		for _, step := range plan.Steps {
			if step.Kind == "context" {
				failRole = step.RoleID
				break
			}
		}
		if failRole == "" {
			t.Fatal("fixture produced no context role to fail")
		}
		runtime.Deps.Specialist = chaosPartialSpecialist{failRole: failRole}
		runtime.Now = func() time.Time { return now }
		result := runtime.Run(context.Background(), request)
		if result.Failure != nil || result.Answer == nil || len(result.ContextFailures) != 1 || len(result.Packets) != 1 {
			t.Fatalf("partial failure did not degrade safely: %+v", result)
		}
		if len(result.Trace.Failures) != 1 || len(store.traces) != 1 {
			t.Fatalf("partial failure was not observable: trace=%+v saves=%d", result.Trace, len(store.traces))
		}
		failedClaim := "claim-context-01"
		for _, section := range result.Answer.Sections {
			for _, claimID := range section.ClaimRefs {
				if claimID == failedClaim {
					t.Fatalf("failed specialist claim escaped into section %q", section.SectionType)
				}
			}
		}
	})
}
