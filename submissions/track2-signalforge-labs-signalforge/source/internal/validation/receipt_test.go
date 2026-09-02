package validation

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func validPacket() contracts.ContextPacket {
	now := time.Date(2026, 7, 22, 12, 0, 0, 0, time.UTC)
	return contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-validation", RunID: "run-validation",
		StepID: "step-validation", SpecialistRole: "accounting-reporting/v1", Objective: "Validate evidence.",
		Scope: contracts.Scope{AsOf: now},
		Evidence: []contracts.EvidenceRef{{
			EvidenceID: "evidence-1", SourceType: "sec_filing", Locator: "fixture://filing",
			ContentSHA: "sha-fixture", AsOf: now.Add(-24 * time.Hour),
		}},
		Findings: []contracts.Finding{{
			ClaimID: "claim-1", ClaimType: contracts.ClaimFact, Origin: contracts.FindingOriginSourceExtraction,
			Statement: "The filing reports the accounting policy.", EvidenceRefs: []string{"evidence-1"},
			Confidence: 0.9, ValidAsOf: now,
		}},
	}
}

func TestValidationReceiptIsStableAndNeverRepairsContent(t *testing.T) {
	packet := validPacket()
	before, err := json.Marshal(packet)
	if err != nil {
		t.Fatal(err)
	}
	policy := Policy{AsOf: packet.Scope.AsOf, MaxEvidenceAge: map[string]time.Duration{"sec_filing": 48 * time.Hour}}
	first := ContextPacket(packet, policy)
	second := ContextPacket(packet, policy)
	if first.Status != StatusPassed || first.RepairsApplied || !first.Deterministic {
		t.Fatalf("unexpected receipt: %+v", first)
	}
	if !reflect.DeepEqual(first, second) {
		t.Fatal("validation receipt is not deterministic")
	}
	after, err := json.Marshal(packet)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, after) {
		t.Fatal("validator mutated or repaired the source packet")
	}
}

func TestValidationReceiptClassifiesRejectedFailureCodes(t *testing.T) {
	now := validPacket().Scope.AsOf
	tests := []struct {
		name   string
		mutate func(*contracts.ContextPacket)
		code   Code
	}{
		{
			name: "contract",
			mutate: func(packet *contracts.ContextPacket) {
				packet.Objective = ""
			},
			code: CodeContractInvalid,
		},
		{
			name: "future evidence",
			mutate: func(packet *contracts.ContextPacket) {
				packet.Evidence[0].AsOf = packet.Scope.AsOf.Add(time.Second)
			},
			code: CodeFutureEvidence,
		},
		{
			name: "reference",
			mutate: func(packet *contracts.ContextPacket) {
				packet.Findings[0].EvidenceRefs = []string{"missing"}
			},
			code: CodeReferenceInvalid,
		},
		{
			name: "quantity",
			mutate: func(packet *contracts.ContextPacket) {
				packet.CalculationReceipts = []contracts.CalculationReceipt{{
					SchemaVersion: contracts.SchemaVersionV1, ReceiptID: "receipt-invalid", RequestID: "request-invalid",
					EngineID: "comparison", OperationID: "comparison", Status: contracts.ReceiptSuccess,
					Scope: contracts.Scope{AsOf: now}, Outputs: []contracts.ReceiptOutput{{
						OutputID: "invalid", Quantity: contracts.Quantity{Value: "NaN", Unit: "ratio"}, Status: "derived",
					}},
					SourceAsOf: now, GeneratedAt: now, CodeCommit: "fixture", InputSHA: "fixture", ReceiptSHA: "fixture",
				}}
			},
			code: CodeQuantityInvalid,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			packet := validPacket()
			test.mutate(&packet)
			receipt := ContextPacket(packet, Policy{AsOf: packet.Scope.AsOf})
			if receipt.Status != StatusRejected || len(receipt.Issues) != 1 || receipt.Issues[0].Code != test.code {
				t.Fatalf("unexpected classified receipt: %+v", receipt)
			}
			if receipt.RepairsApplied || !receipt.Deterministic {
				t.Fatalf("rejection violated validation authority: %+v", receipt)
			}
		})
	}
}

func TestValidationReceiptUsesNotEvaluableForStaleEvidence(t *testing.T) {
	packet := validPacket()
	receipt := ContextPacket(packet, Policy{
		AsOf: packet.Scope.AsOf, MaxEvidenceAge: map[string]time.Duration{"sec_filing": time.Hour},
	})
	if receipt.Status != StatusNotEvaluable || len(receipt.Issues) != 1 || receipt.Issues[0].Code != CodeStaleEvidence {
		t.Fatalf("unexpected stale receipt: %+v", receipt)
	}
}

func TestValidationReceiptRejectsInvalidReferenceWithStableCode(t *testing.T) {
	packet := validPacket()
	packet.Findings[0].EvidenceRefs = []string{"missing"}
	receipt := ContextPacket(packet, Policy{AsOf: packet.Scope.AsOf})
	if receipt.Status != StatusRejected || len(receipt.Issues) != 1 || receipt.Issues[0].Code != CodeReferenceInvalid {
		t.Fatalf("unexpected reference receipt: %+v", receipt)
	}
}

