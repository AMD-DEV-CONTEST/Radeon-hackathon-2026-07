package roles

import "testing"

func TestIRMaterialRoutesToBoundedConsumersAndEvidenceCritic(t *testing.T) {
	for _, test := range []struct {
		documentType string
		requiredRole string
	}{
		{documentType: "earnings_release", requiredRole: AccountingReporting},
		{documentType: "corporate_profile_and_history", requiredRole: BusinessStrategy},
		{documentType: "governance_document", requiredRole: RiskContrarian},
	} {
		consumers := IRConsumerRoles(test.documentType)
		if !contains(consumers, test.requiredRole) || !contains(consumers, EvidenceCritic) {
			t.Fatalf("unexpected consumers for %s: %v", test.documentType, consumers)
		}
	}
	if consumers := IRConsumerRoles("unknown"); consumers != nil {
		t.Fatalf("unknown IR class must fail closed: %v", consumers)
	}
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
