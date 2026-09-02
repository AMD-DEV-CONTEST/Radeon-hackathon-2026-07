package capability

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestFinancialIntelligenceRegistryIsIsolatedAndComplete(t *testing.T) {
	financial := FinancialIntelligenceRegistry().List()
	if len(financial) != 52 {
		t.Fatalf("expected 52 financial-intelligence operations, got %d", len(financial))
	}
	if len(RuntimeRegistry().List()) != len(Tier0Registry().List())+len(financial) {
		t.Fatal("runtime registry does not preserve both isolated catalogs")
	}
	for _, id := range []string{
		"financial.invested_capital",
		"financial.capital_allocation_bridge",
		"financial.roce",
		"valuation.reverse_revenue_growth",
		"valuation.reverse_operating_margin",
		"valuation.enterprise_to_equity_detailed",
		"comparison.peer_statistics",
		"economics.lagged_association",
	} {
		if _, exists := FinancialIntelligenceRegistry().Get(id); !exists {
			t.Fatalf("missing financial-intelligence operation %s", id)
		}
	}
	if Tier0Registry().Authorizes(roles.Valuation, "valuation.reverse_revenue_growth") {
		t.Fatal("frozen Tier0 must not silently absorb Sprint 16B operations")
	}
	if !RuntimeRegistry().Authorizes(roles.Valuation, "valuation.reverse_revenue_growth") {
		t.Fatal("runtime must authorize the new valuation operation")
	}
}
