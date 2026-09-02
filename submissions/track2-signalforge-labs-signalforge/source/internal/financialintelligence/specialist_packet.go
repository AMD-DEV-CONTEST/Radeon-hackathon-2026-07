package financialintelligence

import (
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/roles"
)

const SpecialistPacketSchemaV1 = "signalforge/financial-specialist-packet/v1"

type AnalysisAvailability string

const (
	AvailabilityReady         AnalysisAvailability = "ready"
	AvailabilityMissingData   AnalysisAvailability = "missing_data"
	AvailabilityNotApplicable AnalysisAvailability = "not_applicable"
	AvailabilityDisagreement  AnalysisAvailability = "disagreement"
)

type SpecialistPacket struct {
	SchemaVersion   string                  `json:"schema_version"`
	PacketID        string                  `json:"packet_id"`
	RunID           string                  `json:"run_id"`
	RoleID          string                  `json:"role_id"`
	Objective       string                  `json:"objective"`
	AsOf            time.Time               `json:"as_of"`
	Availability    AnalysisAvailability    `json:"availability"`
	MetricRefs      []MetricReference       `json:"metric_refs,omitempty"`
	RelationRefs    []RelationReference     `json:"relation_refs,omitempty"`
	Evidence        []contracts.EvidenceRef `json:"evidence,omitempty"`
	ReceiptRefs     []ReceiptReference      `json:"receipt_refs,omitempty"`
	Assumptions     []string                `json:"assumptions,omitempty"`
	Limitations     []string                `json:"limitations,omitempty"`
	MissingEvidence []string                `json:"missing_evidence,omitempty"`
	Conflicts       []string                `json:"conflicts,omitempty"`
}

type ReceiptOutputReference struct {
	OutputID string `json:"output_id"`
	Unit     string `json:"unit"`
	Currency string `json:"currency,omitempty"`
	Period   string `json:"period,omitempty"`
	Status   string `json:"status"`
}

// ReceiptReference preserves provenance and semantic shape without exposing numerical values.
type ReceiptReference struct {
	ReceiptID      string                   `json:"receipt_id"`
	OperationID    string                   `json:"operation_id"`
	Status         contracts.ReceiptStatus  `json:"status"`
	FormulaVersion string                   `json:"formula_version"`
	Outputs        []ReceiptOutputReference `json:"outputs"`
	Assumptions    []string                 `json:"assumptions,omitempty"`
	EvidenceRefs   []string                 `json:"evidence_refs,omitempty"`
	InputSHA       string                   `json:"input_sha256"`
	ReceiptSHA     string                   `json:"receipt_sha256"`
}

type SpecialistPacketSet struct {
	SchemaVersion string             `json:"schema_version"`
	RunID         string             `json:"run_id"`
	AsOf          time.Time          `json:"as_of"`
	Packets       []SpecialistPacket `json:"packets"`
}

var financialSpecialistRoles = map[string]bool{
	roles.AccountingReporting:   true,
	roles.FinancialQuality:      true,
	roles.Valuation:             true,
	roles.EconomicsTransmission: true,
	roles.MarketBehavior:        true,
	roles.EvidenceCritic:        true,
}

func BuildSpecialistPackets(packet Packet, objectives map[string]string) (SpecialistPacketSet, error) {
	if err := Validate(packet); err != nil {
		return SpecialistPacketSet{}, err
	}
	roleIDs := make([]string, 0, len(financialSpecialistRoles))
	for roleID := range financialSpecialistRoles {
		roleIDs = append(roleIDs, roleID)
	}
	sort.Strings(roleIDs)
	result := SpecialistPacketSet{
		SchemaVersion: SpecialistPacketSchemaV1, RunID: packet.RunID, AsOf: packet.AsOf,
	}
	for _, roleID := range roleIDs {
		objective := objectives[roleID]
		if objective == "" {
			objective = "Evaluate only the role-authorized financial evidence and deterministic receipts."
		}
		specialist := SpecialistPacket{
			SchemaVersion: SpecialistPacketSchemaV1, PacketID: packet.PacketID + ":" + roleID,
			RunID: packet.RunID, RoleID: roleID, Objective: objective, AsOf: packet.AsOf,
			Availability: AvailabilityReady,
		}
		switch roleID {
		case roles.AccountingReporting:
			specialist.MetricRefs = filterMetrics(packet.Model.Metrics, "accounting.", "financial.")
		case roles.FinancialQuality:
			specialist.MetricRefs = filterMetrics(packet.Model.Metrics, "financial.")
			specialist.RelationRefs = append([]RelationReference(nil), packet.Model.Relations...)
		case roles.Valuation:
			specialist.MetricRefs = filterMetrics(packet.Model.Metrics, "valuation.", "financial.")
			specialist.RelationRefs = append([]RelationReference(nil), packet.Model.Relations...)
		case roles.EconomicsTransmission:
			specialist.MetricRefs = filterMetrics(packet.Model.Metrics, "economics.", "financial.")
		case roles.MarketBehavior:
			specialist.MetricRefs = filterMetrics(packet.Model.Metrics, "market.")
		case roles.EvidenceCritic:
			// The critic receives independent, value-free receipt and evidence references.
			specialist.MetricRefs = append([]MetricReference(nil), packet.Model.Metrics...)
			specialist.RelationRefs = append([]RelationReference(nil), packet.Model.Relations...)
			specialist.ReceiptRefs = receiptReferences(packet.Receipts)
		}
		if roleID != roles.EvidenceCritic {
			specialist.ReceiptRefs = receiptReferencesForMetrics(packet.Receipts, specialist.MetricRefs)
		}
		specialist.Evidence = evidenceForReceiptReferences(specialist.ReceiptRefs, packet.AsOf)
		if len(specialist.MetricRefs) == 0 && len(specialist.ReceiptRefs) == 0 {
			specialist.Availability = AvailabilityNotApplicable
			specialist.Limitations = []string{"No role-authorized financial metric is available for this request."}
		}
		result.Packets = append(result.Packets, specialist)
	}
	if err := ValidateSpecialistPacketSet(result); err != nil {
		return SpecialistPacketSet{}, err
	}
	return result, nil
}

