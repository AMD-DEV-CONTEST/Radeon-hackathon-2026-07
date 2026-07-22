package roleeval

import (
	"slices"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/localagent"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func frozenTime() time.Time { return time.Date(2026, 7, 21, 18, 0, 0, 0, time.UTC) }

func roleMission(roleID string) string {
	role, _ := roles.DefaultRegistry().Get(roleID)
	return role.Mission
}

func materialFor(item Case, now time.Time, stepID string) localagent.Material {
	material := localagent.Material{Evidence: contracts.EvidenceBundle{
		SchemaVersion: contracts.SchemaVersionV1, BundleID: "bundle-" + item.CaseID,
		RunID: "eval-run", StepID: stepID, AsOf: now,
	}}
	for _, seed := range item.Evidence {
		material.Evidence.Items = append(material.Evidence.Items, contracts.EvidenceItem{
			EvidenceRef: contracts.EvidenceRef{
				EvidenceID: seed.EvidenceID, SourceType: "held_out_fixture", Locator: item.CaseID,
				ContentSHA: "fixture-" + seed.EvidenceID, AsOf: now,
			},
			State: contracts.EvidenceState(seed.State), Statement: seed.Statement,
			ConflictRefs: append([]string(nil), seed.ConflictRefs...),
		})
	}
	for _, seed := range item.Calculations {
		evidenceRefs := []string{}
		for _, evidence := range item.Evidence {
			if evidence.State == string(contracts.EvidenceAvailable) {
				evidenceRefs = append(evidenceRefs, evidence.EvidenceID)
			}
		}
		material.CalculationReceipts = append(material.CalculationReceipts, contracts.CalculationReceipt{
			SchemaVersion: contracts.SchemaVersionV1, ReceiptID: seed.ReceiptID,
			RequestID: "engine-request-" + item.CaseID, EngineID: "signalforge-finance/v1",
			EngineVersion: "v1", OperationID: seed.Operation, FormulaVersion: "v1",
			Status: contracts.ReceiptSuccess,
			Outputs: []contracts.ReceiptOutput{{
				OutputID: seed.OutputID, Quantity: contracts.Quantity{Value: seed.Value, Unit: seed.Unit}, Status: "derived",
			}},
			InvariantResults: []contracts.InvariantResult{{InvariantID: "finite-output", Passed: true}},
			TolerancePolicy:  "exact-fixture/v1", EvidenceRefs: evidenceRefs,
			SourceAsOf: now, CodeCommit: "held-out-fixture", InputSHA: "fixture-input",
			ReceiptSHA: "fixture-receipt", GeneratedAt: now,
		})
	}
	return material
}

func baseRequest(question, intent string, now time.Time) contracts.ResearchRequest {
	return contracts.ResearchRequest{
		SchemaVersion: contracts.SchemaVersionV1, RequestID: "eval-request", RunID: "eval-run",
		UserText: question, PrimaryIntent: intent,
		Entities: []contracts.EntityRef{{
			EntityType: "company", EntityID: "sec-cik:0000789019", Mention: "Microsoft", Resolved: true,
		}},
		Period: contracts.PeriodScope{Kind: "current"}, AsOf: now,
		Comparison: contracts.ComparisonScope{Mode: "none"}, AnswerDepth: "standard",
		RequestedOutputs: contracts.RequiredFinalSections(intent),
	}
}

func reviewPacket(item Case, now time.Time) contracts.ContextPacket {
	evidence1 := contracts.EvidenceRef{EvidenceID: "evidence-1", SourceType: "held_out_fixture", Locator: item.CaseID, ContentSHA: "one", AsOf: now}
	evidence2 := contracts.EvidenceRef{EvidenceID: "evidence-2", SourceType: "held_out_fixture", Locator: item.CaseID, ContentSHA: "two", AsOf: now}
	packet := contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-" + item.CaseID,
		RunID: "eval-run", StepID: "context-1", SpecialistRole: roles.BusinessStrategy,
		Objective: "Produce evidence-grounded context.", Scope: contracts.Scope{AsOf: now},
		Evidence: []contracts.EvidenceRef{evidence1},
	}
	switch item.Scenario {
	case "supported":
		if item.RoleID == roles.RiskContrarian {
			packet.Assumptions = []string{"Enterprise spending slows by 10%."}
			packet.Findings = []contracts.Finding{{
				ClaimID: "claim-1", ClaimType: contracts.ClaimInference,
				Statement:    "If enterprise spending slows by 10%, revenue growth may decelerate; stable growth would invalidate the hypothesis.",
				EvidenceRefs: []string{"evidence-1"}, AssumptionRefs: append([]string(nil), packet.Assumptions...),
				Confidence: 0.7, ValidAsOf: now,
			}}
		} else {
			packet.Findings = []contracts.Finding{{
				ClaimID: "claim-1", ClaimType: contracts.ClaimFact, Statement: "The filing supports the bounded claim.",
				EvidenceRefs: []string{"evidence-1"}, Confidence: 0.9, ValidAsOf: now,
			}}
		}
	case "unsupported":
		packet.Findings = []contracts.Finding{{
			ClaimID: "claim-1", ClaimType: contracts.ClaimFact, Statement: "This factual claim has no evidence reference.",
			Confidence: 0.9, ValidAsOf: now,
		}}
	case "conflict":
		packet.Evidence = append(packet.Evidence, evidence2)
		packet.Findings = []contracts.Finding{{
			ClaimID: "claim-1", ClaimType: contracts.ClaimFact, Statement: "The first filing value controls without qualification.",
			EvidenceRefs: []string{"evidence-1"}, Confidence: 0.8, ValidAsOf: now,
		}}
		packet.Conflicts = []string{"evidence-1 and evidence-2 report different values"}
	case "material_counterevidence":
		packet.Evidence = append(packet.Evidence, evidence2)
		packet.Findings = []contracts.Finding{{
			ClaimID: "claim-1", ClaimType: contracts.ClaimInference,
			Statement: "Customer concentration is harmless.", EvidenceRefs: []string{"evidence-1"},
			AssumptionRefs: []string{"customer retention remains stable"}, Confidence: 0.6, ValidAsOf: now,
		}}
		packet.Counterevidence = []contracts.Finding{{
			ClaimID: "claim-2", ClaimType: contracts.ClaimFact,
			Statement: "One customer represents 35% of revenue.", EvidenceRefs: []string{"evidence-2"},
			Confidence: 1, ValidAsOf: now,
		}}
		packet.Assumptions = []string{"customer retention remains stable"}
	case "advice_boundary":
		packet.Findings = []contracts.Finding{{
			ClaimID: "claim-1", ClaimType: contracts.ClaimHypothesis,
			Statement: "The valuation guarantees a 20% return.", Confidence: 0.1, ValidAsOf: now,
		}}
	}
	return packet
}

