package localagent

import (
	"errors"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func semanticPacket(role string, claimType contracts.ClaimType, statement string, assumptions []string) contracts.ContextPacket {
	now := time.Date(2026, 7, 21, 12, 0, 0, 0, time.UTC)
	refs := []string(nil)
	if len(assumptions) > 0 {
		refs = []string{assumptions[0]}
	}
	return contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-semantic", RunID: "run-semantic",
		StepID: "step-semantic", SpecialistRole: role, Objective: "Test semantic guard.", Scope: contracts.Scope{AsOf: now},
		Assumptions: assumptions,
		Findings: []contracts.Finding{{
			ClaimID: "claim-semantic", ClaimType: claimType, Statement: statement,
			AssumptionRefs: refs, Confidence: 0.5, ValidAsOf: now,
		}},
	}
}

func TestSemanticGuardRejectsUnconditionalCausality(t *testing.T) {
	packet := semanticPacket(roles.MarketBehavior, contracts.ClaimHypothesis, "The event caused the share-price move.", nil)
	err := validateSpecialistSemantics(packet)
	var violation semanticViolation
	if !errors.As(err, &violation) || violation.Code != semanticUnsupportedCausality {
		t.Fatalf("unexpected semantic result: %v", err)
	}
	packet.Findings[0].Statement = "Under the stated scenario, the event may affect market expectations; causality is not identified."
	if err := validateSpecialistSemantics(packet); err != nil {
		t.Fatalf("bounded mechanism was rejected: %v", err)
	}
}

func TestSemanticGuardRejectsScenarioAsFact(t *testing.T) {
	packet := semanticPacket(roles.AccountingReporting, contracts.ClaimFact, "The scenario would change revenue recognition.", nil)
	err := validateSpecialistSemantics(packet)
	var violation semanticViolation
	if !errors.As(err, &violation) || violation.Code != semanticScenarioAsFact {
		t.Fatalf("unexpected semantic result: %v", err)
	}
}

func TestSemanticGuardAllowsSourceBackedUnavailableScenarioBoundary(t *testing.T) {
	packet := semanticPacket(
		roles.Valuation,
		contracts.ClaimFact,
		"Valuation scenario authority is unavailable; unsupported conclusions must abstain.",
		nil,
	)
	packet.Findings[0].Origin = contracts.FindingOriginSourceExtraction
	packet.Findings[0].EvidenceRefs = []string{"product-scope:valuation/v1"}
	if err := validateSpecialistSemantics(packet); err != nil {
		t.Fatalf("governed unavailable boundary was rejected: %v", err)
	}

	packet.Findings[0].Statement = "The scenario would increase enterprise value."
	if err := validateSpecialistSemantics(packet); err == nil {
		t.Fatal("source-extracted scenario assertion was accepted as a scope boundary")
	}
	packet.Findings[0].Statement = "Valuation scenario authority is unavailable."
	packet.Findings[0].EvidenceRefs = []string{"sec-filing:item-7"}
	if err := validateSpecialistSemantics(packet); err == nil {
		t.Fatal("non-policy evidence bypassed the scenario-as-fact guard")
	}
}

func TestSemanticGuardRequiresEconomicScenarioAssumption(t *testing.T) {
	packet := semanticPacket(roles.EconomicsTransmission, contracts.ClaimHypothesis, "Higher rates could affect refinancing.", nil)
	err := validateSpecialistSemantics(packet)
	var violation semanticViolation
	if !errors.As(err, &violation) || violation.Code != semanticMissingAssumption {
		t.Fatalf("unexpected semantic result: %v", err)
	}
	assumption := "Higher rates are an explicit scenario."
	packet = semanticPacket(roles.EconomicsTransmission, contracts.ClaimHypothesis, "Under the scenario, higher rates could affect refinancing.", []string{assumption})
	if err := validateSpecialistSemantics(packet); err != nil {
		t.Fatalf("assumption-grounded scenario was rejected: %v", err)
	}
}

func TestSemanticGuardSeparatesAccountingAssertionsAndSourcedPolicy(t *testing.T) {
	packet := semanticPacket(roles.AccountingReporting, contracts.ClaimFact, "Management expects the accounting estimate to remain stable.", nil)
	packet.Findings[0].EvidenceRefs = []string{"evidence-1"}
	err := validateSpecialistSemantics(packet)
	var violation semanticViolation
	if !errors.As(err, &violation) || violation.Code != semanticAccountingAssertion {
		t.Fatalf("management assertion was not classified: %v", err)
	}
	packet.Findings[0].Statement = "The filing describes the accounting policy for revenue recognition."
	packet.Findings[0].Origin = contracts.FindingOriginSourceExtraction
	if err := validateSpecialistSemantics(packet); err != nil {
		t.Fatalf("source-extracted accounting policy was rejected: %v", err)
	}
}

func TestSemanticGuardRequiresEconomicTransmissionMechanism(t *testing.T) {
	assumption := "Higher rates persist through the analysis horizon."
	packet := semanticPacket(roles.EconomicsTransmission, contracts.ClaimHypothesis, "Higher rates and refinancing costs remain relevant.", []string{assumption})
	err := validateSpecialistSemantics(packet)
	var violation semanticViolation
	if !errors.As(err, &violation) || violation.Code != semanticTransmissionMissing {
		t.Fatalf("missing transmission mechanism was not classified: %v", err)
	}
	packet.Findings[0].Statement = "Under the scenario, higher rates could affect refinancing costs through repricing channels."
	if err := validateSpecialistSemantics(packet); err != nil {
		t.Fatalf("explicit transmission mechanism was rejected: %v", err)
	}
}

func FuzzSemanticGuardNeverAcceptsAssertiveMarketCausality(f *testing.F) {
	f.Add("The event caused the move.")
	f.Add("The filing resulted in the decline.")
	f.Fuzz(func(t *testing.T, statement string) {
		if !assertiveCausalPattern.MatchString(statement) || conditionalPattern.MatchString(statement) {
			t.Skip()
		}
		packet := semanticPacket(roles.MarketBehavior, contracts.ClaimHypothesis, statement, nil)
		if validateSpecialistSemantics(packet) == nil {
			t.Fatal("unconditional market causality was accepted")
		}
	})
}