func ValidateSpecialistPacketSet(set SpecialistPacketSet) error {
	if set.SchemaVersion != SpecialistPacketSchemaV1 || set.RunID == "" || set.AsOf.IsZero() {
		return errors.New("specialist packet set envelope is invalid")
	}
	seen := make(map[string]bool)
	for _, packet := range set.Packets {
		if packet.SchemaVersion != SpecialistPacketSchemaV1 || packet.PacketID == "" ||
			packet.RunID != set.RunID || packet.AsOf != set.AsOf || !financialSpecialistRoles[packet.RoleID] ||
			packet.Objective == "" || seen[packet.RoleID] {
			return fmt.Errorf("invalid specialist packet %q", packet.PacketID)
		}
		seen[packet.RoleID] = true
		switch packet.Availability {
		case AvailabilityReady, AvailabilityMissingData, AvailabilityNotApplicable, AvailabilityDisagreement:
		default:
			return fmt.Errorf("invalid availability %q", packet.Availability)
		}
		if packet.Availability == AvailabilityMissingData && len(packet.MissingEvidence) == 0 {
			return errors.New("missing-data packet must identify missing evidence")
		}
		if packet.Availability == AvailabilityDisagreement && len(packet.Conflicts) == 0 {
			return errors.New("disagreement packet must identify conflicts")
		}
		receiptIDs := make(map[string]bool)
		for _, receipt := range packet.ReceiptRefs {
			if receipt.ReceiptID == "" || receipt.OperationID == "" || receipt.FormulaVersion == "" ||
				receipt.InputSHA == "" || receipt.ReceiptSHA == "" || len(receipt.Outputs) == 0 ||
				receiptIDs[receipt.ReceiptID] || !validReceiptStatus(receipt.Status) {
				return fmt.Errorf("invalid receipt reference %q", receipt.ReceiptID)
			}
			receiptIDs[receipt.ReceiptID] = true
			outputIDs := make(map[string]bool)
			for _, output := range receipt.Outputs {
				if output.OutputID == "" || output.Unit == "" || output.Status == "" ||
					outputIDs[output.OutputID] {
					return fmt.Errorf("invalid output reference in receipt %q", receipt.ReceiptID)
				}
				outputIDs[output.OutputID] = true
			}
		}
	}
	if len(seen) != len(financialSpecialistRoles) {
		return errors.New("specialist packet set does not cover all governed roles")
	}
	return nil
}

func validReceiptStatus(status contracts.ReceiptStatus) bool {
	switch status {
	case contracts.ReceiptSuccess, contracts.ReceiptPartial, contracts.ReceiptRefused,
		contracts.ReceiptInvalid, contracts.ReceiptNonConvergent:
		return true
	default:
		return false
	}
}

type ProofRecord struct {
	ReferenceID    string                 `json:"reference_id"`
	Kind           string                 `json:"kind"`
	Source         *contracts.EvidenceRef `json:"source,omitempty"`
	ReceiptID      string                 `json:"receipt_id,omitempty"`
	Period         string                 `json:"period,omitempty"`
	FormulaVersion string                 `json:"formula_version,omitempty"`
	Assumptions    []string               `json:"assumptions,omitempty"`
	Applicability  string                 `json:"applicability"`
	Limitations    []string               `json:"limitations,omitempty"`
}

