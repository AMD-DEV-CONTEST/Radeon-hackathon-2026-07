package numericalcontext

import (
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestCompileProducesDeterministicComparableRelation(t *testing.T) {
	asOf := testAsOf()
	context, err := Compile(Options{
		ContextID: "context-1", RunID: "run-1", AsOf: asOf,
		EntityNames: map[string]string{"msft": "Microsoft", "nvda": "NVIDIA"},
	}, []contracts.CalculationReceipt{
		receipt("receipt-msft", "msft", "FY2025", "0.229", asOf),
		receipt("receipt-nvda", "nvda", "FY2025", "0.025", asOf),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(context.Variables) != 2 || len(context.Relations) != 1 {
		t.Fatalf("unexpected context cardinality: variables=%d relations=%d", len(context.Variables), len(context.Relations))
	}
	relation := context.Relations[0]
	values := map[string]string{}
	for _, variable := range context.Variables {
		values[variable.VariableID] = variable.Value.Value
	}
	wantOperator := contracts.RelationGreaterThan
	if values[relation.LeftVariableID] == "0.025" {
		wantOperator = contracts.RelationLessThan
	}
	if relation.Operator != wantOperator || !relation.Comparable || relation.Difference.Value != "0.204" {
		t.Fatalf("unexpected deterministic relation: %+v", relation)
	}
	if context.Variables[0].VariableID >= context.Variables[1].VariableID {
		t.Fatal("variables must be deterministically sorted")
	}
}

func TestCompileEmitsIncomparablePeriodWarning(t *testing.T) {
	asOf := testAsOf()
	context, err := Compile(Options{ContextID: "context-1", RunID: "run-1", AsOf: asOf}, []contracts.CalculationReceipt{
		receipt("receipt-msft", "msft", "FY2025", "0.229", asOf),
		receipt("receipt-nvda", "nvda", "FY2024", "0.025", asOf),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(context.Relations) != 1 || context.Relations[0].Comparable || context.Relations[0].Operator != contracts.RelationIncomparable || len(context.Relations[0].Warnings) == 0 {
		t.Fatalf("period mismatch must produce an explicit incomparable relation: %+v", context.Relations)
	}
}

func TestCompileRejectsSameFiscalLabelWithDifferentExactBoundaries(t *testing.T) {
	asOf := testAsOf()
	context, err := Compile(Options{
		ContextID: "context-1", RunID: "run-1", AsOf: asOf,
		EntityNames: map[string]string{"msft": "Microsoft", "nvda": "NVIDIA"},
		EntityFiscalPeriods: map[string]FiscalPeriod{
			"msft": {Start: time.Date(2024, 7, 1, 0, 0, 0, 0, time.UTC), End: time.Date(2025, 6, 30, 0, 0, 0, 0, time.UTC)},
			"nvda": {Start: time.Date(2024, 1, 29, 0, 0, 0, 0, time.UTC), End: time.Date(2025, 1, 26, 0, 0, 0, 0, time.UTC)},
		},
	}, []contracts.CalculationReceipt{
		receipt("receipt-msft", "msft", "FY2025", "0.229", asOf),
		receipt("receipt-nvda", "nvda", "FY2025", "0.025", asOf),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(context.Relations) != 1 || context.Relations[0].Comparable || context.Relations[0].Operator != contracts.RelationIncomparable {
		t.Fatalf("same nominal label concealed non-concurrent fiscal periods: %+v", context.Relations)
	}
	warning := context.Relations[0].Warnings[0]
	for _, expected := range []string{"2024-07-01", "2025-06-30", "2024-01-29", "2025-01-26"} {
		if !strings.Contains(warning, expected) {
			t.Fatalf("warning omitted exact boundary %s: %s", expected, warning)
		}
	}
}

func TestCompileKeepsDCFComparableByAnalysisAsOf(t *testing.T) {
	asOf := testAsOf()
	left := receipt("receipt-msft", "msft", "FY2026", "100", asOf)
	right := receipt("receipt-nvda", "nvda", "FY2026", "90", asOf)
	left.OperationID, right.OperationID = "valuation.fcff_dcf", "valuation.fcff_dcf"
	left.Outputs[0].OutputID, right.Outputs[0].OutputID = "enterprise_value", "enterprise_value"
	context, err := Compile(Options{ContextID: "context-1", RunID: "run-1", AsOf: asOf}, []contracts.CalculationReceipt{left, right})
	if err != nil {
		t.Fatal(err)
	}
	if len(context.Relations) != 1 || !context.Relations[0].Comparable {
		t.Fatalf("same-as-of valuation outputs should remain comparable: %+v", context.Relations)
	}
}

func TestCompileRejectsFutureReceiptAndSkipsOperationalOutputs(t *testing.T) {
	asOf := testAsOf()
	future := receipt("future", "msft", "FY2025", "0.229", asOf.Add(time.Second))
	if _, err := Compile(Options{ContextID: "context-1", RunID: "run-1", AsOf: asOf}, []contracts.CalculationReceipt{future}); err == nil {
		t.Fatal("future receipt must fail")
	}

	operational := receipt("count", "msft", "FY2025", "2", asOf)
	operational.Outputs[0].Quantity.Unit = "count"
	if _, err := Compile(Options{ContextID: "context-1", RunID: "run-1", AsOf: asOf}, []contracts.CalculationReceipt{operational}); err == nil {
		t.Fatal("a context containing only operational outputs must fail closed")
	}
}

func TestDecisionOutputPolicyKeepsDCFEnterpriseValueOnly(t *testing.T) {
	derived := func(id string) contracts.ReceiptOutput {
		return contracts.ReceiptOutput{OutputID: id, Quantity: contracts.Quantity{Value: "100", Unit: "currency"}, Status: "derived"}
	}
	if !eligibleOutput("valuation.fcff_dcf", derived("enterprise_value")) {
		t.Fatal("DCF enterprise value must remain eligible for deterministic presentation")
	}
	for _, outputID := range []string{"explicit_present_value", "terminal_present_value", "present_values.0", "4"} {
		if eligibleOutput("valuation.fcff_dcf", derived(outputID)) {
			t.Fatalf("DCF intermediate %q crossed the presentation boundary", outputID)
		}
	}
}

func receipt(id, entity, period, value string, asOf time.Time) contracts.CalculationReceipt {
	return contracts.CalculationReceipt{
		SchemaVersion: contracts.SchemaVersionV1, ReceiptID: id, RequestID: "request-" + id,
		EngineID: "financial", EngineVersion: "0.1.0", OperationID: "financial.capex_intensity",
		FormulaVersion: "ratio-decimal/v1", Scope: contracts.Scope{CompanyIDs: []string{entity}, AsOf: asOf},
		Status: contracts.ReceiptSuccess,
		NormalizedInputs: []contracts.EngineInput{{
			InputID: "revenue", Quantity: contracts.Quantity{Value: "100", Unit: "currency", Currency: "USD", Period: period},
			Status: "normalized", EvidenceRefs: []string{"evidence-" + entity},
		}},
		Outputs:          []contracts.ReceiptOutput{{OutputID: "capex_intensity", Quantity: contracts.Quantity{Value: value, Unit: "ratio"}, Status: "derived"}},
		InvariantResults: []contracts.InvariantResult{{InvariantID: "tier0_registry_match", Passed: true}},
		TolerancePolicy:  "ratio-decimal/v1", EvidenceRefs: []string{"evidence-" + entity}, SourceAsOf: asOf,
		CodeCommit: "test", InputSHA: "input", ReceiptSHA: "receipt", GeneratedAt: asOf,
	}
}

func testAsOf() time.Time {
	return time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
}
