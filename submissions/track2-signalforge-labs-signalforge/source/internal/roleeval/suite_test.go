package roleeval

import "testing"

func TestHeldOutSuiteCoversEveryRole(t *testing.T) {
	suite, err := LoadSuite("../../fixtures/roles/held-out-v12-cases.json")
	if err != nil {
		t.Fatal(err)
	}
	if len(suite.Cases) != 33 {
		t.Fatalf("cases=%d, want 33", len(suite.Cases))
	}
}