func TestValidationReceiptRequiresExplicitInstantDurationBridge(t *testing.T) {
	packet := validPacket()
	now := packet.Scope.AsOf
	packet.CalculationReceipts = []contracts.CalculationReceipt{{
		SchemaVersion: contracts.SchemaVersionV1, ReceiptID: "receipt-period", RequestID: "request-period",
		EngineID: "comparison", EngineVersion: "v1", OperationID: "period-comparison", FormulaVersion: "v1",
		Scope: contracts.Scope{AsOf: now}, Status: contracts.ReceiptSuccess,
		NormalizedInputs: []contracts.EngineInput{
			{InputID: "duration", Quantity: contracts.Quantity{Value: "100", Unit: "USD", Currency: "USD", Period: "FY2025"}, Status: "reported", EvidenceRefs: []string{"evidence-1"}},
			{InputID: "instant", Quantity: contracts.Quantity{Value: "120", Unit: "USD", Currency: "USD", Period: "2026-06-30"}, Status: "reported", EvidenceRefs: []string{"evidence-1"}},
		},
		Outputs:          []contracts.ReceiptOutput{{OutputID: "comparison", Quantity: contracts.Quantity{Value: "1.2", Unit: "ratio"}, Status: "verified"}},
		InvariantResults: []contracts.InvariantResult{{InvariantID: "finite", Passed: true}},
		TolerancePolicy:  "exact", EvidenceRefs: []string{"evidence-1"}, SourceAsOf: now,
		CodeCommit: "fixture", InputSHA: "fixture-input", ReceiptSHA: "fixture-receipt", GeneratedAt: now,
	}}
	packet.Findings = append(packet.Findings, contracts.Finding{
		ClaimID: "claim-calculation", ClaimType: contracts.ClaimCalculation, Origin: contracts.FindingOriginDeterministic,
		Statement: "The deterministic comparison is available.", CalculationRefs: []string{"receipt-period"},
		Confidence: 1, ValidAsOf: now,
	})
	receipt := ContextPacket(packet, Policy{AsOf: now, RequirePeriodBridges: true})
	if receipt.Status != StatusNotEvaluable || len(receipt.Issues) != 1 || receipt.Issues[0].Code != CodePeriodBridge {
		t.Fatalf("missing bridge was accepted: %+v", receipt)
	}
	receipt = ContextPacket(packet, Policy{AsOf: now, RequirePeriodBridges: true, AuthorizedPeriodBridges: []PeriodBridge{{
		ReceiptID: "receipt-period", FromKind: "duration", ToKind: "instant", Method: "explicit-period-alignment/v1",
	}}})
	if receipt.Status != StatusPassed {
		t.Fatalf("authorized bridge was rejected: %+v", receipt)
	}
}

func TestValidationReceiptAppliesHashPinnedEntailmentMetadataWithoutAuthoring(t *testing.T) {
	packet := validPacket()
	before, err := json.Marshal(packet)
	if err != nil {
		t.Fatal(err)
	}
	policy := Policy{AsOf: packet.Scope.AsOf, EvidenceEntailment: []EntailmentMetadata{{
		EvidenceID: "evidence-1", ContentSHA: "sha-fixture",
		AllowedClaimTypes: []contracts.ClaimType{contracts.ClaimFact},
		RequiredTerms:     []string{"accounting policy"}, ForbiddenTerms: []string{"management estimates"},
	}}}
	if receipt := ContextPacket(packet, policy); receipt.Status != StatusPassed {
		t.Fatalf("source-authorized prose was rejected: %+v", receipt)
	}
	packet.Findings[0].Statement = "Management estimates the outcome."
	receipt := ContextPacket(packet, policy)
	if receipt.Status != StatusNotEvaluable || len(receipt.Issues) != 2 {
		t.Fatalf("entailment mismatch was released: %+v", receipt)
	}
	for _, issue := range receipt.Issues {
		if issue.Code != CodeEntailment || issue.Owner != "evidence-authority" {
			t.Fatalf("entailment mismatch has unstable authority: %+v", issue)
		}
	}
	packet = validPacket()
	policy.EvidenceEntailment[0].ContentSHA = "different-source-hash"
	if receipt := ContextPacket(packet, policy); receipt.Status != StatusNotEvaluable || receipt.Issues[0].Code != CodeEntailment {
		t.Fatalf("stale entailment metadata was accepted: %+v", receipt)
	}
	after, err := json.Marshal(validPacket())
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, after) {
		t.Fatal("entailment validation authored or repaired packet prose")
	}
}

func FuzzValidationReceiptNeverPassesFutureEvidence(f *testing.F) {
	f.Add(int64(1))
	f.Add(int64(3600))
	f.Fuzz(func(t *testing.T, seconds int64) {
		if seconds <= 0 || seconds > 86400*365 {
			t.Skip()
		}
		packet := validPacket()
		packet.Evidence[0].AsOf = packet.Scope.AsOf.Add(time.Duration(seconds) * time.Second)
		if receipt := ContextPacket(packet, Policy{AsOf: packet.Scope.AsOf}); receipt.Status == StatusPassed {
			t.Fatal("future evidence received a passing validation receipt")
		}
	})
}

func BenchmarkContextPacketValidationReceipt(b *testing.B) {
	packet := validPacket()
	policy := Policy{AsOf: packet.Scope.AsOf, MaxEvidenceAge: map[string]time.Duration{"sec_filing": 48 * time.Hour}}
	b.ReportAllocs()
	for index := 0; index < b.N; index++ {
		_ = ContextPacket(packet, policy)
	}
}
