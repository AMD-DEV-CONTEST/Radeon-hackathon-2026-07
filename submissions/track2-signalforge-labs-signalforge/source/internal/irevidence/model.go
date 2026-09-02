package irevidence

import "time"

const (
	SourceMapSchemaV1 = "signalforge/investor-relations-source-map/v1"
	DocumentSchemaV1  = "signalforge/investor-relations-document/v1"
)

type SourceMap struct {
	SchemaVersion string             `json:"schema_version"`
	Sources       []SourceDefinition `json:"sources"`
}

type DocumentManifest struct {
	SchemaVersion string     `json:"schema_version"`
	Documents     []Document `json:"documents"`
}

type SourceDefinition struct {
	CompanyID       string   `json:"company_id"`
	CIK             string   `json:"cik"`
	Issuer          string   `json:"issuer"`
	DiscoveryURI    string   `json:"discovery_uri"`
	AllowedHosts    []string `json:"allowed_hosts"`
	MaterialClasses []string `json:"material_classes"`
}

type Document struct {
	SchemaVersion  string     `json:"schema_version"`
	DocumentID     string     `json:"document_id"`
	CompanyID      string     `json:"company_id"`
	Title          string     `json:"title"`
	DocumentType   string     `json:"document_type"`
	AuthorityTier  string     `json:"authority_tier"`
	Issuer         string     `json:"issuer"`
	SourceURI      string     `json:"source_uri"`
	CanonicalURI   string     `json:"canonical_uri"`
	DiscoveryURI   string     `json:"discovery_uri"`
	MediaType      string     `json:"media_type"`
	Language       string     `json:"language"`
	PublishedAt    time.Time  `json:"published_at"`
	AvailableAt    time.Time  `json:"available_at"`
	RetrievedAt    time.Time  `json:"retrieved_at"`
	EffectiveAt    *time.Time `json:"effective_at,omitempty"`
	SupersededAt   *time.Time `json:"superseded_at,omitempty"`
	PredecessorID  string     `json:"predecessor_id,omitempty"`
	SuccessorID    string     `json:"successor_id,omitempty"`
	FiscalPeriod   string     `json:"fiscal_period,omitempty"`
	EventID        string     `json:"event_id,omitempty"`
	Speaker        string     `json:"speaker,omitempty"`
	SpeakerRole    string     `json:"speaker_role,omitempty"`
	Audited        bool       `json:"audited"`
	FiledWithSEC   bool       `json:"filed_with_sec"`
	ForwardLooking bool       `json:"forward_looking"`
	Promotional    bool       `json:"promotional"`
	ContentSHA256  string     `json:"content_sha256"`
	RightsClass    string     `json:"rights_class"`
	ParserVersion  string     `json:"parser_version"`
}

type ClaimClass string

const (
	ClaimRegulatoryFact           ClaimClass = "regulatory_fact"
	ClaimAuditedFinancialFact     ClaimClass = "audited_financial_fact"
	ClaimIssuerReportedResult     ClaimClass = "issuer_reported_result"
	ClaimManagementInterpretation ClaimClass = "management_interpretation"
	ClaimGovernance               ClaimClass = "governance"
	ClaimBusinessContext          ClaimClass = "business_context"
)
