package irevidence

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
)

var cikPattern = regexp.MustCompile(`^[0-9]{10}$`)

func LoadSourceMap(path string) (SourceMap, error) {
	encoded, err := os.ReadFile(path)
	if err != nil {
		return SourceMap{}, err
	}
	var sourceMap SourceMap
	if err := json.Unmarshal(encoded, &sourceMap); err != nil {
		return SourceMap{}, err
	}
	if err := ValidateSourceMap(sourceMap); err != nil {
		return SourceMap{}, err
	}
	return sourceMap, nil
}

func LoadDocumentManifest(path string, sourceMap SourceMap) (DocumentManifest, error) {
	encoded, err := os.ReadFile(path)
	if err != nil {
		return DocumentManifest{}, err
	}
	var manifest DocumentManifest
	if err := json.Unmarshal(encoded, &manifest); err != nil {
		return DocumentManifest{}, err
	}
	if manifest.SchemaVersion != "signalforge/investor-relations-document-manifest/v1" || len(manifest.Documents) == 0 {
		return DocumentManifest{}, errors.New("supported schema_version and at least one document are required")
	}
	seen := make(map[string]struct{}, len(manifest.Documents))
	for _, document := range manifest.Documents {
		if _, duplicate := seen[document.DocumentID]; duplicate {
			return DocumentManifest{}, fmt.Errorf("duplicate document_id %q", document.DocumentID)
		}
		seen[document.DocumentID] = struct{}{}
		if err := ValidateDocument(document, sourceMap); err != nil {
			return DocumentManifest{}, fmt.Errorf("document %q: %w", document.DocumentID, err)
		}
	}
	return manifest, nil
}

func ValidateSourceMap(sourceMap SourceMap) error {
	if sourceMap.SchemaVersion != SourceMapSchemaV1 || len(sourceMap.Sources) == 0 {
		return errors.New("supported schema_version and at least one source are required")
	}
	seen := make(map[string]struct{}, len(sourceMap.Sources))
	for _, source := range sourceMap.Sources {
		if source.CompanyID == "" || source.Issuer == "" || !cikPattern.MatchString(source.CIK) {
			return errors.New("each source requires company_id, issuer, and a ten-digit CIK")
		}
		if _, exists := seen[source.CompanyID]; exists {
			return fmt.Errorf("duplicate company_id %q", source.CompanyID)
		}
		seen[source.CompanyID] = struct{}{}
		if len(source.AllowedHosts) == 0 || len(source.MaterialClasses) == 0 {
			return fmt.Errorf("source %q requires hosts and material classes", source.CompanyID)
		}
		if !allowedURI(source.DiscoveryURI, source.AllowedHosts) {
			return fmt.Errorf("source %q has an untrusted discovery URI", source.CompanyID)
		}
	}
	return nil
}

func ValidateDocument(document Document, sourceMap SourceMap) error {
	if document.SchemaVersion != DocumentSchemaV1 {
		return fmt.Errorf("unsupported schema version %q", document.SchemaVersion)
	}
	for name, value := range map[string]string{
		"document_id": document.DocumentID, "company_id": document.CompanyID, "title": document.Title,
		"document_type": document.DocumentType, "authority_tier": document.AuthorityTier, "issuer": document.Issuer,
		"source_uri": document.SourceURI, "canonical_uri": document.CanonicalURI, "discovery_uri": document.DiscoveryURI,
		"media_type": document.MediaType, "language": document.Language, "content_sha256": document.ContentSHA256,
		"rights_class": document.RightsClass, "parser_version": document.ParserVersion,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("%s is required", name)
		}
	}
	if document.PublishedAt.IsZero() || document.AvailableAt.IsZero() || document.RetrievedAt.IsZero() {
		return errors.New("published_at, available_at, and retrieved_at are required")
	}
	if document.AvailableAt.Before(document.PublishedAt) || document.RetrievedAt.Before(document.AvailableAt) {
		return errors.New("document timestamps must follow publication, availability, and retrieval order")
	}
	if document.SupersededAt != nil && document.SupersededAt.Before(document.AvailableAt) {
		return errors.New("superseded_at cannot precede available_at")
	}
	if !validSHA(document.ContentSHA256) {
		return errors.New("content_sha256 must be a lowercase SHA-256")
	}
	if !member([]string{"A", "B", "C", "D", "E"}, document.AuthorityTier) {
		return errors.New("authority_tier must be A, B, C, D, or E")
	}
	source, ok := sourceFor(sourceMap, document.CompanyID)
	if !ok {
		return errors.New("company is absent from the source map")
	}
	if document.Issuer != source.Issuer || !member(source.MaterialClasses, document.DocumentType) {
		return errors.New("issuer or document_type does not match the source map")
	}
	for _, candidate := range []string{document.SourceURI, document.CanonicalURI, document.DiscoveryURI} {
		if !allowedURI(candidate, source.AllowedHosts) {
			return errors.New("document URI is outside the company allowlist")
		}
	}
	if document.AuthorityTier == "E" && !document.Promotional {
		return errors.New("tier E material must be explicitly marked promotional")
	}
	if document.Promotional && member([]string{"A", "B"}, document.AuthorityTier) {
		return errors.New("promotional material cannot claim tier A or B authority")
	}
	return nil
}

func CurrentAsOf(document Document, asOf time.Time) bool {
	if asOf.IsZero() || document.AvailableAt.After(asOf) {
		return false
	}
	return document.SupersededAt == nil || document.SupersededAt.After(asOf)
}

func CanSupport(document Document, claim ClaimClass, asOf time.Time) bool {
	if !CurrentAsOf(document, asOf) || document.Promotional {
		return claim == ClaimBusinessContext && CurrentAsOf(document, asOf)
	}
	switch claim {
	case ClaimRegulatoryFact:
		return document.AuthorityTier == "A" && document.FiledWithSEC
	case ClaimAuditedFinancialFact:
		return document.AuthorityTier == "A" && document.FiledWithSEC && document.Audited
	case ClaimIssuerReportedResult:
		return member([]string{"A", "B"}, document.AuthorityTier)
	case ClaimManagementInterpretation:
		return member([]string{"A", "B", "C"}, document.AuthorityTier)
	case ClaimGovernance:
		return document.AuthorityTier == "A" || document.AuthorityTier == "D"
	case ClaimBusinessContext:
		return true
	default:
		return false
	}
}

func sourceFor(sourceMap SourceMap, companyID string) (SourceDefinition, bool) {
	for _, source := range sourceMap.Sources {
		if source.CompanyID == companyID {
			return source, true
		}
	}
	return SourceDefinition{}, false
}

func allowedURI(raw string, allowedHosts []string) bool {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme != "https" || parsed.User != nil || parsed.Hostname() == "" {
		return false
	}
	host := strings.ToLower(parsed.Hostname())
	for _, allowed := range allowedHosts {
		allowed = strings.ToLower(strings.TrimSpace(allowed))
		if host == allowed || strings.HasSuffix(host, "."+allowed) {
			return true
		}
	}
	return false
}

func validSHA(value string) bool {
	if len(value) != 64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func member(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
