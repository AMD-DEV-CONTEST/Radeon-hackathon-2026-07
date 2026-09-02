package financialintelligence

import (
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/metricregistry"
	"github.com/rvbernucci/signalforge/internal/numericalcontext"
)

const SchemaVersion = "signalforge.financial-intelligence-packet/v1"

var canonicalRegistry = metricregistry.Default()

type Options struct {
	PacketID            string
	ContextID           string
	RunID               string
	AsOf                time.Time
	EntityNames         map[string]string
	EntityFiscalPeriods map[string]numericalcontext.FiscalPeriod
	CompanyProfiles     map[string]metricregistry.CompanyProfile
	Tolerance           string
}

type MetricReference struct {
	ReferenceID     string                         `json:"reference_id"`
	EntityID        string                         `json:"entity_id"`
	MetricID        string                         `json:"metric_id"`
	EconomicMeaning string                         `json:"economic_meaning"`
	Period          string                         `json:"period"`
	PeriodBasis     contracts.NumericalPeriodBasis `json:"period_basis"`
	Method          contracts.NormalizationMethod  `json:"method"`
	FormulaVersion  string                         `json:"formula_version"`
	ReceiptRefs     []string                       `json:"receipt_refs"`
	EvidenceRefs    []string                       `json:"evidence_refs"`
	Warnings        []string                       `json:"warnings,omitempty"`
}

type RelationReference struct {
	ReferenceID string                     `json:"reference_id"`
	MetricID    string                     `json:"metric_id"`
	LeftRef     string                     `json:"left_ref"`
	RightRef    string                     `json:"right_ref"`
	Operator    contracts.RelationOperator `json:"operator"`
	Comparable  bool                       `json:"comparable"`
	Warnings    []string                   `json:"warnings,omitempty"`
}

type ModelView struct {
	SchemaVersion string              `json:"schema_version"`
	PacketID      string              `json:"packet_id"`
	RunID         string              `json:"run_id"`
	AsOf          time.Time           `json:"as_of"`
	Metrics       []MetricReference   `json:"metrics"`
	Relations     []RelationReference `json:"relations,omitempty"`
}

type Packet struct {
	SchemaVersion string                         `json:"schema_version"`
	PacketID      string                         `json:"packet_id"`
	RunID         string                         `json:"run_id"`
	AsOf          time.Time                      `json:"as_of"`
	Receipts      []contracts.CalculationReceipt `json:"calculation_receipts"`
	Numerical     contracts.NumericalContext     `json:"numerical_context"`
	Model         ModelView                      `json:"model_view"`
}

func Build(options Options, receipts []contracts.CalculationReceipt) (Packet, error) {
	if options.PacketID == "" || options.ContextID == "" || options.RunID == "" || options.AsOf.IsZero() {
		return Packet{}, errors.New("packet_id, context_id, run_id, and as_of are required")
	}
	if len(receipts) == 0 {
		return Packet{}, errors.New("at least one calculation receipt is required")
	}
	registry := canonicalRegistry
	for _, receipt := range receipts {
		if err := contracts.ValidateCalculationReceipt(receipt); err != nil {
			return Packet{}, fmt.Errorf("receipt %q: %w", receipt.ReceiptID, err)
		}
		definition, exists := registry.Active(receipt.OperationID)
		if !exists || definition.Version != receipt.FormulaVersion {
			return Packet{}, fmt.Errorf("definition_conflict: receipt %q has no matching active definition", receipt.ReceiptID)
		}
		for _, companyID := range receipt.Scope.CompanyIDs {
			profile, exists := options.CompanyProfiles[companyID]
			if !exists {
				return Packet{}, fmt.Errorf("company %q has no applicability profile", companyID)
			}
			if applies, reason := registry.Applies(receipt.OperationID, profile); !applies {
				return Packet{}, fmt.Errorf("%s: %s is unavailable for %s", reason, receipt.OperationID, profile)
			}
		}
	}

	numerical, err := numericalcontext.Compile(numericalcontext.Options{
		ContextID: options.ContextID, RunID: options.RunID, AsOf: options.AsOf,
		EntityNames: options.EntityNames, EntityFiscalPeriods: options.EntityFiscalPeriods,
		Tolerance: options.Tolerance,
	}, receipts)
	if err != nil {
		return Packet{}, err
	}
	model, err := buildModelView(options, numerical, registry)
	if err != nil {
		return Packet{}, err
	}
	packet := Packet{
		SchemaVersion: SchemaVersion, PacketID: options.PacketID, RunID: options.RunID, AsOf: options.AsOf,
		Receipts: append([]contracts.CalculationReceipt(nil), receipts...), Numerical: numerical, Model: model,
	}
	if err := Validate(packet); err != nil {
		return Packet{}, err
	}
	return packet, nil
}

