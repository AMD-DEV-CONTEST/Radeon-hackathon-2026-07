package retrieval

import (
	"errors"
	"sort"
)

type ContextPolicy struct {
	TokenBudget      int `json:"token_budget"`
	MinimumDocuments int `json:"minimum_documents"`
	MinimumCompanies int `json:"minimum_companies"`
}

type CompiledEvidence struct {
	Hits            []Hit      `json:"hits"`
	Citations       []Citation `json:"citations"`
	Conflicts       []string   `json:"conflicts,omitempty"`
	Dropped         []string   `json:"dropped_for_budget,omitempty"`
	EstimatedTokens int        `json:"estimated_tokens"`
}

func CompileEvidence(hits []Hit, policy ContextPolicy) (CompiledEvidence, error) {
	if len(hits) == 0 || policy.TokenBudget <= 0 {
		return CompiledEvidence{}, errors.New("hits and positive token budget are required")
	}
	for _, hit := range hits {
		if err := ValidateChunk(hit.Chunk); err != nil {
			return CompiledEvidence{}, err
		}
	}
	ordered := append([]Hit(nil), hits...)
	sort.SliceStable(ordered, func(i, j int) bool {
		if ordered[i].Rank > 0 && ordered[j].Rank > 0 && ordered[i].Rank != ordered[j].Rank {
			return ordered[i].Rank < ordered[j].Rank
		}
		return ordered[i].Score > ordered[j].Score
	})

	result := CompiledEvidence{}
	seenContent := make(map[string]bool)
	selectedDocuments := make(map[string]bool)
	selectedCompanies := make(map[string]bool)
	deferred := make([]Hit, 0, len(ordered))
	for _, hit := range ordered {
		if seenContent[hit.Chunk.ContentSHA256] {
			continue
		}
		if (!selectedDocuments[hit.Chunk.DocumentID] && len(selectedDocuments) < policy.MinimumDocuments) ||
			(!selectedCompanies[hit.Chunk.CompanyID] && len(selectedCompanies) < policy.MinimumCompanies) {
			if !appendWithinBudget(&result, hit, policy.TokenBudget) {
				result.Dropped = append(result.Dropped, hit.Chunk.ChunkID)
				continue
			}
			seenContent[hit.Chunk.ContentSHA256] = true
			selectedDocuments[hit.Chunk.DocumentID] = true
			selectedCompanies[hit.Chunk.CompanyID] = true
			continue
		}
		deferred = append(deferred, hit)
	}
	for _, hit := range deferred {
		if seenContent[hit.Chunk.ContentSHA256] {
			continue
		}
		if !appendWithinBudget(&result, hit, policy.TokenBudget) {
			result.Dropped = append(result.Dropped, hit.Chunk.ChunkID)
			continue
		}
		seenContent[hit.Chunk.ContentSHA256] = true
	}

	claims := make(map[string]map[string]bool)
	for _, hit := range result.Hits {
		if hit.Chunk.ClaimKey == "" || hit.Chunk.ClaimValue == "" {
			continue
		}
		if claims[hit.Chunk.ClaimKey] == nil {
			claims[hit.Chunk.ClaimKey] = make(map[string]bool)
		}
		claims[hit.Chunk.ClaimKey][hit.Chunk.ClaimValue] = true
	}
	for key, values := range claims {
		if len(values) > 1 {
			result.Conflicts = append(result.Conflicts, key)
		}
	}
	sort.Strings(result.Conflicts)
	sort.Strings(result.Dropped)
	return result, nil
}

func appendWithinBudget(result *CompiledEvidence, hit Hit, budget int) bool {
	if result.EstimatedTokens+hit.Chunk.TokenEstimate > budget {
		return false
	}
	result.Hits = append(result.Hits, hit)
	result.Citations = append(result.Citations, hit.Chunk.Citation())
	result.EstimatedTokens += hit.Chunk.TokenEstimate
	return true
}
