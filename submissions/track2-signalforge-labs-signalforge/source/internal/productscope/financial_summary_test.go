package productscope

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestPublicFinancialSummaryRequiresEveryTechnology20Company(t *testing.T) {
	catalog := validPublicCatalogForSummary(t)
	reports := map[string]CompanyFinancialActivation{}
	for _, company := range catalog.Companies {
		report, err := BuildCompanyFinancialActivation(company.CompanyID, nil, nil, catalog.AsOf, "test-commit")
		if err != nil {
			t.Fatal(err)
		}
		reports[company.CompanyID] = report
	}
	summary, err := BuildPublicFinancialSummary(catalog, reports)
	if err != nil {
		t.Fatal(err)
	}
	if len(summary.Companies) != 20 {
		t.Fatalf("companies = %d, want 20", len(summary.Companies))
	}
	delete(reports, catalog.Companies[0].CompanyID)
	if _, err := BuildPublicFinancialSummary(catalog, reports); err == nil {
		t.Fatal("expected missing company report rejection")
	}
}

func validPublicCatalogForSummary(t *testing.T) PublicCatalog {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join("..", "..", "fixtures", "productscope", "technology20-catalog.json"))
	if err != nil {
		t.Fatal(err)
	}
	var catalog PublicCatalog
	if err := json.Unmarshal(payload, &catalog); err != nil {
		t.Fatal(err)
	}
	return catalog
}
