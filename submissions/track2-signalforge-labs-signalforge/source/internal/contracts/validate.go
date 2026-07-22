package contracts

import (
	"errors"
	"fmt"
	"strings"
)

func ValidateContextPacket(packet ContextPacket) error {
	if err := validateEnvelope(packet.SchemaVersion, packet.PacketID, packet.RunID); err != nil {
		return err
	}
	if strings.TrimSpace(packet.StepID) == "" || strings.TrimSpace(packet.SpecialistRole) == "" {
		return errors.New("step_id and specialist_role are required")
	}
	if strings.TrimSpace(packet.Objective) == "" {
		return errors.New("objective is required")
	}
	if packet.Scope.AsOf.IsZero() {
		return errors.New("scope.as_of is required")
	}
	receipts := make(map[string]bool, len(packet.CalculationReceipts))
	for i, receipt := range packet.CalculationReceipts {
		if err := ValidateCalculationReceipt(receipt); err != nil {
			return fmt.Errorf("calculation_receipts[%d]: %w", i, err)
		}
		if receipts[receipt.ReceiptID] {
			return fmt.Errorf("calculation_receipts[%d] duplicates %q", i, receipt.ReceiptID)
		}
		receipts[receipt.ReceiptID] = true
	}
	numericalRefs := map[string]bool{}
	if packet.NumericalContext != nil {
		if packet.NumericalContext.RunID != packet.RunID || packet.NumericalContext.AsOf.After(packet.Scope.AsOf) {
			return errors.New("numerical context does not match packet run or as_of")
		}
		if err := ValidateNumericalContext(*packet.NumericalContext); err != nil {
			return fmt.Errorf("numerical_context: %w", err)
		}
		for _, variable := range packet.NumericalContext.Variables {
			numericalRefs[variable.VariableID] = true
			for _, receiptID := range variable.ReceiptRefs {
				if !receipts[receiptID] {
					return fmt.Errorf("numerical variable %q references missing calculation receipt %q", variable.VariableID, receiptID)
				}
			}
		}
		for _, relation := range packet.NumericalContext.Relations {
			numericalRefs[relation.RelationID] = true
			for _, receiptID := range relation.ReceiptRefs {
				if !receipts[receiptID] {
					return fmt.Errorf("numerical relation %q references missing calculation receipt %q", relation.RelationID, receiptID)
				}
			}
		}
	}
	for i, finding := range packet.Findings {
		if err := validateFinding(finding); err != nil {
			return fmt.Errorf("findings[%d]: %w", i, err)
		}
		for _, receiptID := range finding.CalculationRefs {
			if !receipts[receiptID] {
				return fmt.Errorf("findings[%d] references missing calculation receipt %q", i, receiptID)
			}
		}
		for _, numericalID := range finding.NumericalRefs {
			if !numericalRefs[numericalID] {
				return fmt.Errorf("findings[%d] references missing numerical item %q", i, numericalID)
			}
		}
	}
	for i, finding := range packet.Counterevidence {
		if err := validateFinding(finding); err != nil {
			return fmt.Errorf("counterevidence[%d]: %w", i, err)
		}
		for _, receiptID := range finding.CalculationRefs {
			if !receipts[receiptID] {
				return fmt.Errorf("counterevidence[%d] references missing calculation receipt %q", i, receiptID)
			}
		}
		for _, numericalID := range finding.NumericalRefs {
			if !numericalRefs[numericalID] {
				return fmt.Errorf("counterevidence[%d] references missing numerical item %q", i, numericalID)
			}
		}
	}
	conflicts := make(map[string]struct{}, len(packet.Conflicts))
	for i, conflict := range packet.Conflicts {
		if strings.TrimSpace(conflict) == "" {
			return fmt.Errorf("conflicts[%d] is empty", i)
		}
		if _, duplicate := conflicts[conflict]; duplicate {
			return fmt.Errorf("conflicts[%d] duplicates %q", i, conflict)
		}
		conflicts[conflict] = struct{}{}
	}
	return nil
}

