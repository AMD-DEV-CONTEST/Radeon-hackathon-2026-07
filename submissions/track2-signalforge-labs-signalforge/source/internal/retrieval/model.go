package retrieval

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"
)

const ChunkSchemaV1 = "signalforge/evidence-chunk/v1"

type Chunk struct {
	SchemaVersion   string     `json:"schema_version"`
	ChunkID         string     `json:"chunk_id"`
	DocumentID      string     `json:"document_id"`
	CompanyID       string     `json:"company_id"`
	EvidenceType    string     `json:"evidence_type"`
	FilingID        string     `json:"filing_id,omitempty"`
	AccessionNumber string     `json:"accession_number,omitempty"`
	FormType        string     `json:"form_type,omitempty"`
	DocumentType    string     `json:"document_type"`
	AuthorityTier   string     `json:"authority_tier"`
	Issuer          string     `json:"issuer"`
	Language        string     `json:"language"`
	RightsClass     string     `json:"rights_class"`
	Audited         bool       `json:"audited"`
	FiledWithSEC    bool       `json:"filed_with_sec"`
	ForwardLooking  bool       `json:"forward_looking"`
	Promotional     bool       `json:"promotional"`
	PublishedAt     time.Time  `json:"published_at"`
	EffectiveAt     *time.Time `json:"effective_at,omitempty"`
	SupersededAt    *time.Time `json:"superseded_at,omitempty"`
	Section         string     `json:"section"`
	TableID         string     `json:"table_id,omitempty"`
	Page            int        `json:"page,omitempty"`
	Locator         string     `json:"locator"`
	Periods         []string   `json:"periods,omitempty"`
	ClaimKey        string     `json:"claim_key,omitempty"`
	ClaimValue      string     `json:"claim_value,omitempty"`
	Text            string     `json:"text"`
	SourceURI       string     `json:"source_uri"`
	DocumentSHA256  string     `json:"document_sha256"`
	ContentSHA256   string     `json:"content_sha256"`
	AvailableAt     time.Time  `json:"available_at"`
	RetrievedAt     time.Time  `json:"retrieved_at"`
	TokenEstimate   int        `json:"token_estimate"`
	ChunkingVersion string     `json:"chunking_version"`
}

type Query struct {
	Text           string    `json:"text"`
	AsOf           time.Time `json:"as_of"`
	CompanyIDs     []string  `json:"company_ids,omitempty"`
	FormTypes      []string  `json:"form_types,omitempty"`
	DocumentTypes  []string  `json:"document_types,omitempty"`
	AuthorityTiers []string  `json:"authority_tiers,omitempty"`
	TopK           int       `json:"top_k"`
}

type Hit struct {
	Chunk  Chunk   `json:"chunk"`
	Score  float64 `json:"score"`
	Method string  `json:"method"`
	Rank   int     `json:"rank"`
}

type Citation struct {
	ChunkID         string   `json:"chunk_id"`
	CompanyID       string   `json:"company_id"`
	FilingID        string   `json:"filing_id"`
	AccessionNumber string   `json:"accession_number"`
	EvidenceType    string   `json:"evidence_type"`
	DocumentType    string   `json:"document_type"`
	AuthorityTier   string   `json:"authority_tier"`
	Issuer          string   `json:"issuer"`
	Section         string   `json:"section"`
	Locator         string   `json:"locator"`
	Periods         []string `json:"periods,omitempty"`
	SourceURI       string   `json:"source_uri"`
	DocumentSHA256  string   `json:"document_sha256"`
	ContentSHA256   string   `json:"content_sha256"`
}

