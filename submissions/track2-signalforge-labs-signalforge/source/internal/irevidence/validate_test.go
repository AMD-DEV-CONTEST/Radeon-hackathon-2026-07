package irevidence

import (
	"path/filepath"
	"testing"
	"time"
)

func TestSourceMapAndAuthorityPolicy(t *testing.T) {
	sourceMap, err := LoadSourceMap(filepath.Join("..", "..", "configs", "sources", "investor-relations.json"))
	if err != nil {
		t.Fatal(err)
	}
	document := validDocument()
	if err := ValidateDocument(document, sourceMap); err != nil {
		t.Fatal(err)
	}
	asOf := time.Date(2025, 8, 1, 0, 0, 0, 0, time.UTC)
	if !CanSupport(document, ClaimAuditedFinancialFact, asOf) {
		t.Fatal("audited SEC evidence should support an audited fact")
	}
	if !CanSupport(document, ClaimGovernance, asOf) {
		t.Fatal("a tier A filing may support a governance claim")
	}
}

func TestGoldenInvestorRelationsManifestIsBoundedAndValid(t *testing.T) {
	sourceMap, err := LoadSourceMap(filepath.Join("..", "..", "configs", "sources", "investor-relations.json"))
	if err != nil {
		t.Fatal(err)
	}
	manifest, err := LoadDocumentManifest(filepath.Join("..", "..", "fixtures", "investor-relations", "document-manifest.json"), sourceMap)
	if err != nil {
		t.Fatal(err)
	}
	if len(manifest.Documents) != 7 {
		t.Fatalf("expected seven bounded golden documents, got %d", len(manifest.Documents))
	}
	tiers := make(map[string]bool)
	companies := make(map[string]bool)
	for _, document := range manifest.Documents {
		tiers[document.AuthorityTier] = true
		companies[document.CompanyID] = true
	}
	for _, tier := range []string{"A", "B", "C", "D"} {
		if !tiers[tier] {
			t.Fatalf("golden manifest is missing authority tier %s", tier)
		}
	}
	if !companies["microsoft"] || !companies["nvidia"] {
		t.Fatal("golden manifest must cover both companies")
	}
}

func TestDocumentFailsClosedForUntrustedOrFutureEvidence(t *testing.T) {
	sourceMap, err := LoadSourceMap(filepath.Join("..", "..", "configs", "sources", "investor-relations.json"))
	if err != nil {
		t.Fatal(err)
	}
	document := validDocument()
	document.SourceURI = "https://example.com/copied-report.pdf"
	if ValidateDocument(document, sourceMap) == nil {
		t.Fatal("an untrusted source must fail validation")
	}
	document = validDocument()
	if CanSupport(document, ClaimRegulatoryFact, time.Date(2025, 7, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("future evidence must not support a claim")
	}
}

func TestSupersededAndPromotionalEvidenceCannotBecomeFinancialTruth(t *testing.T) {
	sourceMap, err := LoadSourceMap(filepath.Join("..", "..", "configs", "sources", "investor-relations.json"))
	if err != nil {
		t.Fatal(err)
	}
	document := validDocument()
	superseded := time.Date(2025, 8, 5, 0, 0, 0, 0, time.UTC)
	document.SupersededAt = &superseded
	if CanSupport(document, ClaimRegulatoryFact, time.Date(2025, 8, 6, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("superseded evidence must not represent the current state")
	}

	document = validDocument()
	document.DocumentType = "corporate_profile"
	document.AuthorityTier = "E"
	document.Audited = false
	document.FiledWithSEC = false
	document.Promotional = true
	if err := ValidateDocument(document, sourceMap); err != nil {
		t.Fatal(err)
	}
	if CanSupport(document, ClaimIssuerReportedResult, time.Date(2025, 8, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("promotional context must not support a reported financial result")
	}
	if !CanSupport(document, ClaimBusinessContext, time.Date(2025, 8, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatal("promotional material may support clearly labeled business context")
	}
}

func validDocument() Document {
	return Document{
		SchemaVersion: DocumentSchemaV1,
		DocumentID:    "microsoft-2025-10k",
		CompanyID:     "microsoft",
		Title:         "Microsoft 2025 Annual Report",
		DocumentType:  "annual_report",
		AuthorityTier: "A",
		Issuer:        "Microsoft Corporation",
		SourceURI:     "https://www.microsoft.com/en-us/Investor/annual-reports.aspx",
		CanonicalURI:  "https://www.microsoft.com/en-us/Investor/annual-reports.aspx",
		DiscoveryURI:  "https://www.microsoft.com/en-us/investor/default",
		MediaType:     "text/html",
		Language:      "en",
		PublishedAt:   time.Date(2025, 7, 30, 0, 0, 0, 0, time.UTC),
		AvailableAt:   time.Date(2025, 7, 30, 0, 0, 0, 0, time.UTC),
		RetrievedAt:   time.Date(2025, 8, 1, 0, 0, 0, 0, time.UTC),
		Audited:       true,
		FiledWithSEC:  true,
		ContentSHA256: "564154a15ac28c0f7f72f304ae26b74c29cfca9f3eafe8d59595776769d621ca",
		RightsClass:   "reference_only",
		ParserVersion: "html/v1",
	}
}
