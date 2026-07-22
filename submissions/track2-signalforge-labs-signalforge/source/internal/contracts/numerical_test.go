package contracts

import (
	"strings"
	"testing"
	"time"
)

func TestNumericalContextAcceptsRecomputedRelation(t *testing.T) {
	context := numericalFixture()
	if err := ValidateNumericalContext(context); err != nil {
		t.Fatalf("valid numerical context rejected: %v", err)
	}
}

func TestNumericalContextRejectsReversedDirection(t *testing.T) {
	context := numericalFixture()
	context.Relations[0].Operator = RelationLessThan
	err := ValidateNumericalContext(context)
	if err == nil || !strings.Contains(err.Error(), "contradicts recomputed operator") {
		t.Fatalf("reversed direction must fail, got %v", err)
	}
}

func TestNumericalContextRejectsFutureLeakageAndDuplicateIDs(t *testing.T) {
	context := numericalFixture()
	context.Variables[0].AsOf = context.AsOf.Add(time.Second)
	if err := ValidateNumericalContext(context); err == nil || !strings.Contains(err.Error(), "leaks information") {
		t.Fatalf("future leakage must fail, got %v", err)
	}

	context = numericalFixture()
	context.Variables[1].VariableID = context.Variables[0].VariableID
	if err := ValidateNumericalContext(context); err == nil || !strings.Contains(err.Error(), "duplicates") {
		t.Fatalf("duplicate variable IDs must fail, got %v", err)
	}
}

func TestNumericalContextRejectsUnknownAndIncompatibleReferences(t *testing.T) {
	context := numericalFixture()
	context.Relations[0].RightVariableID = "unknown"
	if err := ValidateNumericalContext(context); err == nil || !strings.Contains(err.Error(), "unknown variable") {
		t.Fatalf("unknown relation reference must fail, got %v", err)
	}

	context = numericalFixture()
	context.Variables[1].Value.Unit = "percent"
	if err := ValidateNumericalContext(context); err == nil || !strings.Contains(err.Error(), "compatible variables") {
		t.Fatalf("a directional relation across units must fail, got %v", err)
	}

	context = numericalFixture()
	context.Variables[1].Value.Currency = "EUR"
	if err := ValidateNumericalContext(context); err == nil || !strings.Contains(err.Error(), "compatible variables") {
		t.Fatalf("a directional relation across currencies must fail, got %v", err)
	}

	context = numericalFixture()
	context.Variables[1].Period = "FY2024"
	context.Variables[1].ComparisonKey = "nominal:FY2024"
	if err := ValidateNumericalContext(context); err == nil || !strings.Contains(err.Error(), "compatible variables") {
		t.Fatalf("a directional relation across periods must fail, got %v", err)
	}
}

func TestNumericalContextAppliesTolerance(t *testing.T) {
	context := numericalFixture()
	context.Variables[0].Value.Value = "0.229"
	context.Variables[1].Value.Value = "0.2285"
	context.Relations[0].Difference.Value = "0.0005"
	context.Relations[0].Tolerance = "0.001"
	context.Relations[0].Operator = RelationEqual
	if err := ValidateNumericalContext(context); err != nil {
		t.Fatalf("difference inside tolerance must be equal: %v", err)
	}
}

func numericalFixture() NumericalContext {
	asOf := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	variable := func(id, entity, value, currency string) NumericalVariable {
		valueAsOf := asOf
		return NumericalVariable{
			VariableID: id, EntityID: entity, MetricID: "financial.capex_intensity.capex_intensity",
			Period: "FY2025", PeriodBasis: PeriodBasisNominalLabel, ComparisonKey: "nominal:FY2025",
			ValueKind: NumericalDerivedView,
			Value:     Quantity{Value: value, Unit: "ratio", Currency: currency, AsOf: &valueAsOf},
			Method:    NormalizationCommonSize, FormulaVersion: "ratio-decimal/v1",
			EvidenceRefs: []string{"evidence-" + entity}, ReceiptRefs: []string{"receipt-" + entity}, AsOf: asOf,
		}
	}
	return NumericalContext{
		SchemaVersion: SchemaVersionV1, ContextID: "numerical-context", RunID: "run-1",
		Version: NumericalContextVersionV1, AsOf: asOf,
		Variables: []NumericalVariable{variable("left", "msft", "0.229", ""), variable("right", "nvda", "0.025", "")},
		Relations: []NumericalRelation{{
			RelationID: "relation-1", MetricID: "financial.capex_intensity.capex_intensity",
			LeftVariableID: "left", Operator: RelationGreaterThan, RightVariableID: "right",
			Difference: &Quantity{Value: "0.204", Unit: "ratio"}, Tolerance: "0",
			Comparable: true, FormulaVersion: "numerical-relation-decimal/v1",
			EvidenceRefs: []string{"evidence-msft", "evidence-nvda"}, ReceiptRefs: []string{"receipt-msft", "receipt-nvda"},
		}},
	}
}
