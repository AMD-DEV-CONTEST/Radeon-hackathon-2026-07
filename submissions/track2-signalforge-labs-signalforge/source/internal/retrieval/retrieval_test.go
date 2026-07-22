package retrieval

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
	"time"
)

func fixtureChunk(id, company, section, text string, available time.Time) Chunk {
	document := sha256.Sum256([]byte("document-" + company))
	content := sha256.Sum256([]byte(text))
	return Chunk{
		SchemaVersion: ChunkSchemaV1, ChunkID: id, DocumentID: "document-" + company,
		CompanyID: company, EvidenceType: "regulatory_filing", FilingID: "filing-" + company,
		AccessionNumber: "0000000000-25-000001", FormType: "10-K", DocumentType: "annual_report",
		AuthorityTier: "A", Issuer: company, Language: "en", RightsClass: "reference_only",
		Audited: true, FiledWithSEC: true, PublishedAt: available, Section: section, Locator: "item-" + id, Text: text,
		SourceURI: "https://www.sec.gov/Archives/example", DocumentSHA256: hex.EncodeToString(document[:]),
		ContentSHA256: hex.EncodeToString(content[:]), AvailableAt: available, RetrievedAt: available.Add(time.Hour),
		TokenEstimate: len(text)/4 + 1, ChunkingVersion: "filing-aware/v1",
	}
}

func TestLexicalVectorFusionAndCitations(t *testing.T) {
	asOf := time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC)
	chunks := []Chunk{
		fixtureChunk("msft-risk", "cik:msft", "Risk Factors", "Cloud demand may be affected by customer optimization and infrastructure spending.", asOf.Add(-time.Hour)),
		fixtureChunk("nvda-business", "cik:nvda", "Business", "Data center revenue depends on accelerated computing demand and customer capital investment.", asOf.Add(-time.Hour)),
		fixtureChunk("future", "cik:msft", "Business", "Future unavailable evidence about artificial intelligence spending.", asOf.Add(time.Hour)),
	}
	lexical, err := NewLexicalIndex(chunks)
	if err != nil {
		t.Fatal(err)
	}
	query := Query{Text: "customer infrastructure spending demand", AsOf: asOf, TopK: 3}
	lexicalHits, err := lexical.Search(query)
	if err != nil {
		t.Fatal(err)
	}
	if len(lexicalHits) != 2 || lexicalHits[0].Chunk.ChunkID == "future" {
		t.Fatalf("unexpected lexical hits %+v", lexicalHits)
	}

	vectors := []VectorRecord{{Chunk: chunks[0], Vector: []float32{1, 0}}, {Chunk: chunks[1], Vector: []float32{0.8, 0.2}}, {Chunk: chunks[2], Vector: []float32{1, 0}}}
	vectorIndex, err := NewVectorIndex(vectors)
	if err != nil {
		t.Fatal(err)
	}
	vectorHits, err := vectorIndex.Search(query, []float32{1, 0})
	if err != nil {
		t.Fatal(err)
	}
	fused := ReciprocalRankFusion([][]Hit{lexicalHits, vectorHits}, 2, 60)
	if len(fused) != 2 {
		t.Fatalf("unexpected fused result %+v", fused)
	}
	weighted := WeightedReciprocalRankFusion([][]Hit{lexicalHits, vectorHits}, []float64{2, 1}, 2, 60)
	if len(weighted) != 2 || weighted[0].Method != "rrf/v1" {
		t.Fatalf("unexpected weighted fusion %+v", weighted)
	}
	if WeightedReciprocalRankFusion([][]Hit{lexicalHits}, nil, 2, 60) != nil {
		t.Fatal("mismatched fusion weights must fail closed")
	}

	resolver, err := NewResolver(chunks)
	if err != nil {
		t.Fatal(err)
	}
	citation, err := resolver.Resolve(fused[0].Chunk.ChunkID, asOf.Unix())
	if err != nil || citation.ContentSHA256 == "" || citation.Locator == "" {
		t.Fatalf("invalid citation %+v: %v", citation, err)
	}
	if _, err := resolver.Resolve("future", asOf.Unix()); err == nil {
		t.Fatal("future citation must fail")
	}
}

func TestChunkTamperingFails(t *testing.T) {
	now := time.Now().UTC()
	chunk := fixtureChunk("chunk", "company", "Business", "original", now)
	chunk.Text = "tampered"
	if err := ValidateChunk(chunk); err == nil {
		t.Fatal("tampered chunk must fail")
	}
}

func TestFinancialQueryExpansionUsesConceptsRatherThanFixtureIDs(t *testing.T) {
	terms := frequencies(expandedQueryTerms("How much contracted revenue was not yet recognized?"))
	for _, expected := range []string{"remaining", "performance", "obligations", "unearned"} {
		if terms[expected] != 1 {
			t.Fatalf("missing financial concept expansion %q in %+v", expected, terms)
		}
	}
	if frequencies(expandedQueryTerms("What products does the company sell?"))["obligations"] != 0 {
		t.Fatal("unrelated queries must not receive financial backlog expansion")
	}
}

func FuzzChunkContentHash(f *testing.F) {
	f.Add("evidence")
	f.Fuzz(func(t *testing.T, text string) {
		if text == "" {
			t.Skip()
		}
		chunk := fixtureChunk("chunk", "company", "Business", text, time.Unix(1, 0).UTC())
		if err := ValidateChunk(chunk); err != nil {
			t.Fatal(err)
		}
	})
}
