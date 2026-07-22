package retrieval

import (
	"errors"
	"net/url"
	"sort"
	"strings"
)

type Resolver struct {
	chunks map[string]Chunk
}

func NewResolver(chunks []Chunk) (*Resolver, error) {
	resolver := &Resolver{chunks: make(map[string]Chunk, len(chunks))}
	for _, chunk := range chunks {
		if err := ValidateChunk(chunk); err != nil {
			return nil, err
		}
		if _, duplicate := resolver.chunks[chunk.ChunkID]; duplicate {
			return nil, errors.New("duplicate chunk ID")
		}
		resolver.chunks[chunk.ChunkID] = chunk
	}
	return resolver, nil
}

func (resolver *Resolver) Resolve(chunkID string, asOfLimit int64) (Citation, error) {
	chunk, ok := resolver.chunks[chunkID]
	if !ok {
		return Citation{}, errors.New("chunk citation does not resolve")
	}
	if asOfLimit > 0 && chunk.AvailableAt.Unix() > asOfLimit {
		return Citation{}, errors.New("chunk citation is not available at requested time")
	}
	return chunk.Citation(), nil
}

func (resolver *Resolver) ResolveAll(chunkIDs []string, asOfLimit int64) ([]Citation, error) {
	seen := make(map[string]struct{})
	result := make([]Citation, 0, len(chunkIDs))
	for _, chunkID := range chunkIDs {
		if _, duplicate := seen[chunkID]; duplicate {
			continue
		}
		citation, err := resolver.Resolve(chunkID, asOfLimit)
		if err != nil {
			return nil, err
		}
		seen[chunkID] = struct{}{}
		result = append(result, citation)
	}
	sort.Slice(result, func(left, right int) bool { return result[left].ChunkID < result[right].ChunkID })
	return result, nil
}

type OpenTarget struct {
	SourceURI string `json:"source_uri"`
	Locator   string `json:"locator"`
	Page      int    `json:"page,omitempty"`
}

func (resolver *Resolver) OpenTarget(chunkID string, asOfLimit int64) (OpenTarget, error) {
	chunk, ok := resolver.chunks[chunkID]
	if !ok {
		return OpenTarget{}, errors.New("chunk citation does not resolve")
	}
	if asOfLimit > 0 && chunk.AvailableAt.Unix() > asOfLimit {
		return OpenTarget{}, errors.New("chunk citation is not available at requested time")
	}
	parsed, err := url.Parse(chunk.SourceURI)
	if err != nil || parsed.Scheme != "https" || !allowedEvidenceHost(parsed.Hostname()) {
		return OpenTarget{}, errors.New("citation source is not an approved HTTPS evidence host")
	}
	return OpenTarget{SourceURI: parsed.String(), Locator: chunk.Locator, Page: chunk.Page}, nil
}

func allowedEvidenceHost(host string) bool {
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	for _, suffix := range []string{"sec.gov", "microsoft.com", "nvidia.com", "cloudfront.net", "q4cdn.com"} {
		if host == suffix || strings.HasSuffix(host, "."+suffix) {
			return true
		}
	}
	return false
}
