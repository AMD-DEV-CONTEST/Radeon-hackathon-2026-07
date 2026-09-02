package contracts

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
)

var currencyPattern = regexp.MustCompile(`^[A-Z]{3}$`)

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
	evidence := make(map[string]bool, len(packet.Evidence))
	for i, item := range packet.Evidence {
		if strings.TrimSpace(item.EvidenceID) == "" || strings.TrimSpace(item.SourceType) == "" ||
			strings.TrimSpace(item.Locator) == "" || strings.TrimSpace(item.ContentSHA) == "" || item.AsOf.IsZero() {
			return fmt.Errorf("evidence[%d] is incomplete", i)
		}
		if item.AsOf.After(packet.Scope.AsOf) {
			return fmt.Errorf("evidence[%d] is later than scope.as_of", i)
		}
		if evidence[item.EvidenceID] {
			return fmt.Errorf("evidence[%d] duplicates %q", i, item.EvidenceID)
		}
		evidence[item.EvidenceID] = true
	}
	assumptions := make(map[string]bool, len(packet.Assumptions))
	for i, assumption := range packet.Assumptions {
		assumption = strings.TrimSpace(assumption)
		if assumption == "" {
			return fmt.Errorf("assumptions[%d] is empty", i)
		}
		if assumptions[assumption] {
			return fmt.Errorf("assumptions[%d] duplicates %q", i, assumption)
		}
		assumptions[assumption] = true
	}
	receipts := make(map[string]bool, len(packet.CalculationReceipts))
	for i, receipt := range packet.CalculationReceipts {
		if err := ValidateCalculationReceipt(receipt); err != nil {
			return fmt.Errorf("calculation_receipts[%d]: %w", i, err)
		}
		if receipts[receipt.ReceiptID] {
			return fmt.Errorf("calculation_receipts[%d] duplicates %q", i, receipt.ReceiptID)
		}
		if receipt.SourceAsOf.After(packet.Scope.AsOf) {
			return fmt.Errorf("calculation_receipts[%d] is later than scope.as_of", i)
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
		if finding.ValidAsOf.After(packet.Scope.AsOf) {
			return fmt.Errorf("findings[%d] is later than scope.as_of", i)
		}
		if err := validateFindingReferences(finding, evidence, assumptions); err != nil {
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
		if finding.ValidAsOf.After(packet.Scope.AsOf) {
			return fmt.Errorf("counterevidence[%d] is later than scope.as_of", i)
		}
		if err := validateFindingReferences(finding, evidence, assumptions); err != nil {
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
		if err := validateQuantity(input.Quantity, request.Scope.AsOf); err != nil {
			return fmt.Errorf("inputs[%d].quantity: %w", i, err)
		}
		if err := validateUniqueStrings(input.EvidenceRefs, "evidence_refs"); err != nil {
			return fmt.Errorf("inputs[%d]: %w", i, err)
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
	if receipt.GeneratedAt.Before(receipt.SourceAsOf) {
		return errors.New("generated_at cannot precede source_as_of")
	}
	if !receipt.Scope.AsOf.IsZero() && receipt.SourceAsOf.After(receipt.Scope.AsOf) {
		return errors.New("source_as_of cannot be later than scope.as_of")
	}
	if err := validateUniqueStrings(receipt.EvidenceRefs, "evidence_refs"); err != nil {
		return err
	}
	outputIDs := map[string]bool{}
	for i, output := range append(append([]ReceiptOutput(nil), receipt.IntermediateValues...), receipt.Outputs...) {
		if strings.TrimSpace(output.OutputID) == "" || strings.TrimSpace(output.Status) == "" {
			return fmt.Errorf("outputs[%d] is incomplete", i)
		}
		if outputIDs[output.OutputID] {
			return fmt.Errorf("outputs[%d] duplicates output_id %q", i, output.OutputID)
		}
		outputIDs[output.OutputID] = true
		if err := validateQuantity(output.Quantity, receipt.SourceAsOf); err != nil {
			return fmt.Errorf("outputs[%d].quantity: %w", i, err)
		}
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

func validateFindingReferences(finding Finding, evidence, assumptions map[string]bool) error {
	for _, refs := range []struct {
		name   string
		values []string
	}{
		{name: "evidence_refs", values: finding.EvidenceRefs},
		{name: "calculation_refs", values: finding.CalculationRefs},
		{name: "numerical_refs", values: finding.NumericalRefs},
		{name: "assumption_refs", values: finding.AssumptionRefs},
	} {
		if err := validateUniqueStrings(refs.values, refs.name); err != nil {
			return err
		}
	}
	for _, reference := range finding.EvidenceRefs {
		if !evidence[reference] {
			return fmt.Errorf("references missing evidence %q", reference)
		}
	}
	for _, reference := range finding.AssumptionRefs {
		if !assumptions[reference] {
			return fmt.Errorf("references missing assumption %q", reference)
		}
	}
	return nil
}

func validateUniqueStrings(values []string, name string) error {
	seen := make(map[string]bool, len(values))
	for i, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			return fmt.Errorf("%s[%d] is empty", name, i)
		}
		if seen[value] {
			return fmt.Errorf("%s[%d] duplicates %q", name, i, value)
		}
		seen[value] = true
	}
	return nil
}

func validateQuantity(quantity Quantity, scopeAsOf time.Time) error {
	if strings.TrimSpace(quantity.Value) == "" || strings.TrimSpace(quantity.Unit) == "" {
		return errors.New("value and unit are required")
	}
	decimal, _, err := apd.NewFromString(strings.TrimSpace(quantity.Value))
	if err != nil || decimal.Form != apd.Finite {
		return errors.New("value must be a finite decimal")
	}
	if quantity.Currency != "" && !currencyPattern.MatchString(quantity.Currency) {
		return errors.New("currency must be an uppercase ISO-style code")
	}
	if quantity.AsOf != nil && !scopeAsOf.IsZero() && quantity.AsOf.After(scopeAsOf) {
		return errors.New("as_of cannot be later than scope.as_of")
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
