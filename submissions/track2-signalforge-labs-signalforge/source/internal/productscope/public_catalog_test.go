package productscope

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestPublicCatalogPreservesActivationBoundary(t *testing.T) {
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "productscope", "technology20-catalog.json"))
	if err != nil {
		t.Fatal(err)
	}
	var catalog PublicCatalog
	if err := json.Unmarshal(payload, &catalog); err != nil {
		t.Fatal(err)
	}
	if err := ValidatePublicCatalog(catalog); err != nil {
		t.Fatal(err)
	}
	if len(catalog.Companies) != 20 || len(catalog.PeerLanes) != 5 {
		t.Fatalf("catalog population = %d companies / %d lanes", len(catalog.Companies), len(catalog.PeerLanes))
	}
	for _, company := range catalog.Companies {
		if company.ResearchEnabled {
			t.Fatalf("data-ready company %q was over-promoted", company.CompanyID)
		}
	}
	for _, lane := range catalog.PeerLanes {
		if lane.Enabled {
			t.Fatalf("unevaluated lane %q was over-promoted", lane.LaneID)
		}
	}
}
