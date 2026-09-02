package irevidence

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSourceRegistryV2LoadsTwentyIssuerBoundary(t *testing.T) {
	registry, err := LoadSourceRegistryV2(filepath.Join("..", "..", "configs", "sources", "investor-relations-20.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Sources) != 20 {
		t.Fatalf("expected 20 sources, got %d", len(registry.Sources))
	}
	hosts, err := registry.AllowedHosts([]string{"sec-cik:0000320193"})
	if err != nil || len(hosts) != 2 || hosts[0] != "investor.apple.com" || hosts[1] != "www.apple.com" {
		t.Fatalf("unexpected Apple host boundary %v: %v", hosts, err)
	}
	if _, err := registry.AllowedHosts([]string{"sec-cik:9999999999"}); err == nil {
		t.Fatal("unknown issuer must fail closed")
	}
	policy, err := registry.CitationPolicy([]string{"sec-cik:0000002488"})
	if err != nil || len(policy.RestrictedHostPrefixes["d1io3yog0oux5.cloudfront.net"]) != 1 {
		t.Fatalf("unexpected AMD shared-host policy %+v: %v", policy, err)
	}
}

func TestSemanticProjectionLoaderVerifiesHash(t *testing.T) {
	text := "Revenue changed by [FINANCIAL_VALUE_001]."
	digest := sha256.Sum256([]byte(text))
	projection := SemanticProjection{
		SchemaVersion: SemanticProjectionSchemaV1, ProjectionID: "projection-1", ChunkID: "chunk-1",
		DocumentID: "document-1", CompanyID: "sec-cik:0000320193", Text: text,
		SourceContentSHA256: strings.Repeat("a", 64), ProjectionSHA256: hex.EncodeToString(digest[:]),
		ProjectionVersion: "test/v1", NumericSpanCount: 1, NumericReferences: []string{"FINANCIAL_VALUE_001"},
	}
	encoded, _ := json.Marshal(projection)
	path := filepath.Join(t.TempDir(), "projections.jsonl")
	if err := os.WriteFile(path, append(encoded, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadSemanticProjectionsJSONL(path)
	if err != nil || loaded["chunk-1"].Text != text {
		t.Fatalf("valid projection failed: %v", err)
	}
	projection.ProjectionSHA256 = strings.Repeat("0", 64)
	encoded, _ = json.Marshal(projection)
	_ = os.WriteFile(path, append(encoded, '\n'), 0o600)
	if _, err := LoadSemanticProjectionsJSONL(path); err == nil {
		t.Fatal("tampered projection must fail closed")
	}
}
