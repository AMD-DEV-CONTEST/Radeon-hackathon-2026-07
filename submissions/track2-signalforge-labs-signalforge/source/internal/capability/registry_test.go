package capability

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestTier0RegistryIsUniqueAndComplete(t *testing.T) {
	registry := Tier0Registry()
	operations := registry.List()
	if len(operations) != 28 {
		t.Fatalf("expected 28 Tier 0 operations, got %d", len(operations))
	}
	for _, expected := range []string{
		"accounting.balance_sheet_identity",
		"financial.free_cash_flow",
		"valuation.fcff_dcf",
		"economics.real_rate",
		"market.beta",
		"scenario.sensitivity_matrix",
	} {
		if _, ok := registry.Get(expected); !ok {
			t.Fatalf("missing Tier 0 operation %q", expected)
		}
	}
}

func TestRegistryEnforcesRolePermissions(t *testing.T) {
	registry := Tier0Registry()
	if !registry.Authorizes(roles.Valuation, "valuation.fcff_dcf") {
		t.Fatal("valuation role should be authorized for DCF")
	}
	if registry.Authorizes(roles.MarketBehavior, "valuation.fcff_dcf") {
		t.Fatal("market role must not be authorized for DCF")
	}
	if registry.Authorizes(roles.Valuation, "unknown.operation") {
		t.Fatal("unknown operation must fail closed")
	}
}

func TestReturnedOperationsCannotMutateRegistry(t *testing.T) {
	registry := Tier0Registry()
	operation, _ := registry.Get("valuation.fcff_dcf")
	operation.AllowedRoles[0] = roles.MarketBehavior
	if registry.Authorizes(roles.MarketBehavior, "valuation.fcff_dcf") {
		t.Fatal("registry leaked mutable operation state")
	}
}
