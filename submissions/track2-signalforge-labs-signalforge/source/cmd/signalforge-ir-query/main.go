package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/irevidence"
	"github.com/rvbernucci/signalforge/internal/retrieval"
)

type contextEvidence struct {
	ChunkID        string               `json:"chunk_id"`
	ProjectionText string               `json:"projection_text"`
	AuthorityTier  string               `json:"authority_tier"`
	DocumentType   string               `json:"document_type"`
	Citation       retrieval.Citation   `json:"citation"`
	OpenTarget     retrieval.OpenTarget `json:"open_target"`
}

func main() {
	registryPath := flag.String("registry", "configs/sources/investor-relations-20.json", "IR source registry")
	chunksPath := flag.String("chunks", "", "citation chunk JSONL")
	projectionsPath := flag.String("projections", "", "numerically silent projection JSONL")
	companyID := flag.String("company", "", "exact sec-cik company ID")
	queryText := flag.String("query", "", "retrieval query")
	asOfText := flag.String("as-of", "", "RFC3339 point-in-time boundary")
	documentTypes := flag.String("document-types", "", "optional comma-separated document classes")
	topK := flag.Int("top-k", 5, "maximum evidence count")
	evaluationOnly := flag.Bool("evaluation-only", false, "allow quarantined pending-rights corpus")
	flag.Parse()
	if *chunksPath == "" || *projectionsPath == "" || *companyID == "" || strings.TrimSpace(*queryText) == "" || *asOfText == "" {
		fatal(fmt.Errorf("chunks, projections, company, query, and as-of are required"))
	}
	asOf, err := time.Parse(time.RFC3339, *asOfText)
	if err != nil {
		fatal(err)
	}
	registry, err := irevidence.LoadSourceRegistryV2(*registryPath)
	if err != nil {
		fatal(err)
	}
	policy, err := registry.CitationPolicy([]string{*companyID})
	if err != nil {
		fatal(err)
	}
	for _, source := range registry.Sources {
		if source.CompanyID == *companyID && strings.HasSuffix(source.RightsClass, "pending_review") && !*evaluationOnly {
			fatal(fmt.Errorf("source rights are pending; product retrieval is quarantined"))
		}
	}
	chunks, err := retrieval.LoadChunksJSONL(*chunksPath)
	if err != nil {
		fatal(err)
	}
	projections, err := irevidence.LoadSemanticProjectionsJSONL(*projectionsPath)
	if err != nil {
		fatal(err)
	}
	index, err := retrieval.NewLexicalIndex(chunks)
	if err != nil {
		fatal(err)
	}
	resolver, err := retrieval.NewResolverWithPolicy(chunks, policy.AllowedHosts, policy.RestrictedHostPrefixes)
	if err != nil {
		fatal(err)
	}
	query := retrieval.Query{Text: *queryText, AsOf: asOf, CompanyIDs: []string{*companyID}, TopK: *topK}
	if value := strings.TrimSpace(*documentTypes); value != "" {
		for _, item := range strings.Split(value, ",") {
			if item = strings.TrimSpace(item); item != "" {
				query.DocumentTypes = append(query.DocumentTypes, item)
			}
		}
	}
	hits, err := index.Search(query)
	if err != nil {
		fatal(err)
	}
	output := make([]contextEvidence, 0, len(hits))
	for _, hit := range hits {
		projection, ok := projections[hit.Chunk.ChunkID]
		if !ok || projection.SourceContentSHA256 != hit.Chunk.ContentSHA256 {
			fatal(fmt.Errorf("projection does not resolve to chunk %q", hit.Chunk.ChunkID))
		}
		citation, err := resolver.Resolve(hit.Chunk.ChunkID, asOf.Unix())
		if err != nil {
			fatal(err)
		}
		target, err := resolver.OpenTarget(hit.Chunk.ChunkID, asOf.Unix())
		if err != nil {
			fatal(err)
		}
		output = append(output, contextEvidence{ChunkID: hit.Chunk.ChunkID, ProjectionText: projection.Text, AuthorityTier: hit.Chunk.AuthorityTier, DocumentType: hit.Chunk.DocumentType, Citation: citation, OpenTarget: target})
	}
	encoded, err := json.MarshalIndent(map[string]any{
		"schema_version":  "signalforge/ir-context-evidence/v1",
		"company_id":      *companyID,
		"as_of":           asOf,
		"evaluation_only": *evaluationOnly,
		"evidence":        output,
	}, "", "  ")
	if err != nil {
		fatal(err)
	}
	fmt.Println(string(encoded))
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
