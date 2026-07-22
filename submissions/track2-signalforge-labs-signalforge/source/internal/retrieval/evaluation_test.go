package retrieval

import (
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"testing"
)

func TestGoldenEvaluationLoadsAndBM25IsMeasured(t *testing.T) {
	eval, chunks, err := LoadEvalSet(filepath.Join("..", "..", "fixtures", "retrieval", "golden-eval.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(chunks) != 25 || len(eval.Questions) != 17 {
		t.Fatalf("unexpected frozen population: chunks=%d questions=%d", len(chunks), len(eval.Questions))
	}
	index, err := NewLexicalIndex(chunks)
	if err != nil {
		t.Fatal(err)
	}
	results := make(map[string][]Hit)
	for _, question := range eval.Questions {
		results[question.QuestionID], err = index.Search(Query{
			Text: question.Text, AsOf: eval.AsOf, CompanyIDs: question.CompanyIDs, TopK: question.TopK,
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	metrics, err := Measure(eval, results)
	if err != nil {
		t.Fatal(err)
	}
	if metrics.CompleteEvidenceRate != 1 || metrics.CitationCorrectness != 1 {
		t.Fatalf("unexpected BM25 baseline: %+v", metrics)
	}
}

func TestContextCompilerDiversityDedupConflictAndBudget(t *testing.T) {
	_, chunks, err := LoadEvalSet(filepath.Join("..", "..", "fixtures", "retrieval", "golden-eval.json"))
	if err != nil {
		t.Fatal(err)
	}
	byID := make(map[string]Chunk)
	for _, chunk := range chunks {
		byID[chunk.ChunkID] = chunk
	}
	conflict := byID["msft-cloud-margin"]
	conflict.ChunkID = "msft-cloud-margin-conflict"
	conflict.ClaimValue = "efficiency_outpaced_infrastructure"
	conflict.Text = "A later interpretation attributes the margin movement primarily to efficiency."
	conflict.ContentSHA256 = hashText(conflict.Text)
	hits := []Hit{
		{Chunk: byID["msft-cloud-margin"], Score: 1, Rank: 1},
		{Chunk: conflict, Score: .99, Rank: 2},
		{Chunk: byID["nvda-gross-margin"], Score: .98, Rank: 3},
		{Chunk: byID["msft-cloud-margin"], Score: .97, Rank: 4},
	}
	compiled, err := CompileEvidence(hits, ContextPolicy{TokenBudget: 180, MinimumDocuments: 2, MinimumCompanies: 2})
	if err != nil {
		t.Fatal(err)
	}
	if len(compiled.Hits) != 3 || len(compiled.Conflicts) != 1 || compiled.Conflicts[0] != "msft.cloud_margin_driver.fy2025" {
		t.Fatalf("unexpected compiled evidence: %+v", compiled)
	}
	if compiled.EstimatedTokens > 180 {
		t.Fatal("compiled evidence exceeded token budget")
	}
}

func hashText(text string) string {
	digest := sha256.Sum256([]byte(text))
	return hex.EncodeToString(digest[:])
}
