package contracts

import (
	"testing"
	"time"
)

func TestContextPacketRequiresEvidenceForFacts(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	packet := ContextPacket{
		SchemaVersion:  SchemaVersionV1,
		PacketID:       "packet-1",
		RunID:          "run-1",
		StepID:         "step-1",
		SpecialistRole: "accounting-reporting/v1",
		Objective:      "Assess revenue quality.",
		Scope:          Scope{CompanyIDs: []string{"cik:0000789019"}, AsOf: now},
		Findings: []Finding{{
			ClaimID: "claim-1", ClaimType: ClaimFact, Statement: "Revenue increased.",
			Confidence: 0.9, ValidAsOf: now,
		}},
	}
	if err := ValidateContextPacket(packet); err == nil {
		t.Fatal("expected unsupported fact to be rejected")
	}
	packet.Findings[0].EvidenceRefs = []string{"sec:accession:example"}
	if err := ValidateContextPacket(packet); err != nil {
		t.Fatalf("expected evidence-backed packet to pass: %v", err)
	}
}

func TestEngineRequestRejectsUnprovenInput(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	request := EngineRequest{
		SchemaVersion: SchemaVersionV1,
		RequestID:     "request-1", RunID: "run-1", StepID: "step-1",
		RequestedBy: "valuation/v1", EngineID: "valuation", OperationID: "dcf.enterprise_value",
		FormulaVersion: "1.0.0", Scope: Scope{CompanyIDs: []string{"cik:1"}, AsOf: now},
		Inputs:          []EngineInput{{InputID: "fcf", Quantity: Quantity{Value: "100.00", Unit: "currency", Currency: "USD"}, Status: "reported"}},
		PrecisionPolicy: "money-usd-v1", RequestedOutputs: []string{"enterprise_value"},
	}
	if err := ValidateEngineRequest(request); err == nil {
		t.Fatal("expected input without evidence to be rejected")
	}
	request.Inputs[0].EvidenceRefs = []string{"sec:fact:fcf"}
	if err := ValidateEngineRequest(request); err != nil {
		t.Fatalf("expected proven request to pass: %v", err)
	}
}

func TestSuccessfulReceiptCannotHideFailedInvariant(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	receipt := CalculationReceipt{
		SchemaVersion: SchemaVersionV1,
		ReceiptID:     "receipt-1", RequestID: "request-1", EngineID: "accounting",
		EngineVersion: "0.1.0", OperationID: "balance_sheet.identity", FormulaVersion: "1.0.0",
		Status:           ReceiptSuccess,
		Outputs:          []ReceiptOutput{{OutputID: "difference", Quantity: Quantity{Value: "1.00", Unit: "USD"}, Status: "derived"}},
		InvariantResults: []InvariantResult{{InvariantID: "assets=liabilities+equity", Passed: false}},
		TolerancePolicy:  "money-usd-v1", SourceAsOf: now, GeneratedAt: now,
		CodeCommit: "abc", InputSHA: "input", ReceiptSHA: "receipt",
	}
	if err := ValidateCalculationReceipt(receipt); err == nil {
		t.Fatal("expected successful receipt with failed invariant to be rejected")
	}
}
