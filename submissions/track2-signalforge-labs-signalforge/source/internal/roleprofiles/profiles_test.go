package roleprofiles

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/evidencefabric"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestDefaultRegistryCoversEveryRoleAndPreservesBoundaries(t *testing.T) {
	registry := DefaultRegistry()
	if got, want := len(registry.List()), len(roles.DefaultRegistry().List()); got != want {
		t.Fatalf("profile coverage got %d want %d", got, want)
	}
	for _, roleID := range []string{
		roles.RequestInterpreter,
		roles.ResearchOrchestrator,
		roles.FinalResearchAnalyst,
	} {
		profile, ok := registry.Get(roleID)
		if !ok || profile.Mode != evidencefabric.RetrievalNone {
			t.Fatalf("role %q must not retrieve: %+v", roleID, profile)
		}
	}
	for _, roleID := range []string{
		roles.BusinessStrategy,
		roles.AccountingReporting,
		roles.EconomicsTransmission,
		roles.RiskContrarian,
	} {
		profile, ok := registry.Get(roleID)
		if !ok || profile.HyDE != evidencefabric.HyDEConditional ||
			profile.Mode != evidencefabric.RetrievalHybrid {
			t.Fatalf("role %q has unexpected HyDE policy: %+v", roleID, profile)
		}
	}
}

func TestProfilesNeverAuthorizeRestrictedMaterial(t *testing.T) {
	for _, profile := range DefaultRegistry().List() {
		for _, rights := range profile.AllowedRights {
			if rights == evidencefabric.RightsRestricted || rights == evidencefabric.RightsQuarantined {
				t.Fatalf("profile %q authorizes %q", profile.ProfileID, rights)
			}
		}
	}
}

func TestUnknownAndOverprivilegedProfilesFail(t *testing.T) {
	profile, _ := DefaultRegistry().Get(roles.BusinessStrategy)
	profile.RoleID = "unknown/v1"
	if _, err := NewRegistry([]evidencefabric.RetrievalProfile{profile}); err == nil {
		t.Fatal("expected unknown role rejection")
	}
	profile, _ = DefaultRegistry().Get(roles.BusinessStrategy)
	profile.ToolAllowlist = append(profile.ToolAllowlist, "market.write")
	if _, err := NewRegistry([]evidencefabric.RetrievalProfile{profile}); err == nil {
		t.Fatal("expected tool authority rejection")
	}
}
