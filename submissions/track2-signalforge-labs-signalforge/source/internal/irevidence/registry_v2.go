package irevidence

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"sort"
	"strings"
)

const SourceRegistrySchemaV2 = "signalforge/investor-relations-source-registry/v2"

type SourceRegistryV2 struct {
	SchemaVersion string               `json:"schema_version"`
	UniverseID    string               `json:"universe_id"`
	Sources       []SourceDefinitionV2 `json:"sources"`
}

type SourceDefinitionV2 struct {
	CompanyID              string              `json:"company_id"`
	CIK                    string              `json:"cik"`
	Issuer                 string              `json:"issuer"`
	PrimaryTicker          string              `json:"primary_ticker"`
	DiscoveryURI           string              `json:"discovery_uri"`
	AllowedHosts           []string            `json:"allowed_hosts"`
	RestrictedHostPrefixes map[string][]string `json:"restricted_host_prefixes,omitempty"`
	RobotsURI              string              `json:"robots_uri"`
	RightsClass            string              `json:"rights_class"`
}

type CitationPolicy struct {
	AllowedHosts           []string
	RestrictedHostPrefixes map[string][]string
}

func LoadSourceRegistryV2(path string) (SourceRegistryV2, error) {
	encoded, err := os.ReadFile(path)
	if err != nil {
		return SourceRegistryV2{}, err
	}
	var registry SourceRegistryV2
	if err := json.Unmarshal(encoded, &registry); err != nil {
		return SourceRegistryV2{}, err
	}
	if err := ValidateSourceRegistryV2(registry); err != nil {
		return SourceRegistryV2{}, err
	}
	return registry, nil
}

func ValidateSourceRegistryV2(registry SourceRegistryV2) error {
	if registry.SchemaVersion != SourceRegistrySchemaV2 || strings.TrimSpace(registry.UniverseID) == "" || len(registry.Sources) == 0 {
		return errors.New("supported schema version, universe, and sources are required")
	}
	companies := make(map[string]struct{}, len(registry.Sources))
	for _, source := range registry.Sources {
		if source.CompanyID != "sec-cik:"+source.CIK || !cikPattern.MatchString(source.CIK) || source.Issuer == "" || source.PrimaryTicker == "" {
			return errors.New("each source requires a consistent SEC identity, issuer, and ticker")
		}
		if _, duplicate := companies[source.CompanyID]; duplicate {
			return fmt.Errorf("duplicate company_id %q", source.CompanyID)
		}
		companies[source.CompanyID] = struct{}{}
		if source.RightsClass == "" || len(source.AllowedHosts) == 0 || !allowedURI(source.DiscoveryURI, source.AllowedHosts) || !allowedURI(source.RobotsURI, source.AllowedHosts) {
			return fmt.Errorf("source %q has an incomplete rights or URI boundary", source.CompanyID)
		}
		for _, host := range source.AllowedHosts {
			parsed, err := url.Parse("https://" + host)
			if err != nil || parsed.Hostname() != strings.ToLower(host) || parsed.Port() != "" || strings.ContainsAny(host, "/*@") {
				return fmt.Errorf("source %q has an invalid host", source.CompanyID)
			}
		}
		for host, prefixes := range source.RestrictedHostPrefixes {
			if !containsExact(source.AllowedHosts, host) || len(prefixes) == 0 {
				return fmt.Errorf("source %q has an invalid restricted host policy", source.CompanyID)
			}
			for _, prefix := range prefixes {
				parsed, err := url.Parse(prefix)
				if err != nil || parsed.Scheme != "https" || parsed.Hostname() != host || parsed.Port() != "" || !strings.HasPrefix(prefix, "https://"+host+"/") {
					return fmt.Errorf("source %q has an invalid restricted URI prefix", source.CompanyID)
				}
			}
		}
	}
	return nil
}

func containsExact(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func (registry SourceRegistryV2) AllowedHosts(companyIDs []string) ([]string, error) {
	policy, err := registry.CitationPolicy(companyIDs)
	if err != nil {
		return nil, err
	}
	return policy.AllowedHosts, nil
}

func (registry SourceRegistryV2) CitationPolicy(companyIDs []string) (CitationPolicy, error) {
	requested := make(map[string]struct{}, len(companyIDs))
	for _, companyID := range companyIDs {
		requested[companyID] = struct{}{}
	}
	hosts := make(map[string]struct{})
	restricted := make(map[string][]string)
	found := make(map[string]struct{})
	for _, source := range registry.Sources {
		if len(requested) > 0 {
			if _, ok := requested[source.CompanyID]; !ok {
				continue
			}
		}
		found[source.CompanyID] = struct{}{}
		for _, host := range source.AllowedHosts {
			hosts[host] = struct{}{}
		}
		for host, prefixes := range source.RestrictedHostPrefixes {
			restricted[host] = append(restricted[host], prefixes...)
		}
	}
	if len(requested) > 0 && len(found) != len(requested) {
		return CitationPolicy{}, errors.New("one or more companies are absent from the IR source registry")
	}
	result := make([]string, 0, len(hosts))
	for host := range hosts {
		result = append(result, host)
	}
	sort.Strings(result)
	for host := range restricted {
		sort.Strings(restricted[host])
		restricted[host] = compactStrings(restricted[host])
	}
	return CitationPolicy{AllowedHosts: result, RestrictedHostPrefixes: restricted}, nil
}

func compactStrings(values []string) []string {
	if len(values) < 2 {
		return values
	}
	result := values[:1]
	for _, value := range values[1:] {
		if value != result[len(result)-1] {
			result = append(result, value)
		}
	}
	return result
}
