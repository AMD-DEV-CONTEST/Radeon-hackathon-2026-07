package irevidence

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/retrieval"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestProviderReleasesOnlySilentPointInTimeRoleScopedEvidence(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	chunk := irChunk(now)
	projectionText := "Revenue changed by [FINANCIAL_VALUE_001] as management emphasized cloud demand."
	projectionDigest := sha256.Sum256([]byte(projectionText))
	projection := SemanticProjection{
		SchemaVersion:       SemanticProjectionSchemaV1,
		ProjectionID:        "projection-" + chunk.ChunkID,
		ChunkID:             chunk.ChunkID,
		DocumentID:          chunk.DocumentID,
		CompanyID:           chunk.CompanyID,
		Text:                projectionText,
		SourceContentSHA256: chunk.ContentSHA256,
		ProjectionSHA256:    hex.EncodeToString(projectionDigest[:]),
		ProjectionVersion:   "test/v1",
		NumericSpanCount:    1,
		NumericReferences:   []string{"FINANCIAL_VALUE_001"},
	}
	registry := testRegistry()
	if _, err := NewProvider(registry, []retrieval.Chunk{chunk}, map[string]SemanticProjection{chunk.ChunkID: projection}, false); err == nil {
		t.Fatal("pending rights must fail outside private evaluation")
	}
	provider, err := NewProvider(registry, []retrieval.Chunk{chunk}, map[string]SemanticProjection{chunk.ChunkID: projection}, true)
	if err != nil {
		t.Fatal(err)
	}
	request := contracts.ContextRequest{
		SchemaVersion:    contracts.SchemaVersionV1,
		ContextRequestID: "request-1", RunID: "run-1", StepID: "step-1",
		SpecialistRole: roles.FinancialQuality,
		Objective:      "Explain financial quality", ResearchQuestion: "What drove the result?",
		Scope:       contracts.Scope{CompanyIDs: []string{chunk.CompanyID}, AsOf: now.Add(time.Hour)},
		TokenBudget: 1000,
	}
	material, err := provider.Load(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if len(material.Evidence.Items) != 1 || material.Evidence.Items[0].Statement != projectionText {
		t.Fatalf("unexpected material: %+v", material)
	}
	if strings.Contains(material.Evidence.Items[0].Statement, "$12") {
		t.Fatal("exact financial value crossed the silent projection boundary")
	}
	request.Scope.AsOf = now.Add(-time.Hour)
	material, err = provider.Load(context.Background(), request)
	if err != nil || len(material.Evidence.Items) != 0 || len(material.Evidence.Missing) != 1 {
		t.Fatalf("future evidence must be unavailable: %+v, %v", material, err)
	}
}

func irChunk(now time.Time) retrieval.Chunk {
	text := "Revenue was $12 million as management emphasized cloud demand."
	digest := sha256.Sum256([]byte(text))
	return retrieval.Chunk{
		SchemaVersion: retrieval.ChunkSchemaV1,
		ChunkID:       "ir-msft-test", DocumentID: "ir-msft-document", CompanyID: "sec-cik:0000789019",
		EvidenceType: "investor_relations", DocumentType: "earnings_release", AuthorityTier: "B",
		Issuer: "Microsoft Corporation", Language: "en", RightsClass: "reference_only_pending_review",
		PublishedAt: now, Section: "Results", Locator: "html:paragraph=1", Text: text,
		SourceURI:      "https://www.microsoft.com/en-us/investor/earnings/results",
		DocumentSHA256: strings.Repeat("a", 64), ContentSHA256: hex.EncodeToString(digest[:]),
		AvailableAt: now, RetrievedAt: now, TokenEstimate: 20, ChunkingVersion: "test/v1",
	}
}

func testRegistry() SourceRegistryV2 {
	return SourceRegistryV2{
		SchemaVersion: SourceRegistrySchemaV2,
		UniverseID:    "test",
		Sources: []SourceDefinitionV2{{
			CompanyID: "sec-cik:0000789019", CIK: "0000789019", Issuer: "Microsoft Corporation",
			PrimaryTicker: "MSFT", DiscoveryURI: "https://www.microsoft.com/en-us/investor/default",
			AllowedHosts: []string{"microsoft.com"}, RobotsURI: "https://www.microsoft.com/robots.txt",
			RightsClass: "reference_only_pending_review",
		}},
	}
}
