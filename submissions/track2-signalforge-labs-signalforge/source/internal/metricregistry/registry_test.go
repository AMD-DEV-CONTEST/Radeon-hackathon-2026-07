package metricregistry

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/capability"
)

func TestDefaultRegistryCoversEveryRuntimeOperation(t *testing.T) {
	registry := Default()
	operations := capability.RuntimeRegistry().List()
	if got := len(registry.ListActive()); got != len(operations) {
		t.Fatalf("active definitions = %d, operations = %d", got, len(operations))
	}
	for _, operation := range operations {
		definition, ok := registry.Active(operation.ID)
		if !ok {
			t.Fatalf("missing active definition for %s", operation.ID)
		}
		if definition.Version != operation.FormulaVersion {
			t.Fatalf("%s definition version %s != operation version %s", operation.ID, definition.Version, operation.FormulaVersion)
		}
		if len(definition.Inputs) != len(operation.RequiredInputs) {
			t.Fatalf("%s input definition count mismatch", operation.ID)
		}
	}
}

func TestRegistryReturnsDefensiveCopies(t *testing.T) {
	registry := Default()
	definition, _ := registry.Active("financial.free_cash_flow")
	definition.Inputs[0].Name = "mutated"
	definition.Applicability.ExcludedProfiles[0] = ProfileUtility

	again, _ := registry.Active("financial.free_cash_flow")
	if again.Inputs[0].Name == "mutated" || again.Applicability.ExcludedProfiles[0] == ProfileUtility {
		t.Fatal("registry leaked mutable state")
	}
}

func TestApplicabilityFailsClosedForStructurallyDifferentSectors(t *testing.T) {
	registry := Default()
	if allowed, reason := registry.Applies("financial.roic_proxy", ProfileBank); allowed || reason != "not_applicable" {
		t.Fatalf("bank ROIC proxy = %v, %s", allowed, reason)
	}
	if allowed, reason := registry.Applies("financial.roic_proxy", ProfileOperatingCompany); !allowed || reason != "applicable" {
		t.Fatalf("operating-company ROIC proxy = %v, %s", allowed, reason)
	}
	if allowed, reason := registry.Applies("unknown.metric", ProfileOperatingCompany); allowed || reason != "definition_missing" {
		t.Fatalf("missing metric = %v, %s", allowed, reason)
	}
}

func TestIssuerNonGAAPRequiresReconciliation(t *testing.T) {
	definition := Default().ListActive()[0]
	definition.MetricID = "financial.non_gaap_test"
	definition.GAAPStatus = IssuerNonGAAP
	definition.ReconciliationRequired = false
	if _, err := New([]Definition{definition}); err == nil {
		t.Fatal("unreconciled issuer non-GAAP definition must fail")
	}
}

func TestAdvancedMetricInputKindsMatchRuntimeContracts(t *testing.T) {
	expected := map[string]string{
		"mid_year": "boolean", "lag": "count", "minimum_sample": "count",
		"days_sales_outstanding": "days", "days_inventory_outstanding": "days", "days_payables_outstanding": "days",
		"years": "years", "peer_values": "series", "return_on_capital": "ratio",
		"roic": "ratio", "wacc": "ratio", "levered_beta": "ratio", "unlevered_beta": "ratio",
	}
	for name, kind := range expected {
		if actual := quantityKind(name); actual != kind {
			t.Errorf("quantityKind(%q) = %q, want %q", name, actual, kind)
		}
	}
}

func BenchmarkDefaultRegistryLookup(b *testing.B) {
	registry := Default()
	b.ReportAllocs()
	for range b.N {
		definition, ok := registry.Active("valuation.multistage_dcf_perpetuity")
		if !ok || definition.Version != "1.0.0" {
			b.Fatal("metric definition unavailable")
		}
	}
}
