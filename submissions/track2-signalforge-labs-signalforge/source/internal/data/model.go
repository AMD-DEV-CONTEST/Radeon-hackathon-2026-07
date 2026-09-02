package data

import "time"

type Availability struct {
	ObservedAt  time.Time `json:"observed_at"`
	AvailableAt time.Time `json:"available_at"`
	RetrievedAt time.Time `json:"retrieved_at"`
}

type Company struct {
	CompanyID       string     `json:"company_id"`
	CIK             string     `json:"cik"`
	LegalName       string     `json:"legal_name"`
	FormerNames     []string   `json:"former_names,omitempty"`
	Jurisdiction    string     `json:"jurisdiction,omitempty"`
	FiscalYearEnd   string     `json:"fiscal_year_end,omitempty"`
	SICCode         string     `json:"sic_code,omitempty"`
	Status          string     `json:"status"`
	ValidFrom       time.Time  `json:"valid_from"`
	ValidTo         *time.Time `json:"valid_to,omitempty"`
	SourceRecordIDs []string   `json:"source_record_ids"`
	RetrievedAt     time.Time  `json:"retrieved_at"`
}

type Filing struct {
	FilingID         string    `json:"filing_id"`
	CompanyID        string    `json:"company_id"`
	AccessionNumber  string    `json:"accession_number"`
	FormType         string    `json:"form_type"`
	ReportPeriodEnd  time.Time `json:"report_period_end"`
	FiledAt          time.Time `json:"filed_at"`
	AcceptedAt       time.Time `json:"accepted_at"`
	PublishedAt      time.Time `json:"published_at"`
	AmendsFilingID   string    `json:"amends_filing_id,omitempty"`
	Taxonomy         string    `json:"taxonomy_namespace,omitempty"`
	TaxonomyVersion  string    `json:"taxonomy_version,omitempty"`
	PrimaryDocument  string    `json:"primary_document,omitempty"`
	PrimaryDocTitle  string    `json:"primary_document_description,omitempty"`
	ReportInferred   bool      `json:"report_period_inferred,omitempty"`
	IsXBRL           bool      `json:"is_xbrl"`
	IsInlineXBRL     bool      `json:"is_inline_xbrl"`
	SourceRecordID   string    `json:"source_record_id"`
	SourceURI        string    `json:"source_uri"`
	ContentSHA256    string    `json:"content_sha256"`
	RetrievedAt      time.Time `json:"retrieved_at"`
	ExtractorVersion string    `json:"extractor_version"`
}

func (filing Filing) Availability() Availability {
	return Availability{ObservedAt: filing.ReportPeriodEnd, AvailableAt: filing.PublishedAt, RetrievedAt: filing.RetrievedAt}
}

type ReportedFact struct {
	FactID            string            `json:"fact_id"`
	FilingID          string            `json:"filing_id"`
	CompanyID         string            `json:"company_id"`
	Taxonomy          string            `json:"taxonomy"`
	Concept           string            `json:"concept"`
	Label             string            `json:"label,omitempty"`
	Value             string            `json:"value"`
	Unit              string            `json:"unit"`
	Scale             int32             `json:"scale"`
	StartDate         *time.Time        `json:"start_date,omitempty"`
	EndDate           *time.Time        `json:"end_date,omitempty"`
	InstantDate       *time.Time        `json:"instant_date,omitempty"`
	FiscalYear        int               `json:"fiscal_year,omitempty"`
	FiscalPeriod      string            `json:"fiscal_period,omitempty"`
	FormType          string            `json:"form_type"`
	Dimensions        map[string]string `json:"dimensions,omitempty"`
	StatementRole     string            `json:"statement_role,omitempty"`
	PresentationOrder *int              `json:"presentation_order,omitempty"`
	CustomConcept     bool              `json:"is_custom_concept"`
	SourceContextID   string            `json:"source_context_id"`
	SourceLocator     string            `json:"source_locator"`
	AvailableAt       time.Time         `json:"available_at"`
	RetrievedAt       time.Time         `json:"retrieved_at"`
}

type NormalizedMetric struct {
	MetricID            string    `json:"metric_id"`
	CompanyID           string    `json:"company_id"`
	CanonicalMetric     string    `json:"canonical_metric"`
	PeriodStart         time.Time `json:"period_start"`
	PeriodEnd           time.Time `json:"period_end"`
	PeriodType          string    `json:"period_type"`
	Value               string    `json:"value"`
	Unit                string    `json:"unit"`
	Currency            string    `json:"currency,omitempty"`
	SourceFactIDs       []string  `json:"source_fact_ids"`
	TransformationID    string    `json:"transformation_id"`
	NormalizationPolicy string    `json:"normalization_policy_version"`
	ComparabilityStatus string    `json:"comparability_status"`
	QualityFlags        []string  `json:"quality_flags,omitempty"`
	SourceAvailableAt   time.Time `json:"source_available_at"`
	ComputedAt          time.Time `json:"computed_at"`
}

type EvidenceReference struct {
	EvidenceID     string    `json:"evidence_id"`
	SourceType     string    `json:"source_type"`
	SourceRecordID string    `json:"source_record_id"`
	SourceURI      string    `json:"source_uri"`
	DocumentSHA256 string    `json:"document_sha256"`
	Locator        string    `json:"section_or_locator"`
	ExcerptSHA256  string    `json:"excerpt_sha256,omitempty"`
	AvailableAt    time.Time `json:"available_at"`
	RetrievedAt    time.Time `json:"retrieved_at"`
	ParserVersion  string    `json:"parser_version"`
	LicenseClass   string    `json:"license_class"`
}
