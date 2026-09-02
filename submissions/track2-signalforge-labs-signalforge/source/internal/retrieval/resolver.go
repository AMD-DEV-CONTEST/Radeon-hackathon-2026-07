package retrieval

import (
	"errors"
	"net/url"
	"sort"
	"strings"
)

type Resolver struct {
	chunks                 map[string]Chunk
	allowedHosts           []string
	restrictedHostPrefixes map[string][]string
}

func NewResolver(chunks []Chunk) (*Resolver, error) {
	return NewResolverWithAllowedHosts(chunks, []string{"sec.gov", "microsoft.com", "nvidia.com", "cloudfront.net", "q4cdn.com"})
}

func NewResolverWithAllowedHosts(chunks []Chunk, allowedHosts []string) (*Resolver, error) {
	return NewResolverWithPolicy(chunks, allowedHosts, nil)
}

func NewResolverWithPolicy(chunks []Chunk, allowedHosts []string, restrictedHostPrefixes map[string][]string) (*Resolver, error) {
	if len(allowedHosts) == 0 {
		return nil, errors.New("at least one citation host is required")
	}
	normalizedHosts := make([]string, 0, len(allowedHosts))
	for _, host := range allowedHosts {
		host = strings.ToLower(strings.TrimSuffix(strings.TrimSpace(host), "."))
		parsed, err := url.Parse("https://" + host)
		if err != nil || host == "" || parsed.Hostname() != host || parsed.Port() != "" || strings.ContainsAny(host, "/*@") {
			return nil, errors.New("citation host must be a plain DNS suffix")
		}
		normalizedHosts = append(normalizedHosts, host)
	}
	normalizedPrefixes := make(map[string][]string, len(restrictedHostPrefixes))
	for rawHost, prefixes := range restrictedHostPrefixes {
		host := strings.ToLower(strings.TrimSuffix(strings.TrimSpace(rawHost), "."))
		if !allowedEvidenceHost(host, normalizedHosts) || len(prefixes) == 0 {
			return nil, errors.New("restricted citation host must be allowed and have prefixes")
		}
		for _, prefix := range prefixes {
			parsed, err := url.Parse(prefix)
			if err != nil || parsed.Scheme != "https" || parsed.Hostname() != host || parsed.Port() != "" || !strings.HasPrefix(prefix, "https://"+host+"/") {
				return nil, errors.New("restricted citation prefix must be an HTTPS path on its host")
			}
			normalizedPrefixes[host] = append(normalizedPrefixes[host], prefix)
		}
	}
	resolver := &Resolver{
		chunks: make(map[string]Chunk, len(chunks)), allowedHosts: normalizedHosts,
		restrictedHostPrefixes: normalizedPrefixes,
	}
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
	if err != nil || parsed.Scheme != "https" || !allowedEvidenceHost(parsed.Hostname(), resolver.allowedHosts) {
		return OpenTarget{}, errors.New("citation source is not an approved HTTPS evidence host")
	}
	if prefixes := resolver.restrictedHostPrefixes[strings.ToLower(parsed.Hostname())]; len(prefixes) > 0 && !hasAllowedPrefix(parsed.String(), prefixes) {
		return OpenTarget{}, errors.New("citation source is outside the issuer-bound path")
	}
	return OpenTarget{SourceURI: parsed.String(), Locator: chunk.Locator, Page: chunk.Page}, nil
}

func hasAllowedPrefix(uri string, prefixes []string) bool {
	for _, prefix := range prefixes {
		if strings.HasPrefix(uri, prefix) {
			return true
		}
	}
	return false
}

func allowedEvidenceHost(host string, allowedHosts []string) bool {
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	for _, suffix := range allowedHosts {
		if host == suffix || strings.HasSuffix(host, "."+suffix) {
			return true
		}
	}
	return false
}