func Validate(packet Packet) error {
	if packet.SchemaVersion != SchemaVersion || packet.PacketID == "" || packet.RunID == "" || packet.AsOf.IsZero() {
		return errors.New("financial-intelligence packet envelope is invalid")
	}
	if packet.Numerical.RunID != packet.RunID || !packet.Numerical.AsOf.Equal(packet.AsOf) {
		return errors.New("numerical context does not match packet envelope")
	}
	if err := contracts.ValidateNumericalContext(packet.Numerical); err != nil {
		return err
	}
	variables := make(map[string]bool, len(packet.Numerical.Variables))
	for _, variable := range packet.Numerical.Variables {
		variables[variable.VariableID] = true
	}
	seen := make(map[string]bool, len(packet.Model.Metrics))
	for _, metric := range packet.Model.Metrics {
		if !variables[metric.ReferenceID] || seen[metric.ReferenceID] || metric.EconomicMeaning == "" || len(metric.ReceiptRefs) == 0 {
			return fmt.Errorf("invalid model metric reference %q", metric.ReferenceID)
		}
		seen[metric.ReferenceID] = true
	}
	for _, relation := range packet.Model.Relations {
		if !variables[relation.LeftRef] || !variables[relation.RightRef] {
			return fmt.Errorf("relation %q references an unavailable metric", relation.ReferenceID)
		}
	}
	return nil
}

func RenderNumericalReferences(packet Packet, references []string) ([]string, error) {
	if err := Validate(packet); err != nil {
		return nil, err
	}
	return numericalcontext.RenderReferences(references, []*contracts.NumericalContext{&packet.Numerical})
}

func buildModelView(options Options, context contracts.NumericalContext, registry metricregistry.Registry) (ModelView, error) {
	view := ModelView{SchemaVersion: SchemaVersion, PacketID: options.PacketID, RunID: options.RunID, AsOf: options.AsOf}
	for _, variable := range context.Variables {
		operationID := operationFromMetricID(variable.MetricID)
		definition, exists := registry.Active(operationID)
		if !exists {
			return ModelView{}, fmt.Errorf("definition missing for %q", operationID)
		}
		view.Metrics = append(view.Metrics, MetricReference{
			ReferenceID: variable.VariableID, EntityID: variable.EntityID, MetricID: variable.MetricID,
			EconomicMeaning: definition.EconomicMeaning, Period: variable.Period, PeriodBasis: variable.PeriodBasis,
			Method: variable.Method, FormulaVersion: variable.FormulaVersion,
			ReceiptRefs: append([]string(nil), variable.ReceiptRefs...), EvidenceRefs: append([]string(nil), variable.EvidenceRefs...), Warnings: append([]string(nil), variable.Warnings...),
		})
	}
	for _, relation := range context.Relations {
		view.Relations = append(view.Relations, RelationReference{
			ReferenceID: relation.RelationID, MetricID: relation.MetricID,
			LeftRef: relation.LeftVariableID, RightRef: relation.RightVariableID,
			Operator: relation.Operator, Comparable: relation.Comparable,
			Warnings: append([]string(nil), relation.Warnings...),
		})
	}
	sort.Slice(view.Metrics, func(i, j int) bool { return view.Metrics[i].ReferenceID < view.Metrics[j].ReferenceID })
	sort.Slice(view.Relations, func(i, j int) bool { return view.Relations[i].ReferenceID < view.Relations[j].ReferenceID })
	return view, nil
}

func operationFromMetricID(metricID string) string {
	last := -1
	for index := len(metricID) - 1; index >= 0; index-- {
		if metricID[index] == '.' {
			last = index
			break
		}
	}
	if last <= 0 {
		return metricID
	}
	return metricID[:last]
}
