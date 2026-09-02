package workspace

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
)

func TestProjectPublishesOnlyWorkspaceSafeMaterial(t *testing.T) {
	now := time.Date(2026, 7, 22, 4, 30, 0, 0, time.UTC)
	answer := contracts.FinalAnswer{
		RunID: "run-1", RequestID: "request-1", PrimaryIntent: "company_comparison", AsOf: now,
		Sections: []contracts.AnswerSection{{
			SectionType: "comparison", Title: "Comparison", Content: "Released answer.",
			EvidenceRefs: []string{"evidence-1"}, ReceiptRefs: []string{"receipt-1"},
		}},
		Assumptions: []string{"Explicit scenario."}, Limitations: []string{"Bounded period."},
	}
	report := golden.Report{
		Question: "Compare Microsoft and NVIDIA.", AsOf: now, Model: "local-model",
		Request: contracts.ResearchRequest{
			RunID: "run-1", RequestID: "request-1",
			Entities: []contracts.EntityRef{
				{EntityID: "msft", Mention: "Microsoft"}, {EntityID: "nvda", Mention: "NVIDIA"},
			},
		},
		Result: orchestrator.Result{
			Answer: &answer,
			Packets: []contracts.ContextPacket{{
				SpecialistRole: "valuation/v1",
				Evidence: []contracts.EvidenceRef{{
					EvidenceID: "evidence-1", SourceType: "sec_filing", Locator: "https://example.com/filing",
					ContentSHA: strings.Repeat("a", 64), AsOf: now,
				}},
				CalculationReceipts: []contracts.CalculationReceipt{{
					ReceiptID: "receipt-1", OperationID: "valuation.fcff_dcf", EngineID: "engine",
					EngineVersion: "1", FormulaVersion: "1", Status: contracts.ReceiptSuccess,
					Outputs:    []contracts.ReceiptOutput{{OutputID: "enterprise_value", Quantity: contracts.Quantity{Value: "100", Unit: "currency", Currency: "USD"}}},
					SourceAsOf: now, ReceiptSHA: strings.Repeat("b", 64),
				}},
				Uncertainties: []string{"A bounded uncertainty."},
			}},
			Trace: orchestrator.Trace{Events: []orchestrator.Event{{
				Sequence: 1, RunID: "run-1", Type: "plan", Status: "accepted", At: now,
			}}},
		},
		Metrics: golden.Metrics{Claims: 1, SupportedClaims: 1, EvidenceCoverage: 1, RequiredSections: 1, PresentRequiredSections: 1},
	}
	projection, err := Project(report)
	if err != nil {
		t.Fatal(err)
	}
	if len(projection.Evidence) != 1 || len(projection.Calculations) != 1 || len(projection.Events) != 1 || len(projection.Warnings) != 1 {
		t.Fatalf("workspace projection lost safe inspectable material: %+v", projection)
	}
	payload, err := json.Marshal(projection)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"prompt_tokens", "completion_tokens", "chain_of_thought", "failure message"} {
		if strings.Contains(string(payload), forbidden) {
			t.Fatalf("workspace projection leaked private field %q", forbidden)
		}
	}
}

func TestProjectFailsClosedOnUnknownSectionAuthority(t *testing.T) {
	now := time.Now().UTC()
	answer := contracts.FinalAnswer{
		PrimaryIntent: "company_comparison",
		Sections:      []contracts.AnswerSection{{SectionType: "comparison", Content: "Answer.", EvidenceRefs: []string{"unknown"}}},
	}
	_, err := Project(golden.Report{
		Question: "Compare Microsoft and NVIDIA.", AsOf: now, Model: "local-model",
		Request: contracts.ResearchRequest{RunID: "run", RequestID: "request", Entities: []contracts.EntityRef{{Mention: "Microsoft"}, {Mention: "NVIDIA"}}},
		Result:  orchestrator.Result{Answer: &answer},
	})
	if err == nil {
		t.Fatal("unknown workspace authority must fail closed")
	}
}
