package evidencefabric

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"unicode"
)

type Resolver struct {
	Sources map[string]PublicSource
	Records []EvidenceRecord
}

func NewResolver(sources []PublicSource, records []EvidenceRecord) (Resolver, error) {
	sourceIndex := make(map[string]PublicSource, len(sources))
	for _, source := range sources {
		if err := source.Validate(); err != nil {
			return Resolver{}, fmt.Errorf("source %q: %w", source.SourceID, err)
		}
		if _, exists := sourceIndex[source.SourceID]; exists {
			return Resolver{}, fmt.Errorf("duplicate source %q", source.SourceID)
		}
		sourceIndex[source.SourceID] = source
	}
	for _, record := range records {
		source, ok := sourceIndex[record.SourceID]
		if !ok {
			return Resolver{}, fmt.Errorf("record %q has unknown source", record.EvidenceID)
		}
		if err := record.Validate(source); err != nil {
			return Resolver{}, fmt.Errorf("record %q: %w", record.EvidenceID, err)
		}
	}
	return Resolver{Sources: sourceIndex, Records: append([]EvidenceRecord(nil), records...)}, nil
}

func (resolver Resolver) Resolve(profile RetrievalProfile, request ContextRequest) (EvidenceBundle, error) {
	if err := profile.Validate(); err != nil {
		return EvidenceBundle{}, err
	}
	if err := request.Validate(profile); err != nil {
		return EvidenceBundle{}, err
	}
	queryTerms := tokenize(request.Query)
	documentFrequency := resolver.documentFrequency(profile, request)
	type scored struct {
		id        string
		score     float64
		authority AuthorityClass
	}
	values := make([]scored, 0)
	for _, record := range resolver.Records {
		if !eligible(profile, request, record) {
			continue
		}
		score := bm25Score(queryTerms, tokenize(record.Text), documentFrequency, len(resolver.Records))
		if score <= 0 {
			continue
		}
		values = append(values, scored{id: record.EvidenceID, score: score, authority: record.Authority})
	}
	sort.Slice(values, func(i, j int) bool {
		if values[i].score != values[j].score {
			return values[i].score > values[j].score
		}
		if values[i].authority != values[j].authority {
			return values[i].authority < values[j].authority
		}
		return values[i].id < values[j].id
	})
	if len(values) > request.MaxCandidates {
		values = values[:request.MaxCandidates]
	}
	candidates := make([]EvidenceCandidate, len(values))
	for index, value := range values {
		candidates[index] = EvidenceCandidate{EvidenceID: value.id, Score: value.score, Rank: index + 1}
	}
	bundle := EvidenceBundle{
		SchemaVersion: SchemaVersion,
		BundleID:      "bundle-" + request.RequestID,
		RequestID:     request.RequestID,
		RunID:         request.RunID,
		RoleID:        request.RoleID,
		AsOf:          request.AsOf,
		Candidates:    candidates,
		Degraded:      profile.Mode != RetrievalHybrid,
	}
	if len(candidates) == 0 {
		bundle.Missing = []string{"no_authorized_point_in_time_candidate"}
	}
	return bundle, nil
}

func (resolver Resolver) Quarantine(evidenceID string) (Resolver, error) {
	result := Resolver{Sources: resolver.Sources, Records: append([]EvidenceRecord(nil), resolver.Records...)}
	for index := range result.Records {
		if result.Records[index].EvidenceID == evidenceID {
			result.Records[index].Lifecycle = "quarantined"
			return result, nil
		}
	}
	return Resolver{}, fmt.Errorf("unknown evidence %q", evidenceID)
}

func (resolver Resolver) Delete(evidenceID string) (Resolver, error) {
	result := Resolver{Sources: resolver.Sources, Records: append([]EvidenceRecord(nil), resolver.Records...)}
	for index := range result.Records {
		if result.Records[index].EvidenceID == evidenceID {
			result.Records[index].Lifecycle = "deleted"
			result.Records[index].Text = ""
			return result, nil
		}
	}
	return Resolver{}, fmt.Errorf("unknown evidence %q", evidenceID)
}

func (resolver Resolver) documentFrequency(profile RetrievalProfile, request ContextRequest) map[string]int {
	result := map[string]int{}
	for _, record := range resolver.Records {
		if !eligible(profile, request, record) {
			continue
		}
		seen := map[string]bool{}
		for _, term := range tokenize(record.Text) {
			if !seen[term] {
				result[term]++
				seen[term] = true
			}
		}
	}
	return result
}

func eligible(profile RetrievalProfile, request ContextRequest, record EvidenceRecord) bool {
	if record.Lifecycle != "active" || record.AvailableAt.After(request.AsOf) {
		return false
	}
	if record.ValidFrom != nil && record.ValidFrom.After(request.AsOf) {
		return false
	}
	if record.ValidTo != nil && !record.ValidTo.After(request.AsOf) {
		return false
	}
	if !containsAuthority(profile.AllowedAuthorities, record.Authority) ||
		!containsRights(profile.AllowedRights, record.Rights) ||
		!contains(profile.AllowedSourceKinds, record.SourceKind) {
		return false
	}
	if len(request.CompanyIDs) > 0 && !contains(request.CompanyIDs, record.CompanyID) {
		return false
	}
	return true
}

func tokenize(value string) []string {
	terms := strings.FieldsFunc(strings.ToLower(value), func(char rune) bool {
		return !unicode.IsLetter(char) && !unicode.IsDigit(char)
	})
	result := make([]string, 0, len(terms))
	for _, term := range terms {
		if len(term) > 1 {
			result = append(result, term)
		}
	}
	return result
}

func bm25Score(query, document []string, documentFrequency map[string]int, documentCount int) float64 {
	if len(query) == 0 || len(document) == 0 || documentCount == 0 {
		return 0
	}
	frequency := map[string]int{}
	for _, term := range document {
		frequency[term]++
	}
	const k1 = 1.2
	const b = 0.75
	averageLength := math.Max(float64(len(document)), 1)
	score := 0.0
	for _, term := range sortedUnique(query) {
		tf := float64(frequency[term])
		if tf == 0 {
			continue
		}
		df := float64(documentFrequency[term])
		idf := math.Log(1 + (float64(documentCount)-df+0.5)/(df+0.5))
		numerator := tf * (k1 + 1)
		denominator := tf + k1*(1-b+b*float64(len(document))/averageLength)
		score += idf * numerator / denominator
	}
	return score
}

func containsAuthority(values []AuthorityClass, target AuthorityClass) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