func ValidateChunk(chunk Chunk) error {
	if chunk.SchemaVersion != ChunkSchemaV1 {
		return fmt.Errorf("unsupported schema version %q", chunk.SchemaVersion)
	}
	for name, value := range map[string]string{
		"chunk_id": chunk.ChunkID, "document_id": chunk.DocumentID, "company_id": chunk.CompanyID,
		"evidence_type": chunk.EvidenceType, "document_type": chunk.DocumentType, "authority_tier": chunk.AuthorityTier,
		"issuer": chunk.Issuer, "language": chunk.Language, "rights_class": chunk.RightsClass,
		"section": chunk.Section, "locator": chunk.Locator, "text": chunk.Text, "source_uri": chunk.SourceURI,
		"document_sha256": chunk.DocumentSHA256, "content_sha256": chunk.ContentSHA256, "chunking_version": chunk.ChunkingVersion,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("%s is required", name)
		}
	}
	if chunk.AvailableAt.IsZero() || chunk.RetrievedAt.IsZero() || chunk.RetrievedAt.Before(chunk.AvailableAt) {
		return errors.New("valid availability and retrieval timestamps are required")
	}
	if chunk.TokenEstimate <= 0 {
		return errors.New("positive token estimate is required")
	}
	if !validSHA(chunk.DocumentSHA256) || !validSHA(chunk.ContentSHA256) {
		return errors.New("document and content hashes must be lowercase SHA-256")
	}
	digest := sha256.Sum256([]byte(chunk.Text))
	if hex.EncodeToString(digest[:]) != chunk.ContentSHA256 {
		return errors.New("content hash does not match chunk text")
	}
	if chunk.PublishedAt.IsZero() || chunk.AvailableAt.Before(chunk.PublishedAt) {
		return errors.New("published_at must exist and cannot follow available_at")
	}
	if chunk.SupersededAt != nil && chunk.SupersededAt.Before(chunk.AvailableAt) {
		return errors.New("superseded_at cannot precede available_at")
	}
	if !member([]string{"A", "B", "C", "D", "E"}, chunk.AuthorityTier) {
		return errors.New("authority_tier must be A, B, C, D, or E")
	}
	switch chunk.EvidenceType {
	case "regulatory_filing":
		if chunk.FilingID == "" || chunk.AccessionNumber == "" || chunk.FormType == "" || !chunk.FiledWithSEC || chunk.AuthorityTier != "A" {
			return errors.New("regulatory filing chunks require filing identity, form, SEC status, and tier A")
		}
	case "investor_relations":
		if chunk.Promotional && member([]string{"A", "B"}, chunk.AuthorityTier) {
			return errors.New("promotional investor-relations chunks cannot claim tier A or B")
		}
	default:
		return errors.New("evidence_type must be regulatory_filing or investor_relations")
	}
	return nil
}

func ValidateQuery(query Query) error {
	if strings.TrimSpace(query.Text) == "" || query.AsOf.IsZero() {
		return errors.New("query text and as_of are required")
	}
	if query.TopK <= 0 || query.TopK > 100 {
		return errors.New("top_k must be between 1 and 100")
	}
	return nil
}

func (chunk Chunk) Citation() Citation {
	return Citation{
		ChunkID: chunk.ChunkID, CompanyID: chunk.CompanyID, FilingID: chunk.FilingID,
		AccessionNumber: chunk.AccessionNumber, EvidenceType: chunk.EvidenceType, DocumentType: chunk.DocumentType,
		AuthorityTier: chunk.AuthorityTier, Issuer: chunk.Issuer, Section: chunk.Section, Locator: chunk.Locator,
		Periods: append([]string(nil), chunk.Periods...), SourceURI: chunk.SourceURI,
		DocumentSHA256: chunk.DocumentSHA256, ContentSHA256: chunk.ContentSHA256,
	}
}

func validSHA(value string) bool {
	if len(value) != 64 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil && strings.ToLower(value) == value
}

func eligible(chunk Chunk, query Query) bool {
	if chunk.AvailableAt.After(query.AsOf) {
		return false
	}
	if chunk.SupersededAt != nil && !chunk.SupersededAt.After(query.AsOf) {
		return false
	}
	if len(query.CompanyIDs) > 0 && !member(query.CompanyIDs, chunk.CompanyID) {
		return false
	}
	if len(query.FormTypes) > 0 && !member(query.FormTypes, chunk.FormType) {
		return false
	}
	if len(query.DocumentTypes) > 0 && !member(query.DocumentTypes, chunk.DocumentType) {
		return false
	}
	return len(query.AuthorityTiers) == 0 || member(query.AuthorityTiers, chunk.AuthorityTier)
}

func member(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
