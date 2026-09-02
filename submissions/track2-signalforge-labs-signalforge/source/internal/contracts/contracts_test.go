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
	packet.Evidence = []EvidenceRef{{
		EvidenceID: "sec:accession:example", SourceType: "sec_filing", Locator: "Item 7",
		ContentSHA: "fixture-content", AsOf: now,
	}}
	if err := ValidateContextPacket(packet); err != nil {
		t.Fatalf("expected evidence-backed packet to pass: %v", err)
	}
}

func TestContextPacketRejectsUnknownReferencesAndFutureEvidence(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	assumption := "Rates remain above the base case."
	packet := ContextPacket{
		SchemaVersion: SchemaVersionV1, PacketID: "packet-refs", RunID: "run-refs",
		StepID: "step-refs", SpecialistRole: "economics-transmission/v1", Objective: "Test references.",
		Scope: Scope{AsOf: now}, Assumptions: []string{assumption},
		Evidence: []EvidenceRef{{EvidenceID: "evidence-1", SourceType: "fred", Locator: "DFF", ContentSHA: "fixture", AsOf: now}},
		Findings: []Finding{{
			ClaimID: "claim-1", ClaimType: ClaimInference, Statement: "The scenario may affect financing.",
			EvidenceRefs: []string{"evidence-1"}, AssumptionRefs: []string{assumption}, Confidence: 0.5, ValidAsOf: now,
		}},
	}
	if err := ValidateContextPacket(packet); err != nil {
		t.Fatalf("valid reference graph failed: %v", err)
	}
	packet.Findings[0].EvidenceRefs = []string{"missing"}
	if err := ValidateContextPacket(packet); err == nil {
		t.Fatal("unknown evidence must fail closed")
	}
	packet.Findings[0].EvidenceRefs = []string{"evidence-1"}
	packet.Findings[0].AssumptionRefs = []string{"unknown assumption"}
	if err := ValidateContextPacket(packet); err == nil {
		t.Fatal("unknown assumption must fail closed")
	}
	packet.Findings[0].AssumptionRefs = []string{assumption}
	packet.Evidence[0].AsOf = now.Add(time.Second)
	if err := ValidateContextPacket(packet); err == nil {
		t.Fatal("future evidence must fail closed")
	}
}

func TestEngineRequestRejectsInvalidQuantitiesAndFutureInputs(t *testing.T) {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	asOf := now
	request := EngineRequest{
		SchemaVersion: SchemaVersionV1, RequestID: "request-quantity", RunID: "run-quantity", StepID: "step-quantity",
		RequestedBy: "valuation/v1", EngineID: "valuation", OperationID: "valuation.test", FormulaVersion: "v1",
		Scope: Scope{AsOf: now}, Inputs: []EngineInput{{
			InputID: "input-1", Quantity: Quantity{Value: "1.25", Unit: "ratio", Currency: "USD", AsOf: &asOf},
			Status: "reported", EvidenceRefs: []string{"evidence-1"},
		}}, PrecisionPolicy: "decimal-v1", RequestedOutputs: []string{"result"},
	}
	if err := ValidateEngineRequest(request); err != nil {
		t.Fatalf("valid quantity failed: %v", err)
	}
	request.Inputs[0].Quantity.Value = "NaN"
	if err := ValidateEngineRequest(request); err == nil {
		t.Fatal("non-finite quantity must fail")
	}
	request.Inputs[0].Quantity.Value = "1.25"
	request.Inputs[0].Quantity.Currency = "usd"
	if err := ValidateEngineRequest(request); err == nil {
		t.Fatal("non-canonical currency must fail")
	}
	request.Inputs[0].Quantity.Currency = "USD"
	future := now.Add(time.Second)
	request.Inputs[0].Quantity.AsOf = &future
	if err := ValidateEngineRequest(request); err == nil {
		t.Fatal("future quantity must fail")
	}
}

func FuzzValidateEngineRequestNeverAcceptsFutureQuantity(f *testing.F) {
	f.Add(int64(1))
	f.Add(int64(3600))
	f.Fuzz(func(t *testing.T, seconds int64) {
		if seconds <= 0 || seconds > 86400*365 {
			t.Skip()
		}
		now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
		future := now.Add(time.Duration(seconds) * time.Second)
		request := EngineRequest{
			SchemaVersion: SchemaVersionV1, RequestID: "request-fuzz", RunID: "run-fuzz", StepID: "step-fuzz",
			RequestedBy: "valuation/v1", EngineID: "valuation", OperationID: "valuation.test", FormulaVersion: "v1",
			Scope: Scope{AsOf: now}, Inputs: []EngineInput{{InputID: "input", Quantity: Quantity{
				Value: "1", Unit: "ratio", AsOf: &future,
			}, Status: "reported", EvidenceRefs: []string{"evidence"}}},
			PrecisionPolicy: "decimal-v1", RequestedOutputs: []string{"result"},
		}
		if ValidateEngineRequest(request) == nil {
			t.Fatal("future quantity was accepted")
		}
	})
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
