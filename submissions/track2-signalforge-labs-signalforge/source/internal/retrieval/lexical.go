package retrieval

import (
	"errors"
	"math"
	"regexp"
	"sort"
	"strings"
)

var tokenPattern = regexp.MustCompile(`[\p{L}\p{N}]+`)

var financialQueryExpansions = []struct {
	phrases []string
	terms   []string
}{
	{phrases: []string{"not yet recognized", "contracted revenue", "revenue backlog"}, terms: []string{"remaining", "performance", "obligations", "unearned"}},
	{phrases: []string{"geographic exposure", "geographical exposure", "country exposure"}, terms: []string{"international", "foreign", "currency", "exchange", "export", "controls", "supply", "chain", "concentrated"}},
	{phrases: []string{"capital commitment", "infrastructure commitment"}, terms: []string{"capital", "expenditures", "purchase", "commitments", "contractual", "obligations"}},
	{phrases: []string{"customer concentration"}, terms: []string{"customer", "represented", "revenue", "concentration"}},
}

type LexicalIndex struct {
	chunks        []Chunk
	frequencies   []map[string]int
	docFrequency  map[string]int
	lengths       []int
	averageLength float64
	k1            float64
	b             float64
}

func NewLexicalIndex(chunks []Chunk) (*LexicalIndex, error) {
	if len(chunks) == 0 {
		return nil, errors.New("at least one chunk is required")
	}
	index := &LexicalIndex{chunks: append([]Chunk(nil), chunks...), docFrequency: make(map[string]int), k1: 1.2, b: 0.75}
	seenIDs := make(map[string]struct{}, len(chunks))
	for _, chunk := range chunks {
		if err := ValidateChunk(chunk); err != nil {
			return nil, err
		}
		if _, duplicate := seenIDs[chunk.ChunkID]; duplicate {
			return nil, errors.New("duplicate chunk ID")
		}
		seenIDs[chunk.ChunkID] = struct{}{}
		frequency := frequencies(tokenize(chunk.Section + " " + chunk.Text))
		index.frequencies = append(index.frequencies, frequency)
		length := 0
		for term, count := range frequency {
			length += count
			index.docFrequency[term]++
		}
		index.lengths = append(index.lengths, length)
		index.averageLength += float64(length)
	}
	index.averageLength /= float64(len(chunks))
	return index, nil
}

func (index *LexicalIndex) Search(query Query) ([]Hit, error) {
	if err := ValidateQuery(query); err != nil {
		return nil, err
	}
	terms := expandedQueryTerms(query.Text)
	hits := make([]Hit, 0, len(index.chunks))
	for position, chunk := range index.chunks {
		if !eligible(chunk, query) {
			continue
		}
		score := 0.0
		for _, term := range terms {
			tf := index.frequencies[position][term]
			if tf == 0 {
				continue
			}
			df := index.docFrequency[term]
			idf := math.Log(1 + (float64(len(index.chunks)-df)+0.5)/(float64(df)+0.5))
			normalized := float64(tf) + index.k1*(1-index.b+index.b*float64(index.lengths[position])/index.averageLength)
			score += idf * (float64(tf) * (index.k1 + 1)) / normalized
		}
		if score > 0 {
			hits = append(hits, Hit{Chunk: chunk, Score: score, Method: "bm25/v1"})
		}
	}
	sortHits(hits)
	if len(hits) > query.TopK {
		hits = hits[:query.TopK]
	}
	for index := range hits {
		hits[index].Rank = index + 1
	}
	return hits, nil
}

func expandedQueryTerms(text string) []string {
	terms := tokenize(text)
	lower := strings.ToLower(text)
	seen := make(map[string]struct{}, len(terms))
	for _, term := range terms {
		seen[term] = struct{}{}
	}
	for _, expansion := range financialQueryExpansions {
		matched := false
		for _, phrase := range expansion.phrases {
			if strings.Contains(lower, phrase) {
				matched = true
				break
			}
		}
		if !matched {
			continue
		}
		for _, term := range expansion.terms {
			if _, exists := seen[term]; exists {
				continue
			}
			terms = append(terms, term)
			seen[term] = struct{}{}
		}
	}
	return terms
}

func tokenize(text string) []string {
	matches := tokenPattern.FindAllString(strings.ToLower(text), -1)
	result := make([]string, 0, len(matches))
	for _, match := range matches {
		if len(match) > 1 {
			result = append(result, match)
		}
	}
	return result
}

func frequencies(tokens []string) map[string]int {
	result := make(map[string]int)
	for _, token := range tokens {
		result[token]++
	}
	return result
}

func sortHits(hits []Hit) {
	sort.Slice(hits, func(left, right int) bool {
		if hits[left].Score == hits[right].Score {
			return hits[left].Chunk.ChunkID < hits[right].Chunk.ChunkID
		}
		return hits[left].Score > hits[right].Score
	})
}