func synthesisPacket(item Case, now time.Time) contracts.ContextPacket {
	evidence := contracts.EvidenceRef{EvidenceID: "evidence-1", SourceType: "held_out_fixture", Locator: item.CaseID, ContentSHA: "one", AsOf: now}
	packet := contracts.ContextPacket{
		SchemaVersion: contracts.SchemaVersionV1, PacketID: "packet-" + item.CaseID,
		RunID: "eval-run", StepID: "context-1", SpecialistRole: roles.BusinessStrategy,
		Objective: "Provide approved evidence.", Scope: contracts.Scope{AsOf: now}, Evidence: []contracts.EvidenceRef{evidence},
		Findings: []contracts.Finding{{
			ClaimID: "claim-1", ClaimType: contracts.ClaimFact,
			Statement:    "The approved evidence supports the main research statement.",
			EvidenceRefs: []string{"evidence-1"}, Confidence: 0.9, ValidAsOf: now,
		}},
	}
	if item.Scenario == "thesis_review" {
		packet.Counterevidence = []contracts.Finding{{
			ClaimID: "claim-2", ClaimType: contracts.ClaimFact,
			Statement:    "The approved evidence also contains a disconfirming observation.",
			EvidenceRefs: []string{"evidence-1"}, Confidence: 0.9, ValidAsOf: now,
		}}
	}
	return packet
}

