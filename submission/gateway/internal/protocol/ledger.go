package protocol

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"time"

	"github.com/xeipuuv/gojsonschema"
)

// source-of-truth: D:/OMIMA/packages/protocol/src/ledger/schema.json
//go:generate go run generate_schema.go

//go:embed testdata/schema.json
var assetLedgerEntrySchema []byte

type PrivacyLevel string

const (
	PrivacyPrivate PrivacyLevel = "private"
	PrivacyFamily  PrivacyLevel = "family"
	PrivacyPublic  PrivacyLevel = "public"
)

type ProcessingStatus string

const (
	StatusRaw      ProcessingStatus = "raw"
	StatusStaging  ProcessingStatus = "staging"
	StatusDerived  ProcessingStatus = "derived"
	StatusArchived ProcessingStatus = "archived"
)

type AssetType string

const (
	AssetCredential      AssetType = "credential"
	AssetIdentity        AssetType = "identity"
	AssetEducation       AssetType = "education"
	AssetPolicy          AssetType = "policy"
	AssetTechCredential  AssetType = "tech-credential"
	AssetServicePassword AssetType = "service-password"
	AssetDocument        AssetType = "document"
	AssetNote            AssetType = "note"
	AssetHealthRecord    AssetType = "health-record"
	AssetFinanceRecord   AssetType = "finance-record"
	AssetFamilyArchive   AssetType = "family-archive"
	AssetMemoryNote      AssetType = "memory-note"
)

type Provenance struct {
	Source      string    `json:"source"`
	IngestedAt  time.Time `json:"ingested_at"`
	IngestedBy  string    `json:"ingested_by"`
	DerivedFrom []string  `json:"derived_from,omitempty"`
}

type AssetLedgerEntry struct {
	AssetID          string           `json:"asset_id"`
	AssetType        AssetType        `json:"asset_type"`
	ContentHash      string           `json:"content_hash"`
	Owner            string           `json:"owner"`
	PrivacyLevel     PrivacyLevel     `json:"privacy_level"`
	ProcessingStatus ProcessingStatus `json:"processing_status"`
	Provenance       Provenance       `json:"provenance"`
	Title            string           `json:"title,omitempty"`
	Tags             []string         `json:"tags,omitempty"`
	Related          []string         `json:"related,omitempty"`
	CreatedAt        time.Time        `json:"created_at"`
	UpdatedAt        time.Time        `json:"updated_at"`
}

func ValidateAssetLedgerEntryJSON(data []byte) (*gojsonschema.Result, error) {
	schemaLoader := gojsonschema.NewBytesLoader(assetLedgerEntrySchema)
	documentLoader := gojsonschema.NewBytesLoader(data)
	return gojsonschema.Validate(schemaLoader, documentLoader)
}

func DecodeAssetLedgerEntry(data []byte) (AssetLedgerEntry, error) {
	var entry AssetLedgerEntry
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	err := decoder.Decode(&entry)
	return entry, err
}