type ProofDrawer struct {
	SchemaVersion string        `json:"schema_version"`
	RunID         string        `json:"run_id"`
	AsOf          time.Time     `json:"as_of"`
	Records       []ProofRecord `json:"records"`
}

func BuildProofDrawer(packetSet SpecialistPacketSet) (ProofDrawer, error) {
	if err := ValidateSpecialistPacketSet(packetSet); err != nil {
		return ProofDrawer{}, err
	}
	drawer := ProofDrawer{
		SchemaVersion: "signalforge/financial-proof-drawer/v1",
		RunID:         packetSet.RunID, AsOf: packetSet.AsOf,
	}
	seen := make(map[string]bool)
	for _, packet := range packetSet.Packets {
		for _, evidence := range packet.Evidence {
			key := "evidence:" + evidence.EvidenceID
			if seen[key] {
				continue
			}
			copy := evidence
			drawer.Records = append(drawer.Records, ProofRecord{
				ReferenceID: key, Kind: "evidence", Source: &copy,
				Applicability: string(packet.Availability), Limitations: append([]string(nil), packet.Limitations...),
			})
			seen[key] = true
		}
		for _, receipt := range packet.ReceiptRefs {
			key := "receipt:" + receipt.ReceiptID
			if seen[key] {
				continue
			}
			period := ""
			if len(receipt.Outputs) > 0 {
				period = receipt.Outputs[0].Period
			}
			drawer.Records = append(drawer.Records, ProofRecord{
				ReferenceID: key, Kind: "calculation", ReceiptID: receipt.ReceiptID,
				Period: period, FormulaVersion: receipt.FormulaVersion,
				Assumptions:   append([]string(nil), receipt.Assumptions...),
				Applicability: string(packet.Availability), Limitations: append([]string(nil), packet.Limitations...),
			})
			seen[key] = true
		}
	}
	sort.Slice(drawer.Records, func(i, j int) bool { return drawer.Records[i].ReferenceID < drawer.Records[j].ReferenceID })
	return drawer, nil
}

func filterMetrics(metrics []MetricReference, prefixes ...string) []MetricReference {
	result := make([]MetricReference, 0)
	for _, metric := range metrics {
		for _, prefix := range prefixes {
			if len(metric.MetricID) >= len(prefix) && metric.MetricID[:len(prefix)] == prefix {
				result = append(result, metric)
				break
			}
		}
	}
	return result
}

func receiptReferencesForMetrics(receipts []contracts.CalculationReceipt, metrics []MetricReference) []ReceiptReference {
	allowed := make(map[string]bool)
	for _, metric := range metrics {
		for _, receiptID := range metric.ReceiptRefs {
			allowed[receiptID] = true
		}
	}
	filtered := make([]contracts.CalculationReceipt, 0)
	for _, receipt := range receipts {
		if allowed[receipt.ReceiptID] {
			filtered = append(filtered, receipt)
		}
	}
	return receiptReferences(filtered)
}

func receiptReferences(receipts []contracts.CalculationReceipt) []ReceiptReference {
	result := make([]ReceiptReference, 0, len(receipts))
	for _, receipt := range receipts {
		reference := ReceiptReference{
			ReceiptID: receipt.ReceiptID, OperationID: receipt.OperationID, Status: receipt.Status,
			FormulaVersion: receipt.FormulaVersion, Assumptions: append([]string(nil), receipt.Assumptions...),
			EvidenceRefs: append([]string(nil), receipt.EvidenceRefs...), InputSHA: receipt.InputSHA,
			ReceiptSHA: receipt.ReceiptSHA,
		}
		for _, output := range receipt.Outputs {
			reference.Outputs = append(reference.Outputs, ReceiptOutputReference{
				OutputID: output.OutputID, Unit: output.Quantity.Unit, Currency: output.Quantity.Currency,
				Period: output.Quantity.Period, Status: output.Status,
			})
		}
		result = append(result, reference)
	}
	return result
}

func evidenceForReceiptReferences(receipts []ReceiptReference, asOf time.Time) []contracts.EvidenceRef {
	seen := make(map[string]bool)
	result := make([]contracts.EvidenceRef, 0)
	for _, receipt := range receipts {
		for _, evidenceID := range receipt.EvidenceRefs {
			if seen[evidenceID] {
				continue
			}
			result = append(result, contracts.EvidenceRef{
				EvidenceID: evidenceID, SourceType: "calculation_input",
				Locator: "receipt:" + receipt.ReceiptID, ContentSHA: receipt.InputSHA, AsOf: asOf,
			})
			seen[evidenceID] = true
		}
	}
	return result
}
