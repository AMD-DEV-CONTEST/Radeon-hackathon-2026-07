package numericalcontext

import (
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestRenderReferencesPreservesValidatedDirection(t *testing.T) {
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
	disclosures, err := RenderReferences([]string{context.Relations[0].RelationID}, []*contracts.NumericalContext{&context})
	if err != nil {
		t.Fatal(err)
	}
	if len(disclosures) != 1 || !strings.Contains(disclosures[0], "22.9%") || !strings.Contains(disclosures[0], "2.5%") || !strings.Contains(disclosures[0], "20.4 percentage points") {
		t.Fatalf("unexpected disclosure: %v", disclosures)
	}
	if strings.Contains(disclosures[0], "22.9%, lower than") || strings.Contains(disclosures[0], "2.5%, higher than") {
		t.Fatalf("renderer reversed the validated direction: %s", disclosures[0])
	}
}

func TestRenderReferencesRejectsUnknownID(t *testing.T) {
	if _, err := RenderReferences([]string{"invented"}, nil); err == nil {
		t.Fatal("unknown numerical reference must fail closed")
	}
}

func TestRenderReferencesDeduplicatesIdenticalVariablesAcrossContexts(t *testing.T) {
	asOf := testAsOf()
	first, err := Compile(Options{
		ContextID: "context-1", RunID: "run-1", AsOf: asOf,
		EntityNames: map[string]string{"msft": "Microsoft"},
	}, []contracts.CalculationReceipt{receipt("receipt-msft", "msft", "FY2025", "0.229", asOf)})
	if err != nil {
		t.Fatal(err)
	}
	second := first
	second.ContextID = "context-2"
	disclosures, err := RenderReferences(
		[]string{first.Variables[0].VariableID},
		[]*contracts.NumericalContext{&first, &second},
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(disclosures) != 1 || !strings.Contains(disclosures[0], "22.9%") {
		t.Fatalf("identical cross-context variable was not rendered once: %v", disclosures)
	}
}

func TestRenderReferencesRejectsConflictingVariablesAcrossContexts(t *testing.T) {
	asOf := testAsOf()
	first, err := Compile(Options{
		ContextID: "context-1", RunID: "run-1", AsOf: asOf,
		EntityNames: map[string]string{"msft": "Microsoft"},
	}, []contracts.CalculationReceipt{receipt("receipt-msft", "msft", "FY2025", "0.229", asOf)})
	if err != nil {
		t.Fatal(err)
	}
	second := first
	second.ContextID = "context-2"
	second.Variables = append([]contracts.NumericalVariable(nil), first.Variables...)
	second.Variables[0].Value.Value = "0.230"
	if _, err := RenderReferences(
		[]string{first.Variables[0].VariableID},
		[]*contracts.NumericalContext{&first, &second},
	); err == nil || !strings.Contains(err.Error(), "conflicting numerical variable") {
		t.Fatalf("conflicting cross-context variable did not fail closed: %v", err)
	}
}

func TestRenderIncomparableRelationNamesExactFiscalBoundaries(t *testing.T) {
	asOf := testAsOf()
	context, err := Compile(Options{
		ContextID: "context-1", RunID: "run-1", AsOf: asOf,
		EntityNames: map[string]string{"msft": "MSFT", "nvda": "NVDA"},
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
	disclosures, err := RenderReferences([]string{context.Relations[0].RelationID}, []*contracts.NumericalContext{&context})
	if err != nil {
		t.Fatal(err)
	}
	if len(disclosures) != 1 || !strings.Contains(disclosures[0], "were not compared") || !strings.Contains(disclosures[0], "2025-06-30") || !strings.Contains(disclosures[0], "2025-01-26") {
		t.Fatalf("incomparable disclosure hid exact period identity: %v", disclosures)
	}
}

func TestRenderVariableDoesNotDuplicateExactDateRangeLabel(t *testing.T) {
	start := time.Date(2024, 11, 30, 0, 0, 0, 0, time.UTC)
	end := time.Date(2025, 11, 28, 0, 0, 0, 0, time.UTC)
	variable := contracts.NumericalVariable{
		VariableID:  "variable-adbe-fcf",
		EntityID:    "sec-cik:0000796343",
		EntityLabel: "ADBE",
		MetricID:    "financial.free_cash_flow.free_cash_flow",
		Value: contracts.Quantity{
			Value: "9850000000", Unit: "currency", Currency: "USD",
		},
		Period:      "2024-11-30/2025-11-28",
		PeriodBasis: contracts.PeriodBasisFiscalExact,
		PeriodStart: &start,
		PeriodEnd:   &end,
	}

	rendered := renderVariable(variable)

	if strings.Count(rendered, "2024-11-30") != 1 ||
		strings.Count(rendered, "2025-11-28") != 1 ||
		strings.Contains(rendered, "2024-11-30/2025-11-28") {
		t.Fatalf("exact period was duplicated: %q", rendered)
	}
	if !strings.Contains(rendered, "2024-11-30 to 2025-11-28") {
		t.Fatalf("exact period boundaries were not retained: %q", rendered)
	}
}

func TestRenderPeerMultipleUsesTimesNotPercent(t *testing.T) {
	asOf := testAsOf()
	msft := receipt("receipt-msft-multiple", "msft", "FY2025", "29.4934", asOf)
	msft.OperationID = "valuation.peer_multiple"
	msft.Outputs[0].OutputID = "multiple"
	nvda := receipt("receipt-nvda-multiple", "nvda", "FY2025", "69.1429", asOf)
	nvda.OperationID = "valuation.peer_multiple"
	nvda.Outputs[0].OutputID = "multiple"
	context, err := Compile(Options{
		ContextID: "context-multiple", RunID: "run-multiple", AsOf: asOf,
		EntityNames: map[string]string{"msft": "MSFT", "nvda": "NVDA"},
	}, []contracts.CalculationReceipt{msft, nvda})
	if err != nil {
		t.Fatal(err)
	}
	disclosures, err := RenderReferences([]string{context.Relations[0].RelationID}, []*contracts.NumericalContext{&context})
	if err != nil {
		t.Fatal(err)
	}
	if len(disclosures) != 1 || !strings.Contains(disclosures[0], "29.49x") || !strings.Contains(disclosures[0], "69.14x") || !strings.Contains(disclosures[0], "39.65x") {
		t.Fatalf("peer multiple was not rendered in times: %v", disclosures)
	}
	if strings.Contains(disclosures[0], "%") {
		t.Fatalf("peer multiple was incorrectly rendered as percent: %s", disclosures[0])
	}
}
