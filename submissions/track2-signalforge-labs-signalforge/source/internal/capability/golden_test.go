package capability

import (
	"encoding/json"
	"os"
	"testing"
)

type goldenCatalog struct {
	SchemaVersion string       `json:"schema_version"`
	Cases         []goldenCase `json:"cases"`
}

type goldenCase struct {
	OperationID string         `json:"operation_id"`
	CaseID      string         `json:"case_id"`
	Inputs      map[string]any `json:"inputs"`
	Expected    map[string]any `json:"expected"`
}

func TestEveryTier0OperationHasOneGoldenCase(t *testing.T) {
	data, err := os.ReadFile("../../fixtures/tier0-golden-cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var catalog goldenCatalog
	if err := json.Unmarshal(data, &catalog); err != nil {
		t.Fatal(err)
	}
	if catalog.SchemaVersion != "signalforge-golden-cases/v1" {
		t.Fatalf("unexpected schema version %q", catalog.SchemaVersion)
	}
	seen := make(map[string]bool, len(catalog.Cases))
	for _, item := range catalog.Cases {
		if item.OperationID == "" || item.CaseID == "" || len(item.Inputs) == 0 || len(item.Expected) == 0 {
			t.Fatalf("incomplete golden case: %+v", item)
		}
		if seen[item.OperationID] {
			t.Fatalf("duplicate operation golden case %q", item.OperationID)
		}
		if _, ok := Tier0Registry().Get(item.OperationID); !ok {
			t.Fatalf("golden case references unknown operation %q", item.OperationID)
		}
		seen[item.OperationID] = true
	}
	for _, operation := range Tier0Registry().List() {
		if !seen[operation.ID] {
			t.Fatalf("operation %q has no golden case", operation.ID)
		}
	}
}
