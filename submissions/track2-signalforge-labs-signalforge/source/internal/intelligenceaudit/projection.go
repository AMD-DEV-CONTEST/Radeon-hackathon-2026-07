package intelligenceaudit

import (
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
)

func FromResult(question string, request contracts.ResearchRequest, result orchestrator.Result) ProjectionInput {
	completedAt := result.Trace.CompletedAt
	if completedAt.IsZero() {
		completedAt = time.Now().UTC()
	}
	status := "completed"
	if result.Failure != nil {
		status = "failed"
	}
	input := ProjectionInput{
		RunID: request.RunID, RequestID: request.RequestID, Question: question,
		StartedAt: result.Trace.StartedAt, CompletedAt: completedAt, Status: status,
	}
	seenEvidence := map[string]bool{}
	seenReceipts := map[string]bool{}
	for _, packet := range result.Packets {
		retrieval := RetrievalRecord{
			RetrievalID: "retrieval-" + digestString(packet.PacketID)[:20],
			StepID:      packet.StepID, RoleID: packet.SpecialistRole,
			Method: "authorized_context_packet", ContextPacketID: packet.PacketID,
			EvidenceIDs: []string{}, Status: "selected", CompletedAt: completedAt,
		}
		for _, evidence := range packet.Evidence {
			retrieval.EvidenceIDs = appendUnique(retrieval.EvidenceIDs, evidence.EvidenceID)
			retrieval.EvidenceSources = append(retrieval.EvidenceSources, EvidenceSourceRecord{
				EvidenceID: evidence.EvidenceID, SourceType: evidence.SourceType,
				Locator: evidence.Locator, DocumentSection: evidence.DocumentSection,
				ContentSHA: evidence.ContentSHA, AsOf: evidence.AsOf,
			})
			seenEvidence[evidence.EvidenceID] = true
		}
		sort.Strings(retrieval.EvidenceIDs)
		sort.Slice(retrieval.EvidenceSources, func(i, j int) bool {
			return retrieval.EvidenceSources[i].EvidenceID < retrieval.EvidenceSources[j].EvidenceID
		})
		input.Retrievals = append(input.Retrievals, retrieval)
		for _, receipt := range packet.CalculationReceipts {
			if seenReceipts[receipt.ReceiptID] {
				continue
			}
			seenReceipts[receipt.ReceiptID] = true
			engine := EngineCall{
				EngineCallID: "engine-" + digestString(receipt.ReceiptID)[:20],
				StepID:       packet.StepID, RequestedBy: packet.SpecialistRole,
				EngineID: receipt.EngineID, EngineVersion: receipt.EngineVersion,
				OperationID: receipt.OperationID, FormulaVersion: receipt.FormulaVersion,
				ReceiptID: receipt.ReceiptID, ReceiptSHA: receipt.ReceiptSHA,
				EvidenceRefs:    append([]string(nil), receipt.EvidenceRefs...),
				InvariantsTotal: len(receipt.InvariantResults), Status: string(receipt.Status),
				GeneratedAt: receipt.GeneratedAt,
			}
			for _, item := range receipt.NormalizedInputs {
				engine.InputRefs = append(engine.InputRefs, item.InputID)
			}
			for _, item := range receipt.Outputs {
				engine.OutputRefs = append(engine.OutputRefs, item.OutputID)
			}
			for _, invariant := range receipt.InvariantResults {
				if invariant.Passed {
					engine.InvariantsPass++
				}
			}
			sort.Strings(engine.InputRefs)
			sort.Strings(engine.OutputRefs)
			sort.Strings(engine.EvidenceRefs)
			input.Engines = append(input.Engines, engine)
			input.Receipts = append(input.Receipts, ProtectedReceipt{
				ReceiptID: receipt.ReceiptID, Payload: receipt,
			})
		}
	}
	for _, critique := range result.Critiques {
		input.Reviews = append(input.Reviews, ReviewRecord{
			ReviewID: critique.ReportID, RoleID: critique.ReviewerRole,
			Decision: string(critique.Decision), RepairPass: critique.RepairPass,
			ApprovedClaims: append([]string(nil), critique.ApprovedClaims...),
			RejectedClaims: append([]string(nil), critique.RejectedClaims...),
		})
	}
	if result.Answer != nil {
		release := &ReleaseRecord{
			AnswerID: result.Answer.AnswerID, PrimaryIntent: result.Answer.PrimaryIntent,
			SectionTypes: []string{}, ClaimRefs: []string{}, EvidenceRefs: []string{},
			ReceiptRefs: []string{}, Status: "released",
		}
		for _, section := range result.Answer.Sections {
			release.SectionTypes = append(release.SectionTypes, section.SectionType)
			release.ClaimRefs = appendManyUnique(release.ClaimRefs, section.ClaimRefs)
			release.EvidenceRefs = appendManyUnique(release.EvidenceRefs, section.EvidenceRefs)
			release.ReceiptRefs = appendManyUnique(release.ReceiptRefs, section.ReceiptRefs)
		}
		sort.Strings(release.ClaimRefs)
		sort.Strings(release.EvidenceRefs)
		sort.Strings(release.ReceiptRefs)
		input.Release = release
	}
	sort.Slice(input.Retrievals, func(i, j int) bool {
		return input.Retrievals[i].RetrievalID < input.Retrievals[j].RetrievalID
	})
	sort.Slice(input.Engines, func(i, j int) bool {
		return input.Engines[i].ReceiptID < input.Engines[j].ReceiptID
	})
	return input
}

func appendUnique(values []string, value string) []string {
	if value == "" {
		return values
	}
	for _, existing := range values {
		if existing == value {
			return values
		}
	}
	return append(values, value)
}

func appendManyUnique(values, additions []string) []string {
	for _, value := range additions {
		values = appendUnique(values, value)
	}
	return values
}
