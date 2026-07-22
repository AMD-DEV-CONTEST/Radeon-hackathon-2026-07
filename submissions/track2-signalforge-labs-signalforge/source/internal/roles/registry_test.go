package roles

import "testing"

func TestDefaultRegistryContainsElevenLogicalRoles(t *testing.T) {
	registry := DefaultRegistry()
	all := registry.List()
	if len(all) != 11 {
		t.Fatalf("expected 11 roles, got %d", len(all))
	}
	counts := map[Class]int{}
	for _, role := range all {
		counts[role.Class]++
	}
	if counts[ClassControl] != 2 || counts[ClassContext] != 6 || counts[ClassReview] != 2 || counts[ClassSynthesis] != 1 {
		t.Fatalf("unexpected role classes: %#v", counts)
	}
}

func TestOnlyFinalAnalystCanReleaseFinalAnswer(t *testing.T) {
	for _, role := range DefaultRegistry().List() {
		for _, artifact := range role.Permissions.Release {
			if artifact == "FinalAnswer" && role.ID != FinalResearchAnalyst {
				t.Fatalf("role %s can release FinalAnswer", role.ID)
			}
		}
	}
}

func TestContextRolesCannotWriteMemoryOrReleaseAnswers(t *testing.T) {
	for _, role := range DefaultRegistry().List() {
		if role.Class != ClassContext {
			continue
		}
		if len(role.Permissions.Remember) != 0 || len(role.Permissions.Release) != 0 {
			t.Fatalf("context role %s exceeds authority", role.ID)
		}
	}
}

func TestReturnedRoleCannotMutateRegistry(t *testing.T) {
	registry := DefaultRegistry()
	role, _ := registry.Get(Valuation)
	role.AllowedTools[0] = "trading.execute"
	again, _ := registry.Get(Valuation)
	if again.AllowedTools[0] == "trading.execute" {
		t.Fatal("registry leaked mutable role state")
	}
}