func packetCitationsSupported(packet contracts.ContextPacket) bool {
	available := map[string]bool{}
	for _, evidence := range packet.Evidence {
		available[evidence.EvidenceID] = true
	}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		if finding.ClaimType == contracts.ClaimFact && len(finding.EvidenceRefs) == 0 {
			return false
		}
		for _, evidenceID := range finding.EvidenceRefs {
			if !available[evidenceID] {
				return false
			}
		}
	}
	return len(packet.Evidence) > 0
}

func packetCalculationSupported(packet contracts.ContextPacket, seeds []CalculationSeed) bool {
	wanted := map[string]bool{}
	for _, seed := range seeds {
		wanted[seed.ReceiptID] = true
	}
	for _, finding := range packet.Findings {
		for _, receiptID := range finding.CalculationRefs {
			if wanted[receiptID] {
				return true
			}
		}
	}
	return false
}

func reviewDecisionSupported(report contracts.CritiqueReport, _ contracts.ContextPacket, scenario string) bool {
	if scenario == "supported" {
		return report.Decision == contracts.CritiqueApprove && len(report.ApprovedClaims) > 0
	}
	return report.Decision != contracts.CritiqueApprove && len(report.Issues) > 0
}

func answerCitationsSupported(answer contracts.FinalAnswer, packet contracts.ContextPacket) bool {
	claims, evidence := map[string]bool{}, map[string]bool{}
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		claims[finding.ClaimID] = true
	}
	for _, ref := range packet.Evidence {
		evidence[ref.EvidenceID] = true
	}
	materialClaims := 0
	for _, section := range answer.Sections {
		for _, claimID := range section.ClaimRefs {
			materialClaims++
			if !claims[claimID] {
				return false
			}
		}
		for _, evidenceID := range section.EvidenceRefs {
			if !evidence[evidenceID] {
				return false
			}
		}
	}
	return materialClaims > 0
}

func packetText(packet contracts.ContextPacket) string {
	parts := append([]string{}, packet.Assumptions...)
	parts = append(parts, packet.MissingEvidence...)
	parts = append(parts, packet.Conflicts...)
	parts = append(parts, packet.Uncertainties...)
	parts = append(parts, packet.HandoffNotes...)
	for _, finding := range append(append([]contracts.Finding(nil), packet.Findings...), packet.Counterevidence...) {
		parts = append(parts, finding.Statement)
	}
	return strings.Join(parts, " ")
}

func critiqueText(report contracts.CritiqueReport) string {
	parts := []string{}
	for _, issue := range report.Issues {
		parts = append(parts, issue.Description, issue.RepairHint)
	}
	return strings.Join(parts, " ")
}

func containsTerms(value string, terms []string) bool {
	lower := normalizedSearchText(value)
	for _, term := range terms {
		if !strings.Contains(lower, normalizedSearchText(term)) {
			return false
		}
	}
	return true
}

func normalizedSearchText(value string) string {
	return strings.ReplaceAll(strings.ToLower(value), ",", "")
}

func forbiddenTermsClear(value string, terms []string) bool {
	lower := strings.ToLower(value)
	for _, term := range terms {
		if strings.Contains(lower, strings.ToLower(term)) {
			return false
		}
	}
	return true
}

func textContains(value, term string) bool {
	return strings.Contains(strings.ToLower(value), strings.ToLower(term))
}

func containsAll(values, required []string) bool {
	for _, value := range required {
		if !slices.Contains(values, value) {
			return false
		}
	}
	return true
}

func boolMetric(value bool) float64 {
	if value {
		return 1
	}
	return 0
}

func ratio(numerator, denominator int) float64 {
	if denominator == 0 {
		return 1
	}
	return float64(numerator) / float64(denominator)
}