func ValidateEngineRequest(request EngineRequest) error {
	if err := validateEnvelope(request.SchemaVersion, request.RequestID, request.RunID); err != nil {
		return err
	}
	if request.StepID == "" || request.RequestedBy == "" || request.EngineID == "" || request.OperationID == "" {
		return errors.New("step_id, requested_by, engine_id, and operation_id are required")
	}
	if request.FormulaVersion == "" || request.PrecisionPolicy == "" {
		return errors.New("formula_version and precision_policy are required")
	}
	if request.Scope.AsOf.IsZero() {
		return errors.New("scope.as_of is required")
	}
	if len(request.Inputs) == 0 || len(request.RequestedOutputs) == 0 {
		return errors.New("at least one input and requested output are required")
	}
	inputIDs := make(map[string]struct{}, len(request.Inputs))
	for i, input := range request.Inputs {
		if input.InputID == "" || input.Quantity.Value == "" || input.Quantity.Unit == "" || input.Status == "" {
			return fmt.Errorf("inputs[%d] is incomplete", i)
		}
		if _, duplicate := inputIDs[input.InputID]; duplicate {
			return fmt.Errorf("inputs[%d] duplicates input_id %q", i, input.InputID)
		}
		inputIDs[input.InputID] = struct{}{}
		switch input.Status {
		case "reported", "normalized", "derived", "assumed":
		default:
			return fmt.Errorf("inputs[%d] has unsupported status %q", i, input.Status)
		}
		if len(input.EvidenceRefs) == 0 && input.Status != "assumed" {
			return fmt.Errorf("inputs[%d] requires evidence or assumed status", i)
		}
	}
	requestedOutputs := make(map[string]struct{}, len(request.RequestedOutputs))
	for i, output := range request.RequestedOutputs {
		if strings.TrimSpace(output) == "" {
			return fmt.Errorf("requested_outputs[%d] is empty", i)
		}
		if _, duplicate := requestedOutputs[output]; duplicate {
			return fmt.Errorf("requested_outputs[%d] duplicates %q", i, output)
		}
		requestedOutputs[output] = struct{}{}
	}
	return nil
}

func ValidateCalculationReceipt(receipt CalculationReceipt) error {
	if receipt.SchemaVersion != SchemaVersionV1 {
		return fmt.Errorf("unsupported schema_version %q", receipt.SchemaVersion)
	}
	if receipt.ReceiptID == "" || receipt.RequestID == "" || receipt.EngineID == "" || receipt.OperationID == "" {
		return errors.New("receipt_id, request_id, engine_id, and operation_id are required")
	}
	if receipt.GeneratedAt.IsZero() || receipt.SourceAsOf.IsZero() {
		return errors.New("generated_at and source_as_of are required")
	}
	if receipt.CodeCommit == "" || receipt.InputSHA == "" || receipt.ReceiptSHA == "" {
		return errors.New("reproducibility hashes and code_commit are required")
	}
	if receipt.Status == ReceiptSuccess {
		if len(receipt.Outputs) == 0 {
			return errors.New("successful receipt requires outputs")
		}
		for _, invariant := range receipt.InvariantResults {
			if !invariant.Passed {
				return fmt.Errorf("successful receipt has failed invariant %q", invariant.InvariantID)
			}
		}
	}
	return nil
}

func validateEnvelope(schemaVersion, objectID, runID string) error {
	if schemaVersion != SchemaVersionV1 {
		return fmt.Errorf("unsupported schema_version %q", schemaVersion)
	}
	if strings.TrimSpace(objectID) == "" || strings.TrimSpace(runID) == "" {
		return errors.New("object identifier and run_id are required")
	}
	return nil
}

func validateFinding(finding Finding) error {
	if finding.ClaimID == "" || strings.TrimSpace(finding.Statement) == "" {
		return errors.New("claim_id and statement are required")
	}
	if finding.Confidence < 0 || finding.Confidence > 1 {
		return errors.New("confidence must be between 0 and 1")
	}
	if finding.ValidAsOf.IsZero() {
		return errors.New("valid_as_of is required")
	}
	if finding.Origin != "" && finding.Origin != FindingOriginDeterministic && finding.Origin != FindingOriginSourceExtraction {
		return fmt.Errorf("unsupported finding origin %q", finding.Origin)
	}
	if finding.Origin == FindingOriginDeterministic && finding.ClaimType != ClaimCalculation {
		return errors.New("deterministic finding origin requires calculation claim_type")
	}
	if finding.Origin == FindingOriginSourceExtraction && finding.ClaimType != ClaimFact {
		return errors.New("source extraction origin requires fact claim_type")
	}
	switch finding.ClaimType {
	case ClaimFact:
		if len(finding.EvidenceRefs) == 0 {
			return errors.New("fact requires evidence_refs")
		}
	case ClaimCalculation:
		if len(finding.CalculationRefs) == 0 {
			return errors.New("calculation requires calculation_refs")
		}
	case ClaimInference:
		if len(finding.EvidenceRefs)+len(finding.CalculationRefs)+len(finding.NumericalRefs) == 0 || len(finding.AssumptionRefs) == 0 {
			return errors.New("inference requires support and assumption_refs")
		}
	case ClaimHypothesis:
		if len(finding.EvidenceRefs)+len(finding.CalculationRefs)+len(finding.NumericalRefs)+len(finding.AssumptionRefs) == 0 {
			return errors.New("hypothesis requires support or an explicit assumption")
		}
	default:
		return fmt.Errorf("unsupported claim_type %q", finding.ClaimType)
	}
	return nil
}
